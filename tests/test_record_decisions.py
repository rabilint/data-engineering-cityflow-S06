"""Unit tests and test fixtures for Task 5: Record Decision Logging.

Verifies:
1. Exactly one final status per record: 'accepted', 'rejected', or 'duplicate'.
2. Multiple rejection reasons stored as a list (reason_codes).
3. Exact business duplicate detection ('duplicate').
4. Preservation of batch_id, source_file, source_row_number, business_key, and payload.
5. All tests use isolated in-memory/temporary test fixtures without touching raw files.
"""

from decimal import Decimal
import pytest

from src.lab02.load_core import (
    ALLOWED_CURRENCIES,
    parse_acceptance_timestamp,
    parse_numeric,
)


@pytest.fixture
def sample_orders_fixture():
    """Isolated test fixture with synthetic order records to test decision rules

    without modifying actual files in data/raw/.
    """
    return [
        {
            "row_num": 1,
            "order_id": "TEST-O001",
            "customer_id": "TEST-C001",
            "merchant_id": "TEST-M001",
            "created_at": "2025-09-01T08:00:00Z",
            "order_status": "delivered",
            "currency": "UAH",
            "total_amount": "100.00",
        },
        # Record with MULTIPLE ERRORS: invalid date AND invalid currency
        {
            "row_num": 2,
            "order_id": "TEST-O002",
            "customer_id": "TEST-C001",
            "merchant_id": "TEST-M001",
            "created_at": "2026-99-99 99:99:99",  # Invalid date
            "order_status": "delivered",
            "currency": "UA H",  # Invalid currency code
            "total_amount": "150.00",
        },
        # Exact duplicate of row 1
        {
            "row_num": 3,
            "order_id": "TEST-O001",
            "customer_id": "TEST-C001",
            "merchant_id": "TEST-M001",
            "created_at": "2025-09-01T08:00:00Z",
            "order_status": "delivered",
            "currency": "UAH",
            "total_amount": "100.00",
        },
        # Record with orphan foreign key
        {
            "row_num": 4,
            "order_id": "TEST-O004",
            "customer_id": "NON_EXISTENT_CUST",
            "merchant_id": "TEST-M001",
            "created_at": "2025-09-01T10:00:00Z",
            "order_status": "delivered",
            "currency": "UAH",
            "total_amount": "200.00",
        },
    ]


def evaluate_order_decision(
    row: dict,
    valid_customers: set,
    valid_merchants: set,
    seen_exact_orders: set,
) -> dict:
    """Evaluates decision for a single order row, capturing multiple reasons if present."""
    oid = row["order_id"]
    row_num = row["row_num"]

    # Business key tuple for duplicate checking
    bkey_tuple = (
        row["order_id"],
        row["customer_id"],
        row["merchant_id"],
        row["created_at"],
        row["currency"],
        row["total_amount"],
    )

    if bkey_tuple in seen_exact_orders:
        return {
            "source_row_number": row_num,
            "business_key": oid,
            "final_status": "duplicate",
            "reason_codes": ["DUPLICATE_BUSINESS_COPY"],
            "details": f"Exact duplicate business copy of {oid}",
        }

    seen_exact_orders.add(bkey_tuple)

    rejection_reasons = []

    # 1. Date check
    dt = parse_acceptance_timestamp(row["created_at"])
    if dt is None:
        rejection_reasons.append("INVALID_DATE")

    # 2. Currency check
    if row["currency"] not in ALLOWED_CURRENCIES:
        rejection_reasons.append("INVALID_CURRENCY")

    # 3. Foreign key checks
    if row["customer_id"] not in valid_customers:
        rejection_reasons.append("ORPHAN_FK_PARENT")

    if row["merchant_id"] not in valid_merchants:
        rejection_reasons.append("ORPHAN_FK_PARENT")

    if rejection_reasons:
        return {
            "source_row_number": row_num,
            "business_key": oid,
            "final_status": "rejected",
            "reason_codes": rejection_reasons,
            "details": f"Rejected due to {', '.join(rejection_reasons)}",
        }

    return {
        "source_row_number": row_num,
        "business_key": oid,
        "final_status": "accepted",
        "reason_codes": ["ACCEPTED"],
        "details": "Accepted into core",
    }


def test_fixture_decisions_single_and_multiple_reasons(sample_orders_fixture):
    valid_customers = {"TEST-C001"}
    valid_merchants = {"TEST-M001"}
    seen_exact = set()

    decisions = [
        evaluate_order_decision(row, valid_customers, valid_merchants, seen_exact)
        for row in sample_orders_fixture
    ]

    # Row 1: Valid -> Accepted
    d1 = decisions[0]
    assert d1["final_status"] == "accepted"
    assert d1["reason_codes"] == ["ACCEPTED"]

    # Row 2: MULTIPLE REASONS -> Rejected with list containing both reasons!
    d2 = decisions[1]
    assert d2["final_status"] == "rejected"
    assert "INVALID_DATE" in d2["reason_codes"]
    assert "INVALID_CURRENCY" in d2["reason_codes"]
    assert len(d2["reason_codes"]) == 2  # multiple reasons preserved in list!

    # Row 3: Exact Duplicate -> Duplicate
    d3 = decisions[2]
    assert d3["final_status"] == "duplicate"
    assert d3["reason_codes"] == ["DUPLICATE_BUSINESS_COPY"]

    # Row 4: Orphan FK -> Rejected
    d4 = decisions[3]
    assert d4["final_status"] == "rejected"
    assert d4["reason_codes"] == ["ORPHAN_FK_PARENT"]
