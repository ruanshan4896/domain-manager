"""Tests for RenewalService domain expiration verification and Google Sheets synchronization."""

from datetime import date, timedelta
from unittest.mock import MagicMock, patch
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


def test_service_updates_sheet_without_telegram():
    """Verify that renewal service updates Google Sheet and sends NO Telegram notifications."""
    config = Config(
        google_service_account_file="nonexistent.json",
        google_sheet_name="Quản Lý Domain",
    )

    mock_sheet_manager = MagicMock()
    mock_notifier = MagicMock()

    today = date.today()
    exp_date = today + timedelta(days=15)
    exp_date_str = exp_date.strftime("%Y-%m-%d")

    mock_sheet_manager.fetch_all_rows.return_value = [
        RenewalRow(
            row_index=2,
            domain="testdomain.com",
            expiry_date_str=exp_date_str,
            expiry_date=exp_date,
            days_left_str="",
        )
    ]

    service = RenewalService(
        config=config,
        sheet_manager=mock_sheet_manager,
        notifier=mock_notifier,
    )

    updated_count = service.process_renewal_cycle()
    assert updated_count == 1
    mock_sheet_manager.batch_update_rows.assert_called_once()
    updates = mock_sheet_manager.batch_update_rows.call_args[0][0]
    assert len(updates) == 1
    assert updates[0].row_index == 2
    assert updates[0].days_left_str == "15 ngày"

    # Verify NO Telegram alert was called
    mock_notifier.send_message.assert_not_called()
    mock_notifier.send_renewal_alert.assert_not_called()


def test_service_auto_lookups_missing_date():
    """Verify missing expiry date triggers RDAP/WHOIS lookup and updates Google Sheet."""
    config = Config(
        google_service_account_file="nonexistent.json",
        google_sheet_name="Quản Lý Domain",
    )

    mock_sheet_manager = MagicMock()

    mock_sheet_manager.fetch_all_rows.return_value = [
        RenewalRow(
            row_index=3,
            domain="auto-lookup.com",
            expiry_date_str="",
            expiry_date=None,
            days_left_str="",
        )
    ]

    service = RenewalService(
        config=config,
        sheet_manager=mock_sheet_manager,
    )

    looked_up = date(2027, 5, 20)
    with patch("renewals.service.lookup_domain_info", return_value=(looked_up, "Namecheap")):
        updated_count = service.process_renewal_cycle()
        assert updated_count == 1
        mock_sheet_manager.batch_update_rows.assert_called_once()
        updates = mock_sheet_manager.batch_update_rows.call_args[0][0]
        assert updates[0].row_index == 3
        assert updates[0].expiry_date_str == "2027-05-20"


def test_service_skip_commented_domains():
    """Verify domains starting with # are skipped."""
    config = Config(
        google_service_account_file="nonexistent.json",
        google_sheet_name="Quản Lý Domain",
    )

    mock_sheet_manager = MagicMock()
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
    )

    updated_count = service.process_renewal_cycle()
    assert updated_count == 0
    mock_sheet_manager.batch_update_rows.assert_not_called()
