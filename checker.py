"""
Availability checker — polls multiple platforms for open reservation slots.

Routes each watch to the correct platform checker (Resy, SevenRooms, OpenTable)
based on the watch's platform field.
"""

import logging
from datetime import datetime

from platforms import get_platform

logger = logging.getLogger(__name__)


async def check_all_watches(watches: list[dict], api_key: str) -> list[dict]:
    """
    Check all active watches for available tables across all platforms.

    Returns a list of alert dicts for any matches found.
    """
    alerts = []
    today = datetime.now().strftime("%Y-%m-%d")

    for watch in watches:
        if watch.get("paused"):
            continue

        venue_id = watch.get("venue_id")
        if not venue_id:
            continue

        platform_name = watch.get("platform", "resy")
        platform = get_platform(platform_name)
        if not platform:
            logger.warning(f"Unknown platform '{platform_name}' for watch #{watch.get('id')}")
            continue

        party_size = watch["party_size"]
        time_min = watch["time_min"]
        time_max = watch["time_max"]
        notified_slots = set(watch.get("notified_slots", []))

        for date in watch["dates"]:
            if date < today:
                continue

            try:
                slots = await platform.fetch_availability(
                    venue_id=str(venue_id),
                    date=date,
                    party_size=party_size,
                    api_key=api_key,
                )
            except Exception as e:
                logger.error(
                    f"Error fetching {platform_name} availability for "
                    f"{watch.get('venue_display', venue_id)} on {date}: {e}"
                )
                continue

            for slot in slots:
                slot_time = slot["time_24h"]
                slot_key = f"{date}_{slot_time}"

                if not (time_min <= slot_time <= time_max):
                    continue

                if slot_key in notified_slots:
                    continue

                booking_url = platform.build_booking_url(
                    watch=watch,
                    date=date,
                    party_size=party_size,
                )

                platform_emoji = {
                    "resy": "🟠",
                    "sevenrooms": "🔵",
                    "opentable": "🔴",
                }.get(platform_name, "⚪")

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
                    "platform": platform_name,
                    "platform_emoji": platform_emoji,
                })

    return alerts


def format_date_display(date_str: str) -> str:
    """Format YYYY-MM-DD to a friendly display string."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%A, %b %-d")
    except ValueError:
        return date_str
