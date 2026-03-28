"""
Multi-platform restaurant lookup.

Search flow:
  1. If user provides a URL → detect platform from URL, resolve venue
  2. If user provides a name → search Resy first, then try Google to detect
     if the restaurant uses SevenRooms or OpenTable
  3. Return normalized results with platform info attached

Platform auto-detection via Google:
  When a restaurant isn't found on Resy, we search Google for:
    "<restaurant name>" site:resy.com OR site:sevenrooms.com OR site:opentable.com
  and use whichever platform appears in the results.
"""

import logging
import re

import httpx

from platforms import PLATFORMS, get_platform

logger = logging.getLogger(__name__)


async def search_restaurant(query: str, api_key: str = "") -> list[dict]:
    """
    Search for a restaurant across all platforms.

    Tries Resy first (since it has the best search API), then falls back
    to Google-based platform detection if nothing is found.
    """
    # Step 1: Try Resy's search API
    resy = get_platform("resy")
    try:
        resy_results = await resy.search(query, api_key=api_key)
        if resy_results:
            return resy_results
    except Exception as e:
        logger.error(f"Resy search failed: {e}")

    # Step 2: Try OpenTable search
    opentable = get_platform("opentable")
    try:
        ot_results = await opentable.search(query)
        if ot_results:
            return ot_results
    except Exception as e:
        logger.error(f"OpenTable search failed: {e}")

    # Step 3: Try Google-based platform detection
    try:
        detected = await detect_platform_via_google(query)
        if detected:
            return [detected]
    except Exception as e:
        logger.error(f"Google platform detection failed: {e}")

    return []


async def detect_platform_via_google(restaurant_name: str) -> dict | None:
    """
    Search Google to find which booking platform a restaurant uses.

    Searches for the restaurant name + booking platform domains and
    extracts the venue slug/ID from the first matching result.
    """
    search_query = (
        f'"{restaurant_name}" reservation '
        f"site:resy.com OR site:sevenrooms.com OR site:opentable.com"
    )

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    }

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(
                "https://www.google.com/search",
                params={"q": search_query, "num": 5},
                headers=headers,
            )

            if resp.status_code != 200:
                return None

            html = resp.text

            # Extract URLs from Google results
            urls = re.findall(r'href="(https?://[^"]+(?:resy|sevenrooms|opentable)[^"]*)"', html)
            if not urls:
                # Try alternate pattern
                urls = re.findall(r'(https?://(?:www\.)?(?:resy\.com|sevenrooms\.com|opentable\.com)/[^\s<"\']+)', html)

    except Exception as e:
        logger.debug(f"Google search failed: {e}")
        return None

    # Try to resolve each URL through the appropriate platform
    for url in urls:
        # Clean up Google redirect URLs
        url = _clean_google_url(url)

        for platform in PLATFORMS.values():
            if platform.can_resolve_url(url):
                try:
                    result = await platform.resolve_url(url)
                    if result:
                        # Override the name with what the user searched for
                        # since the auto-detected name might be slightly different
                        if result["name"].lower().strip() != restaurant_name.lower().strip():
                            result["name"] = restaurant_name.title()
                        return result
                except Exception as e:
                    logger.debug(f"URL resolution failed for {url}: {e}")
                    continue

    return None


async def resolve_venue_from_url(url: str, api_key: str = "") -> dict | None:
    """
    Resolve a booking platform URL to venue info.

    Automatically detects which platform the URL belongs to and
    extracts venue ID, name, and platform-specific metadata.
    """
    for platform in PLATFORMS.values():
        if platform.can_resolve_url(url):
            try:
                result = await platform.resolve_url(url, api_key=api_key)
                if result:
                    return result
            except Exception as e:
                logger.error(f"Error resolving {url} via {platform.name}: {e}")

    return None


def detect_platform_from_url(url: str) -> str | None:
    """Quick check: which platform does this URL belong to?"""
    if "resy.com" in url:
        return "resy"
    if "sevenrooms.com" in url:
        return "sevenrooms"
    if "opentable.com" in url:
        return "opentable"
    if "yelp.com" in url:
        return "yelp"  # future
    return None


def build_booking_url(platform_name: str, watch: dict, date: str, party_size: int) -> str:
    """Build a booking URL using the appropriate platform."""
    platform = get_platform(platform_name)
    if platform:
        return platform.build_booking_url(watch, date, party_size)
    return ""


def _clean_google_url(url: str) -> str:
    """Extract the actual URL from a Google redirect URL."""
    # Google wraps URLs in /url?q=<actual_url>&...
    match = re.search(r"/url\?q=(https?://[^&]+)", url)
    if match:
        from urllib.parse import unquote
        return unquote(match.group(1))
    return url
