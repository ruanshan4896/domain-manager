"""Telegram Notification module with HTML formatting and Inline Keyboard buttons for Domain Renewals."""

from __future__ import annotations

import html
import logging
import re
import time
from typing import Any, Dict, List, Optional
import requests

logger = logging.getLogger(__name__)


def format_telegram_mentions(raw_owner: str) -> str:
    """Format one or more Telegram usernames into valid mention strings (e.g. '@user1 @user2')."""
    cleaned = raw_owner.strip()
    if not cleaned:
        return ""
    parts = [p.strip() for p in re.split(r"[,;\s]+", cleaned) if p.strip()]
    mentions = [p if p.startswith("@") else f"@{p}" for p in parts]
    return " ".join(mentions)


class TelegramNotifier:
    """Sends rich renewal alert messages and inline buttons to Telegram."""

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        timeout: int = 10,
        max_retries: int = 3,
        retry_delay: float = 2.0,
    ) -> None:
        self.bot_token = bot_token.strip()
        self.chat_id = chat_id.strip()
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"

    @property
    def is_configured(self) -> bool:
        """Check if bot token and chat ID are validly set."""
        return bool(
            self.bot_token
            and self.bot_token != "your_bot_token"
            and self.chat_id
            and self.chat_id != "your_chat_id"
        )

    def send_message(
        self,
        text: str,
        inline_keyboard: Optional[List[List[Dict[str, str]]]] = None,
        parse_mode: str = "HTML",
    ) -> bool:
        """Send a message to the configured Telegram chat with retry support.

        Args:
            text: Message body (HTML formatted).
            inline_keyboard: Optional list of button rows for InlineKeyboardMarkup.
            parse_mode: Parsing mode, default 'HTML'.

        Returns:
            bool: True if sent successfully, False otherwise.
        """
        if not self.is_configured:
            logger.warning(
                "Telegram credentials not configured. Skipping message delivery: %s",
                text[:100],
            )
            return False

        url = f"{self.base_url}/sendMessage"
        payload: Dict[str, Any] = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": False,
        }

        if inline_keyboard:
            payload["reply_markup"] = {"inline_keyboard": inline_keyboard}

        for attempt in range(1, self.max_retries + 1):
            try:
                response = requests.post(url, json=payload, timeout=self.timeout)
                res_json = response.json()

                if response.status_code == 200 and res_json.get("ok"):
                    logger.info("Telegram notification sent successfully.")
                    return True

                logger.warning(
                    "Telegram API returned error (attempt %d/%d): HTTP %d - %s",
                    attempt,
                    self.max_retries,
                    response.status_code,
                    res_json.get("description", response.text),
                )
            except Exception as exc:
                logger.warning(
                    "Error sending Telegram message (attempt %d/%d): %s",
                    attempt,
                    self.max_retries,
                    exc,
                )

            if attempt < self.max_retries:
                time.sleep(self.retry_delay * attempt)

        logger.error("Failed to send Telegram notification after %d retries.", self.max_retries)
        return False

    def send_renewal_alert(
        self,
        domain: str,
        expiry_date_str: str = "",
        days_left: int = 0,
        registrar: str = "",
        auto_renew: str = "",
        owner: str = "",
    ) -> bool:
        """Send notification when a domain reaches its expiration date or is past due.

        Message format:
            Tên miền {domain} của @{owner} đã hết hạn, @daudepzai gia hạn giúp anh với em

        Args:
            domain: The domain name being tracked.
            expiry_date_str: Formatted expiration date string (e.g. '2026-10-15').
            days_left: Number of days remaining (0 = today, < 0 = expired).
            registrar: Domain registrar name (e.g. 'Namecheap', 'Cloudflare').
            auto_renew: Auto-renewal status string (e.g. 'YES', 'NO', 'OFF').
            owner: Telegram username of domain owner (e.g. '@user' or 'user').

        Returns:
            bool: True if alert was sent successfully.
        """
        escaped_domain = html.escape(domain)
        owner_tag = format_telegram_mentions(owner)

        if owner_tag:
            message = (
                f"Tên miền <b>{escaped_domain}</b> của <b>{owner_tag}</b> đã hết hạn, "
                f"@daudepzai gia hạn giúp anh với em"
            )
        else:
            message = (
                f"Tên miền <b>{escaped_domain}</b> đã hết hạn, "
                f"@daudepzai gia hạn giúp anh với em"
            )

        inline_keyboard = None
        reg_lower = registrar.strip().lower()
        if "namecheap" in reg_lower:
            inline_keyboard = [[{"text": "🔗 Mở Namecheap Domain List", "url": "https://ap.www.namecheap.com/domains/list/"}]]
        elif "cloudflare" in reg_lower:
            inline_keyboard = [[{"text": "🔗 Mở Cloudflare Dashboard", "url": "https://dash.cloudflare.com/"}]]
        elif "godaddy" in reg_lower:
            inline_keyboard = [[{"text": "🔗 Mở GoDaddy Domains", "url": "https://dcc.godaddy.com/control/portfolio"}]]

        logger.info(
            "Sending renewal alert for domain: %s (owner: %s, days left: %d, expiry: %s)",
            domain,
            owner or "None",
            days_left,
            expiry_date_str,
        )
        return self.send_message(message, inline_keyboard=inline_keyboard)
