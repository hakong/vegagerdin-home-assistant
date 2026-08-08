"""Routing API, geometry matching, and route response models."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from math import cos, hypot, radians
import re
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
    IMPORTANT_NOTICE_KEYS,
    SOURCE_OSRM,
    SOURCE_ROAD_GEOMETRY_WFS,
)

ROAD_GEOMETRY_WFS_URL = "https://gagnaveita.vegagerdin.is/geoserver/gis/ows"
ROAD_GEOMETRY_TYPENAME = "gis:faerdferlar2017_1"
ROUTING_TIMEOUT_SECONDS = 30
EARTH_RADIUS_KM = 6371.0088

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
class OsrmRoute:
    """A route returned by OSRM."""

    distance_km: float
    duration_minutes: float
    coordinates: tuple[Coordinate, ...]
    road_names: tuple[str, ...]
    road_numbers: tuple[str, ...]
    source: str = SOURCE_OSRM

    def as_dict(self, *, include_geometry: bool = True) -> dict[str, Any]:
        """Return a JSON-serializable route dictionary."""
        result: dict[str, Any] = {
            "distance_km": round(self.distance_km, 2),
            "duration_minutes": round(self.duration_minutes, 1),
            "road_names": list(self.road_names),
            "road_numbers": list(self.road_numbers),
            "source": self.source,
        }
        if include_geometry:
            result["geometry"] = {
                "type": "LineString",
                "coordinates": [
                    [coordinate.longitude, coordinate.latitude]
                    for coordinate in self.coordinates
                ],
            }
        return result


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

    @property
    def route_name(self) -> str:
        """Return a human-friendly route name."""
        return f"{self.origin_name} to {self.destination_name}"

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
            _segment_summary(road, self.weather_stations, self.notices)
            for road in self.roads
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
            "weather_stations": [
                match.as_dict() for match in self.weather_stations
            ],
            "cameras": [match.as_dict() for match in self.cameras],
            "traffic_counters": [
                match.as_dict() for match in self.traffic_counters
            ],
            "notices": [notice.as_dict() for notice in self.notices],
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
                ("overview", "full"),
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
    for leg in _mapping_items(route.get("legs")):
        for step in _mapping_items(leg.get("steps")):
            _append_unique(names, _optional_str(step.get("name")))
            reference = _optional_str(step.get("ref"))
            if reference:
                for item in reference.replace(";", ",").split(","):
                    _append_unique(numbers, item.strip() or None)

    return OsrmRoute(
        distance_km=float(route.get("distance") or 0) / 1000,
        duration_minutes=float(route.get("duration") or 0) / 60,
        coordinates=coordinates,
        road_names=tuple(names),
        road_numbers=tuple(numbers),
    )


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
            properties.get("STADARLYSING")
            or properties.get("STUTTNAFNLEIDAR")
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
) -> RouteDetails:
    """Match Vegagerdin records to a route and build a response model."""
    route_bbox = _expanded_bbox(route.coordinates, road_corridor_km)
    road_matches: list[RouteMatch] = []
    for road in roads.values():
        geometry = road_geometries.get(road.road_condition_id)
        match_result: tuple[float, float] | None = None
        if geometry is not None and _bboxes_overlap(route_bbox, geometry.bbox):
            match_result = _geometry_route_distance(geometry, route.coordinates)
        elif road.latitude is not None and road.longitude is not None:
            match_result = nearest_route_position(
                Coordinate(road.latitude, road.longitude),
                route.coordinates,
            )
        if match_result is None or match_result[0] > road_corridor_km:
            continue
        distance_to_route, distance_from_start = match_result
        road_data = road.as_dict() | {
            "is_closed": road.is_closed,
            "has_roadwork": road.has_roadwork,
            "has_weight_restriction": road.has_weight_restriction,
        }
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
        route.coordinates,
        matched_road_ids,
        point_corridor_km,
    )
    camera_matches = _match_points(
        cameras,
        route.coordinates,
        point_corridor_km,
        id_fn=lambda camera: camera.image_id,
        name_fn=lambda camera: camera.name,
        latitude_fn=lambda camera: camera.latitude,
        longitude_fn=lambda camera: camera.longitude,
        data_fn=lambda camera: camera.as_dict(),
    )
    counter_matches = _match_points(
        traffic_counters,
        route.coordinates,
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
        road_matches,
    )
    status = _route_status(road_matches, matched_notices)
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
    )


def nearest_route_position(
    point: Coordinate,
    route: Sequence[Coordinate],
) -> tuple[float, float] | None:
    """Return distance to route and distance from its start in kilometers."""
    if len(route) < 2:
        return None
    latitude_origin = radians(point.latitude)
    projected_route = [
        _project(coordinate, latitude_origin) for coordinate in route
    ]
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


def _geometry_route_distance(
    geometry: RoadGeometry,
    route: Sequence[Coordinate],
) -> tuple[float, float] | None:
    """Return minimum geometry distance and position along the route."""
    if len(route) < 2:
        return None
    reference_latitude = radians(
        sum(coordinate.latitude for coordinate in route) / len(route)
    )
    projected_route = [_project(item, reference_latitude) for item in route]
    route_segments = list(zip(projected_route, projected_route[1:], strict=False))
    route_starts: list[float] = []
    traversed = 0.0
    for start, end in route_segments:
        route_starts.append(traversed)
        traversed += hypot(end[0] - start[0], end[1] - start[1])

    best_distance = float("inf")
    best_along = 0.0
    for path in geometry.paths:
        projected_path = [_project(item, reference_latitude) for item in path]
        for road_start, road_end in zip(
            projected_path,
            projected_path[1:],
            strict=False,
        ):
            for index, (route_start, route_end) in enumerate(route_segments):
                distance, route_fraction = _segment_distance(
                    road_start,
                    road_end,
                    route_start,
                    route_end,
                )
                if distance >= best_distance:
                    continue
                segment_length = hypot(
                    route_end[0] - route_start[0],
                    route_end[1] - route_start[1],
                )
                best_distance = distance
                best_along = route_starts[index] + segment_length * route_fraction
    if best_distance == float("inf"):
        return None
    return best_distance, best_along


def _match_weather_stations(
    stations: Iterable[WeatherStation],
    route: Sequence[Coordinate],
    road_condition_ids: set[str],
    corridor_km: float,
) -> list[RouteMatch]:
    matches: list[RouteMatch] = []
    for station in stations:
        position = None
        if station.latitude is not None and station.longitude is not None:
            position = nearest_route_position(
                Coordinate(station.latitude, station.longitude),
                route,
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
    route: Sequence[Coordinate],
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
        position = nearest_route_position(Coordinate(latitude, longitude), route)
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
    roads: Sequence[RouteMatch],
) -> list[RoadNotice]:
    important_keys = {key.casefold() for key in IMPORTANT_NOTICE_KEYS}
    road_numbers = {
        str(number).casefold()
        for number in route.road_numbers
        if str(number).strip()
    }
    for road in roads:
        road_numbers.update(
            str(number).casefold()
            for number in road.data.get("road_numbers", [])
        )
    road_names = {
        str(name).casefold()
        for name in route.road_names
        if len(str(name).strip()) >= 4
    }
    for road in roads:
        road_names.add(road.name.casefold())
        road_names.update(
            str(name).casefold()
            for name in road.data.get("road_names", [])
            if len(str(name).strip()) >= 4
        )
    matched: list[RoadNotice] = []
    for notice in notices:
        key = (notice.key or "").casefold()
        text = (notice.text or "").casefold()
        if (
            key in important_keys
            or any(_road_number_in_text(number, text) for number in road_numbers)
            or any(name in text for name in road_names)
        ):
            matched.append(notice)
    return sorted(
        matched,
        key=lambda notice: notice.date.timestamp() if notice.date else 0,
        reverse=True,
    )


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
    if any(
        match.data.get("has_roadwork")
        or match.data.get("has_weight_restriction")
        for match in roads
    ) or notices:
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
            ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy)
            / length_squared,
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
    denominator = (b[0] - a[0]) * (d[1] - c[1]) - (b[1] - a[1]) * (
        d[0] - c[0]
    )
    if abs(denominator) < 1e-12:
        return 0.0
    numerator = (c[0] - a[0]) * (d[1] - c[1]) - (c[1] - a[1]) * (
        d[0] - c[0]
    )
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
    notices: Sequence[RoadNotice],
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
    alerts: list[str] = []
    if road.data.get("is_closed"):
        _append_unique(alerts, "Closed")
    if road.data.get("has_roadwork"):
        _append_unique(alerts, "Roadwork")

    restriction = road.data.get("weight_restriction")
    if isinstance(restriction, Mapping):
        _append_unique(
            alerts,
            _optional_str(restriction.get("description")) or "Weight restriction",
        )

    for marker in _mapping_items(road.data.get("condition_markers")):
        _append_unique(
            alerts,
            _optional_str(marker.get("description"))
            or _optional_str(marker.get("code")),
        )
    for marker in _mapping_items(road.data.get("other_markers")):
        title = _optional_str(marker.get("title"))
        title_text = (title or "").casefold()
        if road.data.get("has_roadwork") and any(
            token in title_text
            for token in ("roadwork", "road work", "road repair", "vegavinna")
        ):
            continue
        _append_unique(alerts, title)

    for notice in _segment_notices(road, notices):
        notice_text = f"{notice.sub_category or ''} {notice.text or ''}".casefold()
        if any(token in notice_text for token in _CLOSED_TOKENS):
            _append_unique(alerts, "Closure notice")
        elif "work" in notice_text or "vinna" in notice_text:
            _append_unique(alerts, "Roadwork notice")
        else:
            _append_unique(alerts, "Road notice")

    return {
        "distance_km": _rounded(road.distance_from_start_km),
        "name": road.name,
        "condition": condition_description or "Unknown",
        "temperature": round(temperature, 1) if temperature is not None else None,
        "temperature_type": temperature_type,
        "weather_station": station.name if station else None,
        "closed": bool(road.data.get("is_closed")),
        "alert": " · ".join(alerts) if alerts else None,
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


def _segment_notices(
    road: RouteMatch,
    notices: Sequence[RoadNotice],
) -> list[RoadNotice]:
    """Return notices that name this road segment or one of its roads."""
    names = {
        str(name).casefold()
        for name in (road.name, *road.data.get("road_names", []))
        if len(str(name).strip()) >= 4
    }
    numbers = {
        str(number).casefold()
        for number in road.data.get("road_numbers", [])
        if str(number).strip()
    }
    matched: list[RoadNotice] = []
    for notice in notices:
        text = f"{notice.sub_category or ''} {notice.text or ''}".casefold()
        if any(_road_name_in_notice(name, text) for name in names) or any(
            _road_number_in_notice(number, text) for number in numbers
        ):
            matched.append(notice)
    return matched


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
