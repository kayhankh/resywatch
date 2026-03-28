"""
Parse natural language watch commands into structured watch configs.

Handles formats like:
    "Don Angie, Apr 11-12, 2, 7-9pm"
    "Carbone, any Friday in April, 2, 8-9:30pm"
    "Le Bernardin, May 1-15, 2, 7-9pm"
    "id:1387, May 3, 4, 6:30-8pm"
"""

import re
from datetime import datetime, timedelta
from typing import Optional

# Month name mapping
MONTHS = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

WEEKDAYS = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thurs": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}


def parse_watch_command(text: str) -> dict:
    """
    Parse a watch command string into a structured dict.

    Returns:
        {
            "restaurant_name": str,
            "venue_id": int | None,
            "dates": list[str],        # ["2025-04-11", "2025-04-12"]
            "party_size": int,
            "time_min": str,            # "19:00"
            "time_max": str,            # "21:00"
        }
    """
    # Split by comma, strip whitespace
    parts = [p.strip() for p in text.split(",")]

    if len(parts) < 4:
        raise ValueError(
            "Expected format: <restaurant>, <dates>, <party size>, <time range>\n"
            "Example: Don Angie, Apr 11-12, 2, 7-9pm"
        )

    restaurant_raw = parts[0]
    dates_raw = parts[1]
    party_raw = parts[2]
    time_raw = parts[3]

    # ── Restaurant name or ID ─────────────────────────────────────────────
    venue_id = None
    restaurant_name = restaurant_raw

    # Check for explicit venue ID: "id:1387"
    id_match = re.match(r"id[:\s]*(\d+)", restaurant_raw, re.IGNORECASE)
    if id_match:
        venue_id = int(id_match.group(1))
        restaurant_name = f"Venue #{venue_id}"

    # ── Party size ────────────────────────────────────────────────────────
    party_match = re.search(r"(\d+)", party_raw)
    if not party_match:
        raise ValueError(f"Couldn't parse party size from: \"{party_raw}\"")
    party_size = int(party_match.group(1))

    # ── Time range ────────────────────────────────────────────────────────
    time_min, time_max = parse_time_range(time_raw)

    # ── Dates ─────────────────────────────────────────────────────────────
    dates = parse_dates(dates_raw)

    return {
        "restaurant_name": restaurant_name,
        "venue_id": venue_id,
        "dates": dates,
        "party_size": party_size,
        "time_min": time_min,
        "time_max": time_max,
    }


def parse_time_range(text: str) -> tuple[str, str]:
    """
    Parse time ranges like "7-9pm", "7:30-9:30pm", "19:00-21:00".

    Returns tuple of ("HH:MM", "HH:MM") in 24-hour format.
    """
    text = text.strip().lower()

    # Try "7-9pm", "7:30-9:30pm", "7pm-9pm"
    pattern = r"(\d{1,2}(?::\d{2})?)\s*(am|pm)?\s*[-–to]+\s*(\d{1,2}(?::\d{2})?)\s*(am|pm)?"
    match = re.search(pattern, text)
    if not match:
        raise ValueError(f"Couldn't parse time range from: \"{text}\"")

    start_str, start_ampm, end_str, end_ampm = match.groups()

    # If only end has am/pm, assume start is same period
    # But if start < end numerically and end is pm, start might be pm too
    if not start_ampm and end_ampm:
        start_ampm = end_ampm

    time_min = convert_to_24h(start_str, start_ampm)
    time_max = convert_to_24h(end_str, end_ampm)

    return time_min, time_max


def convert_to_24h(time_str: str, ampm: Optional[str]) -> str:
    """Convert a time string to HH:MM format."""
    if ":" in time_str:
        hours, minutes = time_str.split(":")
        hours = int(hours)
        minutes = int(minutes)
    else:
        hours = int(time_str)
        minutes = 0

    # Already 24h format
    if hours >= 13 and not ampm:
        return f"{hours:02d}:{minutes:02d}"

    if ampm == "pm" and hours != 12:
        hours += 12
    elif ampm == "am" and hours == 12:
        hours = 0

    return f"{hours:02d}:{minutes:02d}"


def parse_dates(text: str) -> list[str]:
    """
    Parse date expressions into a list of YYYY-MM-DD strings.

    Handles:
        "Apr 11-12"           → ["2025-04-11", "2025-04-12"]
        "April 11"            → ["2025-04-11"]
        "May 1-15"            → ["2025-05-01", ..., "2025-05-15"]
        "any Friday in April" → all Fridays in April
        "Fridays in April"    → all Fridays in April
        "Apr 11-May 2"        → range across months
    """
    text = text.strip().lower()
    now = datetime.now()
    current_year = now.year

    # ── Pattern: "any/every/all <weekday>(s) in <month>" ──────────────────
    weekday_pattern = r"(?:any|every|all)?\s*(\w+?)s?\s+in\s+(\w+)"
    wm = re.search(weekday_pattern, text)
    if wm:
        day_name = wm.group(1).lower()
        month_name = wm.group(2).lower()

        if day_name in WEEKDAYS and month_name in MONTHS:
            weekday = WEEKDAYS[day_name]
            month = MONTHS[month_name]
            year = current_year if month >= now.month else current_year + 1
            return get_weekdays_in_month(year, month, weekday)

    # ── Pattern: "<weekday>s in <month>" (without any/every prefix) ───────
    weekday_pattern2 = r"(\w+?)s\s+in\s+(\w+)"
    wm2 = re.search(weekday_pattern2, text)
    if wm2:
        day_name = wm2.group(1).lower()
        month_name = wm2.group(2).lower()

        if day_name in WEEKDAYS and month_name in MONTHS:
            weekday = WEEKDAYS[day_name]
            month = MONTHS[month_name]
            year = current_year if month >= now.month else current_year + 1
            return get_weekdays_in_month(year, month, weekday)

    # ── Pattern: "<month> <day>-<day>" (same month range) ─────────────────
    range_pattern = r"(\w+)\s+(\d{1,2})\s*[-–]\s*(\d{1,2})"
    rm = re.search(range_pattern, text)
    if rm:
        month_name = rm.group(1).lower()
        if month_name in MONTHS:
            month = MONTHS[month_name]
            start_day = int(rm.group(2))
            end_day = int(rm.group(3))
            year = current_year if month >= now.month else current_year + 1
            return [
                f"{year}-{month:02d}-{d:02d}"
                for d in range(start_day, end_day + 1)
            ]

    # ── Pattern: single date "<month> <day>" ──────────────────────────────
    single_pattern = r"(\w+)\s+(\d{1,2})"
    sm = re.search(single_pattern, text)
    if sm:
        month_name = sm.group(1).lower()
        if month_name in MONTHS:
            month = MONTHS[month_name]
            day = int(sm.group(2))
            year = current_year if month >= now.month else current_year + 1
            return [f"{year}-{month:02d}-{day:02d}"]

    raise ValueError(
        f"Couldn't parse dates from: \"{text}\"\n"
        "Try formats like: Apr 11-12, May 3, Fridays in April"
    )


def get_weekdays_in_month(year: int, month: int, weekday: int) -> list[str]:
    """Get all dates for a specific weekday in a month."""
    dates = []
    # Start from 1st of month
    d = datetime(year, month, 1)
    # Find first matching weekday
    while d.weekday() != weekday:
        d += timedelta(days=1)
    # Collect all matching weekdays in the month
    while d.month == month:
        dates.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=7)
    return dates
