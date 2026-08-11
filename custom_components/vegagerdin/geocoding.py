"""Location search for the route planner."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from time import monotonic
from typing import Any

from .api import CannotConnect, InvalidResponse
from .const import (
    DEFAULT_GEOCODER_URL,
    GEOCODER_CACHE_SECONDS,
    GEOCODER_MAX_RESULTS,
    GEOCODER_TIMEOUT_SECONDS,
)
from .routing import Coordinate


@dataclass(frozen=True, slots=True)
class GeocodedLocation:
    """One geocoder search result."""

    label: str
    coordinate: Coordinate
    category: str | None = None
    location_type: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable result."""
        return {
            "label": self.label,
            "latitude": self.coordinate.latitude,
            "longitude": self.coordinate.longitude,
            "category": self.category,
            "type": self.location_type,
        }


class VegagerdinGeocoder:
    """Search Icelandic places with Nominatim-compatible APIs."""

    def __init__(
        self,
        session: Any,
        base_url: str = DEFAULT_GEOCODER_URL,
    ) -> None:
        """Initialize the geocoder."""
        self.session = session
        self.base_url = base_url.rstrip("/")
        self._request_lock = asyncio.Lock()
        self._last_request = 0.0
        self._cache: dict[
            tuple[str, str, int],
            tuple[float, tuple[GeocodedLocation, ...]],
        ] = {}

    async def async_search(
        self,
        query: str,
        *,
        language: str = "en",
        limit: int = GEOCODER_MAX_RESULTS,
    ) -> tuple[GeocodedLocation, ...]:
        """Return matching locations in Iceland."""
        query = query.strip()
        if len(query) < 2:
            return ()
        bounded_limit = max(1, min(limit, GEOCODER_MAX_RESULTS))
        cache_key = (language, query.casefold(), bounded_limit)
        cached = self._cached_result(cache_key)
        if cached is not None:
            return cached
        params = {
            "q": query,
            "format": "jsonv2",
            "addressdetails": "1",
            "countrycodes": "is",
            "accept-language": language,
            "limit": str(bounded_limit),
        }
        try:
            async with self._request_lock:
                cached = self._cached_result(cache_key)
                if cached is not None:
                    return cached
                delay = 1.0 - (monotonic() - self._last_request)
                if delay > 0:
                    await asyncio.sleep(delay)
                async with self.session.get(
                    f"{self.base_url}/search",
                    params=params,
                    timeout=GEOCODER_TIMEOUT_SECONDS,
                    headers={
                        "User-Agent": (
                            "Home-Assistant-Vegagerdin/0.1 "
                            "(https://github.com/hakong/vegagerdin-home-assistant)"
                        )
                    },
                ) as response:
                    self._last_request = monotonic()
                    if response.status != 200:
                        raise CannotConnect(
                            f"Location search returned HTTP {response.status}"
                        )
                    payload = await response.json(content_type=None)
        except (CannotConnect, InvalidResponse):
            raise
        except Exception as err:
            raise CannotConnect("Could not search for locations") from err
        if not isinstance(payload, list):
            raise InvalidResponse("Location search returned invalid JSON")
        results: list[GeocodedLocation] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            try:
                coordinate = Coordinate(
                    latitude=float(item["lat"]),
                    longitude=float(item["lon"]),
                )
            except (KeyError, TypeError, ValueError):
                continue
            label = str(item.get("display_name") or "").strip()
            if not label:
                continue
            results.append(
                GeocodedLocation(
                    label=label,
                    coordinate=coordinate,
                    category=_optional_string(item.get("category")),
                    location_type=_optional_string(item.get("type")),
                )
            )
        parsed_results = tuple(results)
        self._cache[cache_key] = (
            monotonic() + GEOCODER_CACHE_SECONDS,
            parsed_results,
        )
        return parsed_results

    def _cached_result(
        self,
        cache_key: tuple[str, str, int],
    ) -> tuple[GeocodedLocation, ...] | None:
        """Return a non-expired search result."""
        cached = self._cache.get(cache_key)
        if cached is None:
            return None
        expires_at, results = cached
        if monotonic() >= expires_at:
            self._cache.pop(cache_key, None)
            return None
        return results


def _optional_string(value: Any) -> str | None:
    """Return a useful optional string."""
    return str(value) if value not in (None, "") else None
