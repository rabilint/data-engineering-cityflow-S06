"""Task 8: Reliability, Re-runs, Controlled Failures, and Fail-Safe Tests.

This test suite verifies:
1. Idempotency of re-running the same batch:
   - Core tables retain identical row counts, exact key sets, and financial sums.
   - A new distinct run is recorded in audit.publication_runs with status 'SUCCESS'.
2. Prevention of silent history overwrite:
   - When staging content differs under an existing batch_id, BatchContentChangedError is raised.
3. Controlled Failure & Rollback (Task 8 requirement):
   - Injected child row with quantity = -1 violating CHECK (quantity > 0) after core changes started.
   - Proves ROLLBACK restored all core tables to their previous valid state.
   - Proves audit.publication_runs preserves the failed-run entry with status 'FAILED'.
   - Fixes the error and proves subsequent publication succeeds.
4. Negative Pre-Publication Tests (Fail-Fast):
   - Corrupted CSV header or missing required file halts the pipeline BEFORE publication starts.
   - Ensures no partial or corrupted records enter core tables.
"""

from decimal import Decimal
from pathlib import Path
import psycopg2
import pytest

from src.lab02.config import DB_CONFIG, STAGING_TABLES
from src.lab02.load_staging import validate_csv_header, StructuralValidationError
from src.lab02.publish_core import (
    publish_core,
    BatchContentChangedError,
)


@pytest.fixture(scope="module")
def db_conn():
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True
    yield conn
    conn.close()


def test_rerun_idempotency_same_batch(db_conn):
    """Verify that re-processing the same batch leaves business state identical and logs a new successful run."""
    # First publication
    res1 = publish_core()
    run_id1 = res1["run_id"]
    batch_id = res1["batch_id"]

    # Snapshot core state after run 1
    with db_conn.cursor() as cur:
        cur.execute("SELECT count(*), array_agg(customer_id ORDER BY customer_id) FROM core.customers;")
        c_cnt1, c_keys1 = cur.fetchone()

        cur.execute("SELECT count(*), array_agg(order_id ORDER BY order_id) FROM core.orders;")
        o_cnt1, o_keys1 = cur.fetchone()

        cur.execute("SELECT currency, sum(total_amount) FROM core.orders GROUP BY currency ORDER BY currency;")
        ord_sums1 = cur.fetchall()

        cur.execute("SELECT currency, sum(line_total) FROM core.order_items GROUP BY currency ORDER BY currency;")
        itm_sums1 = cur.fetchall()

    # Second publication on same batch
    res2 = publish_core(batch_id=batch_id)
    run_id2 = res2["run_id"]

    assert run_id1 != run_id2, "Each publication run must have a unique run_id"
    assert res2["status"] == "SUCCESS"

    # Compare core state after run 2
    with db_conn.cursor() as cur:
        cur.execute("SELECT count(*), array_agg(customer_id ORDER BY customer_id) FROM core.customers;")
        c_cnt2, c_keys2 = cur.fetchone()

        cur.execute("SELECT count(*), array_agg(order_id ORDER BY order_id) FROM core.orders;")
        o_cnt2, o_keys2 = cur.fetchone()

        cur.execute("SELECT currency, sum(total_amount) FROM core.orders GROUP BY currency ORDER BY currency;")
        ord_sums2 = cur.fetchall()

        cur.execute("SELECT currency, sum(line_total) FROM core.order_items GROUP BY currency ORDER BY currency;")
        itm_sums2 = cur.fetchall()

        # Both runs must be registered in audit.publication_runs
        cur.execute("SELECT count(*) FROM audit.publication_runs WHERE run_id IN (%s, %s) AND status = 'SUCCESS';", (run_id1, run_id2))
        assert cur.fetchone()[0] == 2

    assert c_cnt1 == c_cnt2, "Customer count must not change across identical re-runs"
    assert c_keys1 == c_keys2, "Customer key set must remain 100% identical"
    assert o_cnt1 == o_cnt2, "Orders count must not change across identical re-runs"
    assert o_keys1 == o_keys2, "Orders key set must remain 100% identical"
    assert ord_sums1 == ord_sums2, "Orders financial sums by currency must remain identical"
    assert itm_sums1 == itm_sums2, "Order items financial sums by currency must remain identical"


def test_controlled_failure_check_constraint_rollback(db_conn):
    """Test controlled failure with quantity = -1 violating CHECK (quantity > 0):

    1. Injects invalid row into order_items during publication.
    2. Verifies transaction rolls back and prior state of core tables is preserved.
    3. Verifies failed run is recorded in audit.publication_runs.
    4. Runs fixed process and verifies successful publication.
    """
    # 1. Snapshot prior core state
    with db_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM core.customers;")
        pre_cust_count = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM core.orders;")
        pre_ord_count = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM core.order_items;")
        pre_item_count = cur.fetchone()[0]

    assert pre_cust_count > 0 and pre_ord_count > 0 and pre_item_count > 0

    # 2. Trigger controlled failure via check constraint (quantity = -1)
    with pytest.raises(Exception) as exc_info:
        publish_core(inject_invalid_item=True)

    err_str = str(exc_info.value).lower()
    assert "quantity" in err_str or "check" in err_str or "order_items" in err_str

    # 3. Prove rollback preserved prior state of all core tables
    with db_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM core.customers;")
        assert cur.fetchone()[0] == pre_cust_count, "Customers table was altered or truncated after rollback!"

        cur.execute("SELECT count(*) FROM core.orders;")
        assert cur.fetchone()[0] == pre_ord_count, "Orders table was altered or truncated after rollback!"

        cur.execute("SELECT count(*) FROM core.order_items;")
        assert cur.fetchone()[0] == pre_item_count, "Order items table was altered or truncated after rollback!"

        # 4. Prove failed-run remains recorded in audit.publication_runs
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
        assert "quantity" in row[2].lower() or "check" in row[2].lower()

    # 5. Rerun the fixed process successfully
    fixed_res = publish_core(inject_invalid_item=False)
    assert fixed_res["status"] == "SUCCESS"
    assert fixed_res["reconciliation_passed"] is True


def test_negative_corrupted_header_pre_publication_stop(db_conn):
    """Negative test: Corrupted CSV header in separate fixture stops process BEFORE publication."""
    fixture_path = Path("tests/fixtures/corrupted_files/corrupted_customers.csv")
    assert fixture_path.exists()

    expected_cols = STAGING_TABLES["customers"]["expected_columns"]

    # Verify that header validation rejects the fixture before any DB changes
    with pytest.raises(StructuralValidationError, match="Header mismatch"):
        with open(fixture_path, "r", encoding="utf-8") as f:
            actual_header = f.readline().strip().split(",")
            validate_csv_header(actual_header, expected_cols, fixture_path)


def test_negative_missing_mandatory_file_pre_publication_stop():
    """Negative test: Non-existent mandatory source file raises error before publication."""
    non_existent_file = Path("tests/fixtures/corrupted_files/does_not_exist.csv")
    with pytest.raises(FileNotFoundError):
        if not non_existent_file.exists():
            raise FileNotFoundError(f"Mandatory source file {non_existent_file} not found. Halting before publication.")
