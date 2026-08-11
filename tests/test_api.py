"""Tests for the Vegagerdin API client and parsers."""

from __future__ import annotations

import asyncio
from typing import Any
import unittest

from custom_components.vegagerdin.api import (
    GRAPHQL_URL,
    TRAFFIC_WFS_URL,
    WEBCAM_REST_URL,
    RoadCondition,
    VegagerdinApiClient,
    filter_notices,
    parse_road_conditions_payload,
    parse_road_notifications_payload,
    parse_traffic_counters_payload,
    parse_weather_stations_payload,
    parse_webcams_payload,
)


class FakeResponse:
    """Minimal async response test double."""

    def __init__(self, status: int, payload: Any) -> None:
        """Initialize the response."""
        self.status = status
        self._payload = payload

    async def __aenter__(self) -> "FakeResponse":
        """Enter the async context manager."""
        return self

    async def __aexit__(self, *args: object) -> None:
        """Exit the async context manager."""

    async def json(self, content_type: str | None = None) -> Any:
        """Return JSON payload."""
        return self._payload


class FakeSession:
    """Minimal aiohttp-like session test double."""

    def __init__(self, *, post_payload: Any = None, get_payload: Any = None) -> None:
        """Initialize the session."""
        self.post_payload = post_payload
        self.get_payload = get_payload
        self.post_calls: list[tuple[str, dict[str, Any]]] = []
        self.get_calls: list[tuple[str, list[tuple[str, str]]]] = []

    def post(
        self,
        url: str,
        *,
        json: dict[str, Any],
        timeout: int,
    ) -> FakeResponse:
        """Return a fake POST response."""
        self.post_calls.append((url, json))
        return FakeResponse(200, self.post_payload)

    def get(
        self,
        url: str,
        *,
        params: list[tuple[str, str]],
        timeout: int,
    ) -> FakeResponse:
        """Return a fake GET response."""
        self.get_calls.append((url, params))
        return FakeResponse(200, self.get_payload)


class TestApiParsers(unittest.TestCase):
    """Parser tests."""

    def test_parse_road_conditions(self) -> None:
        """Road condition payloads become stable dataclasses."""
        roads = parse_road_conditions_payload(
            {
                "data": {
                    "RoadCondition": {
                        "results": [
                            {
                                "id": "90101",
                                "name": "Hellisheiði",
                                "serviceCategory": "1",
                                "winterService": "A",
                                "display": True,
                                "lastUpdate": "2026-06-09T22:00:00Z",
                                "geometryCenter": {"lat": 64.0, "lon": -21.3},
                                "condition": {
                                    "code": "closed",
                                    "category": "closed",
                                    "description": "Closed",
                                    "date": "2026-06-09T21:50:00Z",
                                },
                                "conditionPrev": {
                                    "code": "snow",
                                    "category": "warning",
                                    "description": "Snow",
                                },
                                "conditionMarkers": [
                                    {
                                        "code": "snow",
                                        "description": "Snow",
                                        "lastUpdate": "2026-06-09T21:45:00Z",
                                    }
                                ],
                                "conditionsOtherMarkers": [
                                    {
                                        "id": "m1",
                                        "title": "Roadwork",
                                        "description": "Maintenance work",
                                        "code": "work",
                                        "coordinates": {"lat": 64.1, "lon": -21.2},
                                    }
                                ],
                                "weightRestriction": {
                                    "limit": 7,
                                    "description": "7 tons",
                                },
                                "roads": [{"name": "Hringvegur", "nr": "1"}],
                            }
                        ]
                    }
                }
            }
        )

        self.assertEqual(len(roads), 1)
        road = roads[0]
        self.assertIsInstance(road, RoadCondition)
        self.assertEqual(road.road_condition_id, "90101")
        self.assertTrue(road.is_closed)
        self.assertTrue(road.has_roadwork)
        self.assertTrue(road.has_weight_restriction)
        self.assertEqual(road.road_numbers, ("1",))
        self.assertEqual(road.roadwork_markers[0].description, "Maintenance work")
        self.assertEqual(road.as_dict()["condition"]["description"], "Closed")

    def test_parse_and_filter_notices(self) -> None:
        """Notice filters use category, tags, and text."""
        notices = parse_road_notifications_payload(
            {
                "data": {
                    "RoadNotifications": {
                        "results": [
                            {
                                "id": 1,
                                "category": "Roadwork",
                                "subCategory": "Repair",
                                "key": "roadwork",
                                "text": "Road 1 has work",
                                "tags": ["south"],
                                "date": "2026-06-09T20:00:00Z",
                            },
                            {
                                "id": 2,
                                "category": "Ferry",
                                "key": "ferry",
                                "text": "Ferry notice",
                                "tags": ["west"],
                            },
                        ]
                    }
                }
            }
        )

        filtered = filter_notices(
            notices,
            keys=["roadwork"],
            road_numbers=["1"],
            tags=["south"],
            categories=["Roadwork"],
        )

        self.assertEqual([notice.notice_id for notice in filtered], ["1"])

        self.assertEqual(
            [
                notice.notice_id
                for notice in filter_notices(notices, keys=["ferry"])
            ],
            ["2"],
        )

    def test_parse_weather_stations(self) -> None:
        """Weather stations expose weather and traffic fields."""
        stations = parse_weather_stations_payload(
            {
                "data": {
                    "WeatherStations": {
                        "results": [
                            {
                                "id": 77,
                                "name": "Station 77",
                                "category": "road",
                                "RoadConditionIds": ["90101"],
                                "owner": "IRCA",
                                "lastUpdate": "2026-06-09T22:00:00Z",
                                "windAlert": False,
                                "temperature": 4.2,
                                "roadTemperature": 3.1,
                                "humidity": 75,
                                "dewPoint": 0.5,
                                "traffic": 8,
                                "trafficFromMidnight": 600,
                                "wind": {"speed": 6, "gust": 12},
                                "windDirection": {
                                    "description": "N",
                                    "degrees": 5,
                                },
                                "coordinates": {"lat": 64.0, "lon": -21.0},
                            }
                        ]
                    }
                }
            }
        )

        self.assertEqual(stations[0].station_id, 77)
        self.assertEqual(stations[0].wind.gust, 12)
        self.assertEqual(stations[0].traffic_from_midnight, 600)

    def test_parse_webcams(self) -> None:
        """Official webcam REST records parse into camera metadata."""
        cameras = parse_webcams_payload(
            [
                {
                    "Maelist_nr": 7001,
                    "Myndavel": "Hellisheiði",
                    "NrVegur": "1",
                    "Vegheiti": "Hringvegur",
                    "Skyring": "West",
                    "Slod": "https://example.invalid/camera.jpg",
                    "Breidd": 64.01,
                    "Lengd": -21.34,
                },
                {
                    "Maelist_nr": 7001,
                    "Myndavel": "Hellisheiði",
                    "NrVegur": "1",
                    "Vegheiti": "Hringvegur",
                    "Skyring": "East",
                    "Slod": "https://example.invalid/camera_2.jpg",
                    "Breidd": 64.01,
                    "Lengd": -21.34,
                }
            ]
        )

        self.assertEqual(len(cameras), 2)
        self.assertEqual(cameras[0].camera_id, 7001)
        self.assertEqual(cameras[0].image_id, "7001_camera")
        self.assertEqual(cameras[1].image_id, "7001_camera_2")
        self.assertEqual(cameras[0].image_url, "https://example.invalid/camera.jpg")

    def test_parse_traffic_counters(self) -> None:
        """WFS GeoJSON records parse into counter metadata."""
        counters = parse_traffic_counters_payload(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "Point",
                            "coordinates": [-23.48, 64.84],
                        },
                        "properties": {
                            "OBJECTID": 22,
                            "IDSTOD": 22,
                            "NAFN": "Fróðárheiði",
                            "STEFNA": "Both",
                            "UMF_15MIN": 8,
                            "MEDALHRADI_15MIN": 74,
                            "UMF_I_DAG": 600,
                            "DAGS_SIDUSTUGAGNA": "2026-06-09T22:00:00Z",
                            "UMF_DAGUR1": 657,
                            "DAGS_DAGUR1": "2026-06-08T23:59:59Z",
                            "MAELISTOD_TEGUND": 1,
                        },
                    }
                ],
            }
        )

        self.assertEqual(counters[0].counter_id, 22)
        self.assertEqual(counters[0].latitude, 64.84)
        self.assertEqual(counters[0].traffic_today, 600)
        self.assertEqual(counters[0].daily_counts[0][1], 657)


