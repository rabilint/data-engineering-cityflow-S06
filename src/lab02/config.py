"""Configuration and schema definitions for Lab 02 staging loader."""

import os
from pathlib import Path

# Base Paths
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_RAW_BASE = PROJECT_ROOT / "data" / "raw" / "base"
DATA_RAW_RELATIONAL = PROJECT_ROOT / "data" / "raw" / "relational"

# Load .env file if it exists
env_path = PROJECT_ROOT / ".env"
if env_path.exists():
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))
    except Exception:
        pass

# Database Configuration (supports env vars with fallback to standard local postgres settings)
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "5432")),
    "dbname": os.getenv("DB_NAME", "cityflow_db"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", "postgres"),
}

# Table Mapping and Strict Column Ordering Definitions
STAGING_TABLES = {
    "customers": {
        "file_path": DATA_RAW_BASE / "customers.csv",
        "target_table": "stg.customers",
        "expected_columns": [
            "customer_id",
            "full_name",
            "email",
            "phone",
            "city",
            "service_zone_id",
            "registered_at",
            "customer_status",
        ],
    },
    "merchants": {
        "file_path": DATA_RAW_BASE / "merchants.csv",
        "target_table": "stg.merchants",
        "expected_columns": [
            "merchant_id",
            "merchant_name",
            "merchant_type",
            "city",
            "service_zone_id",
            "opened_at",
            "merchant_status",
        ],
    },
    "products": {
        "file_path": DATA_RAW_BASE / "products.csv",
        "target_table": "stg.products",
        "expected_columns": [
            "product_id",
            "merchant_id",
            "product_name",
            "category",
            "unit_price_uah",
            "is_active",
            "updated_at",
        ],
    },
    "orders": {
        "file_path": DATA_RAW_BASE / "orders.csv",
        "target_table": "stg.orders",
        "expected_columns": [
            "order_id",
            "customer_id",
            "merchant_id",
            "created_at",
            "order_status",
            "currency",
            "subtotal_amount",
            "delivery_fee",
            "discount_amount",
            "total_amount",
        ],
    },
    "order_items": {
        "file_path": DATA_RAW_RELATIONAL / "order_items.csv",
        "target_table": "stg.order_items",
        "expected_columns": [
            "order_item_id",
            "order_id",
            "product_id",
            "quantity",
            "unit_price",
            "line_discount",
            "line_total",
            "currency",
        ],
    },
    # Additional relational extension tables (optional / available)
    "couriers": {
        "file_path": DATA_RAW_RELATIONAL / "couriers.csv",
        "target_table": "stg.couriers",
        "expected_columns": [
            "courier_id",
            "full_name",
            "city",
            "home_service_zone_id",
            "hired_at",
            "courier_status",
            "vehicle_type",
        ],
    },
    "deliveries": {
        "file_path": DATA_RAW_RELATIONAL / "deliveries.csv",
        "target_table": "stg.deliveries",
        "expected_columns": [
            "delivery_id",
            "order_id",
            "courier_id",
            "service_zone_id",
            "assigned_at",
            "picked_up_at",
            "delivered_at",
            "delivery_status",
            "sla_minutes",
            "distance_km",
            "actual_delivery_minutes",
            "delay_minutes",
        ],
    },
    "payments": {
        "file_path": DATA_RAW_RELATIONAL / "payments.csv",
        "target_table": "stg.payments",
        "expected_columns": [
            "payment_id",
            "order_id",
            "payment_method",
            "payment_status",
            "authorized_at",
            "captured_at",
            "amount",
            "currency",
            "provider_reference",
        ],
    },
    "refunds": {
        "file_path": DATA_RAW_RELATIONAL / "refunds.csv",
        "target_table": "stg.refunds",
        "expected_columns": [
            "refund_id",
            "payment_id",
            "order_id",
            "refund_type",
            "refund_status",
            "amount",
            "currency",
            "reason",
            "requested_at",
            "completed_at",
        ],
    },
    "service_zones": {
        "file_path": DATA_RAW_RELATIONAL / "service_zones.csv",
        "target_table": "stg.service_zones",
        "expected_columns": [
            "service_zone_id",
            "city",
            "zone_name",
            "base_delivery_fee_uah",
            "sla_minutes",
            "traffic_factor",
            "timezone",
        ],
    },
}
