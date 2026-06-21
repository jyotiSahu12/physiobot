"""Human-friendly date/time rendering for patient-facing messages.

The state machine works with ISO strings internally (YYYY-MM-DD, HH:MM) for
unambiguous calendar/sheets storage, but showing "2026-06-22T13:00" verbatim
to a patient reads like a system log, not a clinic receptionist.
"""
from __future__ import annotations

import datetime as dt


def humanize_date(date_str: str) -> str:
    """"2026-06-22" -> "Monday, June 22, 2026". Returns the input unchanged if
    it isn't a parseable ISO date."""
    try:
        d = dt.date.fromisoformat(date_str)
    except (ValueError, TypeError):
        return date_str
    # d.day is a plain int (no leading zero), unlike strftime's %d.
    return f"{d.strftime('%A, %B')} {d.day}, {d.year}"


def humanize_time(time_str: str) -> str:
    """"13:00" -> "1:00 PM". Returns the input unchanged if it isn't a
    parseable HH:MM time."""
    try:
        t = dt.time.fromisoformat(time_str)
    except (ValueError, TypeError):
        return time_str
    # %I zero-pads the hour ("01:00 PM"); strip just that one leading zero.
    return t.strftime("%I:%M %p").lstrip("0")


def humanize_datetime(date_str: str, time_str: str) -> str:
    return f"{humanize_date(date_str)} at {humanize_time(time_str)}"
