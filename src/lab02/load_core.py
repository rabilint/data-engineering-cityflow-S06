"""Core Model Acceptance and Transformation Pipeline (Lab 02, Tasks 4 & 5).

This module implements the strict educational acceptance contract for transforming
staging data (stg.*) into the normalized core domain model (core.*) and recording
an individual audit decision for EVERY input CSV record (Task 5):
1. Types & NULLs:
   - Primary Keys as text (non-empty).
   - Quantity as integer (> 0).
   - Amounts as numeric(12,2) (>= 0).
   - Timestamps as timestamptz.
   - Rejects empty keys and invalid/unparsable dates.
   - Missing optional phone is nullable (not an error).
   - Unknown numbers are kept NULL (not coerced to 0).
2. Dates:
   - ISO 8601 with offset/Z.
   - Generator format DD/MM/YYYY HH:MM is explicitly assigned UTC.
   - Sub-microsecond fractions (nanoseconds) are truncated to microseconds for timestamptz (preserved in stg).
3. Amounts & Categories:
   - Allowed currencies: {'UAH', 'USD', 'EUR'}.
   - Invalid currency code 'UA H' is NOT guessed or corrected; it is rejected.
   - Active products (is_active=True) with unit_price_uah <= 0 are rejected.
   - Inactive products (is_active=False) with unit_price_uah == 0 are accepted.
   - Whitespace trimming on text fields; lowercase on category/merchant_type.
4. Deduplication & Conflict Resolution:
   - Exact business duplicates: 1 copy accepted, other copies marked as duplicate.
   - Conflicting keys (same PK with different business values): ENTIRE GROUP REJECTED as KEY_CONFLICT_DIFFERENT_VALUES.
   - Technical metadata (batch_id, source_file, source_row_number, loaded_at) excluded from comparison.
5. Foreign Key Integrity:
   - Explicit parent checking: products -> merchants, orders -> customers & merchants, order_items -> orders & products.
   - Orphan rows or rows pointing to rejected parents are explicitly accounted for in audit.record_decisions.
   - No silent drops via unmonitored INNER JOIN.
6. Task 5: Decision Logging for Every Input:
   - Every staging record receives exactly one final status: 'accepted', 'rejected', or 'duplicate'.
   - Stored in audit.record_decisions: batch_id, source_file, source_row_number, business_key, final_status, reason_codes, details, payload.
   - Multiple rejection reasons are stored as a list (reason_codes).
   - Raw records are never deleted from stg.*.
"""

import argparse
import datetime
import json
import logging
import re
import sys
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Set, Tuple

import psycopg2
from psycopg2.extras import execute_values, Json

from src.lab02.config import DB_CONFIG

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("CoreTransformer")

ALLOWED_CURRENCIES: Set[str] = {"UAH", "USD", "EUR"}


def parse_acceptance_timestamp(dt_str: Optional[str]) -> Optional[datetime.datetime]:
    """Parses timestamp according to acceptance rules:

    - ISO 8601 with offset/Z.
    - DD/MM/YYYY HH:MM explicitly treated as UTC.
    - Nanoseconds truncated to microseconds for PostgreSQL timestamptz.
    - Returns None if unparsable.
    """
    if not dt_str or not dt_str.strip():
        return None
    val = dt_str.strip()

    # 1. Generator non-standard format DD/MM/YYYY HH:MM -> explicit UTC
    if "/" in val:
        try:
            return datetime.datetime.strptime(val, "%d/%m/%Y %H:%M").replace(tzinfo=datetime.timezone.utc)
        except Exception:
            return None

    # 2. ISO 8601 with nanoseconds or standard
    try:
        m = re.match(r"^(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})\.(\d+)(Z|[+-]\d{2}:?\d{2})?$", val)
        if m:
            base, frac, tz = m.groups()
            frac6 = frac[:6]  # policy: truncate nanoseconds to microseconds
            tz_str = tz if tz else ""
            if tz_str == "Z":
                tz_str = "+00:00"
            return datetime.datetime.fromisoformat(f"{base}.{frac6}{tz_str}")
        iso_val = val.replace("Z", "+00:00")
        return datetime.datetime.fromisoformat(iso_val)
    except Exception:
        return None


def parse_numeric(val_str: Optional[str]) -> Optional[Decimal]:
    """Parses numeric(12,2). Returns None if missing/unknown (no zero coercion)."""
    if val_str is None or val_str.strip() == "":
        return None
    try:
        d = Decimal(val_str.strip())
        return d.quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError):
        return None


