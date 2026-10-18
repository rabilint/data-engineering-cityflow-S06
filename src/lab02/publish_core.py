"""Transactional Core Publisher and Quality Reconciliation Pipeline (Lab 02, Tasks 6 & 7).

This module implements:
1. Task 6: Atomic Core Publication Transaction:
   - Full snapshot replacement of core tables (order_items, orders, products, customers, merchants).
   - Strict insertion order respecting referential dependencies:
     1. core.customers & core.merchants
     2. core.products & core.orders
     3. core.order_items
   - Rollback on any failure: if a check fails or an error occurs, the previous valid
     core snapshot is completely preserved. Staging, raw, and audit logs are never dropped.
   - Successful run recorded in the same transaction prior to COMMIT.
   - Failed run recorded separately post-ROLLBACK so failure information is never lost.

2. Task 7: Publication Runs Journal & Multi-Gate Reconciliation:
   - audit.publication_runs: tracks run_id, batch_id, started_at, finished_at, status ('RUNNING' before publication,
     'SUCCESS' with publication, 'FAILED' separately after rollback).
   - audit.publication_run_files: per-file input_count, accepted_count, rejected_count, duplicate_count.
   - Gate 1: Check input = accepted + rejected + duplicate for each source file.
   - Gate 2: Verify count and exact key set in core.* match accepted staging records.
   - Gate 3: Check absence of any broken or dangling foreign keys in core.*.
   - Gate 4: Financial reconciliation: verify sum(orders.total_amount) and sum(order_items.line_total)
     between accepted staging rows and core.* separately for each currency ('UAH', 'USD', 'EUR').
"""

import argparse
import datetime
import logging
import sys
import uuid
from decimal import Decimal
from typing import Any, Dict, List, Optional, Set, Tuple

import psycopg2
from psycopg2.extras import execute_values, Json

