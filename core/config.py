"""Core configuration and logging setup for Domain Renewal Reminder Tracker."""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional
from dotenv import load_dotenv


def parse_alert_days(raw_str: str) -> List[int]:
    """Parse comma-separated alert days string into sorted descending list of ints."""
    cleaned = raw_str.strip()
    if not cleaned:
        return [30, 14, 7, 3, 1, 0]
    try:
        days = [int(p.strip()) for p in cleaned.split(",") if p.strip()]
        return sorted(list(set(days)), reverse=True) if days else [30, 14, 7, 3, 1, 0]
    except Exception:
        return [30, 14, 7, 3, 1, 0]


@dataclass(frozen=True)
class Config:
    """Application configuration container."""

    telegram_bot_token: str
    telegram_chat_id: str
    google_service_account_file: str
    google_sheet_name: str
    log_level: str = "INFO"
    google_renewal_worksheet_name: str = "Domain_Renewals"
    renewal_check_interval_seconds: int = 86400
    renewal_alert_days: tuple = (30, 14, 7, 3, 1, 0)
    google_statuscode_worksheet_name: str = "Statuscode"
    statuscode_check_interval_seconds: int = 600

    @property
    def is_configured(self) -> bool:
        """Check if essential API keys and tokens are provided."""
        placeholders = {
            "your_bot_token",
            "your_chat_id",
            "",
        }
        return bool(
            self.telegram_bot_token not in placeholders
            and self.telegram_chat_id not in placeholders
        )


def load_config(env_path: Optional[str | Path] = None) -> Config:
    """Load configuration from environment variables and .env file.

    Args:
        env_path: Optional path to .env file.

    Returns:
        Config: Instantiated configuration dataclass.
    """
    if env_path is not None:
        load_dotenv(dotenv_path=env_path, override=True)
    else:
        load_dotenv(override=False)

    google_renewal_worksheet_name = os.getenv(
        "GOOGLE_RENEWAL_WORKSHEET_NAME", "Domain_Renewals"
    ).strip()
    if not google_renewal_worksheet_name:
        google_renewal_worksheet_name = "Domain_Renewals"

    try:
        renewal_check_interval_seconds = int(
            os.getenv("RENEWAL_CHECK_INTERVAL_SECONDS", "86400").strip()
        )
    except ValueError:
        renewal_check_interval_seconds = 86400

    raw_alert_days = os.getenv("RENEWAL_ALERT_DAYS", "30,14,7,3,1,0")
    renewal_alert_days = tuple(parse_alert_days(raw_alert_days))

    google_statuscode_worksheet_name = os.getenv(
        "GOOGLE_STATUSCODE_WORKSHEET_NAME", "Statuscode"
    ).strip()
    if not google_statuscode_worksheet_name:
        google_statuscode_worksheet_name = "Statuscode"

    try:
        statuscode_check_interval_seconds = int(
            os.getenv("STATUSCODE_CHECK_INTERVAL_SECONDS", "600").strip()
        )
    except ValueError:
        statuscode_check_interval_seconds = 600

    return Config(
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", "").strip(),
        google_service_account_file=os.getenv(
            "GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json"
        ).strip(),
        google_sheet_name=os.getenv(
            "GOOGLE_SHEET_NAME", "Quản Lý Domain"
        ).strip(),
        google_renewal_worksheet_name=google_renewal_worksheet_name,
        renewal_check_interval_seconds=renewal_check_interval_seconds,
        renewal_alert_days=renewal_alert_days,
        google_statuscode_worksheet_name=google_statuscode_worksheet_name,
        statuscode_check_interval_seconds=statuscode_check_interval_seconds,
        log_level=os.getenv("LOG_LEVEL", "INFO").upper().strip(),
    )


def validate_config(config: Config, check_service_account_file: bool = True) -> List[str]:
    """Validate configuration parameters.

    Args:
        config: Config instance to validate.
        check_service_account_file: Whether to check if service account JSON exists on disk.

    Returns:
        List[str]: List of validation error messages. Empty if valid.
    """
    errors: List[str] = []

    if not config.telegram_bot_token or config.telegram_bot_token == "your_bot_token":
        errors.append("TELEGRAM_BOT_TOKEN is missing or using default placeholder.")

    if not config.telegram_chat_id or config.telegram_chat_id == "your_chat_id":
        errors.append("TELEGRAM_CHAT_ID is missing or using default placeholder.")

    if not config.google_sheet_name:
        errors.append("GOOGLE_SHEET_NAME is missing.")

    if not config.google_renewal_worksheet_name:
        errors.append("GOOGLE_RENEWAL_WORKSHEET_NAME is missing.")

    if check_service_account_file:
        sa_path = Path(config.google_service_account_file)
        if not sa_path.exists():
            errors.append(f"Google Service Account file not found at: {sa_path.resolve()}")

    return errors


def setup_logging(log_level_name: str = "INFO") -> logging.Logger:
    """Configure system-wide standard logging with clean format and UTC awareness.

    Args:
        log_level_name: Log level name ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL').

    Returns:
        logging.Logger: Root application logger.
    """
    level = getattr(logging, log_level_name.upper(), logging.INFO)

    log_format = "[%(asctime)s] [%(levelname)-7s] [%(name)s]: %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    if not any(isinstance(h, logging.StreamHandler) for h in root_logger.handlers):
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        formatter = logging.Formatter(fmt=log_format, datefmt=date_format)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("google").setLevel(logging.WARNING)
    logging.getLogger("gspread").setLevel(logging.WARNING)

    logger = logging.getLogger("renewal_tracker")
    logger.setLevel(level)
    return logger