def get_db_connection(custom_config: Optional[Dict] = None):
    config = dict(custom_config or DB_CONFIG)
    try:
        return psycopg2.connect(**config)
    except Exception as e:
        raise ConnectionError(f"Database connection error: {e}")


def transform_customers(
    conn, batch_id: str
) -> Tuple[List[Tuple], List[Tuple], Set[str]]:
    """Transforms stg.customers -> core.customers with full decision tracking for every row."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT source_row_number, customer_id, full_name, email, phone, city, service_zone_id, registered_at, customer_status
            FROM stg.customers
            WHERE batch_id = %s
            ORDER BY source_row_number;
            """,
            (batch_id,),
        )
        stg_rows = cur.fetchall()

    core_records: List[Tuple] = []
    decisions: List[Tuple] = []
    accepted_ids: Set[str] = set()

    grouped: Dict[str, List[Any]] = {}
    for r in stg_rows:
        cid = (r[1] or "").strip()
        grouped.setdefault(cid, []).append(r)

    for cid, rows in grouped.items():
        # Check empty key
        if not cid:
            for r in rows:
                payload = {
                    "source_row_number": r[0], "customer_id": r[1], "full_name": r[2],
                    "email": r[3], "phone": r[4], "city": r[5], "service_zone_id": r[6],
                    "registered_at": r[7], "customer_status": r[8]
                }
                decisions.append((
                    batch_id, "customers.csv", r[0], cid or None, "rejected",
                    ["EMPTY_PRIMARY_KEY"], "customer_id is empty or null", Json(payload)
                ))
            continue

        # Check key collision / duplicate
        if len(rows) > 1:
            norm_copies = [
                ((r[2] or "").strip(), (r[3] or "").strip(), (r[4] or "").strip(), (r[5] or "").strip(), (r[7] or "").strip())
                for r in rows
            ]
            if len(set(norm_copies)) > 1:
                # Conflicting business values -> REJECT ALL
                for r in rows:
                    payload = {
                        "source_row_number": r[0], "customer_id": r[1], "full_name": r[2],
                        "email": r[3], "phone": r[4], "city": r[5], "service_zone_id": r[6],
                        "registered_at": r[7], "customer_status": r[8]
                    }
                    decisions.append((
                        batch_id, "customers.csv", r[0], cid, "rejected",
                        ["KEY_CONFLICT_DIFFERENT_VALUES"],
                        f"Customer {cid} has conflicting values across rows without authoritative version",
                        Json(payload)
                    ))
                continue
            else:
                # Exact duplicates -> 1st accepted, others marked as duplicate
                first_row = rows[0]
                for r in rows[1:]:
                    payload = {
                        "source_row_number": r[0], "customer_id": r[1], "full_name": r[2],
                        "email": r[3], "phone": r[4], "city": r[5], "service_zone_id": r[6],
                        "registered_at": r[7], "customer_status": r[8]
                    }
                    decisions.append((
                        batch_id, "customers.csv", r[0], cid, "duplicate",
                        ["DUPLICATE_BUSINESS_COPY"],
                        f"Exact duplicate business copy of customer {cid}",
                        Json(payload)
                    ))
                rows = [first_row]

        # Validate candidate
        r = rows[0]
        payload = {
            "source_row_number": r[0], "customer_id": r[1], "full_name": r[2],
            "email": r[3], "phone": r[4], "city": r[5], "service_zone_id": r[6],
            "registered_at": r[7], "customer_status": r[8]
        }
        full_name = (r[2] or "").strip()
        city = (r[5] or "").strip()
        reg_at = parse_acceptance_timestamp(r[7])

        rejection_reasons = []
        details_list = []
        if not full_name:
            rejection_reasons.append("EMPTY_REQUIRED_FIELD")
            details_list.append("full_name is missing or empty")
        if not city:
            rejection_reasons.append("EMPTY_REQUIRED_FIELD")
            details_list.append("city is missing or empty")
        if reg_at is None:
            rejection_reasons.append("INVALID_DATE")
            details_list.append(f"registered_at '{r[7]}' cannot be parsed as valid timestamp")

        if rejection_reasons:
            decisions.append((
                batch_id, "customers.csv", r[0], cid, "rejected",
                rejection_reasons, "; ".join(details_list), Json(payload)
            ))
            continue

        core_records.append((cid, full_name, city, reg_at))
        accepted_ids.add(cid)
        decisions.append((
            batch_id, "customers.csv", r[0], cid, "accepted",
            ["ACCEPTED"], "Valid customer record accepted into core", Json(payload)
        ))

    return core_records, decisions, accepted_ids


