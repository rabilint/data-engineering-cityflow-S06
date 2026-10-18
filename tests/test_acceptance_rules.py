"""Unit tests for Lab 02 Task 4: Educational Acceptance Contract Rules."""

import datetime
from decimal import Decimal
import pytest

from src.lab02.load_core import (
    ALLOWED_CURRENCIES,
    parse_acceptance_timestamp,
    parse_numeric,
)


def test_allowed_currencies():
    assert "UAH" in ALLOWED_CURRENCIES
    assert "USD" in ALLOWED_CURRENCIES
    assert "EUR" in ALLOWED_CURRENCIES
    # "Код «UA H» не виправляти здогадкою."
    assert "UA H" not in ALLOWED_CURRENCIES
    assert "GBP" not in ALLOWED_CURRENCIES


def test_parse_acceptance_timestamp_iso():
    # ISO 8601 with Z
    dt = parse_acceptance_timestamp("2025-09-01T08:23:42Z")
    assert dt is not None
    assert dt.tzinfo is not None
    assert dt.year == 2025
    assert dt.month == 9
    assert dt.hour == 8

    # ISO 8601 with nanoseconds: policy truncates to microseconds for PostgreSQL timestamptz
    dt_nano = parse_acceptance_timestamp("2024-11-26T16:13:18.859859510Z")
    assert dt_nano is not None
    assert dt_nano.microsecond == 859859


def test_parse_acceptance_timestamp_generator_format():
    # "Для наявного у генераторі DD/MM/YYYY HH:MM явно застосувати UTC; не визначати day/month автоматично."
    dt_gen = parse_acceptance_timestamp("12/12/2025 14:55")
    assert dt_gen is not None
    assert dt_gen.tzinfo == datetime.timezone.utc
    assert dt_gen.year == 2025
    assert dt_gen.month == 12
    assert dt_gen.day == 12
    assert dt_gen.hour == 14
    assert dt_gen.minute == 55


def test_parse_acceptance_timestamp_invalid():
    # "Порожній ключ і непридатна дата відхиляються."
    assert parse_acceptance_timestamp("2026-19-45 25:61:00") is None
    assert parse_acceptance_timestamp("") is None
    assert parse_acceptance_timestamp("not-a-date") is None


def test_parse_numeric_no_zero_coercion():
    # "Невідоме число не замінювати нулем."
    assert parse_numeric(None) is None
    assert parse_numeric("") is None
    assert parse_numeric("   ") is None
    assert parse_numeric("123.45") == Decimal("123.45")
    assert parse_numeric("0.0") == Decimal("0.00")


def test_product_price_acceptance_rule():
    # "Активний товар з unit_price_uah ≤ 0 відхилити за цим навчальним контрактом; для неактивного допустимий нуль."
    def check_product(is_active: bool, price: Decimal) -> bool:
        if price < Decimal("0.00"):
            return False  # суми невід'ємні
        if is_active and price <= Decimal("0.00"):
            return False
        return True

    # Active with 0 -> Rejected
    assert check_product(is_active=True, price=Decimal("0.00")) is False
    assert check_product(is_active=True, price=Decimal("-5.00")) is False
    assert check_product(is_active=True, price=Decimal("100.00")) is True

    # Inactive with 0 -> Accepted
    assert check_product(is_active=False, price=Decimal("0.00")) is True
    assert check_product(is_active=False, price=Decimal("50.00")) is True
