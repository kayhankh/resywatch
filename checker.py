"""
Availability checker — polls Resy's /4/find endpoint for open reservation slots.

This module handles:
- Fetching available time slots for a given venue/date/party size
- Filtering slots against the user's time window
- Generating alert payloads with direct booking links
"""

import logging
from datetime import datetime

import httpx

from restaurant_lookup import build_resy_booking_url

logger = logging.getLogger(__name__)

RESY_API_BASE = "https://api.resy.com"


async def check_all_watches(watches: list[dict], api_key: str) -> list[dict]:
    """
    Check all active watches for available tables.

    Returns a list of alert dicts for any matches found:
        {
            "watch_id": 1,
            "restaurant": "Don Angie",
            "date": "2025-04-11",
            "time": "7:30 PM",
            "party_size": 2,
            "table_type": "Dining Room",
            "booking_url": "https://resy.com/...",
            "config_id": "abc123",
        }
    """
    alerts = []
    today = datetime.now().strftime("%Y-%m-%d")

    for watch in watches:
        if watch.get("paused"):
            continue

        venue_id = watch.get("venue_id")
        if not venue_id:
            continue

        party_size = watch["party_size"]
        time_min = watch["time_min"]
        time_max = watch["time_max"]
        notified_slots = set(watch.get("notified_slots", []))

        for date in watch["dates"]:
            # Skip past dates
            if date < today:
                continue

            try:
                slots = await fetch_resy_availability(
                    venue_id=venue_id,
                    date=date,
                    party_size=party_size,
                    api_key=api_key,
                )
            except Exception as e:
                logger.error(f"Error fetching availability for {watch.get('venue_display', venue_id)} on {date}: {e}")
                continue

            for slot in slots:
                slot_time = slot["time_24h"]  # "19:30"
                slot_key = f"{date}_{slot_time}"

                # Check if within time window
                if not (time_min <= slot_time <= time_max):
                    continue

                # Check if already notified
                if slot_key in notified_slots:
                    continue

                # Build booking URL
                url_slug = watch.get("resy_url_slug", "")
                if url_slug:
                    booking_url = build_resy_booking_url(
                        venue_slug=url_slug,
                        date=date,
                        party_size=party_size,
                    )
                else:
                    booking_url = f"https://resy.com"

                alerts.append({
                    "watch_id": watch["id"],
                    "restaurant": watch.get("venue_display", watch.get("restaurant_name", "Unknown")),
                    "date": format_date_display(date),
                    "date_raw": date,
                    "time": slot["time_display"],
                    "time_raw": slot_time,
                    "party_size": party_size,
                    "table_type": slot.get("table_type", "Standard"),
                    "booking_url": booking_url,
                    "config_id": slot.get("config_id", ""),
                })

    return alerts


async def fetch_resy_availability(
    venue_id: int,
    date: str,
    party_size: int,
    api_key: str,
) -> list[dict]:
    """
    Fetch available time slots from Resy's /4/find endpoint.

    Returns list of:
        {
            "time_24h": "19:30",
            "time_display": "7:30 PM",
            "table_type": "Dining Room",
            "config_id": "abc123",
        }
    """
    headers = {
        "Authorization": api_key,
        "Origin": "https://resy.com",
        "Referer": "https://resy.com/",
        "X-Origin": "https://resy.com",
    }

    params = {
        "lat": 0,
        "long": 0,
        "day": date,
        "party_size": party_size,
        "venue_id": venue_id,
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{RESY_API_BASE}/4/find",
            headers=headers,
            params=params,
        )
        resp.raise_for_status()
        data = resp.json()

    slots = []

    # Parse the response — Resy returns availability nested under results.venues
    results = data.get("results", {})
    venues = results.get("venues", [])

    for venue in venues:
        venue_slots = venue.get("slots", [])
        for s in venue_slots:
            config = s.get("config", {})
            date_info = s.get("date", {})

            # Extract time
            time_start = date_info.get("start", "")
            if not time_start:
                continue

            # Resy returns times like "2025-04-11 19:30:00"
            try:
                dt = datetime.strptime(time_start, "%Y-%m-%d %H:%M:%S")
                time_24h = dt.strftime("%H:%M")
                time_display = dt.strftime("%-I:%M %p")
            except ValueError:
                # Try alternate format
                try:
                    dt = datetime.fromisoformat(time_start)
                    time_24h = dt.strftime("%H:%M")
                    time_display = dt.strftime("%-I:%M %p")
                except ValueError:
                    continue

            table_type = config.get("type", "Standard")
            config_id = config.get("token", "")

            slots.append({
                "time_24h": time_24h,
                "time_display": time_display,
                "table_type": table_type,
                "config_id": config_id,
            })

    return slots


def format_date_display(date_str: str) -> str:
    """Format YYYY-MM-DD to a friendly display string."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%A, %b %-d")
    except ValueError:
        return date_str
