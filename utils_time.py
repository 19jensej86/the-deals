"""
Time Utilities for DealFinder - v5.0
====================================
Parses Ricardo end time text into datetime objects.

Handles formats like:
- "Heute, 16:01"
- "Morgen, 00:05"
- "So, 18 Jan., 16:20"
- "So, 1 Feb., 21:48"
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Optional

TZ_CH = ZoneInfo("Europe/Zurich")

# German month abbreviations → month number
MONTH_MAP = {
    "jan": 1, "jan.": 1,
    "feb": 2, "feb.": 2,
    "mär": 3, "mär.": 3, "maer": 3, "maer.": 3, "mrz": 3, "mrz.": 3,
    "apr": 4, "apr.": 4,
    "mai": 5,
    "jun": 6, "jun.": 6,
    "jul": 7, "jul.": 7,
    "aug": 8, "aug.": 8,
    "sep": 9, "sept": 9, "sep.": 9, "sept.": 9,
    "okt": 10, "okt.": 10,
    "nov": 11, "nov.": 11,
    "dez": 12, "dez.": 12,
}


def _strip_extra(text: str) -> str:
    """Removes extra info like '(7h)' from end time text"""
    if not text:
        return ""
    
    # Only first line
    line = text.split("\n", 1)[0].strip()
    
    # Remove things like "(7h)" at the end
    line = re.sub(r"\(\d+h\)$", "", line).strip()
    
    return line


def _parse_time_part(s: str) -> Optional[tuple[int, int]]:
    """Extracts HH:MM from a string"""
    m = re.search(r"(\d{1,2}):(\d{2})", s)
    if not m:
        return None
    try:
        h = int(m.group(1))
        mnt = int(m.group(2))
        return h, mnt
    except ValueError:
        return None


def parse_ricardo_end_time(text: Optional[str]) -> Optional[datetime]:
    """
    Converts Ricardo end time text to datetime object (Europe/Zurich).
    
    Returns None if parsing fails.
    """
    if not text:
        return None

    s = _strip_extra(text)
    if not s:
        return None

    now = datetime.now(TZ_CH)
    lower = s.lower()

    # =========================================================================
    # Case 1: "Heute, 16:01"
    # =========================================================================
    if lower.startswith("heute"):
        parts = s.split(",", 1)
        time_part = parts[1].strip() if len(parts) == 2 else parts[0].strip()

        hm = _parse_time_part(time_part)
        if not hm:
            return None

        hour, minute = hm
        dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return dt

    # =========================================================================
    # Case 2: "Morgen, 00:05"
    # =========================================================================
    if lower.startswith("morgen"):
        parts = s.split(",", 1)
        time_part = parts[1].strip() if len(parts) == 2 else parts[0].strip()

        hm = _parse_time_part(time_part)
        if not hm:
            return None

        hour, minute = hm
        dt = (now + timedelta(days=1)).replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
        return dt

    # =========================================================================
    # Case 3: Absolute date, e.g. "So, 18 Jan., 16:20"
    # =========================================================================
    # Ignore weekday → everything after first comma
    if "," in s:
        parts = [p.strip() for p in s.split(",")]
        rest = " ".join(parts[1:]).strip()
    else:
        rest = s

    # Find day & month
    m_date = re.search(r"(\d{1,2})\s+([A-Za-zäöüÄÖÜ\.]+)", rest)
    if not m_date:
        return None

    day_str = m_date.group(1)
    month_str = m_date.group(2).lower()

    try:
        day = int(day_str)
    except ValueError:
        return None

    month = MONTH_MAP.get(month_str)
    if not month:
        return None

    # Extract time
    hm = _parse_time_part(rest)
    if not hm:
        hour, minute = 23, 59
    else:
        hour, minute = hm

    year = now.year
    dt = datetime(year, month, day, hour, minute, tzinfo=TZ_CH)

    # If date is in the past → probably next year
    if dt < now:
        try:
            dt = dt.replace(year=year + 1)
        except ValueError:
            # Feb 29 etc.
            dt = dt + timedelta(days=365)

    return dt


def format_time_remaining(hours: float) -> str:
    """Formats hours into readable string like '2h 30m' or '3d 5h'"""
    if hours is None:
        return "?"
    
    if hours < 1:
        mins = int(hours * 60)
        return f"{mins}m"
    elif hours < 24:
        h = int(hours)
        m = int((hours - h) * 60)
        return f"{h}h {m}m" if m > 0 else f"{h}h"
    else:
        days = int(hours / 24)
        remaining_hours = int(hours % 24)
        return f"{days}d {remaining_hours}h"
