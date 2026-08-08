"""Tests for coverage helper functions."""

from __future__ import annotations

from dataclasses import dataclass
import unittest

from custom_components.vegagerdin.coverage import distance_km, objects_within_radius


@dataclass(frozen=True, slots=True)
class _Item:
    latitude: float | None
    longitude: float | None


class TestCoverage(unittest.TestCase):
    """Coverage helper tests."""

    def test_distance_km(self) -> None:
        """Distances are close enough for coverage suggestions."""
        self.assertAlmostEqual(
            distance_km(64.088, -21.914, 64.146, -21.94),
            6.6,
            delta=0.5,
        )

    def test_objects_within_radius(self) -> None:
        """Only objects with valid nearby coordinates are returned."""
        near = _Item(latitude=64.09, longitude=-21.91)
        far = _Item(latitude=65.68, longitude=-18.1)
        missing = _Item(latitude=None, longitude=None)

        self.assertEqual(
            objects_within_radius(
                [near, far, missing],
                center=(64.088, -21.914),
                radius_km=5,
                latitude_fn=lambda item: item.latitude,
                longitude_fn=lambda item: item.longitude,
            ),
            [near],
        )


if __name__ == "__main__":
    unittest.main()
