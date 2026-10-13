"""Tests for 3-column Google Sheets management in renewals/sheet.py."""

from datetime import date
from unittest.mock import MagicMock
from renewals.sheet import (
    EXPECTED_RENEWAL_HEADERS,
    RenewalRow,
    RenewalRowUpdate,
    RenewalSheetManager,
)


def test_expected_renewal_headers_has_three_columns():
    """Verify that expected headers contain exactly 3 columns: Domain, Expiry Date, Days Left."""
    assert EXPECTED_RENEWAL_HEADERS == ["Domain", "Expiry Date", "Days Left"]


def test_renewal_row_from_row_values_three_columns():
    """Verify parsing of 3-column row values into RenewalRow."""
    values = ["mybrand.com", "2026-10-25", "12 ngày"]
    row = RenewalRow.from_row_values(row_index=2, values=values)

    assert row.row_index == 2
    assert row.domain == "mybrand.com"
    assert row.expiry_date_str == "2026-10-25"
    assert row.expiry_date == date(2026, 10, 25)
    assert row.days_left_str == "12 ngày"


def test_renewal_row_from_row_values_partial():
    """Verify parsing when only Domain is provided in Col A."""
    values = ["newdomain.io"]
    row = RenewalRow.from_row_values(row_index=3, values=values)

    assert row.row_index == 3
    assert row.domain == "newdomain.io"
    assert row.expiry_date_str == ""
    assert row.expiry_date is None
    assert row.days_left_str == ""


def test_renewal_row_update_payload_range_b_to_c():
    """Verify batch update range covers columns B to C (Expiry Date and Days Left)."""
    update = RenewalRowUpdate(
        row_index=4,
        expiry_date_str="2027-01-01",
        days_left_str="80 ngày",
    )
    payload = update.to_range_payload()

    assert payload["range"] == "B4:C4"
    assert payload["values"] == [["2027-01-01", "80 ngày"]]


def test_ensure_headers_updates_a1_c1():
    """Verify ensure_headers updates A1:C1 when headers do not match."""
    manager = RenewalSheetManager(
        service_account_file="nonexistent.json",
        sheet_name="Test Sheet",
    )
    mock_ws = MagicMock()
    mock_ws.row_values.return_value = ["Domain", "Old Header 1", "Old Header 2"]
    manager.worksheet = mock_ws

    manager.ensure_headers()

    mock_ws.update.assert_called_once_with(
        range_name="A1:C1",
        values=[["Domain", "Expiry Date", "Days Left"]],
    )
