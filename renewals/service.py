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
    """Service managing domain expiration verification, RDAP/WHOIS lookup, and alert notifications."""

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
        self.notifier = notifier or TelegramNotifier(
            bot_token=config.telegram_bot_token,
            chat_id=config.telegram_chat_id,
        )
        self.state_file = Path(state_file)

    def _load_alert_state(self) -> Dict[str, Dict[str, Any]]:
        """Load persistent alert states from JSON file."""
        if not self.state_file.exists():
            return {}
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            logger.warning("Error loading alert state from %s: %s", self.state_file, exc)
            return {}

    def _save_alert_state(self, state: Dict[str, Dict[str, Any]]) -> None:
        """Save persistent alert states to JSON file."""
        try:
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            logger.error("Error saving alert state to %s: %s", self.state_file, exc)

    def process_renewal_cycle(self) -> int:
        """Check domain expiration dates and send renewal reminders.

        Returns:
            int: Number of renewal alerts sent.
        """
        logger.info("=== Starting Domain Renewal Check Cycle ===")
        rows = self.sheet_manager.fetch_all_rows()
        if not rows:
            logger.info("No rows found in renewal sheet or failed to fetch.")
            return 0

        active_rows = [r for r in rows if r.domain and not r.domain.startswith("#")]
        logger.info("Fetched %d renewal row(s), %d active to process.", len(rows), len(active_rows))

        if not active_rows:
            return 0

        alert_states = self._load_alert_state()
        updates: List[RenewalRowUpdate] = []
        alerts_sent = 0
        state_changed = False
        today = datetime.now(timezone.utc).date()

        for row in active_rows:
            domain = row.domain.strip()
            expiry_date = row.expiry_date
            expiry_date_str = row.expiry_date_str
            registrar = ""

            # If Expiry Date is missing or unparsed, automatically lookup via RDAP & WHOIS!
            if not expiry_date:
                logger.info("Expiry date missing for '%s'. Performing automatic RDAP/WHOIS lookup...", domain)
                looked_up_date, looked_up_reg = lookup_domain_info(domain)
                if looked_up_date:
                    expiry_date = looked_up_date
                    expiry_date_str = looked_up_date.strftime("%Y-%m-%d")
                    registrar = looked_up_reg or ""
                    logger.info(
                        "Domain lookup success for '%s': Expiry = %s, Registrar = %s",
                        domain,
                        expiry_date_str,
                        registrar,
                    )
                else:
                    logger.warning(
                        "Could not resolve expiration date for '%s' via RDAP/WHOIS. Please enter date manually.",
                        domain,
                    )
                    update = RenewalRowUpdate(
                        row_index=row.row_index,
                        expiry_date_str="",
                        days_left_str="Chưa tra cứu được (vui lòng tự nhập ngày)",
                    )
                    updates.append(update)
                    continue

            days_left = calculate_days_left(expiry_date, today)
            days_left_str = f"{days_left} ngày" if days_left >= 0 else f"Quá hạn {abs(days_left)} ngày"

            domain_state = alert_states.get(domain, {})
            last_stage = domain_state.get("last_alert_stage", "PENDING")
            last_expiry = domain_state.get("expiry_date", "")

            target_stage = determine_alert_stage(days_left, self.config.renewal_alert_days)

            # Check if domain was renewed / extended -> reset alert status to PENDING
            if (days_left > 0 and last_stage != "PENDING") or (last_expiry and expiry_date_str != last_expiry and days_left > 0):
                logger.info(
                    "Domain '%s' expiry extended (%d days left). Resetting alert status to PENDING.",
                    domain,
                    days_left,
                )
                domain_state["last_alert_stage"] = "PENDING"
                domain_state["expiry_date"] = expiry_date_str
                alert_states[domain] = domain_state
                state_changed = True
            elif target_stage:
                # Check if we should trigger a new alert stage (ALERT_0D on day 0, ALERT_EXPIRED on day -1)
                if should_trigger_alert(last_stage, target_stage):
                    logger.warning(
                        "Triggering renewal alert for %s: %d days left (stage: %s)",
                        domain,
                        days_left,
                        target_stage,
                    )
                    sent = self.notifier.send_renewal_alert(
                        domain=domain,
                        expiry_date_str=expiry_date_str,
                        days_left=days_left,
                        registrar=registrar,
                        auto_renew="",
                        owner="",
                    )
                    if sent:
                        alerts_sent += 1
                        domain_state["last_alert_stage"] = target_stage
                        domain_state["expiry_date"] = expiry_date_str
                        domain_state["last_alert_time"] = datetime.now(timezone.utc).isoformat()
                        alert_states[domain] = domain_state
                        state_changed = True

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

        if state_changed:
            self._save_alert_state(alert_states)

        logger.info("Renewal check cycle completed. Sent %d alert(s).", alerts_sent)
        return alerts_sent