def transform_merchants(
    conn, batch_id: str
) -> Tuple[List[Tuple], List[Tuple], Set[str]]:
    """Transforms stg.merchants -> core.merchants with full decision tracking for every row."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT source_row_number, merchant_id, merchant_name, merchant_type, city, service_zone_id, opened_at, merchant_status
            FROM stg.merchants
            WHERE batch_id = %s
            ORDER BY source_row_number;
            """,
            (batch_id,),
        )
        stg_rows = cur.fetchall()

    core_records: List[Tuple] = []
    decisions: List[Tuple] = []
    accepted_ids: Set[str] = set()

    grouped: Dict[str, List[Any]] = {}
    for r in stg_rows:
        mid = (r[1] or "").strip()
        grouped.setdefault(mid, []).append(r)

    for mid, rows in grouped.items():
        if not mid:
            for r in rows:
                payload = {
                    "source_row_number": r[0], "merchant_id": r[1], "merchant_name": r[2],
                    "merchant_type": r[3], "city": r[4], "service_zone_id": r[5],
                    "opened_at": r[6], "merchant_status": r[7]
                }
                decisions.append((
                    batch_id, "merchants.csv", r[0], mid or None, "rejected",
                    ["EMPTY_PRIMARY_KEY"], "merchant_id is empty or null", Json(payload)
                ))
            continue

        if len(rows) > 1:
            norm_copies = [
                ((r[2] or "").strip(), (r[3] or "").strip().lower(), (r[4] or "").strip(), (r[7] or "").strip().lower())
                for r in rows
            ]
            if len(set(norm_copies)) > 1:
                for r in rows:
                    payload = {
                        "source_row_number": r[0], "merchant_id": r[1], "merchant_name": r[2],
                        "merchant_type": r[3], "city": r[4], "service_zone_id": r[5],
                        "opened_at": r[6], "merchant_status": r[7]
                    }
                    decisions.append((
                        batch_id, "merchants.csv", r[0], mid, "rejected",
                        ["KEY_CONFLICT_DIFFERENT_VALUES"],
                        f"Merchant {mid} has conflicting values across rows without authoritative version",
                        Json(payload)
                    ))
                continue
            else:
                first_row = rows[0]
                for r in rows[1:]:
                    payload = {
                        "source_row_number": r[0], "merchant_id": r[1], "merchant_name": r[2],
                        "merchant_type": r[3], "city": r[4], "service_zone_id": r[5],
                        "opened_at": r[6], "merchant_status": r[7]
                    }
                    decisions.append((
                        batch_id, "merchants.csv", r[0], mid, "duplicate",
                        ["DUPLICATE_BUSINESS_COPY"],
                        f"Exact duplicate business copy of merchant {mid}",
                        Json(payload)
                    ))
                rows = [first_row]

        r = rows[0]
        payload = {
            "source_row_number": r[0], "merchant_id": r[1], "merchant_name": r[2],
            "merchant_type": r[3], "city": r[4], "service_zone_id": r[5],
            "opened_at": r[6], "merchant_status": r[7]
        }
        merchant_name = (r[2] or "").strip()
        city = (r[4] or "").strip()
        opened_at = parse_acceptance_timestamp(r[6])

        rejection_reasons = []
        details_list = []
        if not merchant_name:
            rejection_reasons.append("EMPTY_REQUIRED_FIELD")
            details_list.append("merchant_name is missing or empty")
        if not city:
            rejection_reasons.append("EMPTY_REQUIRED_FIELD")
            details_list.append("city is missing or empty")
        if opened_at is None:
            rejection_reasons.append("INVALID_DATE")
            details_list.append(f"opened_at '{r[6]}' cannot be parsed as valid timestamp")

        if rejection_reasons:
            decisions.append((
                batch_id, "merchants.csv", r[0], mid, "rejected",
                rejection_reasons, "; ".join(details_list), Json(payload)
            ))
            continue

        core_records.append((mid, merchant_name, city, opened_at))
        accepted_ids.add(mid)
        decisions.append((
            batch_id, "merchants.csv", r[0], mid, "accepted",
            ["ACCEPTED"], "Valid merchant record accepted into core", Json(payload)
        ))

    return core_records, decisions, accepted_ids