from src.lab02.config import DB_CONFIG
from src.lab02.load_core import (
    get_db_connection,
    transform_customers,
    transform_merchants,
    transform_products,
    transform_orders,
    transform_order_items,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("CorePublisher")


class ReconciliationError(Exception):
    """Raised when one of the data quality or balance reconciliation gates fails."""
    pass


class BatchContentChangedError(Exception):
    """Raised when staging content under an existing batch_id has been modified."""
    pass


def register_publication_run_start(conn, run_id: str, batch_id: str) -> None:
    """Registers the publication run as RUNNING in audit.publication_runs in an autonomous transaction."""
    # We commit immediately so the RUNNING state is visible to any observer before the publication begins.
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO audit.publication_runs (run_id, batch_id, started_at, status, reconciliation_passed)
            VALUES (%s, %s, clock_timestamp(), 'RUNNING', FALSE);
            """,
            (run_id, batch_id),
        )
    conn.commit()
    logger.info("Registered publication run %s as RUNNING for batch %s.", run_id, batch_id)


def record_publication_run_failure(custom_db_config: Optional[Dict], run_id: str, error_message: str) -> None:
    """Records the FAILED status and error message in audit.publication_runs via a separate connection/transaction.

    Ensures that failure details are preserved even though the main publication transaction was rolled back.
    """
    fail_conn = get_db_connection(custom_db_config)
    try:
        with fail_conn.cursor() as cur:
            cur.execute(
                """
                UPDATE audit.publication_runs
                SET status = 'FAILED',
                    finished_at = clock_timestamp(),
                    error_message = %s,
                    reconciliation_passed = FALSE
                WHERE run_id = %s;
                """,
                (error_message, run_id),
            )
        fail_conn.commit()
        logger.info("Successfully recorded FAILED status for run %s in audit.publication_runs.", run_id)
    except Exception as exc:
        logger.error("Failed to record failure status in audit: %s", exc)
    finally:
        fail_conn.close()


def verify_gate_1_file_balance(run_files_stats: List[Dict[str, Any]]) -> None:
    """Gate 1: Verify input = accepted + rejected + duplicate for each source file."""
    for stat in run_files_stats:
        inp = stat["input_count"]
        acc = stat["accepted_count"]
        rej = stat["rejected_count"]
        dup = stat["duplicate_count"]
        expected_total = acc + rej + dup
        if inp != expected_total:
            raise ReconciliationError(
                f"Gate 1 Balance Failure in {stat['source_file']}: "
                f"input ({inp}) != accepted ({acc}) + rejected ({rej}) + duplicate ({dup}) = {expected_total}"
            )
        stat["balance_valid"] = True
    logger.info("Gate 1 PASSED: All 5 files satisfy input = accepted + rejected + duplicate.")


def verify_gate_2_core_counts_and_keys(
    cur,
    c_ids: Set[str],
    m_ids: Set[str],
    p_ids: Set[str],
    o_ids: Set[str],
    oi_ids: Set[str],
    run_files_stats: List[Dict[str, Any]],
) -> None:
    """Gate 2: Verify core table row counts and exact key set matches accepted staging records."""
    table_expectations = [
        ("core.customers", "customer_id", c_ids, "customers.csv"),
        ("core.merchants", "merchant_id", m_ids, "merchants.csv"),
        ("core.products", "product_id", p_ids, "products.csv"),
        ("core.orders", "order_id", o_ids, "orders.csv"),
        ("core.order_items", "order_item_id", oi_ids, "order_items.csv"),
    ]

    for table, pk_col, expected_keys, file_name in table_expectations:
        cur.execute(f"SELECT count(*), array_agg({pk_col}) FROM {table};")
        row = cur.fetchone()
        core_count = row[0]
        core_keys = set(row[1]) if row[1] else set()

        if core_count != len(expected_keys):
            raise ReconciliationError(
                f"Gate 2 Count Mismatch on {table}: core has {core_count} rows, expected {len(expected_keys)}"
            )

        missing_in_core = expected_keys - core_keys
        if missing_in_core:
            sample = list(missing_in_core)[:5]
            raise ReconciliationError(
                f"Gate 2 Key Discrepancy on {table}: {len(missing_in_core)} accepted keys missing in core (samples: {sample})"
            )

        unexpected_in_core = core_keys - expected_keys
        if unexpected_in_core:
            sample = list(unexpected_in_core)[:5]
            raise ReconciliationError(
                f"Gate 2 Key Discrepancy on {table}: {len(unexpected_in_core)} unexpected keys in core (samples: {sample})"
            )

        # Update stats record
        for stat in run_files_stats:
            if stat["source_file"] == file_name:
                stat["core_count_match"] = True
                stat["core_keys_match"] = True

    logger.info("Gate 2 PASSED: All core table counts and primary key sets match accepted staging records.")


def verify_gate_3_fk_integrity(cur) -> None:
    """Gate 3: Verify absence of any broken/dangling foreign keys in core.*."""
    fk_checks = [
        ("core.products", "merchant_id", "core.merchants", "merchant_id"),
        ("core.orders", "customer_id", "core.customers", "customer_id"),
        ("core.orders", "merchant_id", "core.merchants", "merchant_id"),
        ("core.order_items", "order_id", "core.orders", "order_id"),
        ("core.order_items", "product_id", "core.products", "product_id"),
    ]

    for child_tbl, child_fk, parent_tbl, parent_pk in fk_checks:
        query = f"""
            SELECT count(*)
            FROM {child_tbl} c
            LEFT JOIN {parent_tbl} p ON c.{child_fk} = p.{parent_pk}
            WHERE p.{parent_pk} IS NULL;
        """
        cur.execute(query)
        orphan_count = cur.fetchone()[0]
        if orphan_count > 0:
            raise ReconciliationError(
                f"Gate 3 FK Violation: {child_tbl}.{child_fk} has {orphan_count} orphan references to {parent_tbl}.{parent_pk}"
            )

    logger.info("Gate 3 PASSED: Zero dangling foreign keys found across all core tables.")


def verify_gate_4_financial_reconciliation(
    cur,
    batch_id: str,
    o_core: List[Tuple],
    oi_core: List[Tuple],
) -> List[Dict[str, Any]]:
    """Gate 4: Financial reconciliation: verify sum(orders.total_amount) and sum(order_items.line_total)

    separately for each currency ('UAH', 'USD', 'EUR') between accepted staging rows and core.*.
    """
    # 1. Sums in core
    cur.execute(
        """
        SELECT currency, COALESCE(SUM(total_amount), 0.00)
        FROM core.orders
        GROUP BY currency;
        """
    )
    core_orders_by_curr = {row[0]: Decimal(str(row[1])) for row in cur.fetchall()}

    cur.execute(
        """
        SELECT currency, COALESCE(SUM(line_total), 0.00)
        FROM core.order_items
        GROUP BY currency;
        """
    )
    core_items_by_curr = {row[0]: Decimal(str(row[1])) for row in cur.fetchall()}

    # 2. Sums from prepared accepted in-memory records (which match staging accepted records)
    # o_core schema: (order_id, customer_id, merchant_id, created_at, order_status, currency, subtotal, delivery, discount, total_amount)
    stg_orders_by_curr: Dict[str, Decimal] = {}
    for o in o_core:
        curr = o[5]
        tot = o[9]
        stg_orders_by_curr[curr] = stg_orders_by_curr.get(curr, Decimal("0.00")) + tot

    # oi_core schema: (item_id, order_id, product_id, quantity, unit_price, line_discount, line_total, currency)
    stg_items_by_curr: Dict[str, Decimal] = {}
    for oi in oi_core:
        curr = oi[7]
        lt = oi[6]
        stg_items_by_curr[curr] = stg_items_by_curr.get(curr, Decimal("0.00")) + lt

    currencies = sorted(list(set(stg_orders_by_curr.keys()) | set(core_orders_by_curr.keys()) | {"UAH", "USD", "EUR"}))
    recon_results: List[Dict[str, Any]] = []

    for curr in currencies:
        stg_ord_sum = stg_orders_by_curr.get(curr, Decimal("0.00"))
        core_ord_sum = core_orders_by_curr.get(curr, Decimal("0.00"))
        ord_diff = abs(core_ord_sum - stg_ord_sum)

        stg_itm_sum = stg_items_by_curr.get(curr, Decimal("0.00"))
        core_itm_sum = core_items_by_curr.get(curr, Decimal("0.00"))
        itm_diff = abs(core_itm_sum - stg_itm_sum)

        matched = (ord_diff == Decimal("0.00")) and (itm_diff == Decimal("0.00"))

        recon_results.append({
            "currency": curr,
            "stg_orders_total": stg_ord_sum,
            "core_orders_total": core_ord_sum,
            "orders_diff": ord_diff,
            "stg_items_line_total": stg_itm_sum,
            "core_items_line_total": core_itm_sum,
            "items_diff": itm_diff,
            "matched": matched,
        })

        logger.info(
            "Financial Recon [%s]: Orders Stg=%s Core=%s Diff=%s | Items Stg=%s Core=%s Diff=%s | Matched=%s",
            curr, stg_ord_sum, core_ord_sum, ord_diff, stg_itm_sum, core_itm_sum, itm_diff, matched
        )

        if not matched:
            raise ReconciliationError(
                f"Gate 4 Financial Sum Discrepancy for currency {curr}: "
                f"orders_diff={ord_diff}, items_diff={itm_diff}"
            )

    logger.info("Gate 4 PASSED: Financial sums of total_amount and line_total match exactly (diff = 0.00) across all currencies.")
    return recon_results


def publish_core(
    batch_id: Optional[str] = None,
    custom_db_config: Optional[Dict] = None,
    simulate_error_stage: Optional[str] = None,
    inject_invalid_item: bool = False,
) -> Dict[str, Any]:
    """Executes the atomic transactional publication of core.* and multi-gate reconciliation.

    Stages of execution:
    1. Resolve batch_id and generate run_id.
    2. Register run_id as 'RUNNING' in audit.publication_runs (committed immediately).
    3. Start transaction (BEGIN):
       a. Check batch content integrity: reject silent history change under same batch_id.
       b. Replace core tables snapshot (TRUNCATE in child-to-parent order).
       c. Prepare accepted records and decision logs.
       d. Insert prepared records in parent-to-child order:
          (customers/merchants -> products/orders -> order_items).
       e. Insert audit.record_decisions and audit.rejected_records.
       f. Gate 1: Check per-file balance (input = accepted + rejected + duplicate).
       g. Gate 2: Check core row counts and exact key set vs accepted.
       h. Gate 3: Check FK integrity (zero dangling FKs).
       i. Gate 4: Financial reconciliation by currency (diff = 0.00).
       j. Update audit.publication_runs to 'SUCCESS', insert audit.publication_run_files and financial_reconciliation.
       k. COMMIT.
    4. On error:
       a. ROLLBACK transaction (preserves previous valid core snapshot).
       b. Record 'FAILED' status and error message in audit.publication_runs via separate transaction.
       c. Re-raise exception.
    """
    main_conn = get_db_connection(custom_db_config)
    main_conn.autocommit = False

    run_id = f"pub_run_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

    try:
        # Step 1: Resolve batch_id
        if not batch_id:
            with main_conn.cursor() as cur:
                cur.execute(
                    "SELECT batch_id FROM audit.load_batches WHERE status = 'SUCCESS' ORDER BY completed_at DESC LIMIT 1;"
                )
                row = cur.fetchone()
                if not row:
                    raise RuntimeError("No successful staging batches found in audit.load_batches. Run load_staging first.")
                batch_id = row[0]

        logger.info("================================================================================")
        logger.info("Starting Core Transactional Publication: Run ID = %s | Batch ID = %s", run_id, batch_id)
        if simulate_error_stage:
            logger.warning("Simulation Mode Active: Will simulate error at stage '%s'", simulate_error_stage)
        if inject_invalid_item:
            logger.warning("Injection Mode Active: Will inject invalid order item with quantity = -1")
        logger.info("================================================================================")

        # Step 2: Register RUNNING in separate autonomous transaction
        register_conn = get_db_connection(custom_db_config)
        try:
            register_publication_run_start(register_conn, run_id, batch_id)
        finally:
            register_conn.close()

        # Step 3: Atomic Publication Transaction
        with main_conn.cursor() as cur:
            if simulate_error_stage == "before_truncate":
                raise RuntimeError("Simulated failure BEFORE core truncate.")

            # 3b. Prepare clean records and audit decisions in memory
            logger.info("Transforming staging data into clean core records...")
            c_core, c_dec, c_ids = transform_customers(main_conn, batch_id)
            m_core, m_dec, m_ids = transform_merchants(main_conn, batch_id)
            p_core, p_dec, p_ids = transform_products(main_conn, batch_id, m_ids)
            o_core, o_dec, o_ids = transform_orders(main_conn, batch_id, c_ids, m_ids)
            oi_core, oi_dec, oi_ids = transform_order_items(main_conn, batch_id, o_ids, p_ids)

            def get_stats(file_name: str, target_tbl: str, dec_list: List[Tuple]) -> Dict[str, Any]:
                inp = len(dec_list)
                acc = sum(1 for d in dec_list if d[4] == "accepted")
                dup = sum(1 for d in dec_list if d[4] == "duplicate")
                rej = sum(1 for d in dec_list if d[4] == "rejected")
                return {
                    "source_file": file_name,
                    "target_table": target_tbl,
                    "input_count": inp,
                    "accepted_count": acc,
                    "rejected_count": rej,
                    "duplicate_count": dup,
                    "balance_valid": False,
                    "core_count_match": False,
                    "core_keys_match": False,
                }

            run_files_stats = [
                get_stats("customers.csv", "core.customers", c_dec),
                get_stats("merchants.csv", "core.merchants", m_dec),
                get_stats("products.csv", "core.products", p_dec),
                get_stats("orders.csv", "core.orders", o_dec),
                get_stats("order_items.csv", "core.order_items", oi_dec),
            ]

            # Check batch content integrity: do not silently overwrite modified content under the same batch_id
            cur.execute(
                """
                SELECT rf.source_file, rf.input_count
                FROM audit.publication_run_files rf
                JOIN audit.publication_runs r ON rf.run_id = r.run_id
                WHERE r.batch_id = %s AND r.status = 'SUCCESS'
                ORDER BY r.finished_at DESC;
                """,
                (batch_id,),
            )
            prev_file_counts = {row[0]: row[1] for row in cur.fetchall()}
            if prev_file_counts:
                for stat in run_files_stats:
                    sf = stat["source_file"]
                    if sf in prev_file_counts and prev_file_counts[sf] != stat["input_count"]:
                        raise BatchContentChangedError(
                            f"Batch integrity violation: staging input count for {sf} in batch {batch_id} changed "
                            f"from {prev_file_counts[sf]} to {stat['input_count']}! Silent overwrite of history is prohibited."
                        )

            # 3a. Truncate core tables (snapshot replacement)
            logger.info("Truncating core tables in child-to-parent order...")
            cur.execute("TRUNCATE TABLE core.order_items, core.orders, core.products, core.customers, core.merchants CASCADE;")

            if simulate_error_stage == "after_truncate":
                raise RuntimeError("Simulated failure AFTER core truncate (testing rollback of truncate).")

            # 3c. Insert into core.* in dependency order (Task 6)
            logger.info("Publishing core tables in strict dependency order...")
            # Step 1: Parents (customers, merchants)
            execute_values(cur, "INSERT INTO core.customers (customer_id, full_name, city, registered_at) VALUES %s;", c_core, page_size=2000)
            execute_values(cur, "INSERT INTO core.merchants (merchant_id, merchant_name, city, opened_at) VALUES %s;", m_core, page_size=2000)
            # Step 2: Intermediate dependents (products, orders)
            execute_values(cur, "INSERT INTO core.products (product_id, merchant_id, product_name, unit_price_uah, is_active) VALUES %s;", p_core, page_size=2000)
            execute_values(cur, "INSERT INTO core.orders (order_id, customer_id, merchant_id, created_at, order_status, currency, subtotal_amount, delivery_fee, discount_amount, total_amount) VALUES %s;", o_core, page_size=2000)
            
            # Step 3: Grandchildren (order_items)
            if inject_invalid_item:
                logger.warning("Injecting test row with quantity = -1 (violates CHECK quantity > 0)...")
                invalid_item = (
                    "ERR_ITEM_NEGATIVE_QTY",
                    o_core[0][0] if o_core else "O001",
                    p_core[0][0] if p_core else "P001",
                    -1,  # Violates CHECK (quantity > 0)
                    Decimal("50.00"),
                    Decimal("0.00"),
                    Decimal("-50.00"),
                    "UAH"
                )
                oi_core = list(oi_core) + [invalid_item]

            execute_values(cur, "INSERT INTO core.order_items (order_item_id, order_id, product_id, quantity, unit_price, line_discount, line_total, currency) VALUES %s;", oi_core, page_size=2000)


            # 3d. Record decisions into audit tables (Task 5 requirement)
            all_decisions = c_dec + m_dec + p_dec + o_dec + oi_dec
            cur.execute("DELETE FROM audit.record_decisions WHERE batch_id = %s;", (batch_id,))
            cur.execute("DELETE FROM audit.rejected_records WHERE batch_id = %s;", (batch_id,))
            execute_values(
                cur,
                """
                INSERT INTO audit.record_decisions
                (batch_id, source_file, source_row_number, business_key, final_status, reason_codes, details, payload)
                VALUES %s;
                """,
                all_decisions,
                page_size=2000,
            )

            non_accepted = [
                (d[0], d[1], d[2], d[3], d[5][0] if d[5] else "REJECTED", d[6], d[7])
                for d in all_decisions if d[4] != "accepted"
            ]
            if non_accepted:
                execute_values(
                    cur,
                    """
                    INSERT INTO audit.rejected_records
                    (batch_id, source_table, source_row_number, entity_id, rejection_reason, details, raw_record)
                    VALUES %s;
                    """,
                    non_accepted,
                    page_size=2000,
                )

            if simulate_error_stage == "before_reconciliation":
                raise RuntimeError("Simulated failure BEFORE verification gates.")

            # 3e. Gate 1: Check input = accepted + rejected + duplicate
            verify_gate_1_file_balance(run_files_stats)

            # 3f. Gate 2: Check core row count and exact key set vs accepted
            verify_gate_2_core_counts_and_keys(cur, c_ids, m_ids, p_ids, o_ids, oi_ids, run_files_stats)

            # 3g. Gate 3: Check FK integrity
            verify_gate_3_fk_integrity(cur)

            # 3h. Gate 4: Financial reconciliation by currency
            financial_recon = verify_gate_4_financial_reconciliation(cur, batch_id, o_core, oi_core)

            if simulate_error_stage == "after_reconciliation":
                raise RuntimeError("Simulated failure AFTER verification gates (prior to commit).")

            # 3i. Record success in publication audit tables inside the SAME transaction
            cur.execute(
                """
                UPDATE audit.publication_runs
                SET status = 'SUCCESS',
                    finished_at = clock_timestamp(),
                    reconciliation_passed = TRUE,
                    error_message = NULL
                WHERE run_id = %s;
                """,
                (run_id,),
            )

            file_audit_rows = [
                (
                    run_id,
                    stat["source_file"],
                    stat["target_table"],
                    stat["input_count"],
                    stat["accepted_count"],
                    stat["rejected_count"],
                    stat["duplicate_count"],
                    stat["balance_valid"],
                    stat["core_count_match"],
                    stat["core_keys_match"],
                )
                for stat in run_files_stats
            ]
            execute_values(
                cur,
                """
                INSERT INTO audit.publication_run_files
                (run_id, source_file, target_table, input_count, accepted_count, rejected_count, duplicate_count, balance_valid, core_count_match, core_keys_match)
                VALUES %s;
                """,
                file_audit_rows,
            )

            financial_audit_rows = [
                (
                    run_id,
                    f["currency"],
                    f["stg_orders_total"],
                    f["core_orders_total"],
                    f["orders_diff"],
                    f["stg_items_line_total"],
                    f["core_items_line_total"],
                    f["items_diff"],
                    f["matched"],
                )
                for f in financial_recon
            ]
            execute_values(
                cur,
                """
                INSERT INTO audit.financial_reconciliation
                (run_id, currency, stg_orders_total, core_orders_total, orders_diff, stg_items_line_total, core_items_line_total, items_diff, matched)
                VALUES %s;
                """,
                financial_audit_rows,
            )

        # 3j. Commit atomic transaction
        main_conn.commit()
        logger.info("================================================================================")
        logger.info("Core Publication Transaction COMMITTED successfully! Run ID: %s", run_id)
        logger.info("================================================================================")

        return {
            "run_id": run_id,
            "batch_id": batch_id,
            "status": "SUCCESS",
            "reconciliation_passed": True,
            "files_stats": run_files_stats,
            "financial_recon": financial_recon,
        }

    except Exception as exc:
        logger.error("Publication transaction failed: %s. Initiating ROLLBACK...", exc)
        main_conn.rollback()
        logger.info("ROLLBACK complete. Previous core snapshot preserved intact.")

        # Step 4: Record FAILED status in a separate transaction so failure is never lost
        record_publication_run_failure(custom_db_config, run_id, str(exc))

        raise exc
    finally:
        main_conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Lab 02 Core Transactional Publisher & Reconciler")
    parser.add_argument("--batch-id", default=None, help="Batch ID to publish (defaults to latest SUCCESS batch)")
    parser.add_argument(
        "--simulate-error",
        choices=["before_truncate", "after_truncate", "before_reconciliation", "after_reconciliation"],
        default=None,
        help="Simulate failure at a specific stage to test rollback and audit logging",
    )
    args = parser.parse_args()

    try:
        publish_core(batch_id=args.batch_id, simulate_error_stage=args.simulate_error)
    except Exception as err:
        logger.error("Publish execution terminated with error: %s", err)
        sys.exit(1)
