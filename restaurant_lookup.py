"""
Restaurant lookup via Resy's search API.

Searches Resy's public API to find venue IDs and metadata.
"""

import logging
import httpx

logger = logging.getLogger(__name__)

RESY_API_BASE = "https://api.resy.com"


async def search_restaurant(query: str, api_key: str) -> list[dict]:
    """
    Search Resy for restaurants matching the query.

    Returns list of:
        {
            "id": 1234,
            "name": "Don Angie",
            "location": "New York, NY",
            "platform": "resy",
            "url_slug": "don-angie",
            "neighborhood": "West Village",
        }
    """
    results = []

    # ── Resy Search ───────────────────────────────────────────────────────
    try:
        resy_results = await _search_resy(query, api_key)
        results.extend(resy_results)
    except Exception as e:
        logger.error(f"Resy search failed: {e}")

    return results


async def _search_resy(query: str, api_key: str) -> list[dict]:
    """Search Resy's venue search endpoint."""
    headers = {
        "Authorization": api_key,
        "Origin": "https://resy.com",
        "Referer": "https://resy.com/",
    }

    # Resy's search/suggest endpoint
    url = f"{RESY_API_BASE}/3/venuesearch/search"
    params = {
        "query": query,
        "geo": '{"latitude":40.7128,"longitude":-74.0060}',  # Default to NYC
        "types": '["venue"]',
        "per_page": 5,
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, headers=headers, params=params)
        resp.raise_for_status()
        data = resp.json()

    results = []
    hits = data.get("search", {}).get("hits", [])

    for hit in hits:
        venue = hit.get("_source", hit) if "_source" in hit else hit
        # Handle nested structures
        if "id" not in venue and "objectID" in hit:
            venue_id = hit["objectID"]
        else:
            venue_id = venue.get("id", {})
            if isinstance(venue_id, dict):
                venue_id = venue_id.get("resy", 0)

        location_parts = []
        if venue.get("neighborhood"):
            location_parts.append(venue["neighborhood"])
        if venue.get("location", {}).get("city"):
            location_parts.append(venue["location"]["city"])
        elif venue.get("city"):
            location_parts.append(venue["city"])

        results.append({
            "id": venue_id,
            "name": venue.get("name", "Unknown"),
            "location": ", ".join(location_parts) if location_parts else "Unknown",
            "platform": "resy",
            "url_slug": venue.get("url_slug", ""),
            "neighborhood": venue.get("neighborhood", ""),
        })

    # Fallback: try the simpler venue lookup endpoint
    if not results:
        results = await _search_resy_fallback(query, api_key)

    return results


async def _search_resy_fallback(query: str, api_key: str) -> list[dict]:
    """Fallback search using Resy's location suggest endpoint."""
    headers = {
        "Authorization": api_key,
        "Origin": "https://resy.com",
        "Referer": "https://resy.com/",
    }

    url = f"{RESY_API_BASE}/2/search/suggest"
    params = {"query": query}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()

        results = []
        for item in data.get("results", {}).get("venues", []):
            results.append({
                "id": item.get("id", 0),
                "name": item.get("name", "Unknown"),
                "location": f"{item.get('neighborhood', '')}, {item.get('city', '')}".strip(", "),
                "platform": "resy",
                "url_slug": item.get("url_slug", ""),
                "neighborhood": item.get("neighborhood", ""),
            })

        return results
    except Exception as e:
        logger.error(f"Resy fallback search failed: {e}")
        return []


def build_resy_booking_url(venue_slug: str, city: str = "new-york-ny", date: str = "", party_size: int = 2) -> str:
    """Build a direct Resy booking URL."""
    base = f"https://resy.com/cities/{city}/{venue_slug}"
    params = []
    if date:
        params.append(f"date={date}")
    if party_size:
        params.append(f"seats={party_size}")
    if params:
        base += "?" + "&".join(params)
    return base
