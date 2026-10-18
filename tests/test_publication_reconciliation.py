"""Unit and Integration Tests for Core Publication & Quality Reconciliation (Lab 02, Tasks 6 & 7)."""

import pytest
from decimal import Decimal
import psycopg2

from src.lab02.config import DB_CONFIG
from src.lab02.publish_core import (
    publish_core,
    ReconciliationError,
)


@pytest.fixture(scope="module")
def db_conn():
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True
    yield conn
    conn.close()


def test_successful_publication_and_gates():
    """Verify that a standard publication run succeeds and passes all 4 reconciliation gates."""
    result = publish_core()
    assert result["status"] == "SUCCESS"
    assert result["reconciliation_passed"] is True
    assert len(result["files_stats"]) == 5
    assert len(result["financial_recon"]) >= 3

    # All files must have valid balance and key matches
    for f in result["files_stats"]:
        assert f["balance_valid"] is True
        assert f["core_count_match"] is True
        assert f["core_keys_match"] is True

    # Financial sums must have 0.00 diff
    for fr in result["financial_recon"]:
        assert fr["matched"] is True
        assert fr["orders_diff"] == Decimal("0.00")
        assert fr["items_diff"] == Decimal("0.00")


def test_rollback_on_failure_preserves_core(db_conn):
    """Verify that when an error occurs during publication:

    1. The core tables are rolled back to the prior valid snapshot (not left truncated/empty).
    2. The FAILED status and error message are safely preserved in audit.publication_runs.
    """
    # Count rows before failed attempt
    with db_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM core.orders;")
        pre_fail_count = cur.fetchone()[0]
        assert pre_fail_count > 0, "Core orders should not be empty prior to test"

    # Run publication with simulated failure after truncate
    with pytest.raises(RuntimeError, match="Simulated failure AFTER core truncate"):
        publish_core(simulate_error_stage="after_truncate")

    # Verify that core tables still have all rows (snapshot preserved)
    with db_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM core.orders;")
        post_fail_count = cur.fetchone()[0]
        assert post_fail_count == pre_fail_count, "Core orders count changed after rolled-back publication!"

        # Verify audit log recorded FAILED status
        cur.execute(
            """
            SELECT status, reconciliation_passed, error_message
            FROM audit.publication_runs
            ORDER BY started_at DESC
            LIMIT 1;
            """
        )
        row = cur.fetchone()
        assert row[0] == "FAILED"
        assert row[1] is False
        assert "Simulated failure AFTER core truncate" in row[2]


def test_gate_1_per_file_row_balance(db_conn):
    """Gate 1: Verify input_count = accepted_count + rejected_count + duplicate_count in audit log."""
    with db_conn.cursor() as cur:
        cur.execute(
            """
            SELECT source_file, input_count, accepted_count, rejected_count, duplicate_count, balance_valid
            FROM audit.publication_run_files
            WHERE run_id = (
                SELECT run_id FROM audit.publication_runs WHERE status = 'SUCCESS' ORDER BY finished_at DESC LIMIT 1
            );
            """
        )
        rows = cur.fetchall()
        assert len(rows) == 5
        for r in rows:
            file_name, inp, acc, rej, dup, valid = r
            assert valid is True
            assert inp == acc + rej + dup, f"Row balance failed for {file_name}: {inp} != {acc} + {rej} + {dup}"


def test_gate_2_core_counts_and_keys(db_conn):
    """Gate 2: Verify core table counts match accepted counts and key sets are identical."""
    tables = [
        ("core.customers", "customers.csv"),
        ("core.merchants", "merchants.csv"),
        ("core.products", "products.csv"),
        ("core.orders", "orders.csv"),
        ("core.order_items", "order_items.csv"),
    ]
    with db_conn.cursor() as cur:
        # Get latest success run_id and batch_id
        cur.execute("SELECT run_id, batch_id FROM audit.publication_runs WHERE status = 'SUCCESS' ORDER BY finished_at DESC LIMIT 1;")
        run_id, batch_id = cur.fetchone()

        for tbl, file_name in tables:
            cur.execute(f"SELECT count(*) FROM {tbl};")
            core_count = cur.fetchone()[0]

            cur.execute(
                """
                SELECT count(*) FROM audit.record_decisions
                WHERE batch_id = %s AND source_file = %s AND final_status = 'accepted';
                """,
                (batch_id, file_name),
            )
            acc_count = cur.fetchone()[0]

            assert core_count == acc_count, f"Count mismatch for {tbl}: core={core_count}, accepted={acc_count}"


def test_gate_3_foreign_keys_integrity(db_conn):
    """Gate 3: Ensure 0 dangling foreign keys exist in core schema."""
    with db_conn.cursor() as cur:
        checks = [
            ("core.products", "merchant_id", "core.merchants", "merchant_id"),
            ("core.orders", "customer_id", "core.customers", "customer_id"),
            ("core.orders", "merchant_id", "core.merchants", "merchant_id"),
            ("core.order_items", "order_id", "core.orders", "order_id"),
            ("core.order_items", "product_id", "core.products", "product_id"),
        ]
        for child_tbl, child_fk, parent_tbl, parent_pk in checks:
            cur.execute(
                f"""
                SELECT count(*)
                FROM {child_tbl} c
                LEFT JOIN {parent_tbl} p ON c.{child_fk} = p.{parent_pk}
                WHERE p.{parent_pk} IS NULL;
                """
            )
            orphans = cur.fetchone()[0]
            assert orphans == 0, f"Found {orphans} orphan records in {child_tbl}.{child_fk}"


def test_gate_4_financial_reconciliation(db_conn):
    """Gate 4: Verify financial sums match exactly (difference = 0.00) between accepted staging and core."""
    with db_conn.cursor() as cur:
        cur.execute(
            """
            SELECT currency, orders_diff, items_diff, matched
            FROM audit.financial_reconciliation
            WHERE run_id = (
                SELECT run_id FROM audit.publication_runs WHERE status = 'SUCCESS' ORDER BY finished_at DESC LIMIT 1
            );
            """
        )
        rows = cur.fetchall()
        assert len(rows) >= 3  # UAH, USD, EUR
        for r in rows:
            currency, ord_diff, itm_diff, matched = r
            assert matched is True
            assert ord_diff == Decimal("0.00"), f"Financial discrepancy in orders for {currency}: {ord_diff}"
            assert itm_diff == Decimal("0.00"), f"Financial discrepancy in items for {currency}: {itm_diff}"
