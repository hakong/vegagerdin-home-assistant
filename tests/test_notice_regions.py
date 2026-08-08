"""Tests for notice region suggestions."""

from __future__ import annotations

from types import SimpleNamespace
import unittest

from custom_components.vegagerdin.notice_regions import suggest_notice_regions


class _FakeStates:
    def __init__(self, zones: list[SimpleNamespace]) -> None:
        self._zones = zones

    def async_all(self, domain: str) -> list[SimpleNamespace]:
        return self._zones if domain == "zone" else []


class TestNoticeRegions(unittest.TestCase):
    """Notice region helper tests."""

    def test_suggests_capital_from_home_coordinates(self) -> None:
        """A home coordinate in the capital area suggests that region."""
        hass = SimpleNamespace(
            config=SimpleNamespace(latitude=64.088, longitude=-21.914),
            states=_FakeStates([]),
        )

        self.assertIn("capital", suggest_notice_regions(hass))

    def test_suggests_work_zone_region(self) -> None:
        """Zone coordinates can add commute/work regions."""
        hass = SimpleNamespace(
            config=SimpleNamespace(latitude=65.7, longitude=-18.1),
            states=_FakeStates(
                [
                    SimpleNamespace(
                        attributes={"latitude": 64.146, "longitude": -21.94},
                    )
                ]
            ),
        )

        regions = suggest_notice_regions(hass)

        self.assertIn("north", regions)
        self.assertIn("capital", regions)


if __name__ == "__main__":
    unittest.main()
