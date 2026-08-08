"""Client and parsers for Vegagerdin public data sources."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
import logging
from pathlib import PurePosixPath
from typing import Any

from .const import SOURCE_GRAPHQL, SOURCE_TRAFFIC_WFS, SOURCE_WEBCAM_REST

GRAPHQL_URL = "https://umferdin.is/graphql"
WEBCAM_REST_URL = "https://gagnaveita.vegagerdin.is/api/vefmyndavelar2014_1"
TRAFFIC_WFS_URL = "https://gagnaveita.vegagerdin.is/geoserver/gis/ows"
REQUEST_TIMEOUT_SECONDS = 15
TRAFFIC_COUNTER_TYPENAME = "gis:umferdvika_2021_1"

_LOGGER = logging.getLogger(__name__)
_ROADWORK_TOKENS = ("work", "repair", "framkvæmd", "framkvaemd")


class VegagerdinApiError(Exception):
    """Base exception for Vegagerdin API errors."""


class CannotConnect(VegagerdinApiError):
    """Raised when a data source cannot be reached."""


class InvalidResponse(VegagerdinApiError):
    """Raised when a data source response is not usable."""


@dataclass(frozen=True, slots=True)
class RoadConditionValue:
    """Current road condition value."""

    code: str | None
    category: str | None
    description: str | None
    date: datetime | None

    @classmethod
    def from_api(cls, data: Mapping[str, Any] | None) -> "RoadConditionValue":
        """Build condition data from GraphQL."""
        if not isinstance(data, Mapping):
            return cls(code=None, category=None, description=None, date=None)
        return cls(
            code=_optional_str(data.get("code")),
            category=_optional_str(data.get("category")),
            description=_optional_str(data.get("description")),
            date=_parse_datetime(data.get("date")),
        )

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary."""
        return {
            "code": self.code,
            "category": self.category,
            "description": self.description,
            "date": self.date.isoformat() if self.date else None,
        }


@dataclass(frozen=True, slots=True)
class RoadMarker:
    """Road condition marker."""

    code: str | None
    description: str | None
    last_update: datetime | None

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> "RoadMarker":
        """Build a marker from GraphQL."""
        return cls(
            code=_optional_str(data.get("code")),
            description=_optional_str(data.get("description")),
            last_update=_parse_datetime(data.get("lastUpdate")),
        )

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary."""
        return {
            "code": self.code,
            "description": self.description,
            "last_update": self.last_update.isoformat()
            if self.last_update
            else None,
        }


@dataclass(frozen=True, slots=True)
class RoadOtherMarker:
    """Point marker for closures, roadworks, or other road events."""

    marker_id: str | None
    title: str | None
    description: str | None
    code: str | None
    date_from: datetime | None
    date_to: datetime | None
    last_update: datetime | None
    latitude: float | None
    longitude: float | None

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> "RoadOtherMarker":
        """Build an event marker from GraphQL."""
        coordinates = data.get("coordinates")
        if not isinstance(coordinates, Mapping):
            coordinates = {}
        return cls(
            marker_id=_optional_str(data.get("id")),
            title=_optional_str(data.get("title")),
            description=_optional_str(data.get("description")),
            code=_optional_str(data.get("code")),
            date_from=_parse_datetime(data.get("dateFrom")),
            date_to=_parse_datetime(data.get("dateTo")),
            last_update=_parse_datetime(data.get("lastUpdate")),
            latitude=_optional_float(coordinates.get("lat")),
            longitude=_optional_float(coordinates.get("lon")),
        )

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary."""
        return {
            "id": self.marker_id,
            "title": self.title,
            "description": self.description,
            "code": self.code,
            "date_from": self.date_from.isoformat() if self.date_from else None,
            "date_to": self.date_to.isoformat() if self.date_to else None,
            "last_update": self.last_update.isoformat()
            if self.last_update
            else None,
            "latitude": self.latitude,
            "longitude": self.longitude,
        }


