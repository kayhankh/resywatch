"""
Restaurant lookup via Resy's search API.

Searches Resy's public API to find venue IDs and metadata.
"""

import logging
import re

import httpx

logger = logging.getLogger(__name__)

RESY_API_BASE = "https://api.resy.com"


async def search_restaurant(query: str, api_key: str) -> list[dict]:
    results = []
    try:
        resy_results = await _search_resy(query, api_key)
        results.extend(resy_results)
    except Exception as e:
        logger.error(f"Resy search failed: {e}")
    return results


async def _search_resy(query: str, api_key: str) -> list[dict]:
    headers = {
        "Authorization": api_key,
        "Origin": "https://resy.com",
        "Referer": "https://resy.com/",
        "Content-Type": "application/json",
    }

    url = f"{RESY_API_BASE}/3/venuesearch/search"
    payload = {
        "query": query,
        "per_page": 5,
        "types": ["venue"],
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()

    results = []
    hits = data.get("search", {}).get("hits", [])

    for hit in hits:
        venue_id_obj = hit.get("id", {})
        if isinstance(venue_id_obj, dict):
            venue_id = venue_id_obj.get("resy", 0)
        else:
            venue_id = venue_id_obj

        location_parts = []
        if hit.get("neighborhood"):
            location_parts.append(hit["neighborhood"])
        locality = hit.get("locality", "")
        region = hit.get("region", "")
        if locality:
            location_parts.append(locality)
        if region:
            location_parts.append(region)

        location_slug = hit.get("location", {}).get("url_slug", "")

        results.append({
            "id": venue_id,
            "name": hit.get("name", "Unknown"),
            "location": ", ".join(location_parts) if location_parts else "Unknown",
            "platform": "resy",
            "url_slug": hit.get("url_slug", ""),
            "location_slug": location_slug,
            "neighborhood": hit.get("neighborhood", ""),
        })

    return results


async def resolve_venue_from_url(resy_url: str, api_key: str) -> dict | None:
    match = re.search(r"resy\.com/cities/([^/]+)/([^/?]+)", resy_url)
    if not match:
        return None

    location_slug = match.group(1)
    venue_slug = match.group(2)

    query = venue_slug.replace("-", " ")
    results = await search_restaurant(query, api_key)

    for r in results:
        if r.get("url_slug") == venue_slug:
            r["location_slug"] = location_slug
            return r

    if results:
        results[0]["location_slug"] = location_slug
        results[0]["url_slug"] = venue_slug
        return results[0]

    return None


def build_resy_booking_url(
    venue_slug: str,
    location_slug: str = "new-york-ny",
    date: str = "",
    party_size: int = 2,
) -> str:
    base = f"https://resy.com/cities/{location_slug}/{venue_slug}"
    params = []
    if date:
        params.append(f"date={date}")
    if party_size:
        params.append(f"seats={party_size}")
    if params:
        base += "?" + "&".join(params)
    return base
