"""
Resy platform checker.

Uses Resy's public API:
  - /3/venuesearch/search — find venues by name
  - /4/find — get availability for a venue/date/party size
"""

import logging
import re
from datetime import datetime

import httpx

from platforms.base import BasePlatform

logger = logging.getLogger(__name__)

RESY_API_BASE = "https://api.resy.com"
DEFAULT_API_KEY = 'ResyAPI api_key="VbWk7s3L4KiK5fzlO7JD3Q5EYolJI7n5"'


class ResyPlatform(BasePlatform):
    name = "resy"

    async def fetch_availability(
        self,
        venue_id: str,
        date: str,
        party_size: int,
        **kwargs,
    ) -> list[dict]:
        api_key = kwargs.get("api_key", DEFAULT_API_KEY)

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
            "venue_id": int(venue_id),
        }

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{RESY_API_BASE}/4/find",
                headers=headers,
                params=params,
            )
            # Resy returns 500 for venues with no availability config
            if resp.status_code >= 500:
                logger.debug(f"Resy 5xx for venue {venue_id} on {date}")
                return []
            resp.raise_for_status()
            data = resp.json()

        slots = []
        results = data.get("results", {})
        venues = results.get("venues", [])

        for venue in venues:
            for s in venue.get("slots", []):
                config = s.get("config", {})
                date_info = s.get("date", {})
                time_start = date_info.get("start", "")
                if not time_start:
                    continue

                try:
                    dt = datetime.strptime(time_start, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    try:
                        dt = datetime.fromisoformat(time_start)
                    except ValueError:
                        continue

                slots.append({
                    "time_24h": dt.strftime("%H:%M"),
                    "time_display": dt.strftime("%-I:%M %p"),
                    "table_type": config.get("type", "Standard"),
                    "config_id": config.get("token", ""),
                })

        return slots

    def build_booking_url(
        self,
        watch: dict,
        date: str,
        party_size: int,
    ) -> str:
        url_slug = watch.get("resy_url_slug") or watch.get("platform_data", {}).get("url_slug", "")
        location_slug = watch.get("location_slug") or watch.get("platform_data", {}).get("location_slug", "new-york-ny")

        if not url_slug:
            return "https://resy.com"

        base = f"https://resy.com/cities/{location_slug}/{url_slug}"
        params = []
        if date:
            params.append(f"date={date}")
        if party_size:
            params.append(f"seats={party_size}")
        if params:
            base += "?" + "&".join(params)
        return base

    async def search(self, query: str, **kwargs) -> list[dict]:
        api_key = kwargs.get("api_key", DEFAULT_API_KEY)

        headers = {
            "Authorization": api_key,
            "Origin": "https://resy.com",
            "Referer": "https://resy.com/",
            "Content-Type": "application/json",
        }

        payload = {
            "query": query,
            "per_page": 5,
            "types": ["venue"],
        }

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{RESY_API_BASE}/3/venuesearch/search",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        results = []
        for hit in data.get("search", {}).get("hits", []):
            venue_id_obj = hit.get("id", {})
            if isinstance(venue_id_obj, dict):
                venue_id = venue_id_obj.get("resy", 0)
            else:
                venue_id = venue_id_obj

            location_parts = []
            if hit.get("neighborhood"):
                location_parts.append(hit["neighborhood"])
            if hit.get("locality"):
                location_parts.append(hit["locality"])
            if hit.get("region"):
                location_parts.append(hit["region"])

            location_slug = hit.get("location", {}).get("url_slug", "")

            results.append({
                "id": str(venue_id),
                "name": hit.get("name", "Unknown"),
                "location": ", ".join(location_parts) if location_parts else "Unknown",
                "platform": "resy",
                "url_slug": hit.get("url_slug", ""),
                "platform_data": {
                    "url_slug": hit.get("url_slug", ""),
                    "location_slug": location_slug,
                    "neighborhood": hit.get("neighborhood", ""),
                },
            })

        return results

    def can_resolve_url(self, url: str) -> bool:
        return "resy.com" in url

    async def resolve_url(self, url: str, **kwargs) -> dict | None:
        match = re.search(r"resy\.com/cities/([^/]+)/([^/?]+)", url)
        if not match:
            return None

        location_slug = match.group(1)
        venue_slug = match.group(2)
        api_key = kwargs.get("api_key", DEFAULT_API_KEY)

        # Try direct venue lookup by slug first (most reliable)
        venue = await self._lookup_by_slug(venue_slug, location_slug, api_key)
        if venue:
            return venue

        # Fall back to search
        query = venue_slug.replace("-", " ")
        results = await self.search(query, **kwargs)

        for r in results:
            if r.get("url_slug") == venue_slug or r.get("platform_data", {}).get("url_slug") == venue_slug:
                r["platform_data"]["location_slug"] = location_slug
                return r

        if results:
            results[0]["platform_data"]["location_slug"] = location_slug
            results[0]["url_slug"] = venue_slug
            return results[0]

        return None

    async def _lookup_by_slug(self, venue_slug: str, location_slug: str, api_key: str) -> dict | None:
        """Direct venue lookup via Resy's /3/venue endpoint."""
        headers = {
            "Authorization": api_key,
            "Origin": "https://resy.com",
            "Referer": "https://resy.com/",
        }

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{RESY_API_BASE}/3/venue",
                    params={"url_slug": venue_slug, "location": location_slug},
                    headers=headers,
                )
                if resp.status_code != 200:
                    return None
                data = resp.json()
        except Exception:
            return None

        venue_id_obj = data.get("id", {})
        if isinstance(venue_id_obj, dict):
            venue_id = venue_id_obj.get("resy", 0)
        else:
            venue_id = venue_id_obj

        if not venue_id:
            return None

        location_parts = []
        loc = data.get("location", {})
        if loc.get("neighborhood"):
            location_parts.append(loc["neighborhood"])
        if loc.get("locality"):
            location_parts.append(loc["locality"])

        return {
            "id": str(venue_id),
            "name": data.get("name", venue_slug.replace("-", " ").title()),
            "location": ", ".join(location_parts) if location_parts else "",
            "platform": "resy",
            "url_slug": venue_slug,
            "platform_data": {
                "url_slug": venue_slug,
                "location_slug": location_slug,
                "neighborhood": loc.get("neighborhood", ""),
            },
        }
