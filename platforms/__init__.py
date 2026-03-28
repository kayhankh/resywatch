"""
Multi-platform reservation availability checkers.

Each platform module implements fetch_availability() and build_booking_url()
with a consistent interface so the main checker can route transparently.
"""

from platforms.resy import ResyPlatform
from platforms.sevenrooms import SevenRoomsPlatform
from platforms.opentable import OpenTablePlatform

PLATFORMS = {
    "resy": ResyPlatform(),
    "sevenrooms": SevenRoomsPlatform(),
    "opentable": OpenTablePlatform(),
}


def get_platform(name: str):
    """Get a platform checker by name. Returns None if unknown."""
    return PLATFORMS.get(name.lower())


def all_platform_names() -> list[str]:
    return list(PLATFORMS.keys())
