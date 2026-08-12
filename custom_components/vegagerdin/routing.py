"""Routing API, geometry matching, and route response models."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from math import acos, ceil, cos, degrees, floor, hypot, radians
from typing import Any

from .api import (
    CannotConnect,
    InvalidResponse,
    RoadCondition,
    RoadNotice,
    TrafficCounter,
    VegagerdinApiError,
    VegagerdinCamera,
    WeatherStation,
)
from .const import (
    DEFAULT_LANGUAGE,
    IMPORTANT_NOTICE_KEYS,
    SOURCE_OSRM,
    SOURCE_ROAD_GEOMETRY_WFS,
)

ROAD_GEOMETRY_WFS_URL = "https://gagnaveita.vegagerdin.is/geoserver/gis/ows"
ROAD_GEOMETRY_TYPENAME = "gis:faerdferlar2017_1"
ROUTING_TIMEOUT_SECONDS = 30
EARTH_RADIUS_KM = 6371.0088
ROUTE_CAMERA_ALERT_RADIUS_KM = 2.0
ROUTE_CAMERA_MAX_IMAGES = 50
ROUTE_CAMERA_MAX_SITES = 30
ROAD_ROUTE_OVERLAP_CORRIDOR_KM = 0.1
ROAD_ROUTE_MIN_OVERLAP_KM = 0.2
ROAD_ROUTE_OVERLAP_SAMPLE_KM = 0.025
ROAD_ROUTE_MAX_ANGLE_DEGREES = 40.0
ROUTE_DISPLAY_POINTS_PER_KM = 3.0
ROUTE_DISPLAY_MIN_POINTS = 100
ROUTE_DISPLAY_MAX_POINTS = 800
ROUTE_SIMPLIFY_ITERATIONS = 24
ROUTE_SPATIAL_INDEX_CELL_KM = 0.5

_CLOSED_TOKENS = ("closed", "impassable", "ófært", "loka", "lokad")
_DIFFICULT_TOKENS = (
    "difficult",
    "slippery",
    "snow",
    "ice",
    "storm",
    "þungfært",
    "hált",
    "snjór",
    "ísing",
)
_GOOD_TOKENS = (
    "easily passable",
    "clear",
    "greiðfært",
    "greidfært",
    "auðvelt",
)


@dataclass(frozen=True, slots=True)
class Coordinate:
    """A WGS84 coordinate."""

    latitude: float
    longitude: float


@dataclass(frozen=True, slots=True)
class RoadGeometry:
    """Official geometry for one Vegagerdin road-condition section."""

    road_condition_id: str
    name: str | None
    road_number: str | None
    paths: tuple[tuple[Coordinate, ...], ...]
    bbox: tuple[float, float, float, float]
    source: str = SOURCE_ROAD_GEOMETRY_WFS


@dataclass(frozen=True, slots=True)
class OsrmRouteStep:
    """Detailed OSRM step geometry with its road identity."""

    name: str | None
    road_numbers: tuple[str, ...]
    coordinates: tuple[Coordinate, ...]


@dataclass(frozen=True, slots=True)
class OsrmRoute:
    """A route returned by OSRM."""

    distance_km: float
    duration_minutes: float
    coordinates: tuple[Coordinate, ...]
    road_names: tuple[str, ...]
    road_numbers: tuple[str, ...]
    steps: tuple[OsrmRouteStep, ...] = ()
    display_coordinates: tuple[Coordinate, ...] = ()
    source: str = SOURCE_OSRM

    def as_dict(self, *, include_geometry: bool = True) -> dict[str, Any]:
        """Return a JSON-serializable route dictionary."""
        result: dict[str, Any] = {
            "distance_km": round(self.distance_km, 2),
            "duration_minutes": round(self.duration_minutes, 1),
            "road_names": list(self.road_names),
            "road_numbers": list(self.road_numbers),
            "matching_geometry_points": len(self.coordinates),
            "display_geometry_points": len(
                self.display_coordinates or self.coordinates
            ),
            "source": self.source,
        }
        if include_geometry:
            coordinates = self.display_coordinates or self.coordinates
            result["geometry"] = {
                "type": "LineString",
                "coordinates": [
                    [coordinate.longitude, coordinate.latitude]
                    for coordinate in coordinates
                ],
            }
        return result


@dataclass(frozen=True, slots=True)
class _IndexedRouteSegment:
    """One projected OSRM segment stored in the route spatial index."""

    start: tuple[float, float]
    end: tuple[float, float]
    bbox: tuple[float, float, float, float]
    distance_from_start_km: float


@dataclass(frozen=True, slots=True)
class _RouteSpatialIndex:
    """Uniform-grid index over detailed OSRM route segments."""

    reference_latitude: float
    segments: tuple[_IndexedRouteSegment, ...]
    cells: Mapping[tuple[int, int], tuple[int, ...]]
    name_segments: Mapping[str, frozenset[int]]
    number_segments: Mapping[str, frozenset[int]]

    def candidates(
        self,
        bbox: tuple[float, float, float, float],
    ) -> set[int]:
        """Return segment indices whose grid cells intersect a bbox."""
        west, south, east, north = bbox
        results: set[int] = set()
        for cell_x in range(
            floor(west / ROUTE_SPATIAL_INDEX_CELL_KM),
            floor(east / ROUTE_SPATIAL_INDEX_CELL_KM) + 1,
        ):
            for cell_y in range(
                floor(south / ROUTE_SPATIAL_INDEX_CELL_KM),
                floor(north / ROUTE_SPATIAL_INDEX_CELL_KM) + 1,
            ):
                results.update(self.cells.get((cell_x, cell_y), ()))
        return results


@dataclass(frozen=True, slots=True)
class RouteMatch:
    """One source record matched to a route."""

    item_id: str
    name: str
    distance_from_start_km: float | None
    distance_to_route_km: float | None
    data: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        """Return a response dictionary."""
        return {
            "id": self.item_id,
            "name": self.name,
            "distance_from_start_km": _rounded(self.distance_from_start_km),
            "distance_to_route_km": _rounded(self.distance_to_route_km),
            **dict(self.data),
        }


@dataclass(frozen=True, slots=True)
class RouteDetails:
    """Vegagerdin information relevant to one configured route."""

    origin_entity_id: str
    destination_entity_id: str
    origin_name: str
    destination_name: str
    route: OsrmRoute
    status: str
    roads: tuple[RouteMatch, ...]
    weather_stations: tuple[RouteMatch, ...]
    cameras: tuple[RouteMatch, ...]
    traffic_counters: tuple[RouteMatch, ...]
    notices: tuple[RoadNotice, ...]
    language: str = DEFAULT_LANGUAGE
    road_geometries: tuple[Mapping[str, Any], ...] = ()
    issue_geometries: tuple[Mapping[str, Any], ...] = ()

    @property
    def route_name(self) -> str:
        """Return a human-friendly route name."""
        connector = "til" if _is_icelandic(self.language) else "to"
        return f"{self.origin_name} {connector} {self.destination_name}"

    @property
    def closure_count(self) -> int:
        """Return matched closed road count."""
        return sum(bool(match.data.get("is_closed")) for match in self.roads)

    @property
    def roadwork_count(self) -> int:
        """Return matched roadwork count."""
        return sum(bool(match.data.get("has_roadwork")) for match in self.roads)

    @property
    def restriction_count(self) -> int:
        """Return matched weight-restriction count."""
        return sum(
            bool(match.data.get("has_weight_restriction")) for match in self.roads
        )

    @property
    def maximum_wind_gust(self) -> float | None:
        """Return the highest current gust along the route."""
        return _numeric_extreme(
            (match.data.get("wind_gust") for match in self.weather_stations),
            maximum=True,
        )

    @property
    def minimum_road_temperature(self) -> float | None:
        """Return the lowest current road temperature along the route."""
        return _numeric_extreme(
            (match.data.get("road_temperature") for match in self.weather_stations),
            maximum=False,
        )

    @property
    def segment_summaries(self) -> list[dict[str, Any]]:
        """Return compact road rows ordered from route origin to destination."""
        return [
            _segment_summary(road, self.weather_stations, self.language)
            for road in self.roads
        ]

    @property
    def camera_site_count(self) -> int:
        """Return the number of physical camera sites along the route."""
        return len({_camera_site_key(camera) for camera in self.cameras})

    @property
    def camera_summaries(self) -> list[dict[str, Any]]:
        """Return representative route-wide camera views with alert detail."""
        return _select_route_camera_summaries(
            self.cameras,
            self.issue_geometries,
        )

    @property
    def weather_summaries(self) -> list[dict[str, Any]]:
        """Return compact weather rows ordered along the route."""
        return [
            {
                "id": station.item_id,
                "distance_km": _rounded(station.distance_from_start_km),
                "name": station.name,
                "last_update": station.data.get("last_update"),
                "wind_alert": station.data.get("wind_alert"),
                "temperature": station.data.get("temperature"),
                "road_temperature": station.data.get("road_temperature"),
                "wind_speed": station.data.get("wind_speed"),
                "wind_gust": station.data.get("wind_gust"),
                "wind_direction": station.data.get("wind_direction"),
            }
            for station in self.weather_stations
        ]

    @property
    def traffic_summaries(self) -> list[dict[str, Any]]:
        """Return compact traffic-counter rows ordered along the route."""
        return [
            {
                "id": counter.item_id,
                "distance_km": _rounded(counter.distance_from_start_km),
                "name": counter.name,
                "direction": counter.data.get("direction"),
                "traffic_15min": counter.data.get("traffic_15min"),
                "average_speed_15min": counter.data.get("average_speed_15min"),
                "traffic_today": counter.data.get("traffic_today"),
                "last_data": counter.data.get("last_data"),
            }
            for counter in self.traffic_counters
        ]

    def as_dict(self, *, include_geometry: bool = True) -> dict[str, Any]:
        """Return a complete response dictionary."""
        return {
            "origin_entity_id": self.origin_entity_id,
            "destination_entity_id": self.destination_entity_id,
            "origin_name": self.origin_name,
            "destination_name": self.destination_name,
            "route_name": self.route_name,
            "status": self.status,
            "summary": {
                "road_sections": len(self.roads),
                "closures": self.closure_count,
                "roadworks": self.roadwork_count,
                "weight_restrictions": self.restriction_count,
                "notices": len(self.notices),
                "weather_stations": len(self.weather_stations),
                "cameras": len(self.cameras),
                "traffic_counters": len(self.traffic_counters),
                "maximum_wind_gust": self.maximum_wind_gust,
                "minimum_road_temperature": self.minimum_road_temperature,
            },
            "route": self.route.as_dict(include_geometry=include_geometry),
            "road_conditions": [match.as_dict() for match in self.roads],
            "road_segments": self.segment_summaries,
            "weather_stations": [match.as_dict() for match in self.weather_stations],
            "route_weather": self.weather_summaries,
            "cameras": [match.as_dict() for match in self.cameras],
            "route_cameras": self.camera_summaries,
            "camera_sites": self.camera_site_count,
            "traffic_counters": [match.as_dict() for match in self.traffic_counters],
            "route_traffic": self.traffic_summaries,
            "notices": [notice.as_dict() for notice in self.notices],
            "road_geometries": list(self.road_geometries),
            "issue_geometries": list(self.issue_geometries),
        }


class VegagerdinRouteApiClient:
    """Async client for OSRM routes and official road geometries."""

    def __init__(self, session: Any, osrm_url: str) -> None:
        """Initialize the routing client."""
        self._session = session
        self.osrm_url = osrm_url.rstrip("/")

    async def async_get_route(
        self,
        origin: Coordinate,
        destination: Coordinate,
    ) -> OsrmRoute:
        """Return a driving route between two coordinates."""
        if not self.osrm_url:
            raise InvalidResponse("OSRM URL is not configured")
        coordinates = (
            f"{origin.longitude:.6f},{origin.latitude:.6f};"
            f"{destination.longitude:.6f},{destination.latitude:.6f}"
        )
        url = f"{self.osrm_url}/route/v1/driving/{coordinates}"
        payload = await self._async_get_json(
            url,
            params=[
                ("overview", "simplified"),
                ("geometries", "geojson"),
                ("steps", "true"),
            ],
        )
        return parse_osrm_route_payload(payload)

    async def async_get_road_geometries(self) -> dict[str, RoadGeometry]:
        """Return official road-condition section LineStrings."""
        payload = await self._async_get_json(
            ROAD_GEOMETRY_WFS_URL,
            params=[
                ("service", "WFS"),
                ("version", "1.0.0"),
                ("request", "GetFeature"),
                ("typeName", ROAD_GEOMETRY_TYPENAME),
                ("srsName", "EPSG:4326"),
                ("cql_filter", "NAKVAEMNIFERLIS=0"),
                ("outputFormat", "application/json"),
            ],
        )
        return parse_road_geometries_payload(payload)

    async def _async_get_json(
        self,
        url: str,
        *,
        params: Sequence[tuple[str, str]],
    ) -> Any:
        """Fetch and validate one JSON response."""
        try:
            async with self._session.get(
                url,
                params=list(params),
                timeout=ROUTING_TIMEOUT_SECONDS,
            ) as response:
                if response.status >= 500:
                    raise CannotConnect(f"HTTP {response.status}")
                if response.status >= 400:
                    raise InvalidResponse(f"HTTP {response.status}")
                return await response.json(content_type=None)
        except VegagerdinApiError:
            raise
        except Exception as err:  # noqa: BLE001 - aiohttp optional in tests.
            raise CannotConnect(str(err)) from err


def route_unique_id(
    origin_entity_id: str,
    destination_entity_id: str,
    key: str,
) -> str:
    """Return a stable unique ID for one route entity."""
    origin = origin_entity_id.replace(".", "_")
    destination = destination_entity_id.replace(".", "_")
    return f"vegagerdin_route_{origin}_{destination}_{key}"


def route_entity_object_id(
    origin_entity_id: str,
    destination_entity_id: str,
    key: str,
) -> str:
    """Return the searchable object ID requested for a route entity."""
    origin = _entity_id_fragment(origin_entity_id)
    destination = _entity_id_fragment(destination_entity_id)
    return f"vegagerdin_route_{origin}_to_{destination}_{key}"


def _entity_id_fragment(entity_id: str) -> str:
    """Return a conservative object-ID fragment from an HA entity ID."""
    object_id = entity_id.partition(".")[2] or entity_id
    return re.sub(r"[^a-z0-9_]+", "_", object_id.casefold()).strip("_")


def parse_osrm_route_payload(payload: Any) -> OsrmRoute:
    """Parse an OSRM route response."""
    if not isinstance(payload, Mapping) or payload.get("code") != "Ok":
        message = payload.get("message") if isinstance(payload, Mapping) else None
        raise InvalidResponse(str(message or "OSRM did not return a route"))
    routes = payload.get("routes")
    if not _is_sequence(routes) or not routes or not isinstance(routes[0], Mapping):
        raise InvalidResponse("OSRM response has no route")
    route = routes[0]
    geometry = route.get("geometry")
    if not isinstance(geometry, Mapping) or geometry.get("type") != "LineString":
        raise InvalidResponse("OSRM response has no GeoJSON LineString")
    raw_coordinates = geometry.get("coordinates")
    if not _is_sequence(raw_coordinates):
        raise InvalidResponse("OSRM route coordinates are invalid")
    coordinates = tuple(
        coordinate
        for item in raw_coordinates
        if (coordinate := _coordinate_from_geojson(item)) is not None
    )
    if len(coordinates) < 2:
        raise InvalidResponse("OSRM route has too few coordinates")

    names: list[str] = []
    numbers: list[str] = []
    steps: list[OsrmRouteStep] = []
    detailed_coordinates: list[Coordinate] = []
    for leg in _mapping_items(route.get("legs")):
        for step in _mapping_items(leg.get("steps")):
            name = _optional_str(step.get("name"))
            _append_unique(names, name)
            step_numbers = _road_references(step.get("ref"))
            for number in step_numbers:
                _append_unique(numbers, number)
            step_geometry = step.get("geometry")
            step_paths = (
                _geometry_paths(step_geometry)
                if isinstance(step_geometry, Mapping)
                and step_geometry.get("type") == "LineString"
                else []
            )
            step_coordinates = tuple(step_paths[0]) if step_paths else ()
            if len(step_coordinates) >= 2:
                _extend_route_coordinates(detailed_coordinates, step_coordinates)
            steps.append(
                OsrmRouteStep(
                    name=name,
                    road_numbers=step_numbers,
                    coordinates=step_coordinates,
                )
            )

    matching_coordinates = tuple(detailed_coordinates) or coordinates
    if len(matching_coordinates) < 2:
        matching_coordinates = coordinates
    distance_km = float(route.get("distance") or 0) / 1000
    display_coordinates = _simplify_route_for_display(
        matching_coordinates,
        distance_km,
    )

    return OsrmRoute(
        distance_km=distance_km,
        duration_minutes=float(route.get("duration") or 0) / 60,
        coordinates=matching_coordinates,
        road_names=tuple(names),
        road_numbers=tuple(numbers),
        steps=tuple(steps),
        display_coordinates=display_coordinates,
    )


def _road_references(value: Any) -> tuple[str, ...]:
    """Return normalized road references from one OSRM step."""
    reference = _optional_str(value)
    if not reference:
        return ()
    results: list[str] = []
    for item in reference.replace(";", ",").split(","):
        _append_unique(results, item.strip() or None)
    return tuple(results)


def _extend_route_coordinates(
    target: list[Coordinate],
    path: Sequence[Coordinate],
) -> None:
    """Append a route-ordered step path without duplicate endpoints."""
    if not path:
        return
    if not target:
        target.extend(path)
        return
    if coordinate_distance_km(target[-1], path[0]) <= 0.001:
        target.extend(path[1:])
        return
    if coordinate_distance_km(target[-1], path[-1]) <= 0.001:
        target.extend(reversed(path[:-1]))
        return
    target.extend(path)


def _simplify_route_for_display(
    coordinates: Sequence[Coordinate],
    distance_km: float,
) -> tuple[Coordinate, ...]:
    """Return a distance-scaled route overview bounded for HA responses."""
    cleaned: list[Coordinate] = []
    for coordinate in coordinates:
        if not cleaned or coordinate_distance_km(cleaned[-1], coordinate) > 0.001:
            cleaned.append(coordinate)
    if len(cleaned) <= 2:
        return tuple(cleaned)

    point_budget = min(
        ROUTE_DISPLAY_MAX_POINTS,
        max(
            ROUTE_DISPLAY_MIN_POINTS,
            ceil(max(0.0, distance_km) * ROUTE_DISPLAY_POINTS_PER_KM),
        ),
    )
    if len(cleaned) <= point_budget:
        return tuple(cleaned)

    reference_latitude = radians(
        sum(coordinate.latitude for coordinate in cleaned) / len(cleaned)
    )
    projected = [_project(coordinate, reference_latitude) for coordinate in cleaned]
    first = projected[0]
    low = 0.0
    high = max(hypot(point[0] - first[0], point[1] - first[1]) for point in projected)
    best_indices = (0, len(cleaned) - 1)
    for _ in range(ROUTE_SIMPLIFY_ITERATIONS):
        tolerance = (low + high) / 2
        indices = _douglas_peucker_indices(projected, tolerance)
        if len(indices) > point_budget:
            low = tolerance
        else:
            high = tolerance
            best_indices = indices
    return tuple(cleaned[index] for index in best_indices)


def _douglas_peucker_indices(
    points: Sequence[tuple[float, float]],
    tolerance: float,
) -> tuple[int, ...]:
    """Return retained indices from iterative Douglas-Peucker simplification."""
    if len(points) <= 2:
        return tuple(range(len(points)))
    retained = {0, len(points) - 1}
    pending = [(0, len(points) - 1)]
    while pending:
        start_index, end_index = pending.pop()
        best_index: int | None = None
        best_distance = -1.0
        for index in range(start_index + 1, end_index):
            distance, _ = _point_segment_distance(
                points[index],
                points[start_index],
                points[end_index],
            )
            if distance > best_distance:
                best_distance = distance
                best_index = index
        if best_index is not None and best_distance > tolerance:
            retained.add(best_index)
            pending.append((start_index, best_index))
            pending.append((best_index, end_index))
    return tuple(sorted(retained))


def parse_road_geometries_payload(payload: Any) -> dict[str, RoadGeometry]:
    """Parse and group official WFS road-condition geometries."""
    if not isinstance(payload, Mapping) or not _is_sequence(payload.get("features")):
        raise InvalidResponse("Expected road geometry FeatureCollection")

    grouped_paths: dict[str, list[tuple[Coordinate, ...]]] = defaultdict(list)
    names: dict[str, str | None] = {}
    road_numbers: dict[str, str | None] = {}
    for feature in _mapping_items(payload.get("features")):
        properties = feature.get("properties")
        geometry = feature.get("geometry")
        if not isinstance(properties, Mapping) or not isinstance(geometry, Mapping):
            continue
        road_condition_id = _condition_id_from_geometry(properties.get("IDBUTUR"))
        if road_condition_id is None:
            continue
        for path in _geometry_paths(geometry):
            if len(path) >= 2:
                grouped_paths[road_condition_id].append(path)
        name = _optional_str(
            properties.get("STADARLYSING") or properties.get("STUTTNAFNLEIDAR")
        )
        road_number = _optional_str(properties.get("VEGNR"))
        if name is not None:
            names[road_condition_id] = name
        if road_number is not None:
            road_numbers[road_condition_id] = road_number

    results: dict[str, RoadGeometry] = {}
    for road_condition_id, paths in grouped_paths.items():
        coordinates = [coordinate for path in paths for coordinate in path]
        results[road_condition_id] = RoadGeometry(
            road_condition_id=road_condition_id,
            name=names.get(road_condition_id),
            road_number=road_numbers.get(road_condition_id),
            paths=tuple(paths),
            bbox=_coordinate_bbox(coordinates),
        )
    return results


def build_route_details(
    *,
    origin_entity_id: str,
    destination_entity_id: str,
    origin_name: str,
    destination_name: str,
    route: OsrmRoute,
    roads: Mapping[str, RoadCondition],
    road_geometries: Mapping[str, RoadGeometry],
    weather_stations: Iterable[WeatherStation],
    cameras: Iterable[VegagerdinCamera],
    traffic_counters: Iterable[TrafficCounter],
    notices: Iterable[RoadNotice],
    road_corridor_km: float,
    point_corridor_km: float,
    language: str = DEFAULT_LANGUAGE,
) -> RouteDetails:
    """Match Vegagerdin records to a route and build a response model."""
    route_bbox = _expanded_bbox(route.coordinates, road_corridor_km)
    route_index = _build_route_spatial_index(route)
    road_matches: list[RouteMatch] = []
    for road in roads.values():
        geometry = road_geometries.get(road.road_condition_id)
        road_data = road.as_dict() | {
            "is_closed": road.is_closed,
            "has_roadwork": road.has_roadwork,
            "has_weight_restriction": road.has_weight_restriction,
        }
        match_result: tuple[float, float] | None = None
        if geometry is not None and _bboxes_overlap(route_bbox, geometry.bbox):
            allowed_segments = _road_route_segment_ids(road, route_index)
            match_result = _indexed_geometry_route_distance(
                geometry,
                route_index,
                allowed_segments,
                max_distance_km=road_corridor_km,
            )
        elif road.latitude is not None and road.longitude is not None:
            match_result = _indexed_nearest_route_position(
                Coordinate(road.latitude, road.longitude),
                route_index,
                road_corridor_km,
            )
        if match_result is None or match_result[0] > road_corridor_km:
            continue
        if geometry is not None and (
            not _indexed_geometry_has_route_overlap(
                geometry,
                route_index,
                allowed_segments,
                max_distance_km=min(
                    road_corridor_km,
                    ROAD_ROUTE_OVERLAP_CORRIDOR_KM,
                ),
            )
        ):
            continue
        distance_to_route, distance_from_start = match_result
        road_matches.append(
            RouteMatch(
                item_id=road.road_condition_id,
                name=road.name,
                distance_from_start_km=distance_from_start,
                distance_to_route_km=distance_to_route,
                data=road_data,
            )
        )
    road_matches.sort(key=_match_sort_key)
    matched_road_ids = {match.item_id for match in road_matches}

    station_matches = _match_weather_stations(
        weather_stations,
        route_index,
        matched_road_ids,
        point_corridor_km,
    )
    camera_matches = _match_points(
        cameras,
        route_index,
        point_corridor_km,
        id_fn=lambda camera: camera.image_id,
        name_fn=lambda camera: camera.name,
        latitude_fn=lambda camera: camera.latitude,
        longitude_fn=lambda camera: camera.longitude,
        data_fn=lambda camera: camera.as_dict(),
    )
    counter_matches = _match_points(
        traffic_counters,
        route_index,
        point_corridor_km,
        id_fn=lambda counter: counter.counter_id,
        name_fn=lambda counter: counter.name,
        latitude_fn=lambda counter: counter.latitude,
        longitude_fn=lambda counter: counter.longitude,
        data_fn=lambda counter: counter.as_dict(),
    )
    matched_notices = _match_notices(
        notices,
        route,
    )
    status = _route_status(road_matches, matched_notices)
    segment_summaries = [
        _segment_summary(road, station_matches, language) for road in road_matches
    ]
    geometry_summaries = tuple(
        _road_geometry_summary(road, geometry, segment)
        for road, segment in zip(road_matches, segment_summaries, strict=True)
        if (geometry := road_geometries.get(road.item_id)) is not None
    )
    issue_geometries = tuple(
        geometry
        for geometry in geometry_summaries
        if geometry["severity"] != "normal"
    )
    return RouteDetails(
        origin_entity_id=origin_entity_id,
        destination_entity_id=destination_entity_id,
        origin_name=origin_name,
        destination_name=destination_name,
        route=route,
        status=status,
        roads=tuple(road_matches),
        weather_stations=tuple(station_matches),
        cameras=tuple(camera_matches),
        traffic_counters=tuple(counter_matches),
        notices=tuple(matched_notices),
        language=language,
        road_geometries=geometry_summaries,
        issue_geometries=issue_geometries,
    )


def nearest_route_position(
    point: Coordinate,
    route: Sequence[Coordinate],
) -> tuple[float, float] | None:
    """Return distance to route and distance from its start in kilometers."""
    if len(route) < 2:
        return None
    latitude_origin = radians(point.latitude)
    projected_route = [_project(coordinate, latitude_origin) for coordinate in route]
    projected_point = _project(point, latitude_origin)
    best_distance = float("inf")
    best_along = 0.0
    traversed = 0.0
    for start, end in zip(projected_route, projected_route[1:], strict=False):
        distance, fraction = _point_segment_distance(projected_point, start, end)
        segment_length = hypot(end[0] - start[0], end[1] - start[1])
        if distance < best_distance:
            best_distance = distance
            best_along = traversed + segment_length * fraction
        traversed += segment_length
    return best_distance, best_along


def coordinate_distance_km(first: Coordinate, second: Coordinate) -> float:
    """Return an approximate distance between two WGS84 coordinates."""
    latitude_origin = radians((first.latitude + second.latitude) / 2)
    first_projected = _project(first, latitude_origin)
    second_projected = _project(second, latitude_origin)
    return hypot(
        second_projected[0] - first_projected[0],
        second_projected[1] - first_projected[1],
    )


def _build_route_spatial_index(route: OsrmRoute) -> _RouteSpatialIndex:
    """Build a reusable spatial index over detailed OSRM route segments."""
    reference_latitude = radians(
        sum(coordinate.latitude for coordinate in route.coordinates)
        / len(route.coordinates)
    )
    route_paths = [
        (step.coordinates, step.name, step.road_numbers)
        for step in route.steps
        if len(step.coordinates) >= 2
    ]
    if not route_paths:
        route_paths = [(route.coordinates, None, ())]

    segments: list[_IndexedRouteSegment] = []
    cells: dict[tuple[int, int], list[int]] = defaultdict(list)
    name_segments: dict[str, set[int]] = defaultdict(set)
    number_segments: dict[str, set[int]] = defaultdict(set)
    traversed = 0.0
    previous_end: Coordinate | None = None
    for path, name, road_numbers in route_paths:
        if previous_end is not None:
            traversed += coordinate_distance_km(previous_end, path[0])
        projected_path = [_project(item, reference_latitude) for item in path]
        normalized_numbers = frozenset(
            number.casefold().strip() for number in road_numbers if number.strip()
        )
        normalized_name = _normalize_road_name(name or "")
        for start, end in zip(projected_path, projected_path[1:], strict=False):
            bbox = (
                min(start[0], end[0]),
                min(start[1], end[1]),
                max(start[0], end[0]),
                max(start[1], end[1]),
            )
            index = len(segments)
            segments.append(
                _IndexedRouteSegment(
                    start=start,
                    end=end,
                    bbox=bbox,
                    distance_from_start_km=traversed,
                )
            )
            if normalized_name:
                name_segments[normalized_name].add(index)
            for number in normalized_numbers:
                number_segments[number].add(index)
            for cell_x in range(
                floor(bbox[0] / ROUTE_SPATIAL_INDEX_CELL_KM),
                floor(bbox[2] / ROUTE_SPATIAL_INDEX_CELL_KM) + 1,
            ):
                for cell_y in range(
                    floor(bbox[1] / ROUTE_SPATIAL_INDEX_CELL_KM),
                    floor(bbox[3] / ROUTE_SPATIAL_INDEX_CELL_KM) + 1,
                ):
                    cells[(cell_x, cell_y)].append(index)
            traversed += hypot(end[0] - start[0], end[1] - start[1])
        previous_end = path[-1]
    return _RouteSpatialIndex(
        reference_latitude=reference_latitude,
        segments=tuple(segments),
        cells={key: tuple(value) for key, value in cells.items()},
        name_segments={key: frozenset(value) for key, value in name_segments.items()},
        number_segments={
            key: frozenset(value) for key, value in number_segments.items()
        },
    )


def _road_route_segment_ids(
    road: RoadCondition,
    route_index: _RouteSpatialIndex,
) -> set[int] | None:
    """Return indexed OSRM segments carrying the section's primary road."""
    if not route_index.name_segments and not route_index.number_segments:
        return None
    primary_name = road.name.partition(":")[0].strip()
    normalized_name = _normalize_road_name(primary_name)
    primary_numbers = {
        number.casefold().strip()
        for name, number in zip(road.road_names, road.road_numbers, strict=False)
        if number.strip() and _road_identity_names_match(primary_name, name)
    }
    matched: set[int] = set()
    for route_name, segment_ids in route_index.name_segments.items():
        if _normalized_road_names_match(normalized_name, route_name):
            matched.update(segment_ids)
    for number in primary_numbers:
        matched.update(route_index.number_segments.get(number, ()))
    if matched:
        return matched
    return set() if primary_numbers else None


