"""Tests for HTTP Statuscode monitoring module."""

import json
from unittest.mock import MagicMock, patch
from core.config import Config
from statuscode.checker import check_domain_status, is_error_status
from statuscode.sheet import (
    EXPECTED_STATUSCODE_HEADERS,
    StatusCodeRow,
    StatusCodeRowUpdate,
    StatusCodeSheetManager,
)
from statuscode.service import StatusCodeService


def test_is_error_status():
    """Verify classification of status codes into errors vs normal."""
    assert is_error_status("200") is False
    assert is_error_status("301") is False
    assert is_error_status("302") is False
    assert is_error_status("403") is True
    assert is_error_status("404") is True
    assert is_error_status("500") is True
    assert is_error_status("502") is True
    assert is_error_status("TIMEOUT") is True
    assert is_error_status("ERR") is True


@patch("statuscode.checker._request_single_url")
def test_check_domain_status_success(mock_req):
    """Verify checking a 200 OK domain with HTTPS prioritization."""
    mock_req.return_value = "200"

    code = check_domain_status("example.com")
    assert code == "200"
    mock_req.assert_called_with("https://example.com", timeout=10)


@patch("statuscode.checker._request_single_url")
def test_check_domain_status_redirect(mock_req):
    """Verify initial 301 redirect status code is captured without following."""
    mock_req.return_value = "301"

    code = check_domain_status("redirectme.com")
    assert code == "301"


def test_statuscode_headers_and_row_parsing():
    """Verify 2-column header and row parsing."""
    assert EXPECTED_STATUSCODE_HEADERS == ["Domain", "Status Code"]

    row = StatusCodeRow.from_row_values(2, ["mysite.com", "200"])
    assert row.row_index == 2
    assert row.domain == "mysite.com"
    assert row.status_code == "200"

    row_empty = StatusCodeRow.from_row_values(3, ["newsite.org"])
    assert row_empty.domain == "newsite.org"
    assert row_empty.status_code == ""


def test_statuscode_row_update_payload():
    """Verify batch update range is Col B only."""
    update = StatusCodeRowUpdate(row_index=5, status_code="500")
    payload = update.to_range_payload()
    assert payload["range"] == "B5"
    assert payload["values"] == [["500"]]


def test_statuscode_service_updates_sheet_without_telegram():
    """Verify that StatusCodeService updates Google Sheet in real time and sends NO Telegram messages."""
    config = Config(
        google_service_account_file="nonexistent.json",
        google_sheet_name="Quản Lý Domain",
    )

    mock_sheet_manager = MagicMock()
    mock_sheet_manager.update_single_row.return_value = True
    mock_notifier = MagicMock()

    mock_sheet_manager.fetch_all_rows.return_value = [
        StatusCodeRow(row_index=2, domain="mysite.com", status_code=""),
        StatusCodeRow(row_index=3, domain="#ignored.com", status_code=""),
    ]

    service = StatusCodeService(
        config=config,
        sheet_manager=mock_sheet_manager,
        notifier=mock_notifier,
    )

    with patch("statuscode.service.check_domain_status", return_value="200"):
        updated_count = service.process_statuscode_cycle()
        assert updated_count == 1
        mock_sheet_manager.update_single_row.assert_called_once_with(2, "200")

        # Verify NO Telegram message was sent
        mock_notifier.send_message.assert_not_called()
