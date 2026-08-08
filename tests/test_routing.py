"""Tests for OSRM parsing and Vegagerdin route matching."""

from __future__ import annotations

import asyncio
from typing import Any
import unittest

from custom_components.vegagerdin.api import (
    parse_road_conditions_payload,
    parse_road_notifications_payload,
    parse_traffic_counters_payload,
    parse_weather_stations_payload,
    parse_webcams_payload,
)
from custom_components.vegagerdin.routing import (
    Coordinate,
    VegagerdinRouteApiClient,
    build_route_details,
    parse_osrm_route_payload,
    parse_road_geometries_payload,
    route_entity_object_id,
)


class FakeResponse:
    """Minimal aiohttp response test double."""

    status = 200

    def __init__(self, payload: Any) -> None:
        self.payload = payload

    async def __aenter__(self) -> FakeResponse:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def json(self, content_type: str | None = None) -> Any:
        return self.payload


class FakeSession:
    """Minimal aiohttp session test double."""

    def __init__(self, payload: Any) -> None:
        self.payload = payload
        self.calls: list[tuple[str, list[tuple[str, str]]]] = []

    def get(
        self,
        url: str,
        *,
        params: list[tuple[str, str]],
        timeout: int,
    ) -> FakeResponse:
        self.calls.append((url, params))
        return FakeResponse(self.payload)


def _osrm_payload() -> dict[str, Any]:
    return {
        "code": "Ok",
        "routes": [
            {
                "distance": 10_000,
                "duration": 900,
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-21.95, 64.10], [-21.85, 64.10]],
                },
                "legs": [
                    {
                        "steps": [
                            {"name": "Reykjanesbraut", "ref": "41"},
                            {"name": "Breiðholtsbraut", "ref": "413"},
                        ]
                    }
                ],
            }
        ],
    }


class TestRouting(unittest.TestCase):
    """Pure routing model tests."""

    def test_route_client_uses_osrm_geojson_endpoint(self) -> None:
        session = FakeSession(_osrm_payload())
        route = asyncio.run(
            VegagerdinRouteApiClient(
                session,
                "https://osrm.example/",
            ).async_get_route(
                Coordinate(64.10, -21.95),
                Coordinate(64.10, -21.85),
            )
        )

        self.assertEqual(route.distance_km, 10)
        self.assertEqual(route.duration_minutes, 15)
        self.assertEqual(route.road_numbers, ("41", "413"))
        self.assertIn("/route/v1/driving/", session.calls[0][0])
        self.assertIn(("geometries", "geojson"), session.calls[0][1])

    def test_route_object_id_has_searchable_prefix(self) -> None:
        self.assertEqual(
            route_entity_object_id("zone.home", "zone.work", "status"),
            "vegagerdin_route_home_to_work_status",
        )
        self.assertEqual(
            route_entity_object_id(
                "zone.home",
                "device_tracker.navigation_destination",
                "problem",
            ),
            "vegagerdin_route_home_to_navigation_destination_problem",
        )

    def test_wfs_geometry_id_maps_to_condition_id(self) -> None:
        geometries = parse_road_geometries_payload(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "properties": {
                            "IDBUTUR": 901010001,
                            "STADARLYSING": "Route section",
                            "VEGNR": "41",
                        },
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[-21.94, 64.10], [-21.86, 64.10]],
                        },
                    }
                ],
            }
        )

        self.assertEqual(set(geometries), {"90101"})
        self.assertEqual(geometries["90101"].road_number, "41")

    def test_build_route_details_orders_and_summarizes_matches(self) -> None:
        route = parse_osrm_route_payload(_osrm_payload())
        roads = parse_road_conditions_payload(
            {
                "data": {
                    "RoadCondition": {
                        "results": [
                            {
                                "id": "90101",
                                "name": "Route section",
                                "geometryCenter": {"lat": 64.10, "lon": -21.90},
                                "condition": {
                                    "code": "clear",
                                    "category": "clear",
                                    "description": "Easily passable",
                                },
                                "conditionsOtherMarkers": [
                                    {
                                        "id": "work-1",
                                        "title": "Roadwork",
                                        "description": "Reduced speed",
                                        "code": "roadwork",
                                    }
                                ],
                                "roads": [{"name": "Road", "nr": "41"}],
                            }
                        ]
                    }
                }
            }
        )
        geometries = parse_road_geometries_payload(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "properties": {"IDBUTUR": "901010001", "VEGNR": "41"},
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[-21.94, 64.10], [-21.86, 64.10]],
                        },
                    }
                ],
            }
        )
        stations = parse_weather_stations_payload(
            {
                "data": {
                    "WeatherStations": {
                        "results": [
                            {
                                "id": 77,
                                "name": "Route weather",
                                "RoadConditionIds": ["90101"],
                                "roadTemperature": 1,
                                "wind": {"speed": 4, "gust": 12},
                                "windDirection": {"degrees": 90},
                                "coordinates": {"lat": 64.101, "lon": -21.89},
                            }
                        ]
                    }
                }
            }
        )
        cameras = parse_webcams_payload(
            [
                {
                    "Maelist_nr": 7001,
                    "Myndavel": "Route camera",
                    "Slod": "https://example.invalid/route.jpg",
                    "Breidd": 64.102,
                    "Lengd": -21.88,
                }
            ]
        )
        counters = parse_traffic_counters_payload(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "properties": {"IDSTOD": 22, "NAFN": "Route counter"},
                        "geometry": {
                            "type": "Point",
                            "coordinates": [-21.87, 64.101],
                        },
                    }
                ],
            }
        )
        notices = parse_road_notifications_payload(
            {
                "data": {
                    "RoadNotifications": {
                        "results": [
                            {
                                "id": 1,
                                "key": "capital",
                                "category": "Roadwork",
                                "text": "Work on Breiðholtsbraut",
                            }
                        ]
                    }
                }
            }
        )

        details = build_route_details(
            origin_entity_id="zone.home",
            destination_entity_id="zone.work",
            origin_name="Home",
            destination_name="Work",
            route=route,
            roads={road.road_condition_id: road for road in roads},
            road_geometries=geometries,
            weather_stations=stations,
            cameras=cameras,
            traffic_counters=counters,
            notices=notices,
            road_corridor_km=0.25,
            point_corridor_km=2,
        )

        self.assertEqual(details.status, "advisory")
        self.assertEqual(details.roadwork_count, 1)
        self.assertEqual(details.maximum_wind_gust, 12)
        self.assertEqual(details.minimum_road_temperature, 1)
        self.assertEqual(len(details.cameras), 1)
        self.assertEqual(len(details.traffic_counters), 1)
        self.assertEqual(details.notices[0].notice_id, "1")
        self.assertEqual(
            details.as_dict()["route"]["geometry"]["type"],
            "LineString",
        )


if __name__ == "__main__":
    unittest.main()