def _indexed_geometry_route_distance(
    geometry: RoadGeometry,
    route_index: _RouteSpatialIndex,
    allowed_segments: set[int] | None,
    *,
    max_distance_km: float,
) -> tuple[float, float] | None:
    """Return geometry distance using nearby indexed OSRM segments only."""
    if allowed_segments is not None and not allowed_segments:
        return None
    best_distance = float("inf")
    best_along = 0.0
    for path in geometry.paths:
        projected_path = [
            _project(item, route_index.reference_latitude) for item in path
        ]
        for road_start, road_end in zip(
            projected_path,
            projected_path[1:],
            strict=False,
        ):
            road_bbox = (
                min(road_start[0], road_end[0]) - max_distance_km,
                min(road_start[1], road_end[1]) - max_distance_km,
                max(road_start[0], road_end[0]) + max_distance_km,
                max(road_start[1], road_end[1]) + max_distance_km,
            )
            for index in route_index.candidates(road_bbox):
                if allowed_segments is not None and index not in allowed_segments:
                    continue
                segment = route_index.segments[index]
                if not _bboxes_overlap(road_bbox, segment.bbox):
                    continue
                distance, route_fraction = _segment_distance(
                    road_start,
                    road_end,
                    segment.start,
                    segment.end,
                )
                if distance >= best_distance:
                    continue
                segment_length = hypot(
                    segment.end[0] - segment.start[0],
                    segment.end[1] - segment.start[1],
                )
                best_distance = distance
                best_along = (
                    segment.distance_from_start_km
                    + segment_length * route_fraction
                )
    if best_distance == float("inf"):
        return None
    return best_distance, best_along


