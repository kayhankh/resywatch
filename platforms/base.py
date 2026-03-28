"""
Base class for reservation platform checkers.

All platforms implement the same interface so the polling loop
doesn't need to know which platform it's talking to.
"""

from abc import ABC, abstractmethod


class BasePlatform(ABC):
    """Interface every platform checker must implement."""

    name: str = "unknown"

    @abstractmethod
    async def fetch_availability(
        self,
        venue_id: str,
        date: str,
        party_size: int,
        **kwargs,
    ) -> list[dict]:
        """
        Fetch available time slots for a venue on a given date.

        Returns list of:
            {
                "time_24h": "19:30",
                "time_display": "7:30 PM",
                "table_type": "Dining Room",
                "config_id": "abc123",  # platform-specific booking token
            }
        """
        ...

    @abstractmethod
    def build_booking_url(
        self,
        watch: dict,
        date: str,
        party_size: int,
    ) -> str:
        """Build a direct booking link the user can tap to reserve."""
        ...

    @abstractmethod
    async def search(self, query: str, **kwargs) -> list[dict]:
        """
        Search for restaurants on this platform.

        Returns list of:
            {
                "id": str,
                "name": str,
                "location": str,
                "platform": str,
                "url_slug": str,
                "platform_data": dict,  # platform-specific metadata
            }
        """
        ...

    def can_resolve_url(self, url: str) -> bool:
        """Return True if this platform can handle the given URL."""
        return False

    async def resolve_url(self, url: str, **kwargs) -> dict | None:
        """Extract venue info from a platform URL."""
        return None
