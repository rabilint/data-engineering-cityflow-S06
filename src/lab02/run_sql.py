"""Convenient SQL Runner for executing SQL scripts with tabular formatting.

Usage:
    .venv/Scripts/python -m src.lab02.run_sql sql/lab02/07_control_verification_queries.sql
"""

import argparse
import sys
from pathlib import Path
import psycopg2

from src.lab02.config import DB_CONFIG


def run_sql_file(sql_file_path: str) -> None:
    path = Path(sql_file_path)
    if not path.exists():
        print(f"Error: File not found: {sql_file_path}", file=sys.stderr)
        sys.exit(1)

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True
    print(f"=== Executing: {path.name} ===")

    try:
        # Separate statements by semicolons (handling single block or queries)
        queries = [q.strip() for q in content.split(";") if q.strip()]
        with conn.cursor() as cur:
            for i, query in enumerate(queries, 1):
                # Clean leading comments
                clean_query = "\n".join(
                    line for line in query.splitlines() if not line.strip().startswith("--")
                ).strip()
                if not clean_query:
                    continue

                print(f"\n--- [Query {i}] ---")
                cur.execute(query)
                if cur.description:
                    columns = [desc[0] for desc in cur.description]
                    rows = cur.fetchall()
                    # Calculate column widths
                    col_widths = [len(col) for col in columns]
                    for row in rows:
                        for idx, val in enumerate(row):
                            col_widths[idx] = max(col_widths[idx], len(str(val)))

                    header = " | ".join(col.ljust(col_widths[idx]) for idx, col in enumerate(columns))
                    sep = "-+-".join("-" * col_widths[idx] for idx in range(len(columns)))
                    print(header)
                    print(sep)
                    for row in rows:
                        print(" | ".join(str(val if val is not None else "NULL").ljust(col_widths[idx]) for idx, val in enumerate(row)))
                    print(f"({len(rows)} rows)")
                else:
                    print("Executed successfully (no rows returned).")

        for notice in conn.notices:
            print(f"NOTICE: {notice.strip()}")

    except Exception as e:
        print(f"Error during execution: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run SQL file using DB_CONFIG")
    parser.add_argument("file", help="Path to SQL file")
    args = parser.parse_args()
    run_sql_file(args.file)