def _indexed_nearest_route_position(
    point: Coordinate,
    route_index: _RouteSpatialIndex,
    max_distance_km: float,
) -> tuple[float, float] | None:
    """Return the nearest indexed route position within a bounded corridor."""
    projected = _project(point, route_index.reference_latitude)
    bbox = (
        projected[0] - max_distance_km,
        projected[1] - max_distance_km,
        projected[0] + max_distance_km,
        projected[1] + max_distance_km,
    )
    best_distance = float("inf")
    best_along = 0.0
    for index in route_index.candidates(bbox):
        segment = route_index.segments[index]
        distance, fraction = _point_segment_distance(
            projected,
            segment.start,
            segment.end,
        )
        if distance >= best_distance:
            continue
        segment_length = hypot(
            segment.end[0] - segment.start[0],
            segment.end[1] - segment.start[1],
        )
        best_distance = distance
        best_along = segment.distance_from_start_km + segment_length * fraction
    if best_distance > max_distance_km:
        return None
    return best_distance, best_along


def _indexed_geometry_has_route_overlap(
    geometry: RoadGeometry,
    route_index: _RouteSpatialIndex,
    allowed_segments: set[int] | None,
    *,
    max_distance_km: float,
) -> bool:
    """Return whether a section meaningfully follows indexed route segments."""
    if (
        allowed_segments is not None and not allowed_segments
    ) or max_distance_km <= 0:
        return False
    geometry_length = 0.0
    aligned_overlap = 0.0
    for path in geometry.paths:
        projected_path = [
            _project(item, route_index.reference_latitude) for item in path
        ]
        for road_start, road_end in zip(
            projected_path,
            projected_path[1:],
            strict=False,
        ):
            segment_length = hypot(
                road_end[0] - road_start[0],
                road_end[1] - road_start[1],
            )
            geometry_length += segment_length
            sample_count = max(
                1,
                int(segment_length / ROAD_ROUTE_OVERLAP_SAMPLE_KM) + 1,
            )
            sample_length = segment_length / sample_count
            for index in range(sample_count):
                fraction = (index + 0.5) / sample_count
                sample = (
                    road_start[0] + (road_end[0] - road_start[0]) * fraction,
                    road_start[1] + (road_end[1] - road_start[1]) * fraction,
                )
                sample_bbox = (
                    sample[0] - max_distance_km,
                    sample[1] - max_distance_km,
                    sample[0] + max_distance_km,
                    sample[1] + max_distance_km,
                )
                if _sample_follows_indexed_route(
                    sample,
                    road_start,
                    road_end,
                    route_index,
                    route_index.candidates(sample_bbox),
                    allowed_segments,
                    max_distance_km,
                ):
                    aligned_overlap += sample_length
    required_overlap = min(
        ROAD_ROUTE_MIN_OVERLAP_KM,
        geometry_length * 0.5,
    )
    return required_overlap > 0 and aligned_overlap >= required_overlap


