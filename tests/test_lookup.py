"""Tests for domain lookup engine in renewals/lookup.py."""

from datetime import date
from renewals.lookup import lookup_domain_info, parse_expiry_date


def test_parse_expiry_date_formats():
    """Verify various date format parsing."""
    assert parse_expiry_date("2026-10-15") == date(2026, 10, 15)
    assert parse_expiry_date("15/10/2026") == date(2026, 10, 15)
    assert parse_expiry_date("2027-07-02T17:48:00Z") == date(2027, 7, 2)
    assert parse_expiry_date("02/07/2027") == date(2027, 7, 2)


def test_lookup_hanf_ws():
    """Verify hanf.ws is resolved via RDAP to July 2, 2027 with Namecheap registrar."""
    expiry_date, registrar = lookup_domain_info("hanf.ws")
    assert expiry_date == date(2027, 7, 2)
    assert registrar is not None
    assert "namecheap" in registrar.lower()
