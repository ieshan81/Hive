"""NYSE holiday calendar — never default to open when data is missing."""

from __future__ import annotations

from datetime import date

# Embedded NYSE full-day closures (extend annually). calendar_available=True when date is covered.
NYSE_FULL_CLOSURES: dict[date, str] = {
    date(2025, 1, 1): "New Year's Day",
    date(2025, 1, 20): "Martin Luther King Jr. Day",
    date(2025, 2, 17): "Washington's Birthday",
    date(2025, 4, 18): "Good Friday",
    date(2025, 5, 26): "Memorial Day",
    date(2025, 6, 19): "Juneteenth",
    date(2025, 7, 4): "Independence Day",
    date(2025, 9, 1): "Labor Day",
    date(2025, 11, 27): "Thanksgiving",
    date(2025, 12, 25): "Christmas",
    date(2026, 1, 1): "New Year's Day",
    date(2026, 1, 19): "Martin Luther King Jr. Day",
    date(2026, 2, 16): "Washington's Birthday",
    date(2026, 4, 3): "Good Friday",
    date(2026, 5, 25): "Memorial Day",
    date(2026, 6, 19): "Juneteenth",
    date(2026, 7, 3): "Independence Day (observed)",
    date(2026, 9, 7): "Labor Day",
    date(2026, 11, 26): "Thanksgiving",
    date(2026, 12, 25): "Christmas",
}

_CALENDAR_YEAR_MIN = min(d.year for d in NYSE_FULL_CLOSURES)
_CALENDAR_YEAR_MAX = max(d.year for d in NYSE_FULL_CLOSURES)


def calendar_available_for(d: date) -> bool:
    return _CALENDAR_YEAR_MIN <= d.year <= _CALENDAR_YEAR_MAX


def us_market_holiday(d: date) -> tuple[bool, str | None]:
    """Return (is_holiday, holiday_name)."""
    name = NYSE_FULL_CLOSURES.get(d)
    return (name is not None, name)