def _sample_follows_indexed_route(
    sample: tuple[float, float],
    road_start: tuple[float, float],
    road_end: tuple[float, float],
    route_index: _RouteSpatialIndex,
    candidates: set[int],
    allowed_segments: set[int] | None,
    max_distance_km: float,
) -> bool:
    """Return whether a road sample follows one nearby allowed route segment."""
    for index in candidates:
        if allowed_segments is not None and index not in allowed_segments:
            continue
        segment = route_index.segments[index]
        distance, _ = _point_segment_distance(sample, segment.start, segment.end)
        if distance > max_distance_km:
            continue
        if (
            _segment_angle_degrees(
                road_start,
                road_end,
                segment.start,
                segment.end,
            )
            <= ROAD_ROUTE_MAX_ANGLE_DEGREES
        ):
            return True
    return False


def _segment_angle_degrees(
    first_start: tuple[float, float],
    first_end: tuple[float, float],
    second_start: tuple[float, float],
    second_end: tuple[float, float],
) -> float:
    """Return the unsigned angle between two line segments in degrees."""
    first_dx = first_end[0] - first_start[0]
    first_dy = first_end[1] - first_start[1]
    second_dx = second_end[0] - second_start[0]
    second_dy = second_end[1] - second_start[1]
    first_length = hypot(first_dx, first_dy)
    second_length = hypot(second_dx, second_dy)
    if first_length == 0 or second_length == 0:
        return 90.0
    cosine = abs(
        (first_dx * second_dx + first_dy * second_dy)
        / (first_length * second_length)
    )
    cosine = max(-1.0, min(1.0, cosine))
    return degrees(acos(cosine))


