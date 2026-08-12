"""Tests for OSRM parsing and Vegagerdin route matching."""

from __future__ import annotations

import asyncio
import unittest
from math import sin
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
    RoadGeometry,
    RouteDetails,
    RouteMatch,
    VegagerdinRouteApiClient,
    _build_route_spatial_index,
    _indexed_nearest_route_position,
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
                            {
                                "name": "Reykjanesbraut",
                                "ref": "41",
                                "geometry": {
                                    "type": "LineString",
                                    "coordinates": [
                                        [-21.95, 64.10],
                                        [-21.93, 64.10],
                                        [-21.90, 64.10],
                                    ],
                                },
                            },
                            {
                                "name": "Breiðholtsbraut",
                                "ref": "413",
                                "geometry": {
                                    "type": "LineString",
                                    "coordinates": [
                                        [-21.90, 64.10],
                                        [-21.88, 64.10],
                                        [-21.85, 64.10],
                                    ],
                                },
                            },
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
        self.assertEqual(len(route.steps), 2)
        self.assertEqual(len(route.coordinates), 5)
        self.assertEqual(len(route.display_coordinates), 5)
        self.assertEqual(route.steps[0].road_numbers, ("41",))
        self.assertEqual(route.as_dict()["matching_geometry_points"], 5)
        self.assertEqual(route.as_dict()["display_geometry_points"], 5)
        self.assertIn("/route/v1/driving/", session.calls[0][0])
        self.assertIn(("geometries", "geojson"), session.calls[0][1])
        self.assertIn(("overview", "simplified"), session.calls[0][1])

    def test_route_display_geometry_has_dynamic_point_budget(self) -> None:
        detailed_coordinates = [
            [
                -22.0 + index * 0.0005,
                64.0 + sin(index / 7) * 0.002 + sin(index / 29) * 0.001,
            ]
            for index in range(2_001)
        ]
        payload = {
            "code": "Ok",
            "routes": [
                {
                    "distance": 200_000,
                    "duration": 10_000,
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            detailed_coordinates[0],
                            detailed_coordinates[-1],
                        ],
                    },
                    "legs": [
                        {
                            "steps": [
                                {
                                    "name": "Detailed road",
                                    "ref": "1",
                                    "geometry": {
                                        "type": "LineString",
                                        "coordinates": detailed_coordinates,
                                    },
                                }
                            ]
                        }
                    ],
                }
            ],
        }

        route = parse_osrm_route_payload(payload)

        self.assertEqual(len(route.coordinates), 2_001)
        self.assertGreater(len(route.display_coordinates), 100)
        self.assertLessEqual(len(route.display_coordinates), 600)
        self.assertEqual(
            len(route.as_dict()["geometry"]["coordinates"]),
            len(route.display_coordinates),
        )

    def test_route_uses_overview_when_step_geometry_is_missing(self) -> None:
        payload = _osrm_payload()
        for step in payload["routes"][0]["legs"][0]["steps"]:
            step.pop("geometry")

        route = parse_osrm_route_payload(payload)

        self.assertEqual(len(route.coordinates), 2)
        self.assertEqual(len(route.display_coordinates), 2)
        self.assertTrue(all(not step.coordinates for step in route.steps))

    def test_spatial_index_finds_nearby_point_on_detailed_route(self) -> None:
        route = parse_osrm_route_payload(_osrm_payload())
        route_index = _build_route_spatial_index(route)

        position = _indexed_nearest_route_position(
            Coordinate(64.10, -21.88),
            route_index,
            0.25,
        )
        outside = _indexed_nearest_route_position(
            Coordinate(65.0, -21.88),
            route_index,
            0.25,
        )

        self.assertIsNotNone(position)
        assert position is not None
        self.assertLess(position[0], 0.01)
        self.assertGreater(position[1], 3.0)
        self.assertIsNone(outside)

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
                    "severity": "warning",
                    "has_issue": True,
                    "temperature": 1.0,
                    "temperature_type": "road",
                    "weather_station": "Route weather",
                    "closed": False,
                    "alert": "Roadwork: Reduced speed",
                }
            ],
        )
        self.assertEqual(details.issue_geometries[0]["id"], "90101")
        self.assertEqual(
            details.issue_geometries[0]["geometry"]["type"],
            "MultiLineString",
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

    def test_icelandic_route_segment_fallback_labels(self) -> None:
        details = RouteDetails(
            origin_entity_id="zone.home",
            destination_entity_id="zone.work",
            origin_name="Heimili",
            destination_name="Vinna",
            route=parse_osrm_route_payload(_osrm_payload()),
            status="closed",
            roads=(
                RouteMatch(
                    item_id="90101",
                    name="Vegarkafli",
                    distance_from_start_km=1.0,
                    distance_to_route_km=0.0,
                    data={
                        "condition": {},
                        "is_closed": True,
                        "weight_restriction": {},
                    },
                ),
            ),
            weather_stations=(),
            cameras=(),
            traffic_counters=(),
            notices=(),
            language="is",
        )

        self.assertEqual(details.route_name, "Heimili til Vinna")
        self.assertEqual(
            details.segment_summaries[0],
            {
                "id": "90101",
                "url": "https://umferdin.is/kafli/90101",
                "distance_km": 1.0,
                "name": "Vegarkafli",
                "condition": "Óþekkt",
                "severity": "closed",
                "has_issue": True,
                "temperature": None,
                "temperature_type": None,
                "weather_station": None,
                "closed": True,
                "alert": "Lokað · Þungatakmörkun",
            },
        )

    def test_affected_connected_and_nearby_roads_are_not_route_matches(self) -> None:
        route = parse_osrm_route_payload(_osrm_payload())
        roads = parse_road_conditions_payload(
            {
                "data": {
                    "RoadCondition": {
                        "results": [
                            {
                                "id": "90101",
                                "name": "Driven road",
                                "condition": {
                                    "code": "clear",
                                    "category": "clear",
                                    "description": "Easily passable",
                                },
                                "conditionsOtherMarkers": [
                                    {
                                        "id": "work-driven",
                                        "title": "Roadwork",
                                        "description": "On the route",
                                        "code": "roadwork",
                                    }
                                ],
                            },
                            {
                                "id": "90102",
                                "name": "Connected side road",
                                "condition": {
                                    "code": "clear",
                                    "category": "clear",
                                    "description": "Easily passable",
                                },
                                "conditionsOtherMarkers": [
                                    {
                                        "id": "work-branch",
                                        "title": "Roadwork",
                                        "description": "Not on the route",
                                        "code": "roadwork",
                                    }
                                ],
                            },
                            {
                                "id": "90103",
                                "name": "Nearby parallel road",
                                "condition": {
                                    "code": "slippery",
                                    "category": "difficult",
                                    "description": "Slippery",
                                },
                            },
                            {
                                "id": "90104",
                                "name": "Short junction approach",
                                "condition": {
                                    "code": "clear",
                                    "category": "clear",
                                    "description": "Easily passable",
                                },
                                "conditionsOtherMarkers": [
                                    {
                                        "id": "work-approach",
                                        "title": "Roadwork",
                                        "description": "Branches away",
                                        "code": "roadwork",
                                    }
                                ],
                            },
                            {
                                "id": "90105",
                                "name": "Side road: Junction",
                                "condition": {
                                    "code": "clear",
                                    "category": "clear",
                                    "description": "Easily passable",
                                },
                                "conditionMarkers": [
                                    {
                                        "code": "loose_gravel",
                                        "description": "Flying gravel",
                                    }
                                ],
                                "roads": [
                                    {"name": "Route road", "nr": "41"},
                                    {"name": "Side road", "nr": "39"},
                                ],
                            },
                            {
                                "id": "90106",
                                "name": "Normal driven road",
                                "condition": {
                                    "code": "clear",
                                    "category": "clear",
                                    "description": "Easily passable",
                                },
                            },
                        ]
                    }
                }
            }
        )
        geometries = {
            "90101": RoadGeometry(
                road_condition_id="90101",
                name="Driven road",
                road_number=None,
                paths=(
                    (
                        Coordinate(64.10, -21.94),
                        Coordinate(64.10, -21.86),
                    ),
                ),
                bbox=(-21.94, 64.10, -21.86, 64.10),
            ),
            "90102": RoadGeometry(
                road_condition_id="90102",
                name="Connected side road",
                road_number=None,
                paths=(
                    (
                        Coordinate(64.10, -21.90),
                        Coordinate(64.12, -21.90),
                    ),
                ),
                bbox=(-21.90, 64.10, -21.90, 64.12),
            ),
            "90103": RoadGeometry(
                road_condition_id="90103",
                name="Nearby parallel road",
                road_number=None,
                paths=(
                    (
                        Coordinate(64.1015, -21.94),
                        Coordinate(64.1015, -21.86),
                    ),
                ),
                bbox=(-21.94, 64.1015, -21.86, 64.1015),
            ),
            "90104": RoadGeometry(
                road_condition_id="90104",
                name="Short junction approach",
                road_number=None,
                paths=(
                    (
                        Coordinate(64.10, -21.90),
                        Coordinate(64.10, -21.897),
                        Coordinate(64.12, -21.897),
                    ),
                ),
                bbox=(-21.90, 64.10, -21.897, 64.12),
            ),
            "90105": RoadGeometry(
                road_condition_id="90105",
                name="Side road: Junction",
                road_number="39",
                paths=(
                    (
                        Coordinate(64.10, -21.91),
                        Coordinate(64.10, -21.89),
                    ),
                ),
                bbox=(-21.91, 64.10, -21.89, 64.10),
            ),
            "90106": RoadGeometry(
                road_condition_id="90106",
                name="Normal driven road",
                road_number="41",
                paths=(
                    (
                        Coordinate(64.10, -21.88),
                        Coordinate(64.10, -21.86),
                    ),
                ),
                bbox=(-21.88, 64.10, -21.86, 64.10),
            ),
        }

        details = build_route_details(
            origin_entity_id="zone.home",
            destination_entity_id="zone.work",
            origin_name="Home",
            destination_name="Work",
            route=route,
            roads={road.road_condition_id: road for road in roads},
            road_geometries=geometries,
            weather_stations=(),
            cameras=(),
            traffic_counters=(),
            notices=(),
            road_corridor_km=0.25,
            point_corridor_km=2,
        )

        self.assertEqual(
            [road.item_id for road in details.roads],
            ["90101", "90106"],
        )
        self.assertEqual(
            [item["id"] for item in details.road_geometries],
            ["90101", "90106"],
        )
        self.assertEqual([item["id"] for item in details.issue_geometries], ["90101"])

    def test_section_must_overlap_the_corresponding_osrm_road_step(self) -> None:
        route = parse_osrm_route_payload(
            {
                "code": "Ok",
                "routes": [
                    {
                        "distance": 20_000,
                        "duration": 1_200,
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[-22.0, 64.0], [-21.8, 64.1]],
                        },
                        "legs": [
                            {
                                "steps": [
                                    {
                                        "name": "Main road",
                                        "ref": "1",
                                        "geometry": {
                                            "type": "LineString",
                                            "coordinates": [
                                                [-22.0, 64.0],
                                                [-21.9, 64.0],
                                            ],
                                        },
                                    },
                                    {
                                        "name": "Side road",
                                        "ref": "39",
                                        "geometry": {
                                            "type": "LineString",
                                            "coordinates": [
                                                [-21.9, 64.0],
                                                [-21.8, 64.1],
                                            ],
                                        },
                                    },
                                ]
                            }
                        ],
                    }
                ],
            }
        )
        roads = parse_road_conditions_payload(
            {
                "data": {
                    "RoadCondition": {
                        "results": [
                            {
                                "id": "main",
                                "name": "Main road: Before junction",
                                "condition": {
                                    "code": "clear",
                                    "category": "clear",
                                    "description": "Easily passable",
                                },
                                "roads": [{"name": "Main road", "nr": "1"}],
                            },
                            {
                                "id": "side",
                                "name": "Side road: Junction",
                                "condition": {
                                    "code": "clear",
                                    "category": "clear",
                                    "description": "Easily passable",
                                },
                                "conditionMarkers": [
                                    {
                                        "code": "loose_gravel",
                                        "description": "Flying gravel",
                                    }
                                ],
                                "roads": [
                                    {"name": "Main road", "nr": "1"},
                                    {"name": "Side road", "nr": "39"},
                                ],
                            },
                        ]
                    }
                }
            }
        )
        shared_geometry = (
            (
                Coordinate(64.0, -21.99),
                Coordinate(64.0, -21.91),
            ),
        )
        geometries = {
            road_id: RoadGeometry(
                road_condition_id=road_id,
                name=road_id,
                road_number=road_number,
                paths=shared_geometry,
                bbox=(-21.99, 64.0, -21.91, 64.0),
            )
            for road_id, road_number in (("main", "1"), ("side", "39"))
        }

        details = build_route_details(
            origin_entity_id="zone.home",
            destination_entity_id="zone.work",
            origin_name="Home",
            destination_name="Work",
            route=route,
            roads={road.road_condition_id: road for road in roads},
            road_geometries=geometries,
            weather_stations=(),
            cameras=(),
            traffic_counters=(),
            notices=(),
            road_corridor_km=0.25,
            point_corridor_km=2,
        )

        self.assertEqual([road.item_id for road in details.roads], ["main"])
        self.assertEqual(details.issue_geometries, ())

    def test_normal_segment_classification_uses_stable_condition_code(self) -> None:
        details = RouteDetails(
            origin_entity_id="zone.home",
            destination_entity_id="zone.work",
            origin_name="Heimili",
            destination_name="Vinna",
            route=parse_osrm_route_payload(_osrm_payload()),
            status="clear",
            roads=(
                RouteMatch(
                    item_id="90101",
                    name="Vegarkafli",
                    distance_from_start_km=1.0,
                    distance_to_route_km=0.0,
                    data={
                        "condition": {
                            "code": "clear",
                            "category": "clear",
                            "description": "Greiðfært",
                        },
                        "is_closed": False,
                    },
                ),
            ),
            weather_stations=(),
            cameras=(),
            traffic_counters=(),
            notices=(),
            language="is",
        )

        segment = details.segment_summaries[0]
        self.assertEqual(segment["condition"], "Greiðfært")
        self.assertEqual(segment["severity"], "normal")
        self.assertFalse(segment["has_issue"])

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
                    "latitude": 64.0,
                    "longitude": -22.0 + site * 7.0 / 39.0,
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
            issue_geometries=(
                {
                    "id": "alert",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [-22.0 + 5 * 7.0 / 39.0 - 0.01, 64.0],
                            [-22.0 + 5 * 7.0 / 39.0 + 0.01, 64.0],
                        ],
                    },
                },
            ),
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

    def test_camera_alert_priority_uses_geographic_issue_distance(self) -> None:
        cameras = (
            RouteMatch(
                item_id="route-near",
                name="Same route kilometre",
                distance_from_start_km=50,
                distance_to_route_km=0,
                data={
                    "id": "route-near",
                    "image_url": "https://example.invalid/route-near.jpg",
                    "latitude": 65.0,
                    "longitude": -21.0,
                },
            ),
            RouteMatch(
                item_id="geographically-near",
                name="Beside affected road",
                distance_from_start_km=150,
                distance_to_route_km=0,
                data={
                    "id": "geographically-near",
                    "image_url": "https://example.invalid/geographically-near.jpg",
                    "latitude": 64.0,
                    "longitude": -21.0,
                },
            ),
        )
        details = RouteDetails(
            origin_entity_id="zone.home",
            destination_entity_id="zone.work",
            origin_name="Home",
            destination_name="Work",
            route=OsrmRoute(
                distance_km=200,
                duration_minutes=180,
                coordinates=(Coordinate(64.0, -22.0), Coordinate(64.0, -18.0)),
                road_names=(),
                road_numbers=(),
            ),
            status="advisory",
            roads=(),
            weather_stations=(),
            cameras=cameras,
            traffic_counters=(),
            notices=(),
            issue_geometries=(
                {
                    "id": "affected-road",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [-21.01, 64.0],
                            [-20.99, 64.0],
                        ],
                    },
                },
            ),
        )

        near_alert = {
            item["camera_site_id"]: item["near_alert"]
            for item in details.camera_summaries
        }
        self.assertFalse(near_alert["route-near"])
        self.assertTrue(near_alert["geographically-near"])


if __name__ == "__main__":
    unittest.main()
