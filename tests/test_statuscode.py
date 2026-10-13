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


@patch("statuscode.checker.requests.get")
def test_check_domain_status_success(mock_get):
    """Verify checking a 200 OK domain with allow_redirects=False."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_get.return_value = mock_resp

    code = check_domain_status("example.com")
    assert code == "200"
    mock_get.assert_called_once()
    assert mock_get.call_args[1].get("allow_redirects") is False


@patch("statuscode.checker.requests.get")
def test_check_domain_status_redirect(mock_get):
    """Verify initial 301 redirect status code is captured without following."""
    mock_resp = MagicMock()
    mock_resp.status_code = 301
    mock_get.return_value = mock_resp

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


def test_statuscode_service_alert_deduplication(tmp_path):
    """Verify that an error alert is sent once and NOT repeated if already alerted."""
    state_file = tmp_path / "statuscode_state.json"

    config = Config(
        telegram_bot_token="fake_token",
        telegram_chat_id="fake_chat",
        google_service_account_file="nonexistent.json",
        google_sheet_name="Quản Lý Domain",
    )

    mock_sheet_manager = MagicMock()
    mock_notifier = MagicMock()
    mock_notifier.send_message.return_value = True

    # Row with domain returning 500 error
    mock_sheet_manager.fetch_all_rows.return_value = [
        StatusCodeRow(row_index=2, domain="broken-site.com", status_code="")
    ]

    service = StatusCodeService(
        config=config,
        sheet_manager=mock_sheet_manager,
        notifier=mock_notifier,
        state_file=str(state_file),
    )

    with patch("statuscode.service.check_domain_status", return_value="500"):
        # Cycle 1: should send alert
        alerts_sent = service.process_statuscode_cycle()
        assert alerts_sent == 1
        assert mock_notifier.send_message.call_count == 1

        # Check state file recorded error
        assert state_file.exists()
        state = json.loads(state_file.read_text(encoding="utf-8"))
        assert state["broken-site.com"]["is_alerted"] is True
        assert state["broken-site.com"]["last_alert_code"] == "500"

    # Cycle 2 (10 minutes later): error fluctuates to 502 or 500 -> should NOT alert again!
    with patch("statuscode.service.check_domain_status", return_value="502"):
        mock_notifier.send_message.reset_mock()
        alerts_sent_2 = service.process_statuscode_cycle()
        assert alerts_sent_2 == 0
        assert mock_notifier.send_message.call_count == 0

    # Cycle 3: site recovers to 200 OK -> reset state
    with patch("statuscode.service.check_domain_status", return_value="200"):
        service.process_statuscode_cycle()
        state_recovered = json.loads(state_file.read_text(encoding="utf-8"))
        assert state_recovered["broken-site.com"]["is_alerted"] is False
        assert state_recovered["broken-site.com"]["last_alert_code"] == ""