def _road_identity_names_match(first: str, second: str) -> bool:
    """Return whether two road labels identify the same named road."""
    return _normalized_road_names_match(
        _normalize_road_name(first),
        _normalize_road_name(second),
    )


def _normalize_road_name(value: str) -> str:
    """Return a comparison key for one road name."""
    return " ".join(re.findall(r"\w+", value.casefold()))


def _normalized_road_names_match(first_key: str, second_key: str) -> bool:
    """Return whether two normalized keys identify the same named road."""
    if not first_key or not second_key:
        return False
    return (
        first_key == second_key
        or first_key.startswith(second_key + " ")
        or second_key.startswith(first_key + " ")
    )


def _match_weather_stations(
    stations: Iterable[WeatherStation],
    route_index: _RouteSpatialIndex,
    road_condition_ids: set[str],
    corridor_km: float,
) -> list[RouteMatch]:
    matches: list[RouteMatch] = []
    for station in stations:
        position = None
        if station.latitude is not None and station.longitude is not None:
            position = _indexed_nearest_route_position(
                Coordinate(station.latitude, station.longitude),
                route_index,
                corridor_km,
            )
        linked = bool(road_condition_ids.intersection(station.road_condition_ids))
        if not linked and (position is None or position[0] > corridor_km):
            continue
        station_data = station.as_dict() | {
            "wind_speed": station.wind.speed,
            "wind_gust": station.wind.gust,
            "wind_direction": station.wind_direction.degrees,
        }
        matches.append(
            RouteMatch(
                item_id=str(station.station_id),
                name=station.name,
                distance_from_start_km=position[1] if position else None,
                distance_to_route_km=position[0] if position else None,
                data=station_data,
            )
        )
    matches.sort(key=_match_sort_key)
    return matches


