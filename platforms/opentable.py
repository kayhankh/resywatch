"""
OpenTable platform checker.

STATUS: OpenTable aggressively blocks server-side API requests
(Cloudflare, bot detection, 503s). Direct HTTP availability checks
don't work from a server environment.

CURRENT APPROACH:
  - URL resolution works (extract rid/slug from URLs)
  - Search uses a simple scrape attempt with graceful fallback
  - Availability checking requires a proxy service (Apify, ScrapingBee)
    or is skipped with a user-friendly message

To enable full OpenTable monitoring, set APIFY_API_KEY env var
and the checker will use Apify's OpenTable actor for availability.

Without Apify, OpenTable watches will still be created but will
show a "pending setup" status until a proxy service is configured.
"""

import json
import logging
import os
import re
from datetime import datetime

import httpx

from platforms.base import BasePlatform

logger = logging.getLogger(__name__)

APIFY_API_KEY = os.environ.get("APIFY_API_KEY", "")
APIFY_OT_ACTOR = "canadesk/opentable"


class OpenTablePlatform(BasePlatform):
    name = "opentable"

    async def fetch_availability(
        self,
        venue_id: str,
        date: str,
        party_size: int,
        **kwargs,
    ) -> list[dict]:
        """
        Fetch availability from OpenTable.

        If APIFY_API_KEY is set, uses Apify's OpenTable actor.
        Otherwise returns empty (OpenTable blocks direct server requests).
        """
        if APIFY_API_KEY:
            return await self._fetch_via_apify(venue_id, date, party_size)

        # Without a proxy service, we can't check OT availability
        logger.debug(
            f"OpenTable availability check skipped for {venue_id} "
            f"(no APIFY_API_KEY set). Set APIFY_API_KEY to enable."
        )
        return []

    async def _fetch_via_apify(
        self, venue_id: str, date: str, party_size: int
    ) -> list[dict]:
        """Use Apify's OpenTable actor to fetch availability."""
        run_input = {
            "action": "getAvailability",
            "rid": int(venue_id) if venue_id.isdigit() else 0,
            "dateTime": f"{date}T19:00:00",
            "partySize": party_size,
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {APIFY_API_KEY}",
        }

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                # Start the actor run
                resp = await client.post(
                    f"https://api.apify.com/v2/acts/{APIFY_OT_ACTOR}/run-sync-get-dataset-items",
                    headers=headers,
                    json=run_input,
                    params={"token": APIFY_API_KEY},
                )

                if resp.status_code != 200:
                    logger.error(f"Apify OT actor failed: {resp.status_code} {resp.text[:200]}")
                    return []

                data = resp.json()

        except Exception as e:
            logger.error(f"Apify OT request failed: {e}")
            return []

        # Parse Apify response into our standard slot format
        slots = []
        for item in data if isinstance(data, list) else [data]:
            time_slots = item.get("timeSlots", item.get("availability", {}).get("timeSlots", []))
            for ts in time_slots:
                dt_str = ts.get("dateTime", "")
                if not dt_str:
                    continue

                is_available = ts.get("isAvailable", True)
                if not is_available:
                    continue

                try:
                    if "T" in dt_str:
                        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                    else:
                        dt = datetime.strptime(dt_str, "%H:%M")
                    time_24h = dt.strftime("%H:%M")
                    time_display = dt.strftime("%-I:%M %p")
                except ValueError:
                    continue

                slots.append({
                    "time_24h": time_24h,
                    "time_display": time_display,
                    "table_type": ts.get("type", "Standard"),
                    "config_id": ts.get("slotHash", ""),
                })

        return slots

    def build_booking_url(
        self,
        watch: dict,
        date: str,
        party_size: int,
    ) -> str:
        url_slug = (
            watch.get("platform_data", {}).get("url_slug", "")
            or watch.get("url_slug", "")
        )
        rid = watch.get("venue_id", "")

        if url_slug:
            return (
                f"https://www.opentable.com/r/{url_slug}"
                f"?dateTime={date}T19%3A00&covers={party_size}"
            )
        elif rid:
            return (
                f"https://www.opentable.com/restref/client/?rid={rid}"
                f"&datetime={date}T19%3A00&covers={party_size}"
            )
        return "https://www.opentable.com"

    async def search(self, query: str, **kwargs) -> list[dict]:
        """
        OpenTable search is blocked from server-side.
        Returns empty. Users should paste OT URLs directly.
        """
        logger.debug(f"OpenTable search skipped (blocked from server). Use URL directly.")
        return []

    def can_resolve_url(self, url: str) -> bool:
        return "opentable.com" in url

    async def resolve_url(self, url: str, **kwargs) -> dict | None:
        """
        Extract restaurant info from an OpenTable URL.
        This works without API access since we're just parsing the URL.
        """
        # Pattern: /r/restaurant-slug-city
        slug_match = re.search(r"opentable\.com/r/([^/?#]+)", url)
        # Pattern: ?rid=123456
        rid_match = re.search(r"[?&]rid=(\d+)", url)
        # Pattern: /restaurant/profile/123456
        profile_match = re.search(r"opentable\.com/restaurant/profile/(\d+)", url)

        if slug_match:
            url_slug = slug_match.group(1)
            # Extract a readable name from the slug
            # "peter-luger-steak-house-brooklyn" -> "Peter Luger Steak House Brooklyn"
            name = url_slug.replace("-", " ").title()

            # Try to extract rid from page (may fail due to blocking)
            rid = await self._try_extract_rid(url_slug)

            return {
                "id": rid or url_slug,
                "name": name,
                "location": "",
                "platform": "opentable",
                "url_slug": url_slug,
                "platform_data": {
                    "url_slug": url_slug,
                    "rid": rid,
                },
            }

        elif rid_match or profile_match:
            rid = (rid_match or profile_match).group(1)
            return {
                "id": rid,
                "name": f"OpenTable Restaurant #{rid}",
                "location": "",
                "platform": "opentable",
                "url_slug": "",
                "platform_data": {
                    "rid": rid,
                },
            }

        return None

    async def _try_extract_rid(self, url_slug: str) -> str:
        """
        Attempt to extract the numeric rid from an OpenTable page.
        May fail due to bot protection. Non-critical.
        """
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "text/html",
        }

        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                resp = await client.get(
                    f"https://www.opentable.com/r/{url_slug}",
                    headers=headers,
                )
                if resp.status_code == 200:
                    rid_match = re.search(r'"rid":(\d+)', resp.text)
                    if rid_match:
                        return rid_match.group(1)
        except Exception:
            pass

        return ""
