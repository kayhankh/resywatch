"""
SevenRooms platform checker.

Uses SevenRooms' public widget API:
  - /api-yoa/availability/widget/range — get availability for a venue/date range/party size

SevenRooms is used by many London restaurants (Berenjak, Brat, etc.)
and increasingly in NYC/globally.

Venue slugs are found in the booking widget URL, e.g.:
  https://www.sevenrooms.com/reservations/berenjakjks
  → venue slug = "berenjakjks"
"""

import logging
import re
from datetime import datetime

import httpx

from platforms.base import BasePlatform

logger = logging.getLogger(__name__)

SEVENROOMS_API_BASE = "https://www.sevenrooms.com/api-yoa/availability/widget/range"


class SevenRoomsPlatform(BasePlatform):
    name = "sevenrooms"

    async def fetch_availability(
        self,
        venue_id: str,
        date: str,
        party_size: int,
        **kwargs,
    ) -> list[dict]:
        """
        Fetch availability from SevenRooms widget API.

        venue_id here is the venue slug (e.g. "berenjakjks").
        date is "YYYY-MM-DD" — we convert to "MM/DD/YYYY" for SevenRooms.
        """
        # Convert date format
        try:
            dt = datetime.strptime(date, "%Y-%m-%d")
            sr_date = dt.strftime("%m/%d/%Y")
        except ValueError:
            logger.error(f"Invalid date format: {date}")
            return []

        # Default time slot for the query — SevenRooms uses this as a center point
        # and returns all available times around it via halo_size_interval
        preferred_time = kwargs.get("preferred_time", "19:00")

        params = {
            "venue": venue_id,
            "time_slot": preferred_time,
            "party_size": party_size,
            "halo_size_interval": 16,  # returns wide range of times
            "start_date": sr_date,
            "num_days": 1,
            "channel": "SEVENROOMS_WIDGET",
        }

        headers = {
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Referer": f"https://www.sevenrooms.com/reservations/{venue_id}",
        }

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                SEVENROOMS_API_BASE,
                params=params,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()

        slots = []
        availability = data.get("data", {}).get("availability", {})

        for avail_date, shifts in availability.items():
            for shift in shifts:
                times = shift.get("times", [])
                shift_name = shift.get("name", "")

                for t in times:
                    time_iso = t.get("time_iso", "")
                    time_display_raw = t.get("time", "")
                    slot_type = t.get("type", "")

                    # Include request-type slots but flag them
                    # Many high-demand restaurants only offer request slots
                    is_request = slot_type == "request"

                    if not time_iso:
                        continue

                    try:
                        slot_dt = datetime.fromisoformat(time_iso)
                        time_24h = slot_dt.strftime("%H:%M")
                        time_display = slot_dt.strftime("%-I:%M %p")
                    except ValueError:
                        # Fallback: parse the display time
                        time_24h = _parse_display_time(time_display_raw)
                        time_display = time_display_raw
                        if not time_24h:
                            continue

                    table_type = shift_name if shift_name else "Standard"
                    if is_request:
                        table_type = f"{table_type} (Request)"

                    # SevenRooms returns an access_persistent_id for booking
                    config_id = t.get("access_persistent_id", "")

                    slots.append({
                        "time_24h": time_24h,
                        "time_display": time_display,
                        "table_type": table_type,
                        "config_id": config_id,
                        "is_request": is_request,
                    })

        return slots

    def build_booking_url(
        self,
        watch: dict,
        date: str,
        party_size: int,
    ) -> str:
        venue_slug = watch.get("venue_id") or watch.get("platform_data", {}).get("venue_slug", "")
        if not venue_slug:
            return "https://www.sevenrooms.com"

        # Convert date for URL
        try:
            dt = datetime.strptime(date, "%Y-%m-%d")
            date_param = dt.strftime("%m-%d-%Y")
        except ValueError:
            date_param = ""

        url = f"https://www.sevenrooms.com/reservations/{venue_slug}"
        if date_param:
            url += f"?date={date_param}&party_size={party_size}"
        return url

    async def search(self, query: str, **kwargs) -> list[dict]:
        """
        SevenRooms doesn't have a public search API.
        We rely on Google search to find SevenRooms venue pages.
        Returns empty list — discovery is handled by the multi-platform
        search in restaurant_lookup.py via Google.
        """
        return []

    def can_resolve_url(self, url: str) -> bool:
        return "sevenrooms.com" in url

    async def resolve_url(self, url: str, **kwargs) -> dict | None:
        """Extract venue slug from a SevenRooms URL."""
        # Patterns:
        #   https://www.sevenrooms.com/reservations/berenjakjks
        #   https://www.sevenrooms.com/explore/berenjakjks
        match = re.search(r"sevenrooms\.com/(?:reservations|explore|experiences)/([^/?#]+)", url)
        if not match:
            return None

        venue_slug = match.group(1)
        venue_name = venue_slug.replace("-", " ").title()

        # Validate the slug works by making a test availability call
        valid = await self._validate_venue(venue_slug)
        if not valid:
            logger.warning(f"SevenRooms venue slug '{venue_slug}' didn't return valid data")
            # Still return it — might work for different dates
            pass

        return {
            "id": venue_slug,
            "name": venue_name,
            "location": "",
            "platform": "sevenrooms",
            "url_slug": venue_slug,
            "platform_data": {
                "venue_slug": venue_slug,
            },
        }

    async def _validate_venue(self, venue_slug: str) -> bool:
        """Quick check that a venue slug returns data."""
        today = datetime.now()
        params = {
            "venue": venue_slug,
            "time_slot": "19:00",
            "party_size": 2,
            "halo_size_interval": 4,
            "start_date": today.strftime("%m/%d/%Y"),
            "num_days": 1,
            "channel": "SEVENROOMS_WIDGET",
        }
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(SEVENROOMS_API_BASE, params=params)
                if resp.status_code == 200:
                    data = resp.json()
                    return "data" in data
        except Exception:
            pass
        return False


def _parse_display_time(display: str) -> str | None:
    """Parse '7:30 PM' style string to '19:30' format."""
    if not display:
        return None
    display = display.strip().upper()
    match = re.match(r"(\d{1,2}):(\d{2})\s*(AM|PM)", display)
    if not match:
        return None
    hours = int(match.group(1))
    minutes = int(match.group(2))
    ampm = match.group(3)
    if ampm == "PM" and hours != 12:
        hours += 12
    elif ampm == "AM" and hours == 12:
        hours = 0
    return f"{hours:02d}:{minutes:02d}"
