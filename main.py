"""Main daemon and orchestrator for Domain Renewal Reminder Manager."""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from datetime import datetime, timezone

from core.config import Config, load_config, setup_logging, validate_config
from core.notifier import TelegramNotifier
from renewals.service import RenewalService

logger = logging.getLogger("renewal_tracker.main")

# Global flag for graceful shutdown
RUNNING = True


def signal_handler(signum: int, frame: object) -> None:
    """Handle interrupt signals for graceful daemon shutdown."""
    global RUNNING
    sig_name = signal.Signals(signum).name if hasattr(signal, "Signals") else str(signum)
    logger.info("Received shutdown signal (%s). Finishing current cycle...", sig_name)
    RUNNING = False


class AppOrchestrator:
    """Orchestrator managing the Domain Renewal Reminder service."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.notifier = TelegramNotifier(
            bot_token=config.telegram_bot_token,
            chat_id=config.telegram_chat_id,
        )
        self.renewal_service = RenewalService(
            config=config,
            notifier=self.notifier,
        )
        self.last_renewal_check_date = None
        self.last_renewal_check_time: float = 0.0

    @property
    def renewal_manager(self):
        """Property for renewal sheet manager."""
        return self.renewal_service.sheet_manager

    def process_renewal_cycle(self) -> int:
        """Run a single domain renewal verification cycle.

        Returns:
            int: Number of renewal alerts sent.
        """
        return self.renewal_service.process_renewal_cycle()

    def run_forever(self) -> None:
        """Execute continuous 24/7 daemon loop."""
        logger.info("Starting Domain Renewal Tracker daemon...")

        while RUNNING:
            try:
                today_utc = datetime.now(timezone.utc).date()
                now_ts = time.time()

                if self.last_renewal_check_date != today_utc or (
                    now_ts - self.last_renewal_check_time >= self.config.renewal_check_interval_seconds
                ):
                    try:
                        self.process_renewal_cycle()
                    except Exception as renewal_err:
                        logger.error("Error during domain renewal check: %s", renewal_err, exc_info=True)
                    self.last_renewal_check_date = today_utc
                    self.last_renewal_check_time = now_ts

                sleep_duration = min(3600, self.config.renewal_check_interval_seconds)
                self._sleep_interruptible(sleep_duration)

            except Exception as exc:
                logger.error("Unexpected error in renewal daemon cycle: %s", exc, exc_info=True)
                self._sleep_interruptible(15)

        logger.info("Tracker daemon stopped gracefully.")

    def _sleep_interruptible(self, duration: int) -> None:
        """Sleep in short 1-second intervals to promptly respond to shutdown signals."""
        slept = 0
        while RUNNING and slept < duration:
            step = min(1.0, duration - slept)
            time.sleep(step)
            slept += step


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Domain Renewal Reminder Manager with Google Sheets and Telegram Alerts."
    )
    parser.add_argument(
        "--env",
        type=str,
        default=None,
        help="Path to custom .env file",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single renewal check cycle then exit",
    )
    parser.add_argument(
        "--test-telegram",
        action="store_true",
        help="Send a test notification to Telegram and exit",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate configuration and credentials then exit",
    )
    return parser.parse_args()


def main() -> None:
    """Application entrypoint."""
    args = parse_args()
    config = load_config(env_path=args.env)
    setup_logging(config.log_level)

    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    if args.validate_only:
        errors = validate_config(config, check_service_account_file=True)
        if errors:
            logger.error("Configuration validation failed with %d error(s):", len(errors))
            for err in errors:
                logger.error(" - %s", err)
            sys.exit(1)
        else:
            logger.info("Configuration is valid and service account file exists.")
            sys.exit(0)

    orchestrator = AppOrchestrator(config)

    if args.test_telegram:
        logger.info("Testing Telegram connection...")
        success = orchestrator.notifier.send_message(
            "🔔 <b>Domain Renewal Tracker:</b> Kiểm tra kết nối Telegram Bot thành công! 🚀"
        )
        if success:
            logger.info("Telegram test message sent successfully.")
            sys.exit(0)
        else:
            logger.error("Failed to send Telegram test message.")
            sys.exit(1)

    if args.once:
        logger.info("Running in single-cycle mode (--once)...")
        orchestrator.process_renewal_cycle()
        logger.info("Cycle finished.")
        return

    # Start 24/7 daemon
    orchestrator.run_forever()


if __name__ == "__main__":
    main()