def transform_products(
    conn, batch_id: str, valid_merchant_ids: Set[str]
) -> Tuple[List[Tuple], List[Tuple], Set[str]]:
    """Transforms stg.products -> core.products with full decision tracking for every row."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT source_row_number, product_id, merchant_id, product_name, category, unit_price_uah, is_active, updated_at
            FROM stg.products
            WHERE batch_id = %s
            ORDER BY source_row_number;
            """,
            (batch_id,),
        )
        stg_rows = cur.fetchall()

    core_records: List[Tuple] = []
    decisions: List[Tuple] = []
    accepted_ids: Set[str] = set()

    grouped: Dict[str, List[Any]] = {}
    for r in stg_rows:
        pid = (r[1] or "").strip()
        grouped.setdefault(pid, []).append(r)

    for pid, rows in grouped.items():
        if not pid:
            for r in rows:
                payload = {
                    "source_row_number": r[0], "product_id": r[1], "merchant_id": r[2],
                    "product_name": r[3], "category": r[4], "unit_price_uah": r[5],
                    "is_active": r[6], "updated_at": r[7]
                }
                decisions.append((
                    batch_id, "products.csv", r[0], pid or None, "rejected",
                    ["EMPTY_PRIMARY_KEY"], "product_id is empty or null", Json(payload)
                ))
            continue

        if len(rows) > 1:
            norm_copies = [
                ((r[2] or "").strip(), (r[3] or "").strip(), (r[4] or "").strip().lower(), (r[5] or "").strip(), str(r[6]).strip().lower())
                for r in rows
            ]
            if len(set(norm_copies)) > 1:
                for r in rows:
                    payload = {
                        "source_row_number": r[0], "product_id": r[1], "merchant_id": r[2],
                        "product_name": r[3], "category": r[4], "unit_price_uah": r[5],
                        "is_active": r[6], "updated_at": r[7]
                    }
                    decisions.append((
                        batch_id, "products.csv", r[0], pid, "rejected",
                        ["KEY_CONFLICT_DIFFERENT_VALUES"],
                        f"Product {pid} has conflicting values across rows without authoritative version",
                        Json(payload)
                    ))
                continue
            else:
                first_row = rows[0]
                for r in rows[1:]:
                    payload = {
                        "source_row_number": r[0], "product_id": r[1], "merchant_id": r[2],
                        "product_name": r[3], "category": r[4], "unit_price_uah": r[5],
                        "is_active": r[6], "updated_at": r[7]
                    }
                    decisions.append((
                        batch_id, "products.csv", r[0], pid, "duplicate",
                        ["DUPLICATE_BUSINESS_COPY"],
                        f"Exact duplicate business copy of product {pid}",
                        Json(payload)
                    ))
                rows = [first_row]

        r = rows[0]
        payload = {
            "source_row_number": r[0], "product_id": r[1], "merchant_id": r[2],
            "product_name": r[3], "category": r[4], "unit_price_uah": r[5],
            "is_active": r[6], "updated_at": r[7]
        }
        merchant_id = (r[2] or "").strip()
        product_name = (r[3] or "").strip()
        price_val = parse_numeric(r[5])
        is_active_str = str(r[6]).strip().lower()
        is_active = is_active_str in ("true", "1", "t", "yes")

        rejection_reasons = []
        details_list = []

        if merchant_id not in valid_merchant_ids:
            rejection_reasons.append("ORPHAN_FK_PARENT")
            details_list.append(f"merchant_id '{merchant_id}' not found in core.merchants")

        if not product_name:
            rejection_reasons.append("EMPTY_REQUIRED_FIELD")
            details_list.append("product_name is missing or empty")

        if price_val is None:
            rejection_reasons.append("INVALID_AMOUNT")
            details_list.append(f"unit_price_uah '{r[5]}' is not a valid number")
        elif price_val < Decimal("0.00"):
            rejection_reasons.append("NEGATIVE_AMOUNT")
            details_list.append(f"unit_price_uah {price_val} is negative")
        elif is_active and price_val <= Decimal("0.00"):
            # Rule: Active product with unit_price_uah <= 0 rejected
            rejection_reasons.append("ACTIVE_PRODUCT_ZERO_PRICE")
            details_list.append(f"Active product {pid} has unit_price_uah = {price_val} <= 0")

        if rejection_reasons:
            decisions.append((
                batch_id, "products.csv", r[0], pid, "rejected",
                rejection_reasons, "; ".join(details_list), Json(payload)
            ))
            continue

        core_records.append((pid, merchant_id, product_name, price_val, is_active))
        accepted_ids.add(pid)
        decisions.append((
            batch_id, "products.csv", r[0], pid, "accepted",
            ["ACCEPTED"], "Valid product record accepted into core", Json(payload)
        ))

    return core_records, decisions, accepted_ids