@dataclass(frozen=True, slots=True)
class WeightRestriction:
    """Road weight restriction."""

    limit: float | None
    description: str | None

    @classmethod
    def from_api(cls, data: Mapping[str, Any] | None) -> "WeightRestriction | None":
        """Build a weight restriction from GraphQL."""
        if not isinstance(data, Mapping):
            return None
        limit = _optional_float(data.get("limit"))
        description = _optional_str(data.get("description"))
        if limit is None and description is None:
            return None
        return cls(limit=limit, description=description)

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary."""
        return {"limit": self.limit, "description": self.description}


@dataclass(frozen=True, slots=True)
class RoadCondition:
    """Road condition section."""

    road_condition_id: str
    name: str
    service_category: str | None
    winter_service: str | None
    display: bool | None
    last_update: datetime | None
    condition: RoadConditionValue
    previous_condition: RoadConditionValue
    condition_markers: tuple[RoadMarker, ...] = field(default_factory=tuple)
    other_markers: tuple[RoadOtherMarker, ...] = field(default_factory=tuple)
    weight_restriction: WeightRestriction | None = None
    road_numbers: tuple[str, ...] = field(default_factory=tuple)
    road_names: tuple[str, ...] = field(default_factory=tuple)
    latitude: float | None = None
    longitude: float | None = None
    source: str = SOURCE_GRAPHQL

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> "RoadCondition":
        """Build a road condition from GraphQL."""
        roads = data.get("roads")
        if not isinstance(roads, Sequence) or isinstance(roads, (str, bytes)):
            roads = []
        center = data.get("geometryCenter")
        if not isinstance(center, Mapping):
            center = {}
        return cls(
            road_condition_id=str(data.get("id") or ""),
            name=str(data.get("name") or data.get("id") or ""),
            service_category=_optional_str(data.get("serviceCategory")),
            winter_service=_optional_str(data.get("winterService")),
            display=_optional_bool(data.get("display")),
            last_update=_parse_datetime(data.get("lastUpdate")),
            condition=RoadConditionValue.from_api(data.get("condition")),
            previous_condition=RoadConditionValue.from_api(data.get("conditionPrev")),
            condition_markers=tuple(
                RoadMarker.from_api(marker)
                for marker in _mapping_items(data.get("conditionMarkers"))
            ),
            other_markers=tuple(
                RoadOtherMarker.from_api(marker)
                for marker in _mapping_items(data.get("conditionsOtherMarkers"))
            ),
            weight_restriction=WeightRestriction.from_api(
                data.get("weightRestriction")
            ),
            road_numbers=tuple(
                str(road.get("nr"))
                for road in _mapping_items(roads)
                if road.get("nr") is not None
            ),
            road_names=tuple(
                str(road.get("name"))
                for road in _mapping_items(roads)
                if road.get("name") is not None
            ),
            latitude=_optional_float(center.get("lat")),
            longitude=_optional_float(center.get("lon")),
        )

    @property
    def is_closed(self) -> bool:
        """Return whether this road looks closed or impassable."""
        text = " ".join(
            value
            for value in (
                self.condition.code,
                self.condition.category,
                self.condition.description,
            )
            if value
        ).casefold()
        return any(
            token in text
            for token in ("closed", "impassable", "ófært", "loka", "lokad")
        )

    @property
    def has_roadwork(self) -> bool:
        """Return whether this road has active roadwork-like markers."""
        return bool(self.roadwork_markers)

    @property
    def roadwork_markers(self) -> tuple[RoadOtherMarker, ...]:
        """Return active markers that look like roadwork."""
        return tuple(
            marker
            for marker in self.other_markers
            if _marker_matches(marker, _ROADWORK_TOKENS)
        )

    @property
    def has_weight_restriction(self) -> bool:
        """Return whether this road has a weight restriction."""
        return self.weight_restriction is not None

    def as_dict(self) -> dict[str, Any]:
        """Return a response dictionary."""
        return {
            "id": self.road_condition_id,
            "name": self.name,
            "service_category": self.service_category,
            "winter_service": self.winter_service,
            "display": self.display,
            "last_update": self.last_update.isoformat()
            if self.last_update
            else None,
            "condition": self.condition.as_dict(),
            "previous_condition": self.previous_condition.as_dict(),
            "condition_markers": [
                marker.as_dict() for marker in self.condition_markers
            ],
            "other_markers": [marker.as_dict() for marker in self.other_markers],
            "weight_restriction": self.weight_restriction.as_dict()
            if self.weight_restriction
            else None,
            "road_numbers": list(self.road_numbers),
            "road_names": list(self.road_names),
            "latitude": self.latitude,
            "longitude": self.longitude,
            "source": self.source,
        }


def _marker_matches(marker: RoadOtherMarker, tokens: Iterable[str]) -> bool:
    """Return whether marker text contains any of the given tokens."""
    text = " ".join(
        value for value in (marker.title, marker.description, marker.code) if value
    ).casefold()
    return any(token in text for token in tokens)


def _webcam_image_id(
    camera_id: int,
    image_url: str | None,
    data: Mapping[str, Any],
) -> str:
    """Return a stable image-level webcam id."""
    if image_url:
        stem = PurePosixPath(image_url).stem
        if stem:
            return f"{camera_id}_{stem}"
    description = _optional_str(data.get("Skyring"))
    if description:
        return f"{camera_id}_{_slugish(description)}"
    return str(camera_id)


def _slugish(value: str) -> str:
    """Return a conservative id fragment."""
    return "_".join(value.casefold().split())


@dataclass(frozen=True, slots=True)
class RoadNotice:
    """Road notice / notification."""

    notice_id: str
    category: str | None
    key: str | None
    sub_category: str | None
    text: str | None
    tags: tuple[str, ...]
    date: datetime | None
    source: str = SOURCE_GRAPHQL

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> "RoadNotice":
        """Build a notice from GraphQL."""
        tags = data.get("tags")
        if not isinstance(tags, Sequence) or isinstance(tags, (str, bytes)):
            tags = []
        return cls(
            notice_id=str(data.get("id") or ""),
            category=_optional_str(data.get("category")),
            key=_optional_str(data.get("key")),
            sub_category=_optional_str(data.get("subCategory")),
            text=_optional_str(data.get("text")),
            tags=tuple(str(tag) for tag in tags),
            date=_parse_datetime(data.get("date")),
        )

    def as_dict(self) -> dict[str, Any]:
        """Return a response dictionary."""
        return {
            "id": self.notice_id,
            "category": self.category,
            "key": self.key,
            "sub_category": self.sub_category,
            "text": self.text,
            "tags": list(self.tags),
            "date": self.date.isoformat() if self.date else None,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class Wind:
    """Wind measurement."""

    speed: float | None
    gust: float | None

    @classmethod
    def from_api(cls, data: Mapping[str, Any] | None) -> "Wind":
        """Build wind data from GraphQL."""
        if not isinstance(data, Mapping):
            return cls(speed=None, gust=None)
        return cls(
            speed=_optional_float(data.get("speed")),
            gust=_optional_float(data.get("gust")),
        )

    def as_dict(self) -> dict[str, Any]:
        """Return a response dictionary."""
        return {"speed": self.speed, "gust": self.gust}


@dataclass(frozen=True, slots=True)
class WindDirection:
    """Wind direction measurement."""

    description: str | None
    degrees: float | None

    @classmethod
    def from_api(cls, data: Mapping[str, Any] | None) -> "WindDirection":
        """Build wind direction from GraphQL."""
        if not isinstance(data, Mapping):
            return cls(description=None, degrees=None)
        return cls(
            description=_optional_str(data.get("description")),
            degrees=_optional_float(data.get("degrees")),
        )

    def as_dict(self) -> dict[str, Any]:
        """Return a response dictionary."""
        return {"description": self.description, "degrees": self.degrees}


@dataclass(frozen=True, slots=True)
class WeatherMeasurement:
    """Weather station measurement history item."""

    date: datetime | None
    wind: float | None
    wind_gust: float | None
    wind_direction: float | None
    temperature: float | None
    road_temperature: float | None
    humidity: float | None
    dew_point: float | None
    traffic: float | None
    traffic_from_midnight: float | None

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> "WeatherMeasurement":
        """Build measurement history from GraphQL."""
        return cls(
            date=_parse_datetime(data.get("date")),
            wind=_optional_float(data.get("wind")),
            wind_gust=_optional_float(data.get("windGust")),
            wind_direction=_optional_float(data.get("windDirection")),
            temperature=_optional_float(data.get("temperature")),
            road_temperature=_optional_float(data.get("roadTemperature")),
            humidity=_optional_float(data.get("humidity")),
            dew_point=_optional_float(data.get("dewPoint")),
            traffic=_optional_float(data.get("traffic")),
            traffic_from_midnight=_optional_float(data.get("trafficFromMidnight")),
        )

    def as_dict(self) -> dict[str, Any]:
        """Return a response dictionary."""
        return {
            "date": self.date.isoformat() if self.date else None,
            "wind": self.wind,
            "wind_gust": self.wind_gust,
            "wind_direction": self.wind_direction,
            "temperature": self.temperature,
            "road_temperature": self.road_temperature,
            "humidity": self.humidity,
            "dew_point": self.dew_point,
            "traffic": self.traffic,
            "traffic_from_midnight": self.traffic_from_midnight,
        }


@dataclass(frozen=True, slots=True)
class WeatherStation:
    """Vegagerdin weather station."""

    station_id: int
    name: str
    category: str | None
    road_condition_ids: tuple[str, ...]
    owner: str | None
    last_update: datetime | None
    wind_alert: bool | None
    temperature: float | None
    road_temperature: float | None
    humidity: float | None
    dew_point: float | None
    traffic: float | None
    traffic_from_midnight: float | None
    wind: Wind
    wind_direction: WindDirection
    latitude: float | None
    longitude: float | None
    tooltip: str | None
    measurements: tuple[WeatherMeasurement, ...] = field(default_factory=tuple)
    source: str = SOURCE_GRAPHQL

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> "WeatherStation":
        """Build a station from GraphQL."""
        coordinates = data.get("coordinates")
        if not isinstance(coordinates, Mapping):
            coordinates = {}
        road_condition_ids = data.get("RoadConditionIds")
        if not isinstance(road_condition_ids, Sequence) or isinstance(
            road_condition_ids,
            (str, bytes),
        ):
            road_condition_ids = []
        return cls(
            station_id=_required_int(data, "id"),
            name=str(data.get("name") or data.get("id") or ""),
            category=_optional_str(data.get("category")),
            road_condition_ids=tuple(str(item) for item in road_condition_ids),
            owner=_optional_str(data.get("owner")),
            last_update=_parse_datetime(data.get("lastUpdate")),
            wind_alert=_optional_bool(data.get("windAlert")),
            temperature=_optional_float(data.get("temperature")),
            road_temperature=_optional_float(data.get("roadTemperature")),
            humidity=_optional_float(data.get("humidity")),
            dew_point=_optional_float(data.get("dewPoint")),
            traffic=_optional_float(data.get("traffic")),
            traffic_from_midnight=_optional_float(data.get("trafficFromMidnight")),
            wind=Wind.from_api(data.get("wind")),
            wind_direction=WindDirection.from_api(data.get("windDirection")),
            latitude=_optional_float(coordinates.get("lat")),
            longitude=_optional_float(coordinates.get("lon")),
            tooltip=_optional_str(data.get("tooltip")),
            measurements=tuple(
                WeatherMeasurement.from_api(item)
                for item in _mapping_items(data.get("measurements"))
            ),
        )

    def as_dict(self) -> dict[str, Any]:
        """Return a response dictionary."""
        return {
            "id": self.station_id,
            "name": self.name,
            "category": self.category,
            "road_condition_ids": list(self.road_condition_ids),
            "owner": self.owner,
            "last_update": self.last_update.isoformat()
            if self.last_update
            else None,
            "wind_alert": self.wind_alert,
            "temperature": self.temperature,
            "road_temperature": self.road_temperature,
            "humidity": self.humidity,
            "dew_point": self.dew_point,
            "traffic": self.traffic,
            "traffic_from_midnight": self.traffic_from_midnight,
            "wind": self.wind.as_dict(),
            "wind_direction": self.wind_direction.as_dict(),
            "latitude": self.latitude,
            "longitude": self.longitude,
            "tooltip": self.tooltip,
            "measurements": [item.as_dict() for item in self.measurements],
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class VegagerdinCamera:
    """Vegagerdin webcam."""

    image_id: str
    camera_id: int
    name: str
    road_number: str | None
    road_name: str | None
    description: str | None
    image_url: str | None
    latitude: float | None
    longitude: float | None
    source: str = SOURCE_WEBCAM_REST

    @classmethod
    def from_webcam_api(cls, data: Mapping[str, Any]) -> "VegagerdinCamera":
        """Build camera metadata from the official webcam REST API."""
        camera_id = _required_int(data, "Maelist_nr")
        image_url = _optional_str(data.get("Slod"))
        return cls(
            image_id=_webcam_image_id(camera_id, image_url, data),
            camera_id=camera_id,
            name=str(data.get("Myndavel") or data.get("Maelist_nr") or ""),
            road_number=_optional_str(data.get("NrVegur")),
            road_name=_optional_str(data.get("Vegheiti")),
            description=_optional_str(data.get("Skyring")),
            image_url=image_url,
            latitude=_optional_float(data.get("Breidd")),
            longitude=_optional_float(data.get("Lengd")),
        )

    def as_dict(self) -> dict[str, Any]:
        """Return a response dictionary."""
        return {
            "image_id": self.image_id,
            "id": self.camera_id,
            "name": self.name,
            "road_number": self.road_number,
            "road_name": self.road_name,
            "description": self.description,
            "image_url": self.image_url,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class TrafficCounter:
    """Vegagerdin WFS traffic counter."""

    counter_id: int
    object_id: int | None
    name: str
    direction: str | None
    traffic_15min: float | None
    average_speed_15min: float | None
    traffic_today: float | None
    last_data: datetime | None
    daily_counts: tuple[tuple[str | None, float | None], ...]
    counter_type: int | None
    latitude: float | None
    longitude: float | None
    source: str = SOURCE_TRAFFIC_WFS

    @classmethod
    def from_wfs_feature(cls, feature: Mapping[str, Any]) -> "TrafficCounter":
        """Build a traffic counter from WFS GeoJSON."""
        properties = feature.get("properties")
        geometry = feature.get("geometry")
        if not isinstance(properties, Mapping):
            raise InvalidResponse("Traffic counter feature has no properties")
        longitude: float | None = None
        latitude: float | None = None
        if isinstance(geometry, Mapping):
            coordinates = geometry.get("coordinates")
            if isinstance(coordinates, Sequence) and len(coordinates) >= 2:
                longitude = _optional_float(coordinates[0])
                latitude = _optional_float(coordinates[1])
        daily_counts = tuple(
            (
                _optional_str(properties.get(f"DAGS_DAGUR{index}")),
                _optional_float(properties.get(f"UMF_DAGUR{index}")),
            )
            for index in range(1, 8)
        )
        return cls(
            counter_id=_required_int(properties, "IDSTOD"),
            object_id=_optional_int(properties.get("OBJECTID")),
            name=str(properties.get("NAFN") or properties.get("IDSTOD") or ""),
            direction=_optional_str(properties.get("STEFNA")),
            traffic_15min=_optional_float(properties.get("UMF_15MIN")),
            average_speed_15min=_optional_float(properties.get("MEDALHRADI_15MIN")),
            traffic_today=_optional_float(properties.get("UMF_I_DAG")),
            last_data=_parse_datetime(properties.get("DAGS_SIDUSTUGAGNA")),
            daily_counts=daily_counts,
            counter_type=_optional_int(properties.get("MAELISTOD_TEGUND")),
            latitude=latitude,
            longitude=longitude,
        )

    def as_dict(self) -> dict[str, Any]:
        """Return a response dictionary."""
        return {
            "id": self.counter_id,
            "object_id": self.object_id,
            "name": self.name,
            "direction": self.direction,
            "traffic_15min": self.traffic_15min,
            "average_speed_15min": self.average_speed_15min,
            "traffic_today": self.traffic_today,
            "last_data": self.last_data.isoformat() if self.last_data else None,
            "daily_counts": [
                {"date": date, "traffic": traffic}
                for date, traffic in self.daily_counts
            ],
            "counter_type": self.counter_type,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "source": self.source,
        }


class VegagerdinApiClient:
    """Small async client for Vegagerdin data sources."""

    def __init__(self, session: Any) -> None:
        """Initialize the client."""
        self._session = session

    async def async_get_road_conditions(
        self,
        *,
        language: str = "en",
    ) -> list[RoadCondition]:
        """Return current road conditions."""
        payload = await self._async_graphql(
            ROAD_CONDITION_QUERY,
            {"lang": _graphql_language(language)},
        )
        return parse_road_conditions_payload(payload)

    async def async_get_road_notifications(
        self,
        *,
        language: str = "en",
    ) -> list[RoadNotice]:
        """Return active road notices."""
        payload = await self._async_graphql(
            ROAD_NOTIFICATIONS_QUERY,
            {"language": _notification_language(language)},
        )
        return parse_road_notifications_payload(payload)

    async def async_get_weather_stations(self) -> list[WeatherStation]:
        """Return current weather station summaries."""
        payload = await self._async_graphql(WEATHER_STATIONS_QUERY)
        return parse_weather_stations_payload(payload)

    async def async_get_weather_station_measurements(
        self,
        station_ids: Iterable[int],
    ) -> list[WeatherStation]:
        """Return weather station measurement histories."""
        stations: list[WeatherStation] = []
        for station_id in dict.fromkeys(int(station_id) for station_id in station_ids):
            payload = await self._async_graphql(
                WEATHER_STATION_MEASUREMENTS_QUERY,
                {"id": station_id},
            )
            station_data = payload.get("data", {}).get("WeatherStation")
            if isinstance(station_data, Mapping):
                stations.append(WeatherStation.from_api(station_data))
        return stations

    async def async_get_webcams(
        self,
        *,
        camera_ids: Iterable[int] | None = None,
        bbox: Sequence[float] | None = None,
    ) -> list[VegagerdinCamera]:
        """Return official webcam metadata."""
        payload = await self._async_get_json(WEBCAM_REST_URL)
        cameras = parse_webcams_payload(payload)
        selected_ids = {int(camera_id) for camera_id in camera_ids or []}
        if selected_ids:
            cameras = [camera for camera in cameras if camera.camera_id in selected_ids]
        if bbox:
            cameras = [
                camera
                for camera in cameras
                if _point_in_bbox(camera.latitude, camera.longitude, bbox)
            ]
        return cameras

    async def async_get_traffic_counters(
        self,
        *,
        counter_ids: Iterable[int] | None = None,
        bbox: Sequence[float] | None = None,
    ) -> list[TrafficCounter]:
        """Return traffic counters from GeoServer WFS as GeoJSON."""
        params = [
            ("service", "WFS"),
            ("version", "1.0.0"),
            ("request", "GetFeature"),
            ("typeName", TRAFFIC_COUNTER_TYPENAME),
            ("outputFormat", "application/json"),
            ("srsName", "EPSG:4326"),
        ]
        payload = await self._async_get_json(TRAFFIC_WFS_URL, params=params)
        counters = parse_traffic_counters_payload(payload)
        selected_ids = {int(counter_id) for counter_id in counter_ids or []}
        if selected_ids:
            counters = [
                counter for counter in counters if counter.counter_id in selected_ids
            ]
        if bbox:
            counters = [
                counter
                for counter in counters
                if _point_in_bbox(counter.latitude, counter.longitude, bbox)
            ]
        return counters

    async def _async_graphql(
        self,
        query: str,
        variables: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        """Send a raw GraphQL POST request."""
        payload = {"query": query}
        if variables:
            payload["variables"] = dict(variables)
        try:
            async with self._session.post(
                GRAPHQL_URL,
                json=payload,
                timeout=REQUEST_TIMEOUT_SECONDS,
            ) as response:
                if response.status >= 500:
                    raise CannotConnect(f"GraphQL HTTP {response.status}")
                if response.status >= 400:
                    raise InvalidResponse(f"GraphQL HTTP {response.status}")
                data = await response.json(content_type=None)
        except VegagerdinApiError:
            raise
        except Exception as err:  # noqa: BLE001 - aiohttp is optional in tests.
            raise CannotConnect(str(err)) from err

        if not isinstance(data, Mapping):
            raise InvalidResponse("Expected GraphQL object response")
        if data.get("errors"):
            raise InvalidResponse(f"GraphQL errors: {data['errors']}")
        return data

    async def _async_get_json(
        self,
        url: str,
        *,
        params: Sequence[tuple[str, str]] | None = None,
    ) -> Any:
        """Fetch JSON from a REST/WFS endpoint."""
        try:
            async with self._session.get(
                url,
                params=list(params or []),
                timeout=REQUEST_TIMEOUT_SECONDS,
            ) as response:
                if response.status >= 500:
                    raise CannotConnect(f"HTTP {response.status}")
                if response.status >= 400:
                    raise InvalidResponse(f"HTTP {response.status}")
                return await response.json(content_type=None)
        except VegagerdinApiError:
            raise
        except Exception as err:  # noqa: BLE001 - aiohttp is optional in tests.
            raise CannotConnect(str(err)) from err


def parse_road_conditions_payload(payload: Mapping[str, Any]) -> list[RoadCondition]:
    """Parse a GraphQL road condition payload."""
    results = _graphql_results(payload, "RoadCondition")
    return [RoadCondition.from_api(item) for item in results]


def parse_road_notifications_payload(payload: Mapping[str, Any]) -> list[RoadNotice]:
    """Parse a GraphQL road notification payload."""
    results = _graphql_results(payload, "RoadNotifications")
    return [RoadNotice.from_api(item) for item in results]


def parse_weather_stations_payload(payload: Mapping[str, Any]) -> list[WeatherStation]:
    """Parse a GraphQL weather stations payload."""
    results = _graphql_results(payload, "WeatherStations")
    return [WeatherStation.from_api(item) for item in results]


def parse_webcams_payload(payload: Any) -> list[VegagerdinCamera]:
    """Parse official webcam REST payload."""
    if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes)):
        raise InvalidResponse("Expected webcam list")
    return [
        VegagerdinCamera.from_webcam_api(item)
        for item in payload
        if isinstance(item, Mapping)
    ]


def parse_traffic_counters_payload(payload: Mapping[str, Any]) -> list[TrafficCounter]:
    """Parse WFS GeoJSON traffic counter payload."""
    features = payload.get("features")
    if not isinstance(features, Sequence) or isinstance(features, (str, bytes)):
        raise InvalidResponse("Expected traffic counter FeatureCollection")
    return [
        TrafficCounter.from_wfs_feature(feature)
        for feature in features
        if isinstance(feature, Mapping)
    ]


def filter_notices(
    notices: Iterable[RoadNotice],
    *,
    keys: Iterable[str] | None = None,
    road_numbers: Iterable[str] | None = None,
    tags: Iterable[str] | None = None,
    categories: Iterable[str] | None = None,
) -> list[RoadNotice]:
    """Filter notices by simple category/tag/text criteria."""
    wanted_roads = {str(item).casefold() for item in road_numbers or []}
    wanted_keys = {str(item).casefold() for item in keys or []}
    wanted_tags = {str(item).casefold() for item in tags or []}
    wanted_categories = {str(item).casefold() for item in categories or []}
    results: list[RoadNotice] = []
    for notice in notices:
        notice_tags = {tag.casefold() for tag in notice.tags}
        notice_text = (notice.text or "").casefold()
        if wanted_keys and (notice.key or "").casefold() not in wanted_keys:
            continue
        if wanted_categories and (notice.category or "").casefold() not in (
            wanted_categories
        ):
            continue
        if wanted_tags and not wanted_tags.intersection(notice_tags):
            continue
        if wanted_roads and not any(road in notice_text for road in wanted_roads):
            continue
        results.append(notice)
    return results


ROAD_CONDITION_QUERY = """
query RoadCondition($lang: Languages) {
  RoadCondition(lang: $lang) {
    results {
      id
      name
      serviceCategory
      winterService
      display
      lastUpdate
      geometryCenter { lat lon }
      condition { code category description date }
      conditionPrev { code category description date }
      conditionMarkers { code description lastUpdate }
      conditionsOtherMarkers {
        id
        title
        description
        code
        dateFrom
        dateTo
        lastUpdate
        coordinates { lat lon }
      }
      weightRestriction { limit description }
      roads { name nr }
    }
  }
}
"""

ROAD_NOTIFICATIONS_QUERY = """
query RoadNotifications($language: RoadNotificationsLanguage) {
  RoadNotifications(language: $language) {
    results {
      id
      category
      key
      subCategory
      text
      tags
      date
    }
  }
}
"""

WEATHER_STATIONS_QUERY = """
query WeatherStations {
  WeatherStations {
    results {
      id
      name
      category
      RoadConditionIds
      owner
      lastUpdate
      windAlert
      temperature
      roadTemperature
      humidity
      dewPoint
      traffic
      trafficFromMidnight
      wind { speed gust }
      windDirection { description degrees }
      coordinates { lat lon }
    }
  }
}
"""

WEATHER_STATION_MEASUREMENTS_QUERY = """
query WeatherStationWithMeasurements($id: Int!) {
  WeatherStation(id: $id) {
    id
    name
    category
    RoadConditionIds
    owner
    lastUpdate
    windAlert
    temperature
    roadTemperature
    humidity
    dewPoint
    traffic
    trafficFromMidnight
    wind { speed gust }
    windDirection { description degrees }
    coordinates { lat lon }
    measurements {
      date
      wind
      windGust
      windDirection
      temperature
      roadTemperature
      humidity
      dewPoint
      traffic
      trafficFromMidnight
    }
  }
}
"""


def _graphql_results(payload: Mapping[str, Any], field: str) -> list[Mapping[str, Any]]:
    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise InvalidResponse("GraphQL response has no data object")
    container = data.get(field)
    if not isinstance(container, Mapping):
        raise InvalidResponse(f"GraphQL response has no {field} object")
    results = container.get("results")
    if not isinstance(results, Sequence) or isinstance(results, (str, bytes)):
        raise InvalidResponse(f"GraphQL {field} response has no results list")
    return [item for item in results if isinstance(item, Mapping)]


def _mapping_items(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _required_int(data: Mapping[str, Any], key: str) -> int:
    value = _optional_int(data.get(key))
    if value is None:
        raise InvalidResponse(f"Missing integer field {key}")
    return value


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)


def _parse_datetime(value: Any) -> datetime | None:
    text = _optional_str(value)
    if text is None:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        _LOGGER.debug("Could not parse Vegagerdin timestamp: %s", value)
        return None


def _graphql_language(language: str) -> str:
    if language.casefold().startswith("is"):
        return "IS"
    return "EN"


def _notification_language(language: str) -> str:
    if language.casefold().startswith("is"):
        return "IS"
    return "EN"


def _point_in_bbox(
    latitude: float | None,
    longitude: float | None,
    bbox: Sequence[float],
) -> bool:
    if latitude is None or longitude is None or len(bbox) != 4:
        return False
    min_lon, min_lat, max_lon, max_lat = (float(value) for value in bbox)
    return min_lon <= longitude <= max_lon and min_lat <= latitude <= max_lat
