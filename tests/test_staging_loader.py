"""Unit tests for Lab 02 staging validation and ingestion logic."""

import csv
import pytest
from pathlib import Path

from src.lab02.load_staging import (
    StructuralValidationError,
    validate_csv_header,
    read_and_validate_csv,
)


def test_validate_csv_header_success(tmp_path: Path):
    expected = ["col_a", "col_b", "col_c"]
    actual = ["col_a", "col_b", "col_c"]
    test_file = tmp_path / "test.csv"
    validate_csv_header(actual, expected, test_file)


def test_validate_csv_header_reordered_fails(tmp_path: Path):
    expected = ["col_a", "col_b", "col_c"]
    actual = ["col_b", "col_a", "col_c"]
    test_file = tmp_path / "test.csv"
    with pytest.raises(StructuralValidationError, match="Header mismatch"):
        validate_csv_header(actual, expected, test_file)


def test_validate_csv_header_missing_column_fails(tmp_path: Path):
    expected = ["col_a", "col_b", "col_c"]
    actual = ["col_a", "col_b"]
    test_file = tmp_path / "test.csv"
    with pytest.raises(StructuralValidationError, match="Header mismatch"):
        validate_csv_header(actual, expected, test_file)


def test_read_and_validate_csv_success_and_metadata(tmp_path: Path):
    csv_file = tmp_path / "sample.csv"
    columns = ["id", "name", "city"]
    rows = [
        ["1", "Alice", "Kyiv"],
        ["2", "Bob", "Lviv"],
        ["3", "Alice_Duplicate", "Kyiv"],
    ]

    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        writer.writerows(rows)

    batch_id = "test_batch_001"
    records, count = read_and_validate_csv(csv_file, columns, batch_id, "sample.csv")

    assert count == 3
    # Check that source_row_number is 1-based and matches exact row order
    for idx, rec in enumerate(records, start=1):
        # rec structure: (batch_id, source_file, source_row_number, loaded_at, *row)
        assert rec[0] == batch_id
        assert rec[1] == "sample.csv"
        assert rec[2] == idx  # source_row_number: 1, 2, 3
        assert rec[3] is not None  # loaded_at
        assert list(rec[4:]) == rows[idx - 1]


def test_read_and_validate_csv_broken_row_fails_immediately(tmp_path: Path):
    csv_file = tmp_path / "corrupted.csv"
    columns = ["id", "name", "city"]

    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        writer.writerow(["1", "Valid Row", "Kyiv"])
        writer.writerow(["2", "Broken Row - Missing City"])  # 2 columns instead of 3
        writer.writerow(["3", "Another Row", "Odesa"])

    batch_id = "test_batch_corrupted"
    with pytest.raises(StructuralValidationError, match="Structurally broken file.*at row 2"):
        read_and_validate_csv(csv_file, columns, batch_id, "corrupted.csv")