def transform_orders(
    conn, batch_id: str, valid_customer_ids: Set[str], valid_merchant_ids: Set[str]
) -> Tuple[List[Tuple], List[Tuple], Set[str]]:
    """Transforms stg.orders -> core.orders with full decision tracking for every row."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT source_row_number, order_id, customer_id, merchant_id, created_at, order_status, currency, subtotal_amount, delivery_fee, discount_amount, total_amount
            FROM stg.orders
            WHERE batch_id = %s
            ORDER BY source_row_number;
            """,
            (batch_id,),
        )
        stg_rows = cur.fetchall()

    core_records: List[Tuple] = []
    decisions: List[Tuple] = []
    accepted_ids: Set[str] = set()

    grouped: Dict[str, List[Any]] = {}
    for r in stg_rows:
        oid = (r[1] or "").strip()
        grouped.setdefault(oid, []).append(r)

    for oid, rows in grouped.items():
        if not oid:
            for r in rows:
                payload = {
                    "source_row_number": r[0], "order_id": r[1], "customer_id": r[2],
                    "merchant_id": r[3], "created_at": r[4], "order_status": r[5],
                    "currency": r[6], "subtotal_amount": r[7], "delivery_fee": r[8],
                    "discount_amount": r[9], "total_amount": r[10]
                }
                decisions.append((
                    batch_id, "orders.csv", r[0], oid or None, "rejected",
                    ["EMPTY_PRIMARY_KEY"], "order_id is empty or null", Json(payload)
                ))
            continue

        if len(rows) > 1:
            norm_copies = [
                ((r[2] or "").strip(), (r[3] or "").strip(), (r[4] or "").strip(), (r[5] or "").strip().lower(), (r[6] or "").strip(), (r[10] or "").strip())
                for r in rows
            ]
            if len(set(norm_copies)) > 1:
                for r in rows:
                    payload = {
                        "source_row_number": r[0], "order_id": r[1], "customer_id": r[2],
                        "merchant_id": r[3], "created_at": r[4], "order_status": r[5],
                        "currency": r[6], "subtotal_amount": r[7], "delivery_fee": r[8],
                        "discount_amount": r[9], "total_amount": r[10]
                    }
                    decisions.append((
                        batch_id, "orders.csv", r[0], oid, "rejected",
                        ["KEY_CONFLICT_DIFFERENT_VALUES"],
                        f"Order {oid} has conflicting values across rows without authoritative version",
                        Json(payload)
                    ))
                continue
            else:
                first_row = rows[0]
                for r in rows[1:]:
                    payload = {
                        "source_row_number": r[0], "order_id": r[1], "customer_id": r[2],
                        "merchant_id": r[3], "created_at": r[4], "order_status": r[5],
                        "currency": r[6], "subtotal_amount": r[7], "delivery_fee": r[8],
                        "discount_amount": r[9], "total_amount": r[10]
                    }
                    decisions.append((
                        batch_id, "orders.csv", r[0], oid, "duplicate",
                        ["DUPLICATE_BUSINESS_COPY"],
                        f"Exact duplicate business copy of order {oid}",
                        Json(payload)
                    ))
                rows = [first_row]

        r = rows[0]
        payload = {
            "source_row_number": r[0], "order_id": r[1], "customer_id": r[2],
            "merchant_id": r[3], "created_at": r[4], "order_status": r[5],
            "currency": r[6], "subtotal_amount": r[7], "delivery_fee": r[8],
            "discount_amount": r[9], "total_amount": r[10]
        }
        customer_id = (r[2] or "").strip()
        merchant_id = (r[3] or "").strip()
        raw_created_at = r[4]
        order_status = (r[5] or "").strip().lower()
        currency = (r[6] or "").strip()
        subtotal = parse_numeric(r[7])
        delivery_fee = parse_numeric(r[8]) if r[8] is not None and str(r[8]).strip() != "" else Decimal("0.00")
        discount_amount = parse_numeric(r[9]) if r[9] is not None and str(r[9]).strip() != "" else Decimal("0.00")
        total_amount = parse_numeric(r[10])

        rejection_reasons = []
        details_list = []

        # Date validation
        created_at = parse_acceptance_timestamp(raw_created_at)
        if created_at is None:
            rejection_reasons.append("INVALID_DATE")
            details_list.append(f"created_at '{raw_created_at}' is invalid")

        # Currency validation: 'UA H' must not be guessed
        if currency not in ALLOWED_CURRENCIES:
            rejection_reasons.append("INVALID_CURRENCY")
            details_list.append(f"currency '{currency}' not in {ALLOWED_CURRENCIES}")

        # FK checks
        if customer_id not in valid_customer_ids:
            rejection_reasons.append("ORPHAN_FK_PARENT")
            details_list.append(f"customer_id '{customer_id}' not found in core.customers")

        if merchant_id not in valid_merchant_ids:
            rejection_reasons.append("ORPHAN_FK_PARENT")
            details_list.append(f"merchant_id '{merchant_id}' not found in core.merchants")

        # Amount checks
        if subtotal is None or subtotal < Decimal("0.00"):
            rejection_reasons.append("NEGATIVE_AMOUNT")
            details_list.append(f"subtotal_amount '{r[7]}' is invalid or negative")
        if total_amount is None or total_amount < Decimal("0.00"):
            rejection_reasons.append("NEGATIVE_AMOUNT")
            details_list.append(f"total_amount '{r[10]}' is invalid or negative")
        if delivery_fee is not None and delivery_fee < Decimal("0.00"):
            rejection_reasons.append("NEGATIVE_AMOUNT")
            details_list.append(f"delivery_fee '{r[8]}' is negative")
        if discount_amount is not None and discount_amount < Decimal("0.00"):
            rejection_reasons.append("NEGATIVE_AMOUNT")
            details_list.append(f"discount_amount '{r[9]}' is negative")

        if rejection_reasons:
            decisions.append((
                batch_id, "orders.csv", r[0], oid, "rejected",
                rejection_reasons, "; ".join(details_list), Json(payload)
            ))
            continue

        core_records.append((
            oid, customer_id, merchant_id, created_at, order_status, currency,
            subtotal, delivery_fee, discount_amount, total_amount
        ))
        accepted_ids.add(oid)
        decisions.append((
            batch_id, "orders.csv", r[0], oid, "accepted",
            ["ACCEPTED"], "Valid order record accepted into core", Json(payload)
        ))

    return core_records, decisions, accepted_ids


