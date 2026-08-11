"""Tests for route planner location search."""

from __future__ import annotations

import asyncio
import unittest
from typing import Any, Self

from custom_components.vegagerdin.geocoding import VegagerdinGeocoder


class FakeResponse:
    """Minimal aiohttp response test double."""

    status = 200

    def __init__(self, payload: Any) -> None:
        self.payload = payload

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def json(self, content_type: str | None = None) -> Any:
        return self.payload


class FakeSession:
    """Capture a Nominatim-compatible request."""

    def __init__(self, payload: Any) -> None:
        self.payload = payload
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        return FakeResponse(self.payload)


class TestGeocoding(unittest.TestCase):
    """Location search parser and request tests."""

    def test_search_is_bounded_to_iceland(self) -> None:
        session = FakeSession(
            [
                {
                    "display_name": "Hallgrimskirkja, Reykjavik, Iceland",
                    "lat": "64.14172",
                    "lon": "-21.92676",
                    "category": "amenity",
                    "type": "place_of_worship",
                }
            ]
        )
        results = asyncio.run(
            VegagerdinGeocoder(session).async_search(
                "Hallgrimskirkja",
                language="is",
            )
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].coordinate.latitude, 64.14172)
        self.assertEqual(session.calls[0]["params"]["countrycodes"], "is")
        self.assertEqual(session.calls[0]["params"]["accept-language"], "is")
        self.assertIn("User-Agent", session.calls[0]["headers"])

    def test_short_queries_do_not_call_geocoder(self) -> None:
        session = FakeSession([])
        results = asyncio.run(VegagerdinGeocoder(session).async_search(" "))

        self.assertEqual(results, ())
        self.assertEqual(session.calls, [])

    def test_repeated_search_uses_cache(self) -> None:
        session = FakeSession(
            [
                {
                    "display_name": "Harpa, Reykjavik, Iceland",
                    "lat": "64.1500",
                    "lon": "-21.9325",
                }
            ]
        )
        geocoder = VegagerdinGeocoder(session)

        first = asyncio.run(geocoder.async_search("Harpa"))
        second = asyncio.run(geocoder.async_search("  HARPA  "))

        self.assertEqual(first, second)
        self.assertEqual(len(session.calls), 1)


if __name__ == "__main__":
    unittest.main()
