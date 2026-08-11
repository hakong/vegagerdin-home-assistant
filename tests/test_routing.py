"""Tests for OSRM parsing and Vegagerdin route matching."""

from __future__ import annotations

import asyncio
import unittest
from typing import Any

from custom_components.vegagerdin.api import (
    parse_road_conditions_payload,
    parse_road_notifications_payload,
    parse_traffic_counters_payload,
    parse_weather_stations_payload,
    parse_webcams_payload,
)
from custom_components.vegagerdin.routing import (
    Coordinate,
    OsrmRoute,
    RouteDetails,
    RouteMatch,
    VegagerdinRouteApiClient,
    _road_name_in_notice,
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
        self.assertIn(("overview", "simplified"), session.calls[0][1])

    def test_notice_road_names_do_not_match_substrings(self) -> None:
        self.assertTrue(
            _road_name_in_notice("arnarnesbraut", "closure on arnarnesbraut")
        )
        self.assertFalse(_road_name_in_notice("nesbraut", "closure on arnarnesbraut"))

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
                            },
                            {
                                "id": 2,
                                "key": "east",
                                "category": "Closure",
                                "subCategory": "Fáskrúðsfjörður",
                                "text": "Ring Road (1) is closed nearby",
                            },
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
        self.assertEqual(
            details.segment_summaries,
            [
                {
                    "id": "90101",
                    "url": "https://umferdin.is/kafli/90101",
                    "distance_km": 0.0,
                    "name": "Route section",
                    "condition": "Easily passable",
                    "temperature": 1.0,
                    "temperature_type": "road",
                    "weather_station": "Route weather",
                    "closed": False,
                    "alert": "Roadwork: Reduced speed",
                }
            ],
        )
        self.assertEqual(details.weather_summaries[0]["name"], "Route weather")
        self.assertEqual(details.weather_summaries[0]["road_temperature"], 1.0)
        self.assertEqual(details.traffic_summaries[0]["name"], "Route counter")
        self.assertEqual(len(details.cameras), 1)
        self.assertEqual(len(details.camera_summaries), 1)
        self.assertEqual(details.camera_summaries[0]["camera_site_id"], "7001")
        self.assertEqual(len(details.traffic_counters), 1)
        self.assertEqual(
            [notice.notice_id for notice in details.notices],
            ["1"],
        )
        self.assertEqual(
            details.as_dict()["route"]["geometry"]["type"],
            "LineString",
        )

    def test_camera_summaries_cover_route_and_expand_alert_site(self) -> None:
        route = OsrmRoute(
            distance_km=390,
            duration_minutes=300,
            coordinates=(Coordinate(64.0, -22.0), Coordinate(65.0, -15.0)),
            road_names=(),
            road_numbers=(),
        )
        alert_road = RouteMatch(
            item_id="alert",
            name="Alert segment",
            distance_from_start_km=50,
            distance_to_route_km=0,
            data={
                "condition": {"description": "Easily passable"},
                "has_roadwork": True,
                "other_markers": [
                    {
                        "title": "Roadwork",
                        "description": "Reduced speed",
                    }
                ],
            },
        )
        cameras = tuple(
            RouteMatch(
                item_id=f"{site}_{view}",
                name=f"Camera {site}",
                distance_from_start_km=float(site * 10),
                distance_to_route_km=0,
                data={
                    "id": site,
                    "description": (
                        "View down at road" if view == 0 else f"Direction {view}"
                    ),
                    "image_url": f"https://example.invalid/{site}_{view}.jpg",
                },
            )
            for site in range(40)
            for view in range(2)
        )
        details = RouteDetails(
            origin_entity_id="zone.home",
            destination_entity_id="zone.work",
            origin_name="Home",
            destination_name="Work",
            route=route,
            status="advisory",
            roads=(alert_road,),
            weather_stations=(),
            cameras=cameras,
            traffic_counters=(),
            notices=(),
        )

        summaries = details.camera_summaries
        site_ids = {item["camera_site_id"] for item in summaries}

        self.assertLessEqual(len(summaries), 50)
        self.assertEqual(len(site_ids), 30)
        self.assertIn("0", site_ids)
        self.assertIn("39", site_ids)
        alert_views = [item for item in summaries if item["camera_site_id"] == "5"]
        self.assertEqual(len(alert_views), 2)
        self.assertTrue(all(item["near_alert"] for item in alert_views))


if __name__ == "__main__":
    unittest.main()
