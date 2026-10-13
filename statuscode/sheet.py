"""Google Sheets Manager module for Statuscode worksheet."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
import gspread
from google.oauth2.service_account import Credentials

logger = logging.getLogger(__name__)

EXPECTED_STATUSCODE_HEADERS = [
    "Domain",       # Col A (1) - Domain to check
    "Status Code",  # Col B (2) - HTTP Status code e.g. 200, 301, 404, 500
]

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


@dataclass
class StatusCodeRow:
    """Representation of a domain row in Statuscode worksheet."""

    row_index: int  # 1-indexed row number
    domain: str
    status_code: str

    @classmethod
    def from_row_values(cls, row_index: int, values: List[str]) -> StatusCodeRow:
        """Parse raw row values from worksheet."""
        padded = values + [""] * max(0, 2 - len(values))
        domain = padded[0].strip()
        status_code = padded[1].strip()
        return cls(row_index=row_index, domain=domain, status_code=status_code)


@dataclass
class StatusCodeRowUpdate:
    """Update payload for column B (Status Code)."""

    row_index: int
    status_code: str

    def to_range_payload(self) -> Dict[str, Any]:
        """Convert to gspread batch_update range dictionary for column B."""
        return {
            "range": f"B{self.row_index}",
            "values": [[self.status_code]],
        }


class StatusCodeSheetManager:
    """Manages Google Sheets reading and updating for Statuscode tab."""

    def __init__(
        self,
        service_account_file: str,
        sheet_name: str,
        worksheet_name: str = "Statuscode",
    ) -> None:
        self.service_account_file = service_account_file
        self.sheet_name = sheet_name
        self.worksheet_name = worksheet_name
        self.client: Optional[gspread.Client] = None
        self.spreadsheet: Optional[gspread.Spreadsheet] = None
        self.worksheet: Optional[gspread.Worksheet] = None

    def connect(self) -> bool:
        """Establish connection with Google Sheets API for Statuscode worksheet."""
        sa_path = Path(self.service_account_file)
        if not sa_path.exists():
            logger.error("Service account JSON file not found: %s", sa_path.resolve())
            return False

        try:
            creds = Credentials.from_service_account_file(str(sa_path), scopes=SCOPES)
            self.client = gspread.authorize(creds)
            self.spreadsheet = self.client.open(self.sheet_name)

            try:
                self.worksheet = self.spreadsheet.worksheet(self.worksheet_name)
            except gspread.exceptions.WorksheetNotFound:
                logger.info("Worksheet '%s' not found. Creating it now.", self.worksheet_name)
                self.worksheet = self.spreadsheet.add_worksheet(
                    title=self.worksheet_name, rows=100, cols=5
                )

            self.ensure_headers()
            logger.info(
                "Successfully connected to Google Sheet '%s' -> Worksheet '%s'.",
                self.sheet_name,
                self.worksheet_name,
            )
            return True

        except Exception as exc:
            logger.error("Failed to connect to Statuscode worksheet: %s", exc)
            return False

    def ensure_headers(self) -> None:
        """Ensure standard header columns are present in row 1."""
        if not self.worksheet:
            return

        try:
            first_row = self.worksheet.row_values(1)
            if not first_row or first_row[: len(EXPECTED_STATUSCODE_HEADERS)] != EXPECTED_STATUSCODE_HEADERS:
                logger.info("Initializing/updating headers in row 1 of '%s'.", self.worksheet_name)
                self.worksheet.update(
                    range_name="A1:B1",
                    values=[EXPECTED_STATUSCODE_HEADERS],
                )
        except Exception as exc:
            logger.warning("Error checking or updating statuscode sheet headers: %s", exc)

    def fetch_all_rows(self) -> List[StatusCodeRow]:
        """Fetch all domain rows from Statuscode worksheet."""
        if not self.worksheet:
            if not self.connect():
                return []

        try:
            raw_values = self.worksheet.get_all_values()
            if not raw_values or len(raw_values) <= 1:
                return []

            rows: List[StatusCodeRow] = []
            for idx, row_vals in enumerate(raw_values[1:], start=2):
                if not row_vals or not any(str(v).strip() for v in row_vals):
                    continue
                if not row_vals[0].strip():
                    continue

                row = StatusCodeRow.from_row_values(row_index=idx, values=row_vals)
                rows.append(row)

            return rows

        except Exception as exc:
            logger.error("Error fetching rows from Statuscode sheet: %s", exc)
            self.worksheet = None
            return []

    def update_single_row(self, row_index: int, status_code: str) -> bool:
        """Update a single domain's status code in Column B immediately in real time.

        Args:
            row_index: 1-indexed row number.
            status_code: HTTP status code string (e.g. '200', '301').

        Returns:
            bool: True if update succeeded, False otherwise.
        """
        if not self.worksheet:
            if not self.connect():
                return False

        try:
            self.worksheet.update(
                values=[[status_code]],
                range_name=f"B{row_index}",
                value_input_option="USER_ENTERED",
            )
            return True
        except Exception as exc:
            logger.error("Error updating status code for row B%d: %s", row_index, exc)
            self.worksheet = None
            return False

    def batch_update_rows(self, updates: List[StatusCodeRowUpdate]) -> bool:
        """Batch update modified statuscode rows in a single API call."""
        if not updates:
            return True

        if not self.worksheet:
            if not self.connect():
                return False

        try:
            batch_data = [update.to_range_payload() for update in updates]
            logger.info("Performing Google Sheets batch update for %d statuscode row(s).", len(batch_data))
            self.worksheet.batch_update(batch_data, value_input_option="USER_ENTERED")
            return True

        except Exception as exc:
            logger.error("Error performing Google Sheets batch update for statuscode: %s", exc)
            self.worksheet = None
            return False