def _match_points(
    items: Iterable[Any],
    route_index: _RouteSpatialIndex,
    corridor_km: float,
    *,
    id_fn: Any,
    name_fn: Any,
    latitude_fn: Any,
    longitude_fn: Any,
    data_fn: Any,
) -> list[RouteMatch]:
    matches: list[RouteMatch] = []
    for item in items:
        latitude = _optional_float(latitude_fn(item))
        longitude = _optional_float(longitude_fn(item))
        if latitude is None or longitude is None:
            continue
        position = _indexed_nearest_route_position(
            Coordinate(latitude, longitude),
            route_index,
            corridor_km,
        )
        if position is None or position[0] > corridor_km:
            continue
        matches.append(
            RouteMatch(
                item_id=str(id_fn(item)),
                name=str(name_fn(item)),
                distance_from_start_km=position[1],
                distance_to_route_km=position[0],
                data=data_fn(item),
            )
        )
    matches.sort(key=_match_sort_key)
    return matches


def _match_notices(
    notices: Iterable[RoadNotice],
    route: OsrmRoute,
) -> list[RoadNotice]:
    """Return global notices and notices naming a driven OSRM road."""
    important_keys = {key.casefold() for key in IMPORTANT_NOTICE_KEYS}
    route_terms: set[str] = set()
    for name in route.road_names:
        route_terms.update(_notice_route_terms(name))

    matched: list[RoadNotice] = []
    for notice in notices:
        key = (notice.key or "").casefold()
        text = f"{notice.sub_category or ''} {notice.text or ''}".casefold()
        if key in important_keys or any(
            _road_name_in_notice(term, text) for term in route_terms
        ):
            matched.append(notice)
    return sorted(
        matched,
        key=lambda notice: notice.date.timestamp() if notice.date else 0,
        reverse=True,
    )


_GENERIC_NOTICE_ROUTE_TERMS = {
    "allur",
    "austan",
    "east",
    "frá",
    "from",
    "hringvegur",
    "norðan",
    "north",
    "og",
    "ring road",
    "road",
    "route",
    "sunnan",
    "south",
    "the",
    "til",
    "to",
    "um",
    "unnamed",
    "vegur",
    "vestan",
    "west",
}


def _notice_route_terms(value: str) -> set[str]:
    """Return a complete, specific road name suitable for notice matching."""
    normalized = value.casefold().strip()
    if len(normalized) < 5 or normalized in _GENERIC_NOTICE_ROUTE_TERMS:
        return set()
    return {normalized}


def _route_status(
    roads: Sequence[RouteMatch],
    notices: Sequence[RoadNotice],
) -> str:
    if any(match.data.get("is_closed") for match in roads):
        return "closed"
    descriptions = [
        " ".join(
            str(value or "")
            for value in (
                match.data.get("condition", {}).get("code"),
                match.data.get("condition", {}).get("category"),
                match.data.get("condition", {}).get("description"),
            )
        ).casefold()
        for match in roads
    ]
    if any(any(token in text for token in _CLOSED_TOKENS) for text in descriptions):
        return "closed"
    if any(any(token in text for token in _DIFFICULT_TOKENS) for text in descriptions):
        return "difficult"
    if (
        any(
            match.data.get("has_roadwork") or match.data.get("has_weight_restriction")
            for match in roads
        )
        or notices
    ):
        return "advisory"
    if not roads:
        return "unknown"
    if any(
        text and not any(token in text for token in _GOOD_TOKENS)
        for text in descriptions
    ):
        return "advisory"
    return "clear"


def _road_number_in_text(number: str, text: str) -> bool:
    if not number or not text:
        return False
    padded = f" {text.replace('-', ' ')} "
    return f" {number} " in padded or f"road {number}" in padded


def _geometry_paths(geometry: Mapping[str, Any]) -> list[tuple[Coordinate, ...]]:
    raw_coordinates = geometry.get("coordinates")
    if not _is_sequence(raw_coordinates):
        return []
    if geometry.get("type") == "LineString":
        path = tuple(
            coordinate
            for item in raw_coordinates
            if (coordinate := _coordinate_from_geojson(item)) is not None
        )
        return [path]
    if geometry.get("type") == "MultiLineString":
        return [
            tuple(
                coordinate
                for item in path
                if (coordinate := _coordinate_from_geojson(item)) is not None
            )
            for path in raw_coordinates
            if _is_sequence(path)
        ]
    return []


