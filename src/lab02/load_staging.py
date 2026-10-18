"""Repeatable Staging Data Loader with Strict Structural Validation.

This module loads raw CSV datasets into the PostgreSQL staging schema (stg.*)
ensuring:
1. Zero record loss (including duplicates and dirty rows).
2. All raw business columns are loaded as TEXT.
3. Metadata injection: batch_id, source_file, source_row_number, loaded_at.
4. Strict header and column order verification (fail-fast on mismatch).
5. Strict row structure checking (no silent drop of malformed lines).
6. 100% Parameterized SQL insertion (no string concatenation).
7. Audit tracking in audit.load_batches and audit.load_files.
"""

import argparse
import csv
import datetime
import logging
import sys
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import psycopg2
from psycopg2.extras import execute_values

from src.lab02.config import DB_CONFIG, STAGING_TABLES

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("StagingLoader")


class StructuralValidationError(Exception):
    """Raised when CSV header or row structure is corrupted/invalid."""
    pass


def validate_csv_header(actual_header: List[str], expected_header: List[str], file_path: Path) -> None:
    """Explicitly verify that the CSV header exactly matches expected columns in name and order."""
    # Clean possible BOM or leading/trailing whitespaces in headers
    clean_actual = [col.strip().lstrip("\ufeff") for col in actual_header]
    clean_expected = [col.strip() for col in expected_header]

    if clean_actual != clean_expected:
        raise StructuralValidationError(
            f"Header mismatch in file '{file_path.name}'.\n"
            f"Expected ({len(clean_expected)} columns): {clean_expected}\n"
            f"Actual   ({len(clean_actual)} columns): {clean_actual}"
        )


def read_and_validate_csv(
    file_path: Path,
    expected_columns: List[str],
    batch_id: str,
    source_file_label: str,
) -> Tuple[List[Tuple], int]:
    """Reads CSV file, validates header, checks structural integrity of every line,

    and attaches required metadata columns.
    Returns:
        (rows_to_insert, total_row_count)
    """
    if not file_path.exists():
        raise FileNotFoundError(f"Source file not found: {file_path}")

    rows_to_insert = []
    loaded_at = datetime.datetime.now(datetime.timezone.utc)
    expected_col_count = len(expected_columns)

    with open(file_path, mode="r", encoding="utf-8") as f:
        reader = csv.reader(f)

        try:
            raw_header = next(reader)
        except StopIteration:
            raise StructuralValidationError(f"File '{file_path.name}' is completely empty (no header).")

        validate_csv_header(raw_header, expected_columns, file_path)

        # source_row_number is 1-indexed relative to first record after header
        for source_row_number, row in enumerate(reader, start=1):
            if len(row) != expected_col_count:
                raise StructuralValidationError(
                    f"Structurally broken file '{file_path.name}' at row {source_row_number}: "
                    f"expected {expected_col_count} columns, found {len(row)} columns. Row content: {row}"
                )

            # Metadata prepended: batch_id, source_file, source_row_number, loaded_at
            record = (batch_id, source_file_label, source_row_number, loaded_at, *row)
            rows_to_insert.append(record)

    return rows_to_insert, len(rows_to_insert)


def get_db_connection(custom_config: Optional[Dict] = None):
    """Establishes and returns a PostgreSQL connection with informative error handling."""
    config = dict(custom_config or DB_CONFIG)
    try:
        return psycopg2.connect(**config)
    except UnicodeDecodeError:
        safe_cfg = {k: (v if k != "password" else "***") for k, v in config.items()}
        raise ConnectionError(
            f"\n[Помилка авторизації або підключення до PostgreSQL]\n"
            f"Параметри: {safe_cfg}\n"
            f"Причина: Сервер PostgreSQL повернув помилку аутентифікації.\n"
            f"1. Перевірте, чи створена база даних '{config.get('dbname')}'.\n"
            f"2. Перевірте пароль користувача '{config.get('user')}'.\n"
            f"Вкажіть актуальний пароль у файлі .env (DB_PASSWORD=...) або запустіть команду з параметром:\n"
            f".venv\\Scripts\\python -m src.lab02.load_staging --password ВАШ_ПАРОЛЬ --dbname ВАША_БД"
        )
    except psycopg2.OperationalError as op_err:
        safe_cfg = {k: (v if k != "password" else "***") for k, v in config.items()}
        raise ConnectionError(
            f"Не вдалося з'єднатися з PostgreSQL ({safe_cfg}): {op_err}\n"
            f"Перевірте, чи запущено сервер PostgreSQL на {config.get('host')}:{config.get('port')}."
        )