class TestApiClient(unittest.TestCase):
    """Client request-shaping tests."""

    def test_graphql_road_conditions_posts_json(self) -> None:
        """Road condition requests use the GraphQL endpoint."""
        session = FakeSession(
            post_payload={
                "data": {
                    "RoadCondition": {
                        "results": [
                            {
                                "id": "90101",
                                "name": "Road",
                                "condition": {"description": "Clear"},
                            }
                        ]
                    }
                }
            }
        )
        client = VegagerdinApiClient(session)

        roads = asyncio.run(client.async_get_road_conditions(language="en"))

        self.assertEqual(roads[0].road_condition_id, "90101")
        self.assertEqual(session.post_calls[0][0], GRAPHQL_URL)
        self.assertEqual(session.post_calls[0][1]["variables"], {"lang": "EN"})

    def test_graphql_road_content_uses_icelandic_language(self) -> None:
        """Road conditions and notices request Icelandic content with IS."""
        conditions_session = FakeSession(
            post_payload={"data": {"RoadCondition": {"results": []}}}
        )
        notices_session = FakeSession(
            post_payload={"data": {"RoadNotifications": {"results": []}}}
        )

        asyncio.run(
            VegagerdinApiClient(conditions_session).async_get_road_conditions(
                language="is"
            )
        )
        asyncio.run(
            VegagerdinApiClient(notices_session).async_get_road_notifications(
                language="is"
            )
        )

        self.assertEqual(
            conditions_session.post_calls[0][1]["variables"],
            {"lang": "IS"},
        )
        self.assertEqual(
            notices_session.post_calls[0][1]["variables"],
            {"language": "IS"},
        )

    def test_webcam_client_filters_by_id(self) -> None:
        """Webcam REST requests filter requested camera IDs client-side."""
        session = FakeSession(
            get_payload=[
                {"Maelist_nr": 7001, "Myndavel": "One"},
                {"Maelist_nr": 7002, "Myndavel": "Two"},
            ]
        )
        client = VegagerdinApiClient(session)

        cameras = asyncio.run(client.async_get_webcams(camera_ids=[7002]))

        self.assertEqual([camera.camera_id for camera in cameras], [7002])
        self.assertEqual(session.get_calls[0][0], WEBCAM_REST_URL)

    def test_traffic_client_requests_geojson_4326(self) -> None:
        """Traffic WFS requests GeoJSON in WGS84 coordinates."""
        session = FakeSession(get_payload={"features": []})
        client = VegagerdinApiClient(session)

        asyncio.run(client.async_get_traffic_counters())

        url, params = session.get_calls[0]
        self.assertEqual(url, TRAFFIC_WFS_URL)
        self.assertIn(("outputFormat", "application/json"), params)
        self.assertIn(("srsName", "EPSG:4326"), params)


if __name__ == "__main__":
    unittest.main()
