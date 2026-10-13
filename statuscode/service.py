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

        updated_count = 0

        # Run HTTP checks concurrently and update Google Sheet immediately in real time
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_row = {
                executor.submit(check_domain_status, r.domain): r
                for r in active_rows
            }
            for future in as_completed(future_to_row):
                row = future_to_row[future]
                try:
                    code = future.result()
                except Exception as exc:
                    logger.debug("Error checking domain %s: %s", row.domain, exc)
                    code = "ERR"

                # Update Google Sheet cell in real time if status code changed or was empty
                if row.status_code != code:
                    logger.info("Real-time update: %s -> %s (Row B%d)", row.domain, code, row.row_index)
                    if self.sheet_manager.update_single_row(row.row_index, code):
                        updated_count += 1
                        row.status_code = code

        logger.info("Statuscode check cycle finished. Real-time updated %d row(s).", updated_count)
        return updated_count
