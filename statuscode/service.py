"""Business service for domain HTTP Statuscode checks and error alert dispatch."""

from __future__ import annotations

import html
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.config import Config
from core.notifier import TelegramNotifier
from statuscode.checker import check_domain_status, is_error_status
from statuscode.sheet import (
    StatusCodeRow,
    StatusCodeRowUpdate,
    StatusCodeSheetManager,
)

logger = logging.getLogger(__name__)


class StatusCodeService:
    """Service managing periodic HTTP statuscode checks and Telegram alerts."""

    def __init__(
        self,
        config: Config,
        sheet_manager: Optional[StatusCodeSheetManager] = None,
        notifier: Optional[TelegramNotifier] = None,
        state_file: str = "statuscode_state.json",
        max_workers: int = 5,
    ) -> None:
        self.config = config
        self.sheet_manager = sheet_manager or StatusCodeSheetManager(
            service_account_file=config.google_service_account_file,
            sheet_name=config.google_sheet_name,
            worksheet_name=getattr(config, "google_statuscode_worksheet_name", "Statuscode"),
        )
        self.notifier = notifier or TelegramNotifier(
            bot_token=config.telegram_bot_token,
            chat_id=config.telegram_chat_id,
        )
        self.state_file = Path(state_file)
        self.max_workers = max_workers

    def _load_state(self) -> Dict[str, Dict[str, Any]]:
        """Load persistent error alert states from JSON file."""
        if not self.state_file.exists():
            return {}
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            logger.warning("Error loading statuscode state from %s: %s", self.state_file, exc)
            return {}

    def _save_state(self, state: Dict[str, Dict[str, Any]]) -> None:
        """Save persistent error alert states to JSON file."""
        try:
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            logger.error("Error saving statuscode state to %s: %s", self.state_file, exc)

    def process_statuscode_cycle(self) -> int:
        """Perform concurrent HTTP status checks across all domains in Statuscode worksheet.

        Returns:
            int: Number of new error alerts sent to Telegram.
        """
        logger.info("=== Starting Domain HTTP Statuscode Check Cycle ===")
        rows = self.sheet_manager.fetch_all_rows()
        if not rows:
            logger.info("No rows found in Statuscode sheet or failed to fetch.")
            return 0

        active_rows = [r for r in rows if r.domain and not r.domain.startswith("#")]
        logger.info("Fetched %d statuscode row(s), %d active to verify.", len(rows), len(active_rows))

        if not active_rows:
            return 0

        state = self._load_state()
        updates: List[StatusCodeRowUpdate] = []
        alerts_sent = 0
        state_changed = False

        # Run HTTP checks concurrently
        check_results: Dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_domain = {
                executor.submit(check_domain_status, r.domain): r.domain
                for r in active_rows
            }
            for future in as_completed(future_to_domain):
                d = future_to_domain[future]
                try:
                    check_results[d] = future.result()
                except Exception as exc:
                    logger.debug("Error checking domain %s: %s", d, exc)
                    check_results[d] = "ERR"

        for row in active_rows:
            domain = row.domain
            code = check_results.get(domain, "ERR")

            # Queue sheet update if code changed or was empty
            if row.status_code != code:
                updates.append(StatusCodeRowUpdate(row_index=row.row_index, status_code=code))

            domain_state = state.get(domain, {})
            is_alerted = domain_state.get("is_alerted", False)

            # If status represents an error (4xx, 5xx, or network failure)
            if is_error_status(code):
                # Alert only once when error is first detected; do not alert again while still in error state
                if not is_alerted:
                    logger.warning("Domain '%s' reported error status code: %s", domain, code)
                    escaped_domain = html.escape(domain)
                    message = (
                        f"⚠️ <b>Cảnh báo lỗi HTTP:</b> Tên miền <b>{escaped_domain}</b> "
                        f"phát hiện trả về mã lỗi <b>{code}</b>! Vui lòng kiểm tra lại dịch vụ."
                    )
                    sent = self.notifier.send_message(message)
                    if sent:
                        alerts_sent += 1
                        domain_state["is_alerted"] = True
                        domain_state["last_alert_code"] = code
                        domain_state["last_alert_time"] = datetime.now(timezone.utc).isoformat()
                        state[domain] = domain_state
                        state_changed = True
            else:
                # Domain is healthy (2xx, 3xx) -> reset state if it previously alerted an error
                if is_alerted:
                    logger.info("Domain '%s' recovered with status %s. Resetting alert state.", domain, code)
                    domain_state["is_alerted"] = False
                    domain_state["last_alert_code"] = ""
                    domain_state["recovered_time"] = datetime.now(timezone.utc).isoformat()
                    state[domain] = domain_state
                    state_changed = True

        if updates:
            self.sheet_manager.batch_update_rows(updates)

        if state_changed:
            self._save_state(state)

        logger.info("Statuscode check cycle finished. Sent %d new error alert(s).", alerts_sent)
        return alerts_sent