def _condition_id_from_geometry(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    if not text or not text.isdigit():
        return None
    return text[:-4] if len(text) > 4 else text


def _coordinate_from_geojson(value: Any) -> Coordinate | None:
    if not _is_sequence(value) or len(value) < 2:
        return None
    longitude = _optional_float(value[0])
    latitude = _optional_float(value[1])
    if latitude is None or longitude is None:
        return None
    return Coordinate(latitude=latitude, longitude=longitude)


def _coordinate_bbox(
    coordinates: Sequence[Coordinate],
) -> tuple[float, float, float, float]:
    return (
        min(item.longitude for item in coordinates),
        min(item.latitude for item in coordinates),
        max(item.longitude for item in coordinates),
        max(item.latitude for item in coordinates),
    )


def _expanded_bbox(
    coordinates: Sequence[Coordinate],
    distance_km: float,
) -> tuple[float, float, float, float]:
    west, south, east, north = _coordinate_bbox(coordinates)
    latitude_delta = distance_km / 111.0
    longitude_scale = max(0.1, cos(radians((south + north) / 2)))
    longitude_delta = distance_km / (111.0 * longitude_scale)
    return (
        west - longitude_delta,
        south - latitude_delta,
        east + longitude_delta,
        north + latitude_delta,
    )


def _bboxes_overlap(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> bool:
    return not (
        left[2] < right[0]
        or right[2] < left[0]
        or left[3] < right[1]
        or right[3] < left[1]
    )


def _project(coordinate: Coordinate, latitude_origin: float) -> tuple[float, float]:
    return (
        EARTH_RADIUS_KM * radians(coordinate.longitude) * cos(latitude_origin),
        EARTH_RADIUS_KM * radians(coordinate.latitude),
    )


def _point_segment_distance(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> tuple[float, float]:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length_squared = dx * dx + dy * dy
    if length_squared == 0:
        return hypot(point[0] - start[0], point[1] - start[1]), 0.0
    fraction = max(
        0.0,
        min(
            1.0,
            ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_squared,
        ),
    )
    closest = (start[0] + fraction * dx, start[1] + fraction * dy)
    return hypot(point[0] - closest[0], point[1] - closest[1]), fraction


def _segment_distance(
    first_start: tuple[float, float],
    first_end: tuple[float, float],
    route_start: tuple[float, float],
    route_end: tuple[float, float],
) -> tuple[float, float]:
    if _segments_intersect(first_start, first_end, route_start, route_end):
        return 0.0, _intersection_fraction(
            first_start,
            first_end,
            route_start,
            route_end,
        )
    candidates = [
        _point_segment_distance(first_start, route_start, route_end),
        _point_segment_distance(first_end, route_start, route_end),
    ]
    distance, route_fraction = min(candidates, key=lambda item: item[0])
    first_distance_a, _ = _point_segment_distance(
        route_start,
        first_start,
        first_end,
    )
    first_distance_b, _ = _point_segment_distance(
        route_end,
        first_start,
        first_end,
    )
    if first_distance_a < distance:
        return first_distance_a, 0.0
    if first_distance_b < distance:
        return first_distance_b, 1.0
    return distance, route_fraction


def _segments_intersect(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
    d: tuple[float, float],
) -> bool:
    def orientation(
        first: tuple[float, float],
        second: tuple[float, float],
        third: tuple[float, float],
    ) -> float:
        return (second[0] - first[0]) * (third[1] - first[1]) - (
            second[1] - first[1]
        ) * (third[0] - first[0])

    def on_segment(
        first: tuple[float, float],
        second: tuple[float, float],
        point: tuple[float, float],
    ) -> bool:
        epsilon = 1e-12
        return (
            min(first[0], second[0]) - epsilon
            <= point[0]
            <= max(first[0], second[0]) + epsilon
            and min(first[1], second[1]) - epsilon
            <= point[1]
            <= max(first[1], second[1]) + epsilon
        )

    epsilon = 1e-12
    first = orientation(a, b, c)
    second = orientation(a, b, d)
    third = orientation(c, d, a)
    fourth = orientation(c, d, b)
    if (first > epsilon and second < -epsilon) or (
        first < -epsilon and second > epsilon
    ):
        return (third > epsilon and fourth < -epsilon) or (
            third < -epsilon and fourth > epsilon
        )
    return (
        (abs(first) <= epsilon and on_segment(a, b, c))
        or (abs(second) <= epsilon and on_segment(a, b, d))
        or (abs(third) <= epsilon and on_segment(c, d, a))
        or (abs(fourth) <= epsilon and on_segment(c, d, b))
    )


def _intersection_fraction(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
    d: tuple[float, float],
) -> float:
    denominator = (b[0] - a[0]) * (d[1] - c[1]) - (b[1] - a[1]) * (d[0] - c[0])
    if abs(denominator) < 1e-12:
        return 0.0
    numerator = (c[0] - a[0]) * (d[1] - c[1]) - (c[1] - a[1]) * (d[0] - c[0])
    first_fraction = numerator / denominator
    intersection_x = a[0] + first_fraction * (b[0] - a[0])
    intersection_y = a[1] + first_fraction * (b[1] - a[1])
    _, route_fraction = _point_segment_distance(
        (intersection_x, intersection_y),
        c,
        d,
    )
    return route_fraction


def _match_sort_key(match: RouteMatch) -> tuple[float, str]:
    return (
        match.distance_from_start_km
        if match.distance_from_start_km is not None
        else float("inf"),
        match.name.casefold(),
    )


def _segment_summary(
    road: RouteMatch,
    weather_stations: Sequence[RouteMatch],
    language: str,
) -> dict[str, Any]:
    """Build one compact route table row."""
    station = _nearest_segment_weather(road, weather_stations)
    temperature = None
    temperature_type = None
    if station is not None:
        temperature = _optional_float(station.data.get("road_temperature"))
        temperature_type = "road"
        if temperature is None:
            temperature = _optional_float(station.data.get("temperature"))
            temperature_type = "air" if temperature is not None else None

    condition = road.data.get("condition")
    condition_description = (
        _optional_str(condition.get("description"))
        if isinstance(condition, Mapping)
        else None
    )
    severity = _road_severity(road.data)
    alerts: list[str] = []
    icelandic = _is_icelandic(language)
    if road.data.get("is_closed"):
        _append_unique(alerts, "Lokað" if icelandic else "Closed")
    restriction = road.data.get("weight_restriction")
    if isinstance(restriction, Mapping):
        _append_unique(
            alerts,
            _optional_str(restriction.get("description"))
            or ("Þungatakmörkun" if icelandic else "Weight restriction"),
        )

    for marker in _mapping_items(road.data.get("condition_markers")):
        _append_unique(
            alerts,
            _optional_str(marker.get("description"))
            or _optional_str(marker.get("code")),
        )
    for marker in _mapping_items(road.data.get("other_markers")):
        title = _optional_str(marker.get("title"))
        description = _optional_str(marker.get("description"))
        if title and description and description.casefold() != title.casefold():
            _append_unique(alerts, f"{title}: {description}")
        else:
            _append_unique(
                alerts,
                description or title or _optional_str(marker.get("code")),
            )

    return {
        "id": road.item_id,
        "url": f"https://umferdin.is/kafli/{road.item_id}",
        "distance_km": _rounded(road.distance_from_start_km),
        "name": road.name,
        "condition": condition_description or ("Óþekkt" if icelandic else "Unknown"),
        "severity": severity,
        "has_issue": severity != "normal",
        "temperature": round(temperature, 1) if temperature is not None else None,
        "temperature_type": temperature_type,
        "weather_station": station.name if station else None,
        "closed": bool(road.data.get("is_closed")),
        "alert": " · ".join(alerts) if alerts else None,
    }


def _road_severity(data: Mapping[str, Any]) -> str:
    """Return a stable route-row severity independent of display language."""
    condition = data.get("condition")
    condition_text = " ".join(
        str(value or "")
        for value in (
            condition.get("code") if isinstance(condition, Mapping) else None,
            condition.get("category") if isinstance(condition, Mapping) else None,
            condition.get("description") if isinstance(condition, Mapping) else None,
        )
    ).casefold()
    if data.get("is_closed") or any(
        token in condition_text for token in _CLOSED_TOKENS
    ):
        return "closed"
    if (
        data.get("has_roadwork")
        or data.get("has_weight_restriction")
        or data.get("weight_restriction")
        or _mapping_items(data.get("condition_markers"))
        or _mapping_items(data.get("other_markers"))
    ):
        return "warning"
    if any(token in condition_text for token in _DIFFICULT_TOKENS):
        return "caution"
    if any(token in condition_text for token in _GOOD_TOKENS):
        return "normal"
    return "unknown" if not condition_text.strip() else "caution"


def _road_geometry_summary(
    road: RouteMatch,
    geometry: RoadGeometry,
    segment: Mapping[str, Any],
) -> dict[str, Any]:
    """Return GeoJSON for one matched official road-condition section."""
    return {
        "id": road.item_id,
        "name": road.name,
        "severity": segment["severity"],
        "condition": segment["condition"],
        "alert": segment["alert"],
        "url": segment["url"],
        "geometry": {
            "type": "MultiLineString",
            "coordinates": [
                [
                    [coordinate.longitude, coordinate.latitude]
                    for coordinate in path
                ]
                for path in geometry.paths
            ],
        },
    }


def _is_icelandic(language: str) -> bool:
    """Return whether content should use Icelandic labels."""
    return language.casefold().startswith("is")


def _select_route_camera_summaries(
    cameras: Sequence[RouteMatch],
    issue_geometries: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Sample physical camera sites across a route and expand alert-near sites."""
    groups: dict[str, list[RouteMatch]] = defaultdict(list)
    for camera in cameras:
        if camera.data.get("image_url"):
            groups[_camera_site_key(camera)].append(camera)
    sites = sorted(
        groups.items(),
        key=lambda item: _camera_distance(item[1][0]),
    )
    if not sites:
        return []

    target_sites = min(ROUTE_CAMERA_MAX_SITES, len(sites))
    issue_distances = {
        site_key: _camera_issue_distance_km(site_cameras[0], issue_geometries)
        for site_key, site_cameras in sites
    }
    priority_keys = {
        site_key
        for site_key, distance in sorted(
            issue_distances.items(),
            key=lambda item: item[1] if item[1] is not None else float("inf"),
        )[:target_sites]
        if distance is not None and distance <= ROUTE_CAMERA_ALERT_RADIUS_KM
    }
    selected_keys = set(priority_keys)
    remaining = [site for site in sites if site[0] not in selected_keys]
    slots = max(0, target_sites - len(selected_keys))
    for index in _even_sample_indices(len(remaining), slots):
        selected_keys.add(remaining[index][0])

    selected: dict[str, tuple[RouteMatch, bool, int]] = {}
    for site_key, site_cameras in sites:
        if site_key not in selected_keys:
            continue
        representative = min(site_cameras, key=_camera_representative_key)
        selected[representative.item_id] = (
            representative,
            site_key in priority_keys,
            len(site_cameras),
        )

    for site_key, site_cameras in sites:
        if site_key not in priority_keys:
            continue
        for camera in site_cameras:
            if len(selected) >= ROUTE_CAMERA_MAX_IMAGES:
                break
            selected[camera.item_id] = (camera, True, len(site_cameras))

    return [
        _camera_summary(camera, priority=priority, view_count=view_count)
        for camera, priority, view_count in sorted(
            selected.values(),
            key=lambda item: (
                _camera_distance(item[0]),
                item[0].item_id,
            ),
        )
    ]


def _camera_issue_distance_km(
    camera: RouteMatch,
    issue_geometries: Sequence[Mapping[str, Any]],
) -> float | None:
    """Return geographic distance from a camera to affected road geometry."""
    latitude = _optional_float(camera.data.get("latitude"))
    longitude = _optional_float(camera.data.get("longitude"))
    if latitude is None or longitude is None:
        return None
    point = Coordinate(latitude, longitude)
    best_distance: float | None = None
    for item in issue_geometries:
        geometry = item.get("geometry")
        if not isinstance(geometry, Mapping):
            continue
        for path in _geometry_paths(geometry):
            position = nearest_route_position(point, path)
            if position is not None and (
                best_distance is None or position[0] < best_distance
            ):
                best_distance = position[0]
    return best_distance


def _even_sample_indices(item_count: int, sample_count: int) -> list[int]:
    """Return evenly distributed indices including both ends when possible."""
    if item_count <= 0 or sample_count <= 0:
        return []
    if sample_count >= item_count:
        return list(range(item_count))
    if sample_count == 1:
        return [item_count // 2]
    return [
        round(index * (item_count - 1) / (sample_count - 1))
        for index in range(sample_count)
    ]


def _camera_site_key(camera: RouteMatch) -> str:
    """Return the physical camera site ID for an image."""
    site_id = camera.data.get("id")
    return str(site_id if site_id is not None else camera.item_id)


def _camera_distance(camera: RouteMatch) -> float:
    """Return a sortable route distance."""
    return camera.distance_from_start_km or 0.0


def _camera_representative_key(camera: RouteMatch) -> tuple[bool, str]:
    """Prefer a view looking down at the road."""
    description = str(camera.data.get("description") or "").casefold()
    road_facing = any(
        token in description
        for token in ("niður á veg", "down at road", "road surface", "road view")
    )
    return (not road_facing, description)


def _camera_summary(
    camera: RouteMatch,
    *,
    priority: bool,
    view_count: int,
) -> dict[str, Any]:
    """Return a compact route-camera dictionary for entity attributes."""
    return {
        "camera_site_id": _camera_site_key(camera),
        "image_id": camera.item_id,
        "distance_km": _rounded(camera.distance_from_start_km),
        "name": camera.name,
        "description": camera.data.get("description"),
        "road_name": camera.data.get("road_name"),
        "road_number": camera.data.get("road_number"),
        "image_url": camera.data.get("image_url"),
        "near_alert": priority,
        "site_view_count": view_count,
    }


def _nearest_segment_weather(
    road: RouteMatch,
    weather_stations: Sequence[RouteMatch],
) -> RouteMatch | None:
    """Return the most relevant route weather station for a road segment."""
    candidates = [
        station
        for station in weather_stations
        if station.distance_from_start_km is not None
        and (
            _optional_float(station.data.get("road_temperature")) is not None
            or _optional_float(station.data.get("temperature")) is not None
        )
    ]
    linked = [
        station
        for station in candidates
        if road.item_id
        in {str(item) for item in station.data.get("road_condition_ids", [])}
    ]
    if linked:
        candidates = linked
    if not candidates:
        return None
    road_position = road.distance_from_start_km or 0.0
    return min(
        candidates,
        key=lambda station: abs(
            (station.distance_from_start_km or 0.0) - road_position
        ),
    )


def _road_name_in_notice(name: str, text: str) -> bool:
    """Match a complete road name rather than a substring of another road."""
    return re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text) is not None


def _road_number_in_notice(number: str, text: str) -> bool:
    """Match explicit notice road-number forms without matching dates."""
    normalized = text.replace("-", " ")
    return f"road {number}" in normalized or f"({number})" in normalized


def _numeric_extreme(values: Iterable[Any], *, maximum: bool) -> float | None:
    numbers: list[float] = []
    for value in values:
        number = _optional_float(value)
        if number is not None:
            numbers.append(number)
    if not numbers:
        return None
    return max(numbers) if maximum else min(numbers)


def _rounded(value: float | None) -> float | None:
    return round(value, 2) if value is not None else None


def _mapping_items(value: Any) -> list[Mapping[str, Any]]:
    if not _is_sequence(value):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _is_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes))


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _append_unique(values: list[str], value: str | None) -> None:
    if value and value not in values:
        values.append(value)