def transform_order_items(
    conn, batch_id: str, valid_order_ids: Set[str], valid_product_ids: Set[str]
) -> Tuple[List[Tuple], List[Tuple], Set[str]]:
    """Transforms stg.order_items -> core.order_items with full decision tracking for every row."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT source_row_number, order_item_id, order_id, product_id, quantity, unit_price, line_discount, line_total, currency
            FROM stg.order_items
            WHERE batch_id = %s
            ORDER BY source_row_number;
            """,
            (batch_id,),
        )
        stg_rows = cur.fetchall()

    core_records: List[Tuple] = []
    decisions: List[Tuple] = []
    accepted_ids: Set[str] = set()

    grouped: Dict[str, List[Any]] = {}
    for r in stg_rows:
        iid = (r[1] or "").strip()
        grouped.setdefault(iid, []).append(r)

    for iid, rows in grouped.items():
        if not iid:
            for r in rows:
                payload = {
                    "source_row_number": r[0], "order_item_id": r[1], "order_id": r[2],
                    "product_id": r[3], "quantity": r[4], "unit_price": r[5],
                    "line_discount": r[6], "line_total": r[7], "currency": r[8]
                }
                decisions.append((
                    batch_id, "order_items.csv", r[0], iid or None, "rejected",
                    ["EMPTY_PRIMARY_KEY"], "order_item_id is empty or null", Json(payload)
                ))
            continue

        if len(rows) > 1:
            norm_copies = [
                ((r[2] or "").strip(), (r[3] or "").strip(), (r[4] or "").strip(), (r[5] or "").strip(), (r[7] or "").strip(), (r[8] or "").strip())
                for r in rows
            ]
            if len(set(norm_copies)) > 1:
                for r in rows:
                    payload = {
                        "source_row_number": r[0], "order_item_id": r[1], "order_id": r[2],
                        "product_id": r[3], "quantity": r[4], "unit_price": r[5],
                        "line_discount": r[6], "line_total": r[7], "currency": r[8]
                    }
                    decisions.append((
                        batch_id, "order_items.csv", r[0], iid, "rejected",
                        ["KEY_CONFLICT_DIFFERENT_VALUES"],
                        f"Order item {iid} has conflicting values across rows without authoritative version",
                        Json(payload)
                    ))
                continue
            else:
                first_row = rows[0]
                for r in rows[1:]:
                    payload = {
                        "source_row_number": r[0], "order_item_id": r[1], "order_id": r[2],
                        "product_id": r[3], "quantity": r[4], "unit_price": r[5],
                        "line_discount": r[6], "line_total": r[7], "currency": r[8]
                    }
                    decisions.append((
                        batch_id, "order_items.csv", r[0], iid, "duplicate",
                        ["DUPLICATE_BUSINESS_COPY"],
                        f"Exact duplicate business copy of order_item {iid}",
                        Json(payload)
                    ))
                rows = [first_row]

        r = rows[0]
        payload = {
            "source_row_number": r[0], "order_item_id": r[1], "order_id": r[2],
            "product_id": r[3], "quantity": r[4], "unit_price": r[5],
            "line_discount": r[6], "line_total": r[7], "currency": r[8]
        }
        order_id = (r[2] or "").strip()
        product_id = (r[3] or "").strip()
        try:
            quantity = int(r[4])
        except (ValueError, TypeError):
            quantity = None
        unit_price = parse_numeric(r[5])
        line_discount = parse_numeric(r[6]) if r[6] is not None and str(r[6]).strip() != "" else Decimal("0.00")
        line_total = parse_numeric(r[7])
        currency = (r[8] or "").strip()

        rejection_reasons = []
        details_list = []

        if order_id not in valid_order_ids:
            rejection_reasons.append("ORPHAN_FK_PARENT")
            details_list.append(f"order_id '{order_id}' not found in core.orders")

        if product_id not in valid_product_ids:
            rejection_reasons.append("ORPHAN_FK_PARENT")
            details_list.append(f"product_id '{product_id}' not found in core.products")

        if currency not in ALLOWED_CURRENCIES:
            rejection_reasons.append("INVALID_CURRENCY")
            details_list.append(f"currency '{currency}' not in {ALLOWED_CURRENCIES}")

        if quantity is None or quantity <= 0:
            rejection_reasons.append("INVALID_QUANTITY")
            details_list.append(f"quantity '{r[4]}' must be integer > 0")

        if unit_price is None or unit_price < Decimal("0.00"):
            rejection_reasons.append("NEGATIVE_AMOUNT")
            details_list.append(f"unit_price '{r[5]}' is invalid or negative")

        if line_total is None or line_total < Decimal("0.00"):
            rejection_reasons.append("NEGATIVE_AMOUNT")
            details_list.append(f"line_total '{r[7]}' is invalid or negative")

        if rejection_reasons:
            decisions.append((
                batch_id, "order_items.csv", r[0], iid, "rejected",
                rejection_reasons, "; ".join(details_list), Json(payload)
            ))
            continue

        core_records.append((
            iid, order_id, product_id, quantity, unit_price, line_discount, line_total, currency
        ))
        accepted_ids.add(iid)
        decisions.append((
            batch_id, "order_items.csv", r[0], iid, "accepted",
            ["ACCEPTED"], "Valid order item record accepted into core", Json(payload)
        ))

    return core_records, decisions, accepted_ids


