"""Tests for registry cleanup calculations."""

from __future__ import annotations

from types import SimpleNamespace
import unittest

from custom_components.vegagerdin import (
    _desired_entity_unique_ids,
    _is_managed_entity_unique_id,
)
from custom_components.vegagerdin.const import (
    CONF_CAMERA_IDS,
    CONF_ENABLE_CAMERAS,
    CONF_ENABLE_ROAD_SUMMARIES,
    CONF_ENABLE_ROUTE_SENSORS,
    CONF_ENABLE_TRAFFIC_COUNTER_SENSORS,
    CONF_ENABLE_WEATHER_STATION_SENSORS,
    CONF_NOTICE_REGION_KEYS,
    CONF_ROAD_CONDITION_IDS,
    CONF_ROUTE_ORIGIN_ENTITY_ID,
    CONF_TRAFFIC_COUNTER_IDS,
    CONF_WEATHER_STATION_IDS,
    DOMAIN,
    SELECTED_ROUTE_ENTITY_PREFIX,
)


class TestRegistryCleanup(unittest.TestCase):
    """Registry cleanup helper tests."""

    def test_desired_unique_ids_follow_current_selection(self) -> None:
        """Only selected favorites and always-on notice sensors remain desired."""
        desired = _desired_entity_unique_ids(
            {
                CONF_ENABLE_ROAD_SUMMARIES: True,
                CONF_ROAD_CONDITION_IDS: ["91405"],
                CONF_ENABLE_WEATHER_STATION_SENSORS: True,
                CONF_WEATHER_STATION_IDS: [14],
                CONF_ENABLE_TRAFFIC_COUNTER_SENSORS: False,
                CONF_TRAFFIC_COUNTER_IDS: [5021],
                CONF_ENABLE_CAMERAS: True,
                CONF_CAMERA_IDS: [7040],
                CONF_NOTICE_REGION_KEYS: [],
                CONF_ENABLE_ROUTE_SENSORS: True,
                CONF_ROUTE_ORIGIN_ENTITY_ID: "zone.home",
            },
            selected_webcams=[
                SimpleNamespace(image_id="7040_nonskard_1"),
                SimpleNamespace(image_id="7040_nonskard_2"),
            ],
            route_target_entity_ids=("zone.work",),
        )

        self.assertIn(f"{DOMAIN}_91405_condition", desired)
        self.assertIn(f"{DOMAIN}_91405_roadwork", desired)
        self.assertIn(f"{DOMAIN}_station_14_temperature", desired)
        self.assertIn(f"{DOMAIN}_camera_7040_nonskard_1", desired)
        self.assertNotIn(f"{DOMAIN}_counter_5021_traffic_today", desired)
        self.assertNotIn(f"{DOMAIN}_regional_notices", desired)
        self.assertIn(
            f"{DOMAIN}_route_zone_home_zone_work_status",
            desired,
        )
        self.assertIn(
            f"{DOMAIN}_route_zone_home_zone_work_problem",
            desired,
        )
        for key in (
            "origin",
            "destination",
            "swap",
            "refresh",
            "status",
            "problem",
        ):
            self.assertIn(f"{SELECTED_ROUTE_ENTITY_PREFIX}_{key}", desired)

    def test_managed_unique_id_detection(self) -> None:
        """Cleanup only touches known Vegagerdin entity unique IDs."""
        self.assertTrue(_is_managed_entity_unique_id(f"{DOMAIN}_road_notices"))
        self.assertTrue(_is_managed_entity_unique_id(f"{DOMAIN}_123_condition"))
        self.assertTrue(_is_managed_entity_unique_id(f"{DOMAIN}_123_closed"))
        self.assertTrue(_is_managed_entity_unique_id(f"{DOMAIN}_station_1_humidity"))
        self.assertTrue(_is_managed_entity_unique_id(f"{DOMAIN}_camera_7040_x"))
        self.assertTrue(
            _is_managed_entity_unique_id(
                f"{DOMAIN}_route_zone_home_zone_work_status"
            )
        )
        self.assertFalse(_is_managed_entity_unique_id("other_domain_123"))
        self.assertFalse(_is_managed_entity_unique_id(f"{DOMAIN}_unrelated"))


if __name__ == "__main__":
    unittest.main()
