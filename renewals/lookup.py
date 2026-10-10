"""RDAP, Socket WHOIS, and Web lookup engine for querying domain expiration dates and registrars."""

from __future__ import annotations

import logging
import re
import socket
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple
import requests

logger = logging.getLogger(__name__)

# Pre-mapped authoritative WHOIS servers (SLDs take priority over TLDs)
WHOIS_SERVER_MAP: Dict[str, str] = {
    # Special SLDs
    "in.net": "whois.nic.in.net",
    "it.com": "whois.it.com",
    "co.uk": "whois.nic.uk",
    "org.uk": "whois.nic.uk",
    "me.uk": "whois.nic.uk",
    "uk.com": "whois.centralnic.com",
    "us.com": "whois.centralnic.com",
    "eu.com": "whois.centralnic.com",
    "de.com": "whois.centralnic.com",
    "co.com": "whois.centralnic.com",
    "cn.com": "whois.centralnic.com",
    "sa.com": "whois.centralnic.com",
    "se.com": "whois.centralnic.com",
    "za.com": "whois.centralnic.com",
    "com.de": "whois.centralnic.com",
    # Common ccTLDs
    "nl": "whois.domain-registry.nl",
    "se": "whois.iis.se",
    "me": "whois.nic.me",
    "io": "whois.nic.io",
    "ai": "whois.nic.ai",
    "co": "whois.nic.co",
    "uk": "whois.nic.uk",
    "de": "whois.denic.de",
    "fr": "whois.nic.fr",
    "eu": "whois.eu",
    "ca": "whois.cira.ca",
    "us": "whois.nic.us",
    "au": "whois.auda.org.au",
    "it": "whois.nic.it",
    "es": "whois.nic.es",
    "ch": "whois.nic.ch",
    "at": "whois.nic.at",
    "be": "whois.dns.be",
    "pl": "whois.dns.pl",
    "cz": "whois.nic.cz",
    "in": "whois.registry.in",
    "vn": "whois.vnnic.vn",
    "cc": "ccwhois.verisign-grs.com",
    "tv": "tvwhois.verisign-grs.com",
    "ws": "whois.website.ws",
    "to": "whois.tonic.to",
    "la": "whois.nic.la",
    "is": "whois.isnic.is",
    # Common gTLDs
    "com": "whois.verisign-grs.com",
    "net": "whois.verisign-grs.com",
    "org": "whois.pir.org",
    "info": "whois.afilias.net",
    "biz": "whois.biz",
    "mobi": "whois.afilias.net",
    "pro": "whois.afilias.net",
    "onl": "whois.afilias.net",
    "xyz": "whois.nic.xyz",
    "top": "whois.nic.top",
    "club": "whois.nic.club",
    "online": "whois.nic.online",
    "site": "whois.nic.site",
    "store": "whois.nic.store",
    "shop": "whois.nic.shop",
    "spot": "whois.nic.spot",
    "deal": "whois.nic.deal",
    "vip": "whois.nic.vip",
    "win": "whois.nic.win",
    "bet": "whois.nic.bet",
    "live": "whois.nic.live",
    "icu": "whois.nic.icu",
    "fun": "whois.nic.fun",
    "space": "whois.nic.space",
    "click": "whois.nic.click",
    "link": "whois.uniregistry.net",
    "press": "whois.nic.press",
    "buzz": "whois.nic.buzz",
    "tech": "whois.nic.tech",
    "app": "whois.nic.google",
    "dev": "whois.nic.google",
}


def clean_domain_name(raw: str) -> str:
    """Clean domain string (remove http://, https://, slashes, spaces, query params)."""
    cleaned = raw.strip()
    if not cleaned:
        return ""
    if "://" in cleaned:
        cleaned = cleaned.split("://")[-1]
    if "/" in cleaned:
        cleaned = cleaned.split("/")[0]
    if "?" in cleaned:
        cleaned = cleaned.split("?")[0]
    return cleaned.strip().lower()


