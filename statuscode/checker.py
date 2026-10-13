"""HTTP Statuscode checker for domains without following redirects."""

from __future__ import annotations

import logging
import requests

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def is_error_status(code: str) -> bool:
    """Determine whether a status code represents an error (4xx, 5xx, or network failure)."""
    cleaned = str(code).strip().upper()
    if cleaned in ("TIMEOUT", "ERR", "ERR_CONN", "ERR_SSL"):
        return True
    if cleaned.isdigit():
        val = int(cleaned)
        if 400 <= val <= 599:
            return True
        if 200 <= val <= 399:
            return False
    return True


def check_domain_status(domain: str, timeout: int = 10) -> str:
    """Send an HTTP request without following redirects and return the initial status code.

    Args:
        domain: Domain or URL string (e.g. 'example.com', 'https://test.vn').
        timeout: Request timeout in seconds.

    Returns:
        str: Status code string (e.g. '200', '301', '404', '500') or 'TIMEOUT' / 'ERR'.
    """
    cleaned = domain.strip()
    if not cleaned:
        return "ERR"

    # Normalize URL scheme
    if cleaned.startswith("http://") or cleaned.startswith("https://"):
        urls_to_try = [cleaned]
    else:
        urls_to_try = [f"https://{cleaned}", f"http://{cleaned}"]

    for url in urls_to_try:
        try:
            resp = requests.get(
                url,
                headers=DEFAULT_HEADERS,
                timeout=timeout,
                allow_redirects=False,
            )
            return str(resp.status_code)
        except requests.exceptions.Timeout:
            logger.debug("Timeout checking %s", url)
            if url == urls_to_try[-1]:
                return "TIMEOUT"
        except requests.exceptions.SSLError:
            logger.debug("SSL error on %s, trying fallback if available", url)
            continue
        except requests.exceptions.RequestException as exc:
            logger.debug("Request error on %s: %s", url, exc)
            if url == urls_to_try[-1]:
                return "ERR"
        except Exception as exc:
            logger.debug("Unexpected error checking %s: %s", url, exc)
            if url == urls_to_try[-1]:
                return "ERR"

    return "ERR"
