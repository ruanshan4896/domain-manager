"""Google Sheets Manager module for Domain Renewals worksheet."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional
import gspread
from google.oauth2.service_account import Credentials
from renewals.lookup import parse_expiry_date

logger = logging.getLogger(__name__)

# Expected standard headers in Row 1 for Domain Renewals worksheet
EXPECTED_RENEWAL_HEADERS = [
    "Domain",       # Col A (1) - Domain to track
    "Expiry Date",  # Col B (2) - Expiry date YYYY-MM-DD
    "Days Left",    # Col C (3) - Remaining days text e.g. "15 ngày"
]

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


@dataclass
class RenewalRow:
    """Representation of a domain renewal row in Google Sheets."""

    row_index: int  # 1-indexed row number in the worksheet
    domain: str
    expiry_date_str: str
    expiry_date: Optional[date]
    days_left_str: str

    @classmethod
    def from_row_values(cls, row_index: int, values: List[str]) -> RenewalRow:
        """Parse raw row values from worksheet."""
        padded = values + [""] * max(0, 3 - len(values))

        domain = padded[0].strip()
        expiry_date_str = padded[1].strip()
        expiry_date = parse_expiry_date(expiry_date_str)
        days_left_str = padded[2].strip()

        return cls(
            row_index=row_index,
            domain=domain,
            expiry_date_str=expiry_date_str,
            expiry_date=expiry_date,
            days_left_str=days_left_str,
        )


@dataclass
class RenewalRowUpdate:
    """Update payload for columns B to C (Expiry Date, Days Left)."""

    row_index: int
    expiry_date_str: str
    days_left_str: str

    def to_range_payload(self) -> Dict[str, Any]:
        """Convert to gspread batch_update range dictionary for columns B to C."""
        return {
            "range": f"B{self.row_index}:C{self.row_index}",
            "values": [
                [
                    self.expiry_date_str,
                    self.days_left_str,
                ]
            ],
        }


class RenewalSheetManager:
    """Manages Google Sheets reading and updating for Domain Renewals."""

    def __init__(
        self,
        service_account_file: str,
        sheet_name: str,
        worksheet_name: str = "Domain_Renewals",
    ) -> None:
        self.service_account_file = service_account_file
        self.sheet_name = sheet_name
        self.worksheet_name = worksheet_name
        self.client: Optional[gspread.Client] = None
        self.spreadsheet: Optional[gspread.Spreadsheet] = None
        self.worksheet: Optional[gspread.Worksheet] = None

    def connect(self) -> bool:
        """Establish connection with Google Sheets API for Domain Renewals worksheet."""
        sa_path = Path(self.service_account_file)
        if not sa_path.exists():
            logger.error(
                "Service account JSON file not found: %s", sa_path.resolve()
            )
            return False

        try:
            creds = Credentials.from_service_account_file(
                str(sa_path), scopes=SCOPES
            )
            self.client = gspread.authorize(creds)
            self.spreadsheet = self.client.open(self.sheet_name)

            try:
                self.worksheet = self.spreadsheet.worksheet(self.worksheet_name)
            except gspread.exceptions.WorksheetNotFound:
                logger.info(
                    "Renewal worksheet '%s' not found. Creating it now.", self.worksheet_name
                )
                self.worksheet = self.spreadsheet.add_worksheet(
                    title=self.worksheet_name, rows=100, cols=10
                )

            self.ensure_headers()
            logger.info(
                "Successfully connected to Google Sheet '%s' -> Worksheet '%s'.",
                self.sheet_name,
                self.worksheet_name,
            )
            return True

        except Exception as exc:
            logger.error("Failed to connect to Domain Renewals worksheet: %s", exc)
            return False

    def ensure_headers(self) -> None:
        """Ensure standard header columns are present in row 1."""
        if not self.worksheet:
            return

        try:
            first_row = self.worksheet.row_values(1)
            if not first_row or first_row[: len(EXPECTED_RENEWAL_HEADERS)] != EXPECTED_RENEWAL_HEADERS:
                logger.info("Initializing/updating headers in row 1 of '%s'.", self.worksheet_name)
                self.worksheet.update(
                    range_name="A1:C1",
                    values=[EXPECTED_RENEWAL_HEADERS],
                )
        except Exception as exc:
            logger.warning("Error checking or updating renewal sheet headers: %s", exc)

    def fetch_all_rows(self) -> List[RenewalRow]:
        """Fetch all domain renewal rows in a single batch read.

        Returns:
            List[RenewalRow]: Parsed renewal row representations (excluding header).
        """
        if not self.worksheet:
            if not self.connect():
                return []

        try:
            raw_values = self.worksheet.get_all_values()
            if not raw_values or len(raw_values) <= 1:
                logger.debug("Renewal worksheet is empty or has only header.")
                return []

            rows: List[RenewalRow] = []
            for idx, row_vals in enumerate(raw_values[1:], start=2):
                if not row_vals or not any(str(v).strip() for v in row_vals):
                    continue

                if not row_vals[0].strip():
                    continue

                renewal_row = RenewalRow.from_row_values(
                    row_index=idx, values=row_vals
                )
                rows.append(renewal_row)

            return rows

        except Exception as exc:
            logger.error("Error fetching renewal rows from Google Sheets: %s", exc)
            self.worksheet = None
            return []

    def update_single_row(self, row_index: int, expiry_date_str: str, days_left_str: str) -> bool:
        """Update a single domain's renewal info (Columns B:C) immediately in real time.

        Args:
            row_index: 1-indexed row number.
            expiry_date_str: Formatted expiration date string (YYYY-MM-DD).
            days_left_str: Remaining days string (e.g. '15 ngày').

        Returns:
            bool: True if update succeeded, False otherwise.
        """
        if not self.worksheet:
            if not self.connect():
                return False

        try:
            self.worksheet.update(
                values=[[expiry_date_str, days_left_str]],
                range_name=f"B{row_index}:C{row_index}",
                value_input_option="USER_ENTERED",
            )
            return True
        except Exception as exc:
            logger.error("Error updating renewal row B%d:C%d: %s", row_index, row_index, exc)
            self.worksheet = None
            return False

    def batch_update_rows(self, updates: List[RenewalRowUpdate]) -> bool:
        """Batch update modified renewal rows in a single API call to save quota.

        Args:
            updates: List of RenewalRowUpdate objects to send in batch.

        Returns:
            bool: True if batch update succeeded, False otherwise.
        """
        if not updates:
            logger.debug("No renewal row updates to apply.")
            return True

        if not self.worksheet:
            if not self.connect():
                return False

        try:
            batch_data = [update.to_range_payload() for update in updates]
            logger.info("Performing Google Sheets batch update for %d renewal row(s).", len(batch_data))
            self.worksheet.batch_update(batch_data, value_input_option="USER_ENTERED")
            return True

        except Exception as exc:
            logger.error("Error performing Google Sheets batch update for renewals: %s", exc)
            self.worksheet = None
            return False


# Alias for backward compatibility
RenewalManager = RenewalSheetManager