def parse_expiry_date(date_str: str) -> Optional[date]:
    """Parse various date string formats into a standard datetime.date object.

    Supported formats:
        - '2026-10-15' or '2026/10/15' (YYYY-MM-DD / YYYY/MM/DD)
        - '15-10-2026' or '15/10/2026' (DD-MM-YYYY / DD/MM/YYYY)
        - '14-May-2027' or '14-Dec-2034' (DD-Mon-YYYY)
        - 'May 14, 2027'
        - '2026-10-15 12:00:00' or ISO strings
        - '20261015'
    """
    cleaned = date_str.strip()
    if not cleaned:
        return None

    # Handle ISO datetime with space or T
    if "T" in cleaned or " " in cleaned:
        cleaned = cleaned.replace("T", " ").split(" ")[0].strip()

    formats = [
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%m-%d-%Y",
        "%d-%b-%Y",
        "%d-%B-%Y",
        "%b %d, %Y",
        "%B %d, %Y",
        "%d %b %Y",
        "%d %B %Y",
        "%Y%m%d",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue

    return None


def query_whois_socket(domain: str, server: str, port: int = 43, timeout: int = 8) -> str:
    """Query a WHOIS server directly over TCP socket port 43.

    Args:
        domain: Domain name to query.
        server: WHOIS hostname.
        port: Port number (default 43).
        timeout: Timeout in seconds.

    Returns:
        str: Raw WHOIS response text.
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((server, port))
        s.send((domain + "\r\n").encode("utf-8"))
        res = b""
        while True:
            data = s.recv(4096)
            if not data:
                break
            res += data
        s.close()
        return res.decode("utf-8", errors="ignore")
    except Exception as exc:
        logger.debug("Socket WHOIS query failed for %s on %s: %s", domain, server, exc)
        return ""


def parse_whois_text(text: str, domain: str) -> Tuple[Optional[date], Optional[str]]:
    """Parse expiration date and registrar name from raw WHOIS text output.

    Args:
        text: Raw WHOIS response string.
        domain: Queried domain name.

    Returns:
        Tuple[Optional[date], Optional[str]]: (expiry_date, registrar_name)
    """
    if not text:
        return None, None

    expiry_date: Optional[date] = None
    registrar: Optional[str] = None
    created_date: Optional[date] = None

    # 1. Search for explicit expiration date
    exp_patterns = [
        r'(?i)(?:Registry Expiry Date|Registrar Registration Expiration Date|Registry Expiry|Expir\w+ Date|Expiration Time|paid-till|expires on|expires|Expiry Date|Expiry|Valid Until)\s*:\s*([^\r\n<]+)',
        r'(?i)(?:renewal date|expire-date|expire)\s*:\s*([^\r\n<]+)',
    ]
    for pat in exp_patterns:
        m = re.search(pat, text)
        if m:
            val = m.group(1).strip()
            parsed = parse_expiry_date(val)
            if parsed:
                expiry_date = parsed
                break

    # 2. Search for creation date (used for registries like .nl that renew annually on anniversary)
    created_patterns = [
        r'(?i)(?:Creation Date|Created Date|Created|Registered On|Registration Date|Record created)\s*:\s*([^\r\n<]+)',
    ]
    for pat in created_patterns:
        m = re.search(pat, text)
        if m:
            val = m.group(1).strip()
            parsed = parse_expiry_date(val)
            if parsed:
                created_date = parsed
                break

    # If no explicit expiration date (e.g. SIDN .nl), calculate next annual renewal from creation date
    if not expiry_date and created_date:
        today = datetime.now().date()
        try:
            cand = date(today.year, created_date.month, created_date.day)
            if cand < today:
                cand = date(today.year + 1, created_date.month, created_date.day)
            expiry_date = cand
        except ValueError:
            # Handle Feb 29 leap day edge case
            cand = date(today.year, created_date.month, 28)
            if cand < today:
                cand = date(today.year + 1, created_date.month, 28)
            expiry_date = cand

    # 3. Search for registrar name
    reg_patterns = [
        r'(?i)(?:Registrar Name|Sponsoring Registrar|Registrar|registrar)\s*:\s*([^\r\n<]+)',
        r'(?i)Registrar:\s*\n\s*([^\r\n<]+)',
    ]
    for pat in reg_patterns:
        m = re.search(pat, text)
        if m:
            val = m.group(1).strip()
            if not val.startswith("http") and not val.isdigit() and "whois" not in val.lower():
                # Clean email formats like 'operations@sav.com' -> 'sav.com'
                if "@" in val and "." in val:
                    val = val.split("@")[-1].strip()
                registrar = val
                break

    return expiry_date, registrar


def lookup_domain_socket_whois(domain: str, timeout: int = 8) -> Tuple[Optional[date], Optional[str]]:
    """Lookup domain information directly via Port 43 Socket WHOIS."""
    cleaned = clean_domain_name(domain)
    if not cleaned or "." not in cleaned:
        return None, None

    parts = cleaned.split(".")
    server = None

    # Check SLD first, e.g. 'in.net', 'it.com', 'co.uk'
    if len(parts) >= 3:
        sld = ".".join(parts[-2:])
        server = WHOIS_SERVER_MAP.get(sld)

    # Check TLD, e.g. 'nl', 'se', 'me', 'io'
    if not server and len(parts) >= 2:
        tld = parts[-1]
        server = WHOIS_SERVER_MAP.get(tld)

    if not server:
        server = f"whois.nic.{parts[-1]}"

    # Query mapped server
    raw_text = query_whois_socket(cleaned, server, timeout=timeout)
    exp, reg = parse_whois_text(raw_text, cleaned)
    if exp:
        return exp, reg

    # Fallback to whois.iana.org referral
    iana_text = query_whois_socket(cleaned, "whois.iana.org", timeout=timeout)
    m_refer = re.search(r'(?i)refer:\s*([^\r\n]+)', iana_text)
    if m_refer:
        refer_server = m_refer.group(1).strip()
        ref_text = query_whois_socket(cleaned, refer_server, timeout=timeout)
        exp, reg = parse_whois_text(ref_text, cleaned)
        if exp:
            return exp, reg

    return None, None


def extract_registrar_name(entities: List[Dict[str, Any]]) -> Optional[str]:
    """Extract registrar organization name from RDAP entities list."""
    if not entities or not isinstance(entities, list):
        return None

    for entity in entities:
        roles = entity.get("roles", [])
        if "registrar" in roles or "sponsor" in roles:
            vcard = entity.get("vcardArray")
            if vcard and isinstance(vcard, list) and len(vcard) > 1:
                for item in vcard[1]:
                    if isinstance(item, list) and len(item) > 3 and item[0] == "fn":
                        return str(item[3]).strip()
            if entity.get("handle"):
                return str(entity.get("handle")).strip()
            if entity.get("name"):
                return str(entity.get("name")).strip()

    return None


def extract_expiry_date(events: List[Dict[str, Any]]) -> Optional[date]:
    """Extract expiration date from RDAP events list."""
    if not events or not isinstance(events, list):
        return None

    for event in events:
        action = str(event.get("eventAction", "")).lower()
        if "expiration" in action:
            date_str = event.get("eventDate")
            if date_str:
                return parse_expiry_date(str(date_str))

    return None


def lookup_domain_rdap(domain: str, timeout: int = 10) -> Tuple[Optional[date], Optional[str]]:
    """Lookup domain expiration date and registrar using ICANN RDAP protocol with fallback endpoints."""
    cleaned = clean_domain_name(domain)
    if not cleaned or "." not in cleaned:
        return None, None

    endpoints = [
        f"https://rdap.org/domain/{cleaned}",
        f"https://rdap.cloudflare.com/client/v4/rdap/domain/{cleaned}",
        f"https://rdap.identitydigital.services/rdap/domain/{cleaned}",
        f"https://rdap.sidn.nl/domain/{cleaned}",
    ]

    parts = cleaned.split(".")
    if len(parts) >= 3:
        for i in range(1, len(parts)):
            suffix = ".".join(parts[i:])
            endpoints.append(f"https://rdap.centralnic.com/{suffix}/domain/{cleaned}")
            endpoints.append(f"https://rdap.nominet.uk/{suffix}/domain/{cleaned}")

    headers = {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }

    for url in endpoints:
        try:
            response = requests.get(url, headers=headers, timeout=timeout)
            if response.status_code == 200:
                data = response.json()
                expiry_date = extract_expiry_date(data.get("events", []))
                registrar = extract_registrar_name(data.get("entities", []))
                if expiry_date:
                    return expiry_date, registrar
        except Exception as exc:
            logger.debug("RDAP query failed for %s at %s: %s", cleaned, url, exc)

    return None, None


def lookup_whois_com(domain: str, timeout: int = 10) -> Tuple[Optional[date], Optional[str]]:
    """Lookup domain information from whois.com web page."""
    cleaned = clean_domain_name(domain)
    if not cleaned or "." not in cleaned:
        return None, None

    url = f"https://www.whois.com/whois/{cleaned}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        response = requests.get(url, headers=headers, timeout=timeout)
        if response.status_code != 200:
            return None, None

        html_text = response.text
        expiry_date = None
        registrar = None
        registered_on = None

        # 1. Parse structured df-row blocks
        pairs = re.findall(
            r'<div class=["\']df-row["\']>\s*<div class=["\']df-label["\']>([^<]+)</div>\s*<div class=["\']df-value["\']>([^<]+)</div>\s*</div>',
            html_text,
        )
        data = {k.strip().rstrip(":").lower(): v.strip() for k, v in pairs}

        # Check expiration keys
        for key in ["expires on", "registry expiry date", "expiration date", "expiry date", "paid-till"]:
            if key in data and data[key]:
                expiry_date = parse_expiry_date(data[key])
                if expiry_date:
                    break

        # Check registered on (anniversary for .nl, etc.)
        for key in ["registered on", "creation date", "created on"]:
            if key in data and data[key]:
                registered_on = parse_expiry_date(data[key])
                if registered_on:
                    break

        if not expiry_date and registered_on:
            today = datetime.now().date()
            cand = date(today.year, registered_on.month, registered_on.day)
            if cand < today:
                cand = date(today.year + 1, registered_on.month, registered_on.day)
            expiry_date = cand

        # Check registrar keys
        for key in ["registrar", "registrar name", "sponsoring registrar"]:
            if key in data and data[key]:
                val = data[key]
                if not val.startswith("http") and not val.isdigit() and "@" not in val:
                    registrar = val
                    break

        # 2. Fallback to raw whois blocks if not found
        if not expiry_date:
            raw_blocks = re.findall(r'<pre[^>]*class=["\']df-raw["\'][^>]*>(.*?)</pre>', html_text, re.DOTALL)
            for raw_text in raw_blocks:
                exp_res, reg_res = parse_whois_text(raw_text, cleaned)
                if exp_res:
                    expiry_date = exp_res
                if not registrar and reg_res:
                    registrar = reg_res
                if expiry_date:
                    break

        return expiry_date, registrar

    except Exception as exc:
        logger.debug("whois.com lookup failed for %s: %s", cleaned, exc)

    return None, None


def lookup_domain_info(domain: str, timeout: int = 10) -> Tuple[Optional[date], Optional[str]]:
    """Comprehensive domain expiration date and registrar lookup combining Socket WHOIS, RDAP, and WHOIS.com.

    Strategy:
        1. Fast, reliable Direct Port 43 Socket WHOIS (bypasses web anti-bot, rate limits, and CAPTCHAs).
        2. ICANN & CentralNic/IdentityDigital RDAP protocol endpoints.
        3. whois.com web page scraping as fallback.

    Args:
        domain: Domain name (e.g. 'google.com', '99okae.it.com', 'hubet.in.net').
        timeout: Request timeout in seconds.

    Returns:
        Tuple[Optional[date], Optional[str]]: (expiry_date, registrar_name)
    """
    # 1. Try Direct Port 43 Socket WHOIS
    expiry_date, registrar = lookup_domain_socket_whois(domain, timeout=timeout)
    if expiry_date:
        return expiry_date, registrar

    # 2. Try RDAP
    expiry_date, registrar = lookup_domain_rdap(domain, timeout=timeout)
    if expiry_date:
        return expiry_date, registrar

    # 3. Try whois.com web scrape
    logger.debug("Socket & RDAP did not resolve '%s'. Falling back to whois.com...", domain)
    expiry_date, registrar = lookup_whois_com(domain, timeout=timeout)
    if expiry_date:
        return expiry_date, registrar

    return None, None
