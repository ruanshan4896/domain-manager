"""Tests for RenewalService expiration check and alert state persistence."""

import json
from datetime import date
from unittest.mock import MagicMock
from core.config import Config
from renewals.service import (
    RenewalService,
    calculate_days_left,
    determine_alert_stage,
)
from renewals.sheet import RenewalRow


def test_calculate_days_left():
    """Verify remaining days calculation."""
    today = date(2026, 10, 13)
    exp = date(2026, 10, 23)
    assert calculate_days_left(exp, today) == 10

    exp_same = date(2026, 10, 13)
    assert calculate_days_left(exp_same, today) == 0

    exp_past = date(2026, 10, 12)
    assert calculate_days_left(exp_past, today) == -1


def test_determine_alert_stage():
    """Verify alert stages: 0 days -> ALERT_0D, <0 days -> ALERT_EXPIRED."""
    assert determine_alert_stage(0) == "ALERT_0D"
    assert determine_alert_stage(-1) == "ALERT_EXPIRED"
    assert determine_alert_stage(-5) == "ALERT_EXPIRED"
    assert determine_alert_stage(1) is None
    assert determine_alert_stage(30) is None


def test_service_alert_deduplication(tmp_path):
    """Verify that alert is not re-sent if already alerted at the same stage for current expiry date."""
    state_file = tmp_path / "alerts_state.json"

    config = Config(
        telegram_bot_token="fake_token",
        telegram_chat_id="fake_chat",
        google_service_account_file="nonexistent.json",
        google_sheet_name="Quản Lý Domain",
    )

    mock_sheet_manager = MagicMock()
    mock_notifier = MagicMock()
    mock_notifier.send_renewal_alert.return_value = True

    # Row 1: expires today (0 days left)
    today = date.today()
    mock_sheet_manager.fetch_all_rows.return_value = [
        RenewalRow(
            row_index=2,
            domain="testdomain.com",
            expiry_date_str=today.strftime("%Y-%m-%d"),
            expiry_date=today,
            days_left_str="",
        )
    ]

    service = RenewalService(
        config=config,
        sheet_manager=mock_sheet_manager,
        notifier=mock_notifier,
        state_file=str(state_file),
    )

    # First cycle: alert should be sent
    alerts_sent = service.process_renewal_cycle()
    assert alerts_sent == 1
    assert mock_notifier.send_renewal_alert.call_count == 1

    # Verify state was saved to json
    assert state_file.exists()
    state_data = json.loads(state_file.read_text(encoding="utf-8"))
    assert state_data["testdomain.com"]["last_alert_stage"] == "ALERT_0D"

    # Second cycle with same state: alert should NOT be sent again
    mock_notifier.send_renewal_alert.reset_mock()
    alerts_sent_2 = service.process_renewal_cycle()
    assert alerts_sent_2 == 0
    assert mock_notifier.send_renewal_alert.call_count == 0


def test_service_alert_escalation_and_reset(tmp_path):
    """Verify that stage escalates from ALERT_0D to ALERT_EXPIRED, then resets when renewed."""
    from datetime import timedelta
    today = date.today()
    past_date = today - timedelta(days=1)
    past_date_str = past_date.strftime("%Y-%m-%d")

    state_file = tmp_path / "alerts_state.json"
    state_file.write_text(
        json.dumps({
            "mydomain.org": {
                "last_alert_stage": "ALERT_0D",
                "expiry_date": past_date_str,
            }
        }),
        encoding="utf-8",
    )

    config = Config(
        telegram_bot_token="fake_token",
        telegram_chat_id="fake_chat",
        google_service_account_file="nonexistent.json",
        google_sheet_name="Quản Lý Domain",
    )

    mock_sheet_manager = MagicMock()
    mock_notifier = MagicMock()
    mock_notifier.send_renewal_alert.return_value = True

    # 1. Past expiration day (-1 days left) -> should escalate to ALERT_EXPIRED
    mock_sheet_manager.fetch_all_rows.return_value = [
        RenewalRow(
            row_index=2,
            domain="mydomain.org",
            expiry_date_str=past_date_str,
            expiry_date=past_date,
            days_left_str="",
        )
    ]

    service = RenewalService(
        config=config,
        sheet_manager=mock_sheet_manager,
        notifier=mock_notifier,
        state_file=str(state_file),
    )

    service.process_renewal_cycle()
    state_data = json.loads(state_file.read_text(encoding="utf-8"))
    assert state_data["mydomain.org"]["last_alert_stage"] == "ALERT_EXPIRED"

    # 2. Domain is renewed for another year (+365 days) -> resets to PENDING
    next_year = date.today().year + 1
    renewed_date_str = f"{next_year}-10-13"
    mock_sheet_manager.fetch_all_rows.return_value = [
        RenewalRow(
            row_index=2,
            domain="mydomain.org",
            expiry_date_str=renewed_date_str,
            expiry_date=date(next_year, 10, 13),
            days_left_str="Quá hạn 1 ngày",
        )
    ]

    service.process_renewal_cycle()
    state_data_renewed = json.loads(state_file.read_text(encoding="utf-8"))
    assert state_data_renewed["mydomain.org"]["last_alert_stage"] == "PENDING"
    assert state_data_renewed["mydomain.org"]["expiry_date"] == renewed_date_str


def test_service_skip_commented_domains(tmp_path):
    """Verify domains starting with # are skipped."""
    state_file = tmp_path / "alerts_state.json"
    config = Config(
        telegram_bot_token="fake_token",
        telegram_chat_id="fake_chat",
        google_service_account_file="nonexistent.json",
        google_sheet_name="Quản Lý Domain",
    )

    mock_sheet_manager = MagicMock()
    mock_notifier = MagicMock()
    mock_sheet_manager.fetch_all_rows.return_value = [
        RenewalRow(
            row_index=2,
            domain="#commented_domain.com",
            expiry_date_str="2026-10-13",
            expiry_date=date(2026, 10, 13),
            days_left_str="",
        )
    ]

    service = RenewalService(
        config=config,
        sheet_manager=mock_sheet_manager,
        notifier=mock_notifier,
        state_file=str(state_file),
    )

    alerts_sent = service.process_renewal_cycle()
    assert alerts_sent == 0
    assert not state_file.exists()

