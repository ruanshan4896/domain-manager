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
    """Service managing periodic HTTP statuscode checks and Google Sheets updates."""

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
        self.notifier = notifier
        self.state_file = Path(state_file)
        self.max_workers = max_workers

    def process_statuscode_cycle(self) -> int:
        """Perform concurrent HTTP status checks across all domains and update Google Sheet.

        Returns:
            int: Number of rows updated on Google Sheet.
        """
        logger.info("=== Starting Domain HTTP Statuscode Check & Sync Cycle ===")
        rows = self.sheet_manager.fetch_all_rows()
        if not rows:
            logger.info("No rows found in Statuscode sheet or failed to fetch.")
            return 0

        active_rows = [r for r in rows if r.domain and not r.domain.startswith("#")]
        logger.info("Fetched %d statuscode row(s), %d active to verify.", len(rows), len(active_rows))

        if not active_rows:
            return 0

        updates: List[StatusCodeRowUpdate] = []

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

        if updates:
            self.sheet_manager.batch_update_rows(updates)
            logger.info("Updated %d domain status code(s) on Google Sheet.", len(updates))
        else:
            logger.info("All domain status codes are up to date on Google Sheet.")

        logger.info("Statuscode check cycle finished.")
        return len(updates)