def run_core_pipeline(
    batch_id: Optional[str] = None,
    truncate_core: bool = True,
    dry_run: bool = False,
    custom_db_config: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Executes the core transformation pipeline and populates core.* and audit.record_decisions."""
    conn = get_db_connection(custom_db_config)
    try:
        if not batch_id:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT batch_id FROM audit.load_batches WHERE status = 'SUCCESS' ORDER BY completed_at DESC LIMIT 1;"
                )
                row = cur.fetchone()
                if not row:
                    raise RuntimeError("No successful staging batches found in audit.load_batches. Run load_staging first.")
                batch_id = row[0]

        logger.info("==================================================")
        logger.info("Starting Core Transformation for batch: %s", batch_id)
        logger.info("Truncate core tables: %s | Dry-run: %s", truncate_core, dry_run)
        logger.info("==================================================")

        # 1. Customers
        c_core, c_dec, accepted_cust_ids = transform_customers(conn, batch_id)
        # 2. Merchants
        m_core, m_dec, accepted_merch_ids = transform_merchants(conn, batch_id)
        # 3. Products
        p_core, p_dec, accepted_prod_ids = transform_products(conn, batch_id, accepted_merch_ids)
        # 4. Orders
        o_core, o_dec, accepted_order_ids = transform_orders(conn, batch_id, accepted_cust_ids, accepted_merch_ids)
        # 5. Order Items
        oi_core, oi_dec, accepted_item_ids = transform_order_items(conn, batch_id, accepted_order_ids, accepted_prod_ids)

        all_decisions = c_dec + m_dec + p_dec + o_dec + oi_dec

        def count_status(dec_list, status):
            return sum(1 for d in dec_list if d[4] == status)

        logger.info("Customers  : Total = %d | Accepted = %d | Duplicate = %d | Rejected = %d",
                    len(c_dec), count_status(c_dec, 'accepted'), count_status(c_dec, 'duplicate'), count_status(c_dec, 'rejected'))
        logger.info("Merchants  : Total = %d | Accepted = %d | Duplicate = %d | Rejected = %d",
                    len(m_dec), count_status(m_dec, 'accepted'), count_status(m_dec, 'duplicate'), count_status(m_dec, 'rejected'))
        logger.info("Products   : Total = %d | Accepted = %d | Duplicate = %d | Rejected = %d",
                    len(p_dec), count_status(p_dec, 'accepted'), count_status(p_dec, 'duplicate'), count_status(p_dec, 'rejected'))
        logger.info("Orders     : Total = %d | Accepted = %d | Duplicate = %d | Rejected = %d",
                    len(o_dec), count_status(o_dec, 'accepted'), count_status(o_dec, 'duplicate'), count_status(o_dec, 'rejected'))
        logger.info("Order Items: Total = %d | Accepted = %d | Duplicate = %d | Rejected = %d",
                    len(oi_dec), count_status(oi_dec, 'accepted'), count_status(oi_dec, 'duplicate'), count_status(oi_dec, 'rejected'))

        total_accepted = len(c_core) + len(m_core) + len(p_core) + len(o_core) + len(oi_core)
        total_dup = count_status(all_decisions, 'duplicate')
        total_rej = count_status(all_decisions, 'rejected')
        logger.info("--------------------------------------------------")
        logger.info("Total CSV records evaluated: %d", len(all_decisions))
        logger.info("Total Accepted Records     : %d", total_accepted)
        logger.info("Total Duplicate Records    : %d", total_dup)
        logger.info("Total Rejected Records     : %d", total_rej)
        logger.info("--------------------------------------------------")

        if dry_run:
            logger.info("Dry-run complete. No changes made to PostgreSQL.")
            return {
                "batch_id": batch_id,
                "total_decisions": len(all_decisions),
                "accepted": total_accepted,
                "duplicate": total_dup,
                "rejected": total_rej,
            }

        with conn.cursor() as cur:
            if truncate_core:
                logger.info("Truncating core tables and clearing audit decisions for batch %s...", batch_id)
                cur.execute("TRUNCATE TABLE core.order_items, core.orders, core.products, core.customers, core.merchants CASCADE;")
                cur.execute("DELETE FROM audit.record_decisions WHERE batch_id = %s;", (batch_id,))
                cur.execute("DELETE FROM audit.rejected_records WHERE batch_id = %s;", (batch_id,))

            # 1. Insert Record Decisions (Task 5: exactly 1 decision per CSV record)
            logger.info("Inserting %d record decisions into audit.record_decisions...", len(all_decisions))
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

            # 2. Insert into audit.rejected_records for backward compatibility (non-accepted rows)
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

            # 3. Insert into core.* in dependency order
            execute_values(cur, "INSERT INTO core.customers (customer_id, full_name, city, registered_at) VALUES %s;", c_core, page_size=2000)
            execute_values(cur, "INSERT INTO core.merchants (merchant_id, merchant_name, city, opened_at) VALUES %s;", m_core, page_size=2000)
            execute_values(cur, "INSERT INTO core.products (product_id, merchant_id, product_name, unit_price_uah, is_active) VALUES %s;", p_core, page_size=2000)
            execute_values(cur, "INSERT INTO core.orders (order_id, customer_id, merchant_id, created_at, order_status, currency, subtotal_amount, delivery_fee, discount_amount, total_amount) VALUES %s;", o_core, page_size=2000)
            execute_values(cur, "INSERT INTO core.order_items (order_item_id, order_id, product_id, quantity, unit_price, line_discount, line_total, currency) VALUES %s;", oi_core, page_size=2000)

        conn.commit()
        logger.info("Core transformation & decision logging committed successfully!")

        return {
            "batch_id": batch_id,
            "total_decisions": len(all_decisions),
            "accepted": total_accepted,
            "duplicate": total_dup,
            "rejected": total_rej,
        }
    except Exception as e:
        conn.rollback()
        logger.error("Core pipeline failed: %s. Rolled back.", e)
        raise e
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Lab 02 Core Acceptance & Transformation")
    parser.add_argument("--batch-id", default=None, help="Batch ID to transform (defaults to latest successful batch)")
    parser.add_argument("--dry-run", action="store_true", help="Analyze and validate without inserting into core.*")
    parser.add_argument("--no-truncate", action="store_true", help="Do not truncate core tables before loading")
    args = parser.parse_args()

    try:
        run_core_pipeline(batch_id=args.batch_id, truncate_core=not args.no_truncate, dry_run=args.dry_run)
    except Exception as exc:
        logger.error("Execution terminated: %s", exc)
        sys.exit(1)
