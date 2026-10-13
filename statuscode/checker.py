"""HTTP Statuscode checker for domains with Chrome TLS impersonation and fallback."""

from __future__ import annotations

import logging
from typing import Optional
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

try:
    from curl_cffi import requests as cffi_requests
    HAS_CURL_CFFI = True
except ImportError:  # pragma: no cover
    cffi_requests = None
    HAS_CURL_CFFI = False

import requests

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8,"
        "application/signed-exchange;v=b3;q=0.7"
    ),
    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
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


def _request_single_url(url: str, timeout: int = 10) -> Optional[str]:
    """Request a single URL using Chrome impersonation with fallback to standard requests."""
    # 1. Try curl_cffi Chrome impersonation first (bypasses Cloudflare & WAF)
    if HAS_CURL_CFFI and cffi_requests is not None:
        try:
            resp = cffi_requests.get(
                url,
                impersonate="chrome124",
                timeout=timeout,
                allow_redirects=False,
                verify=False,
                headers=DEFAULT_HEADERS,
            )
            return str(resp.status_code)
        except Exception as exc:
            logger.debug("curl_cffi error for %s: %s", url, exc)

    # 2. Fallback to standard Python requests
    try:
        resp = requests.get(
            url,
            headers=DEFAULT_HEADERS,
            timeout=timeout,
            allow_redirects=False,
            verify=False,
        )
        return str(resp.status_code)
    except requests.exceptions.Timeout:
        logger.debug("Timeout checking %s via standard requests", url)
        return "TIMEOUT"
    except Exception as exc:
        logger.debug("Standard requests error for %s: %s", url, exc)
        return None


def check_domain_status(domain: str, timeout: int = 10) -> str:
    """Send an HTTP request without following redirects and return the initial status code.

    Features:
        - Chrome 124 TLS/JA3 impersonation (Cloudflare/WAF bypass)
        - Full browser headers (Sec-Ch-Ua, Accept-Language)
        - SSL verify=False fallback for dev/self-signed certs
        - HTTPS -> HTTP -> WWW fallback

    Args:
        domain: Domain or URL string (e.g. 'example.com', 'https://test.vn').
        timeout: Request timeout in seconds.

    Returns:
        str: Status code string (e.g. '200', '301', '404', '500') or 'TIMEOUT' / 'ERR'.
    """
    cleaned = domain.strip()
    if not cleaned:
        return "ERR"

    # Normalize URLs to test
    if cleaned.startswith("http://") or cleaned.startswith("https://"):
        urls_to_try = [cleaned]
    else:
        urls_to_try = [
            f"https://{cleaned}",
            f"http://{cleaned}",
        ]
        # Also try www. fallback if not already a www or subdomain
        if not cleaned.startswith("www.") and cleaned.count(".") == 1:
            urls_to_try.extend([
                f"https://www.{cleaned}",
                f"http://www.{cleaned}",
            ])

    timed_out = False
    for url in urls_to_try:
        code = _request_single_url(url, timeout=timeout)
        if code == "TIMEOUT":
            timed_out = True
            continue
        if code and code != "ERR":
            return code

    return "TIMEOUT" if timed_out else "ERR"