def load_file_to_staging(
    conn,
    table_key: str,
    batch_id: str,
    truncate_before_load: bool = False,
) -> int:
    """Loads a single CSV dataset into staging using parameterized batch insertion."""
    table_meta = STAGING_TABLES[table_key]
    file_path = table_meta["file_path"]
    target_table = table_meta["target_table"]
    expected_columns = table_meta["expected_columns"]
    source_file_label = file_path.name

    logger.info("Reading & validating '%s' -> %s...", file_path.name, target_table)
    rows_to_insert, row_count = read_and_validate_csv(
        file_path=file_path,
        expected_columns=expected_columns,
        batch_id=batch_id,
        source_file_label=source_file_label,
    )

    with conn.cursor() as cur:
        if truncate_before_load:
            logger.info("Truncating table %s before load...", target_table)
            cur.execute(f"TRUNCATE TABLE {target_table};")

        # Columns in target table
        all_columns = ["batch_id", "source_file", "source_row_number", "loaded_at"] + expected_columns
        cols_sql = ", ".join(all_columns)

        # Parameterized query template (using %s placeholders for execute_values)
        insert_query = f"INSERT INTO {target_table} ({cols_sql}) VALUES %s"

        logger.info("Inserting %d rows into %s (batch_id: %s)...", row_count, target_table, batch_id)
        execute_values(cur, insert_query, rows_to_insert, page_size=2000)

        # Verification of exact count in staging
        cur.execute(
            f"SELECT COUNT(*) FROM {target_table} WHERE batch_id = %s",
            (batch_id,),
        )
        loaded_count = cur.fetchone()[0]

        if loaded_count != row_count:
            raise RuntimeError(
                f"Count mismatch in {target_table}! CSV records: {row_count}, Loaded in DB: {loaded_count}"
            )

        # Record file audit entry
        cur.execute(
            """
            INSERT INTO audit.load_files (batch_id, source_file, target_table, rows_read, rows_loaded, status)
            VALUES (%s, %s, %s, %s, %s, 'SUCCESS');
            """,
            (batch_id, source_file_label, target_table, row_count, loaded_count),
        )

    logger.info("Successfully loaded %d records into %s.", loaded_count, target_table)
    return loaded_count


def run_pipeline(
    tables_to_load: Optional[List[str]] = None,
    truncate: bool = False,
    dry_run: bool = False,
    custom_db_config: Optional[Dict] = None,
) -> str:
    """Executes the staging ingestion pipeline for selected tables inside a single transactional batch."""
    tables = tables_to_load or ["customers", "merchants", "products", "orders", "order_items"]
    batch_id = f"batch_{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

    logger.info("==================================================")
    logger.info("Starting Staging Pipeline. Batch ID: %s", batch_id)
    logger.info("Target tables: %s", tables)
    logger.info("Dry-run mode: %s", dry_run)
    logger.info("==================================================")

    if dry_run:
        # Validate CSV structure and row integrity without DB connection
        for table_key in tables:
            meta = STAGING_TABLES[table_key]
            records, count = read_and_validate_csv(
                meta["file_path"],
                meta["expected_columns"],
                batch_id,
                meta["file_path"].name,
            )
            logger.info("Dry-run validation PASSED for %s: %d rows verified.", meta["file_path"].name, count)
        logger.info("Dry-run completed successfully for all files.")
        return batch_id

    conn = get_db_connection(custom_db_config)
    try:
        # Register batch in audit
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO audit.load_batches (batch_id, started_at, status) VALUES (%s, clock_timestamp(), 'RUNNING');",
                (batch_id,),
            )
        conn.commit()

        # Ingest each table
        for table_key in tables:
            load_file_to_staging(conn, table_key, batch_id, truncate_before_load=truncate)

        # Finalize batch in audit
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE audit.load_batches
                SET status = 'SUCCESS', completed_at = clock_timestamp()
                WHERE batch_id = %s;
                """,
                (batch_id,),
            )
        conn.commit()
        logger.info("Batch %s completed and committed successfully!", batch_id)

    except Exception as exc:
        conn.rollback()
        logger.error("Pipeline FAILED with error: %s. Transaction rolled back.", exc)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE audit.load_batches
                    SET status = 'FAILED', completed_at = clock_timestamp(), error_message = %s
                    WHERE batch_id = %s;
                    """,
                    (str(exc), batch_id),
                )
            conn.commit()
        except Exception as audit_exc:
            logger.error("Failed to update audit table: %s", audit_exc)
        raise exc
    finally:
        conn.close()

    return batch_id


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Lab 02 Staging Data Loader")
    parser.add_argument(
        "--tables",
        nargs="+",
        default=["customers", "merchants", "products", "orders", "order_items"],
        help="List of tables to load (e.g. customers merchants products orders order_items)",
    )
    parser.add_argument(
        "--all-tables",
        action="store_true",
        help="Load all available tables including couriers, deliveries, payments, refunds, service_zones",
    )
    parser.add_argument(
        "--truncate",
        action="store_true",
        help="Truncate staging tables before loading",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate CSV structure, headers and row integrity without connecting to PostgreSQL",
    )
    # Database connection parameters overrides
    parser.add_argument("--dbname", default=None, help="PostgreSQL database name")
    parser.add_argument("--user", default=None, help="PostgreSQL user name")
    parser.add_argument("--password", default=None, help="PostgreSQL password")
    parser.add_argument("--host", default=None, help="PostgreSQL host (default: localhost)")
    parser.add_argument("--port", type=int, default=None, help="PostgreSQL port (default: 5432)")

    args = parser.parse_args()

    # Build DB override config if any DB arg is passed
    custom_cfg = dict(DB_CONFIG)
    if args.dbname:
        custom_cfg["dbname"] = args.dbname
    if args.user:
        custom_cfg["user"] = args.user
    if args.password:
        custom_cfg["password"] = args.password
    if args.host:
        custom_cfg["host"] = args.host
    if args.port:
        custom_cfg["port"] = args.port

    selected_tables = list(STAGING_TABLES.keys()) if args.all_tables else args.tables

    try:
        run_pipeline(
            tables_to_load=selected_tables,
            truncate=args.truncate,
            dry_run=args.dry_run,
            custom_db_config=custom_cfg,
        )
    except Exception as e:
        logger.error("Execution terminated: %s", e)
        sys.exit(1)
