"""Domain Renewal business service for expiration checks, stage determination, and alert dispatch."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from core.config import Config
from core.notifier import TelegramNotifier
from renewals.lookup import lookup_domain_info, parse_expiry_date
from renewals.sheet import RenewalRow, RenewalRowUpdate, RenewalSheetManager

logger = logging.getLogger(__name__)

STAGE_PRIORITY: Dict[str, int] = {
    "PENDING": 0,
    "ALERT_0D": 1,
    "ALERT_EXPIRED": 2,
    "EXPIRED": 2,
}


def calculate_days_left(expiry_date: date, today: Optional[date] = None) -> int:
    """Calculate the number of calendar days remaining until expiry_date.

    Args:
        expiry_date: The domain expiration date.
        today: Optional reference date (defaults to datetime.now(timezone.utc).date()).

    Returns:
        int: Number of days remaining (negative if already expired).
    """
    if today is None:
        today = datetime.now(timezone.utc).date()
    return (expiry_date - today).days


def determine_alert_stage(
    days_left: int, thresholds: Sequence[int] = (0,)
) -> Optional[str]:
    """Determine the alert stage key based on remaining days.

    Alert rules:
        - days_left == 0: 'ALERT_0D' (Notification on expiration day)
        - days_left < 0: 'ALERT_EXPIRED' (Notification on the following day)
        - days_left > 0: None (No advance spam notifications)

    Args:
        days_left: Number of remaining days.
        thresholds: Unused, kept for backwards compatibility.

    Returns:
        Optional[str]: Alert stage key ('ALERT_0D', 'ALERT_EXPIRED') or None.
    """
    if days_left < 0:
        return "ALERT_EXPIRED"
    if days_left == 0:
        return "ALERT_0D"
    return None


def should_trigger_alert(current_alert_status: str, target_stage: Optional[str]) -> bool:
    """Check if target alert stage is higher priority than current alert status.

    Args:
        current_alert_status: Current status stored in sheet or state (e.g. 'PENDING', 'ALERT_0D').
        target_stage: Newly calculated target stage (e.g. 'ALERT_0D', 'ALERT_EXPIRED').

    Returns:
        bool: True if an alert notification should be sent.
    """
    if not target_stage:
        return False

    curr_key = current_alert_status.strip().upper()
    curr_priority = STAGE_PRIORITY.get(curr_key, 0)
    target_priority = STAGE_PRIORITY.get(target_stage.upper(), 0)

    return target_priority > curr_priority


class RenewalService:
    """Service managing domain expiration verification, RDAP/WHOIS lookup, and Google Sheets updates."""

    def __init__(
        self,
        config: Config,
        sheet_manager: Optional[RenewalSheetManager] = None,
        notifier: Optional[TelegramNotifier] = None,
        state_file: str = "alerts_state.json",
    ) -> None:
        self.config = config
        self.sheet_manager = sheet_manager or RenewalSheetManager(
            service_account_file=config.google_service_account_file,
            sheet_name=config.google_sheet_name,
            worksheet_name=config.google_renewal_worksheet_name,
        )
        self.notifier = notifier
        self.state_file = Path(state_file)

    def process_renewal_cycle(self) -> int:
        """Check domain expiration dates and update Google Sheets without sending Telegram notifications.

        Returns:
            int: Number of renewal rows updated on Google Sheet.
        """
        logger.info("=== Starting Domain Renewal Check & Sync Cycle ===")
        rows = self.sheet_manager.fetch_all_rows()
        if not rows:
            logger.info("No rows found in renewal sheet or failed to fetch.")
            return 0

        active_rows = [r for r in rows if r.domain and not r.domain.startswith("#")]
        logger.info("Fetched %d renewal row(s), %d active to process.", len(rows), len(active_rows))

        if not active_rows:
            return 0

        updates: List[RenewalRowUpdate] = []
        today = datetime.now(timezone.utc).date()

        for row in active_rows:
            domain = row.domain.strip()
            expiry_date = row.expiry_date
            expiry_date_str = row.expiry_date_str

            # If Expiry Date is missing or unparsed, automatically lookup via RDAP & WHOIS!
            if not expiry_date:
                logger.info("Expiry date missing for '%s'. Performing automatic RDAP/WHOIS lookup...", domain)
                looked_up_date, looked_up_reg = lookup_domain_info(domain)
                if looked_up_date:
                    expiry_date = looked_up_date
                    expiry_date_str = looked_up_date.strftime("%Y-%m-%d")
                    logger.info(
                        "Domain lookup success for '%s': Expiry = %s, Registrar = %s",
                        domain,
                        expiry_date_str,
                        looked_up_reg or "",
                    )
                else:
                    if domain.endswith(".es"):
                        msg = "Vui lòng tự nhập ngày (Red.es chặn WHOIS tự do)"
                    else:
                        msg = "Chưa tra cứu được (vui lòng tự nhập ngày)"
                    logger.warning(
                        "Could not resolve expiration date for '%s'. %s",
                        domain,
                        msg,
                    )
                    update = RenewalRowUpdate(
                        row_index=row.row_index,
                        expiry_date_str="",
                        days_left_str=msg,
                    )
                    updates.append(update)
                    continue

            days_left = calculate_days_left(expiry_date, today)
            days_left_str = f"{days_left} ngày" if days_left >= 0 else f"Quá hạn {abs(days_left)} ngày"

            # If days_left changed or expiry_date was filled, queue row update
            if row.expiry_date_str != expiry_date_str or row.days_left_str != days_left_str:
                update = RenewalRowUpdate(
                    row_index=row.row_index,
                    expiry_date_str=expiry_date_str,
                    days_left_str=days_left_str,
                )
                updates.append(update)

        if updates:
            self.sheet_manager.batch_update_rows(updates)
            logger.info("Updated %d domain renewal row(s) on Google Sheet.", len(updates))
        else:
            logger.info("All domain renewals are up to date on Google Sheet.")

        logger.info("Renewal check cycle completed.")
        return len(updates)
