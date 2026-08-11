"""Data coordinators for the Vegagerdin integration."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from functools import partial
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    CannotConnect,
    InvalidResponse,
    RoadCondition,
    RoadNotice,
    TrafficCounter,
    VegagerdinApiClient,
    VegagerdinCamera,
    WeatherStation,
)
from .const import (
    CONF_LANGUAGE,
    CONF_ROUTE_INCLUDE_ZONES,
    CONF_ROUTE_ORIGIN_ENTITY_ID,
    CONF_ROUTE_POINT_CORRIDOR_KM,
    CONF_ROUTE_ROAD_CORRIDOR_KM,
    CONF_ROUTE_TRACKER_ENTITY_IDS,
    DEFAULT_LANGUAGE,
    DEFAULT_ROUTE_INCLUDE_ZONES,
    DEFAULT_ROUTE_ORIGIN_ENTITY_ID,
    DEFAULT_ROUTE_POINT_CORRIDOR_KM,
    DEFAULT_ROUTE_ROAD_CORRIDOR_KM,
    DOMAIN,
    METADATA_SCAN_INTERVAL_HOURS,
    NOTICE_SCAN_INTERVAL_MINUTES,
    ROAD_SCAN_INTERVAL_SECONDS,
    ROUTE_ENDPOINT_DOMAINS,
    ROUTE_PLANNER_STORAGE_KEY,
    ROUTE_PLANNER_STORAGE_VERSION,
    ROUTE_REFRESH_DEBOUNCE_SECONDS,
    ROUTE_SCAN_INTERVAL_SECONDS,
    SELECTED_ROUTE_DATA_KEY,
    TRAFFIC_SCAN_INTERVAL_MINUTES,
    WEATHER_SCAN_INTERVAL_SECONDS,
    WEBCAM_SCAN_INTERVAL_HOURS,
)
from .routing import (
    Coordinate,
    OsrmRoute,
    RoadGeometry,
    RouteDetails,
    VegagerdinRouteApiClient,
    build_route_details,
    coordinate_distance_km,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class VegagerdinMetadata:
    """Discovery metadata for config and diagnostics."""

    roads: dict[str, RoadCondition]
    weather_stations: dict[int, WeatherStation]
    cameras: dict[int, VegagerdinCamera]
    traffic_counters: dict[int, TrafficCounter]
    road_geometries: dict[str, RoadGeometry]


@dataclass(slots=True)
class VegagerdinRuntimeData:
    """Runtime data stored on a Home Assistant config entry."""

    client: VegagerdinApiClient
    metadata: VegagerdinMetadataCoordinator
    road_conditions: VegagerdinRoadConditionCoordinator
    notices: VegagerdinNoticeCoordinator
    weather_stations: VegagerdinWeatherStationCoordinator
    webcams: VegagerdinWebcamCoordinator
    traffic_counters: VegagerdinTrafficCounterCoordinator
    routes: VegagerdinRouteCoordinator | None = None
    route_client: VegagerdinRouteApiClient | None = None


class VegagerdinMetadataCoordinator(DataUpdateCoordinator[VegagerdinMetadata]):
    """Coordinate metadata used for selection and device information."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: VegagerdinApiClient,
        entry: ConfigEntry,
        route_client: VegagerdinRouteApiClient | None = None,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            logger=_LOGGER,
            name=f"{DOMAIN}_metadata",
            config_entry=entry,
            update_interval=timedelta(hours=METADATA_SCAN_INTERVAL_HOURS),
        )
        self.client = client
        self.route_client = route_client
        self.language = (entry.options or entry.data).get(
            CONF_LANGUAGE,
            DEFAULT_LANGUAGE,
        )

    async def _async_update_data(self) -> VegagerdinMetadata:
        """Fetch metadata."""
        try:
            roads = await self.client.async_get_road_conditions(
                language=self.language,
            )
            stations = await self.client.async_get_weather_stations()
            cameras = await self.client.async_get_webcams()
            counters = await self.client.async_get_traffic_counters()
        except (CannotConnect, InvalidResponse) as err:
            raise UpdateFailed(str(err)) from err
        road_geometries: dict[str, RoadGeometry] = {}
        if self.route_client is not None:
            try:
                road_geometries = await self.route_client.async_get_road_geometries()
            except (CannotConnect, InvalidResponse) as err:
                _LOGGER.warning("Could not update Vegagerdin road geometries: %s", err)
        return VegagerdinMetadata(
            roads={road.road_condition_id: road for road in roads},
            weather_stations={station.station_id: station for station in stations},
            cameras={camera.camera_id: camera for camera in cameras},
            traffic_counters={counter.counter_id: counter for counter in counters},
            road_geometries=road_geometries,
        )


class VegagerdinRoadConditionCoordinator(
    DataUpdateCoordinator[dict[str, RoadCondition]]
):
    """Coordinate selected road condition updates."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: VegagerdinApiClient,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            logger=_LOGGER,
            name=f"{DOMAIN}_road_conditions",
            config_entry=entry,
            update_interval=timedelta(seconds=ROAD_SCAN_INTERVAL_SECONDS),
        )
        self.client = client
        entry_config = entry.options or entry.data
        self.language = entry_config.get(CONF_LANGUAGE, DEFAULT_LANGUAGE)

    async def _async_update_data(self) -> dict[str, RoadCondition]:
        """Fetch selected road conditions."""
        try:
            roads = await self.client.async_get_road_conditions(
                language=self.language,
            )
        except (CannotConnect, InvalidResponse) as err:
            raise UpdateFailed(str(err)) from err
        return {road.road_condition_id: road for road in roads}


class VegagerdinNoticeCoordinator(DataUpdateCoordinator[tuple[RoadNotice, ...]]):
    """Coordinate road notification updates."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: VegagerdinApiClient,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            logger=_LOGGER,
            name=f"{DOMAIN}_notices",
            config_entry=entry,
            update_interval=timedelta(minutes=NOTICE_SCAN_INTERVAL_MINUTES),
        )
        self.client = client
        self.language = (entry.options or entry.data).get(
            CONF_LANGUAGE,
            DEFAULT_LANGUAGE,
        )

    async def _async_update_data(self) -> tuple[RoadNotice, ...]:
        """Fetch active road notices."""
        try:
            notices = await self.client.async_get_road_notifications(
                language=self.language,
            )
        except (CannotConnect, InvalidResponse) as err:
            raise UpdateFailed(str(err)) from err
        return tuple(notices)


class VegagerdinWeatherStationCoordinator(
    DataUpdateCoordinator[dict[int, WeatherStation]]
):
    """Coordinate selected weather station updates."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: VegagerdinApiClient,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            logger=_LOGGER,
            name=f"{DOMAIN}_weather_stations",
            config_entry=entry,
            update_interval=timedelta(seconds=WEATHER_SCAN_INTERVAL_SECONDS),
        )
        self.client = client

    async def _async_update_data(self) -> dict[int, WeatherStation]:
        """Fetch selected weather stations."""
        try:
            stations = await self.client.async_get_weather_stations()
        except (CannotConnect, InvalidResponse) as err:
            raise UpdateFailed(str(err)) from err
        return {station.station_id: station for station in stations}


class VegagerdinWebcamCoordinator(DataUpdateCoordinator[dict[str, VegagerdinCamera]]):
    """Coordinate selected webcam metadata."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: VegagerdinApiClient,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            logger=_LOGGER,
            name=f"{DOMAIN}_webcams",
            config_entry=entry,
            update_interval=timedelta(hours=WEBCAM_SCAN_INTERVAL_HOURS),
        )
        self.client = client

    async def _async_update_data(self) -> dict[str, VegagerdinCamera]:
        """Fetch selected webcam metadata."""
        try:
            cameras = await self.client.async_get_webcams()
        except (CannotConnect, InvalidResponse) as err:
            raise UpdateFailed(str(err)) from err
        return {camera.image_id: camera for camera in cameras}


class VegagerdinTrafficCounterCoordinator(
    DataUpdateCoordinator[dict[int, TrafficCounter]]
):
    """Coordinate selected traffic counter updates."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: VegagerdinApiClient,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            logger=_LOGGER,
            name=f"{DOMAIN}_traffic_counters",
            config_entry=entry,
            update_interval=timedelta(minutes=TRAFFIC_SCAN_INTERVAL_MINUTES),
        )
        self.client = client

    async def _async_update_data(self) -> dict[int, TrafficCounter]:
        """Fetch selected traffic counters."""
        try:
            counters = await self.client.async_get_traffic_counters()
        except (CannotConnect, InvalidResponse) as err:
            raise UpdateFailed(str(err)) from err
        return {counter.counter_id: counter for counter in counters}


@dataclass(frozen=True, slots=True)
class _CachedRoute:
    """An OSRM route and the endpoints used to calculate it."""

    origin: Coordinate
    destination: Coordinate
    route: OsrmRoute


@dataclass(frozen=True, slots=True)
class RouteEndpoint:
    """A planner endpoint backed by an HA entity or fixed coordinates."""

    label: str
    entity_id: str | None = None
    coordinate: Coordinate | None = None

    @classmethod
    def for_entity(cls, entity_id: str, label: str | None = None) -> RouteEndpoint:
        """Create an entity-backed endpoint."""
        return cls(label=label or entity_id, entity_id=entity_id)

    @property
    def identifier(self) -> str:
        """Return a stable cache identifier."""
        if self.entity_id is not None:
            return self.entity_id
        if self.coordinate is None:
            return "invalid"
        return (
            f"coordinate:{self.coordinate.latitude:.6f},{self.coordinate.longitude:.6f}"
        )

    def as_dict(self) -> dict[str, Any]:
        """Return a storable endpoint dictionary."""
        result: dict[str, Any] = {"label": self.label}
        if self.entity_id is not None:
            result["entity_id"] = self.entity_id
        if self.coordinate is not None:
            result.update(
                {
                    "latitude": self.coordinate.latitude,
                    "longitude": self.coordinate.longitude,
                }
            )
        return result

    @classmethod
    def from_dict(
        cls,
        value: Any,
        fallback: RouteEndpoint,
    ) -> RouteEndpoint:
        """Restore a validated endpoint dictionary."""
        if not isinstance(value, dict):
            return fallback
        label = str(value.get("label") or "").strip()
        entity_id = str(value.get("entity_id") or "").strip()
        if entity_id:
            return cls.for_entity(entity_id, label or entity_id)
        try:
            coordinate = Coordinate(
                latitude=float(value["latitude"]),
                longitude=float(value["longitude"]),
            )
        except (KeyError, TypeError, ValueError):
            return fallback
        return cls(label=label or "Selected point", coordinate=coordinate)


def route_target_entity_ids(
    hass: HomeAssistant,
    entry_config: dict[str, Any],
) -> tuple[str, ...]:
    """Return configured route destinations, including all HA zones."""
    origin = str(
        entry_config.get(
            CONF_ROUTE_ORIGIN_ENTITY_ID,
            DEFAULT_ROUTE_ORIGIN_ENTITY_ID,
        )
    )
    targets = {
        str(entity_id)
        for entity_id in entry_config.get(CONF_ROUTE_TRACKER_ENTITY_IDS, [])
        if str(entity_id)
    }
    if entry_config.get(CONF_ROUTE_INCLUDE_ZONES, DEFAULT_ROUTE_INCLUDE_ZONES):
        targets.update(state.entity_id for state in hass.states.async_all("zone"))
    targets.discard(origin)
    return tuple(sorted(targets))


def route_dispatcher_signal(entry_id: str) -> str:
    """Return the signal used when route destinations change."""
    return f"{DOMAIN}_{entry_id}_route_targets"


def route_endpoint_entity_ids(hass: HomeAssistant) -> tuple[str, ...]:
    """Return coordinate-bearing entities suitable as route endpoints."""
    return tuple(
        sorted(
            state.entity_id
            for domain in ROUTE_ENDPOINT_DOMAINS
            for state in hass.states.async_all(domain)
            if _state_coordinate(state) is not None
        )
    )


class VegagerdinRouteCoordinator(DataUpdateCoordinator[dict[str, RouteDetails]]):
    """Coordinate route calculation and matching for HA destinations."""

    def __init__(
        self,
        hass: HomeAssistant,
        route_client: VegagerdinRouteApiClient,
        entry: ConfigEntry,
        metadata: VegagerdinMetadataCoordinator,
        roads: VegagerdinRoadConditionCoordinator,
        notices: VegagerdinNoticeCoordinator,
        stations: VegagerdinWeatherStationCoordinator,
        webcams: VegagerdinWebcamCoordinator,
        counters: VegagerdinTrafficCounterCoordinator,
    ) -> None:
        """Initialize the route coordinator."""
        super().__init__(
            hass,
            logger=_LOGGER,
            name=f"{DOMAIN}_routes",
            config_entry=entry,
            update_interval=timedelta(seconds=ROUTE_SCAN_INTERVAL_SECONDS),
        )
        self.route_client = route_client
        self.entry = entry
        self.metadata = metadata
        self.roads = roads
        self.notices = notices
        self.stations = stations
        self.webcams = webcams
        self.counters = counters
        entry_config = entry.options or entry.data
        self.origin_entity_id = str(
            entry_config.get(
                CONF_ROUTE_ORIGIN_ENTITY_ID,
                DEFAULT_ROUTE_ORIGIN_ENTITY_ID,
            )
        )
        endpoints = route_endpoint_entity_ids(hass)
        default_destination = next(
            (
                entity_id
                for entity_id in self.target_entity_ids
                if entity_id != self.origin_entity_id
            ),
            next(
                (
                    entity_id
                    for entity_id in endpoints
                    if entity_id != self.origin_entity_id
                ),
                self.origin_entity_id,
            ),
        )
        self.selected_origin = RouteEndpoint.for_entity(self.origin_entity_id)
        self.selected_destination = RouteEndpoint.for_entity(default_destination)
        self.road_corridor_km = float(
            entry_config.get(
                CONF_ROUTE_ROAD_CORRIDOR_KM,
                DEFAULT_ROUTE_ROAD_CORRIDOR_KM,
            )
        )
        self.point_corridor_km = float(
            entry_config.get(
                CONF_ROUTE_POINT_CORRIDOR_KM,
                DEFAULT_ROUTE_POINT_CORRIDOR_KM,
            )
        )
        self.errors: dict[str, str] = {}
        self._route_cache: dict[str, _CachedRoute] = {}
        self._known_targets: set[str] = set()
        self._cancel_debounce: Callable[[], None] | None = None
        self._store = Store(
            hass,
            ROUTE_PLANNER_STORAGE_VERSION,
            f"{ROUTE_PLANNER_STORAGE_KEY}.{entry.entry_id}",
        )

    async def async_initialize(self) -> None:
        """Restore the planner endpoints before the first refresh."""
        stored = await self._store.async_load()
        if not isinstance(stored, dict):
            return
        self.selected_origin = RouteEndpoint.from_dict(
            stored.get("origin"),
            self.selected_origin,
        )
        self.selected_destination = RouteEndpoint.from_dict(
            stored.get("destination"),
            self.selected_destination,
        )

    @property
    def target_entity_ids(self) -> tuple[str, ...]:
        """Return current destination entity IDs."""
        return route_target_entity_ids(self.hass, self.entry.options or self.entry.data)

    @property
    def selected_details(self) -> RouteDetails | None:
        """Return details for the route currently selected in the planner."""
        return (self.data or {}).get(SELECTED_ROUTE_DATA_KEY)

    @property
    def selected_origin_entity_id(self) -> str:
        """Return the selected origin entity ID, if entity-backed."""
        return self.selected_origin.entity_id or ""

    @property
    def selected_destination_entity_id(self) -> str:
        """Return the selected destination entity ID, if entity-backed."""
        return self.selected_destination.entity_id or ""

    def selected_endpoint_payload(self, endpoint: str) -> dict[str, Any]:
        """Return a resolved endpoint for entity state attributes."""
        value = (
            self.selected_origin if endpoint == "origin" else self.selected_destination
        )
        try:
            coordinate, label = self._resolve_endpoint(value)
        except InvalidResponse:
            return value.as_dict()
        result = value.as_dict()
        result["label"] = label
        result["latitude"] = coordinate.latitude
        result["longitude"] = coordinate.longitude
        return result

    async def async_set_selected_origin(self, entity_id: str) -> None:
        """Set the planner origin and recalculate its route."""
        self.selected_origin = self._entity_endpoint(entity_id)
        await self._async_save_and_refresh()

    async def async_set_selected_destination(self, entity_id: str) -> None:
        """Set the planner destination and recalculate its route."""
        self.selected_destination = self._entity_endpoint(entity_id)
        await self._async_save_and_refresh()

    async def async_set_selected_route(
        self,
        origin: RouteEndpoint,
        destination: RouteEndpoint,
    ) -> RouteDetails | None:
        """Set arbitrary planner endpoints and recalculate."""
        self.selected_origin = origin
        self.selected_destination = destination
        await self._async_save_and_refresh()
        return self.selected_details

    async def async_swap_selected_route(self) -> None:
        """Swap planner origin and destination."""
        self.selected_origin, self.selected_destination = (
            self.selected_destination,
            self.selected_origin,
        )
        await self._async_save_and_refresh()

    async def async_refresh_selected_route(self) -> None:
        """Discard the selected route cache and recalculate."""
        self._route_cache.pop(self._selected_route_cache_key, None)
        await self.async_request_refresh()

    async def _async_save_and_refresh(self) -> None:
        """Persist planner choices and refresh the selected route."""
        await self._store.async_save(
            {
                "origin": self.selected_origin.as_dict(),
                "destination": self.selected_destination.as_dict(),
            }
        )
        await self.async_request_refresh()

    def _entity_endpoint(self, entity_id: str) -> RouteEndpoint:
        state = self.hass.states.get(entity_id)
        if _state_coordinate(state) is None:
            raise InvalidResponse(f"{entity_id} has no coordinates")
        return RouteEndpoint.for_entity(entity_id, _state_name(state))

    @property
    def _selected_route_cache_key(self) -> str:
        return (
            f"selected:{self.selected_origin.identifier}:"
            f"{self.selected_destination.identifier}"
        )

    def async_start_tracking(self) -> Callable[[], None]:
        """Listen for endpoint movement and newly created zones."""
        self._known_targets = set(self.target_entity_ids)
        return self.hass.bus.async_listen(
            EVENT_STATE_CHANGED,
            self._async_handle_state_changed,
        )

    @callback
    def _async_handle_state_changed(self, event: Event) -> None:
        entity_id = str(event.data.get("entity_id") or "")
        current_targets = set(self.target_entity_ids)
        selected_endpoints = {
            endpoint.entity_id
            for endpoint in (self.selected_origin, self.selected_destination)
            if endpoint.entity_id
        }
        if (
            entity_id != self.origin_entity_id
            and entity_id not in current_targets
            and entity_id not in selected_endpoints
        ):
            return
        old_state = event.data.get("old_state")
        new_state = event.data.get("new_state")
        if _state_coordinate(old_state) == _state_coordinate(new_state):
            return
        new_targets = current_targets - self._known_targets
        if new_targets:
            self._known_targets.update(new_targets)
            async_dispatcher_send(
                self.hass,
                route_dispatcher_signal(self.entry.entry_id),
                tuple(sorted(new_targets)),
            )
        if self._cancel_debounce is not None:
            self._cancel_debounce()
        self._cancel_debounce = async_call_later(
            self.hass,
            ROUTE_REFRESH_DEBOUNCE_SECONDS,
            self._async_debounced_refresh,
        )

    async def _async_debounced_refresh(self, _now: Any) -> None:
        self._cancel_debounce = None
        await self.async_request_refresh()

    async def _async_update_data(self) -> dict[str, RouteDetails]:
        origin_state = self.hass.states.get(self.origin_entity_id)
        origin = _state_coordinate(origin_state)
        self.errors = {}
        details: dict[str, RouteDetails] = {}
        if origin is None:
            self.errors[self.origin_entity_id] = "Origin has no coordinates"
        else:
            targets = self.target_entity_ids
            self._known_targets.update(targets)
            results = await asyncio.gather(
                *(self._async_build_target(target, origin) for target in targets),
            )
            for target, result in zip(targets, results, strict=True):
                if isinstance(result, RouteDetails):
                    details[target] = result

        selected = await self._async_build_selected_route()
        if selected is not None:
            details[SELECTED_ROUTE_DATA_KEY] = selected
        return details

    async def _async_build_selected_route(self) -> RouteDetails | None:
        """Build the current user-selected route."""
        try:
            origin, origin_name = self._resolve_endpoint(self.selected_origin)
            destination, destination_name = self._resolve_endpoint(
                self.selected_destination
            )
            if coordinate_distance_km(origin, destination) < 0.001:
                raise InvalidResponse("Origin and destination must be different")
            route = await self._async_route_for(
                self._selected_route_cache_key,
                origin,
                destination,
            )
            return await self._async_build_details(
                origin_entity_id=self.selected_origin.identifier,
                destination_entity_id=self.selected_destination.identifier,
                origin_name=origin_name,
                destination_name=destination_name,
                route=route,
            )
        except (CannotConnect, InvalidResponse) as err:
            self.errors[SELECTED_ROUTE_DATA_KEY] = str(err)
            return None

    def _resolve_endpoint(
        self,
        endpoint: RouteEndpoint,
    ) -> tuple[Coordinate, str]:
        if endpoint.entity_id is not None:
            state = self.hass.states.get(endpoint.entity_id)
            coordinate = _state_coordinate(state)
            if coordinate is None:
                raise InvalidResponse(f"{endpoint.entity_id} has no coordinates")
            return coordinate, _state_name(state)
        if endpoint.coordinate is None:
            raise InvalidResponse("Route endpoint has no coordinates")
        return endpoint.coordinate, endpoint.label

    async def _async_build_target(
        self,
        target_entity_id: str,
        origin: Coordinate,
    ) -> RouteDetails | None:
        destination_state = self.hass.states.get(target_entity_id)
        destination = _state_coordinate(destination_state)
        if destination is None:
            self.errors[target_entity_id] = "Destination has no coordinates"
            return None
        try:
            route = await self._async_route_for(
                target_entity_id,
                origin,
                destination,
            )
        except (CannotConnect, InvalidResponse) as err:
            self.errors[target_entity_id] = str(err)
            return None

        return await self._async_build_details(
            origin_entity_id=self.origin_entity_id,
            destination_entity_id=target_entity_id,
            origin_name=_state_name(self.hass.states.get(self.origin_entity_id)),
            destination_name=_state_name(destination_state),
            route=route,
        )

    async def async_get_route_details(
        self,
        origin_entity_id: str,
        destination_entity_id: str,
        *,
        cache_key: str | None = None,
    ) -> RouteDetails:
        """Calculate complete details for any two coordinate-bearing entities."""
        origin_state = self.hass.states.get(origin_entity_id)
        destination_state = self.hass.states.get(destination_entity_id)
        origin = _state_coordinate(origin_state)
        destination = _state_coordinate(destination_state)
        if origin is None:
            raise InvalidResponse(f"{origin_entity_id} has no coordinates")
        if destination is None:
            raise InvalidResponse(f"{destination_entity_id} has no coordinates")
        route = await self._async_route_for(
            cache_key or f"{origin_entity_id}:{destination_entity_id}",
            origin,
            destination,
        )
        return await self._async_build_details(
            origin_entity_id=origin_entity_id,
            destination_entity_id=destination_entity_id,
            origin_name=_state_name(origin_state),
            destination_name=_state_name(destination_state),
            route=route,
        )

    async def _async_build_details(
        self,
        *,
        origin_entity_id: str,
        destination_entity_id: str,
        origin_name: str,
        destination_name: str,
        route: OsrmRoute,
    ) -> RouteDetails:
        """Match current Vegagerdin data against a route off the event loop."""
        metadata = self.metadata.data
        return await self.hass.async_add_executor_job(
            partial(
                build_route_details,
                origin_entity_id=origin_entity_id,
                destination_entity_id=destination_entity_id,
                origin_name=origin_name,
                destination_name=destination_name,
                route=route,
                roads=self.roads.data or (metadata.roads if metadata else {}),
                road_geometries=metadata.road_geometries if metadata else {},
                weather_stations=tuple((self.stations.data or {}).values()),
                cameras=tuple((self.webcams.data or {}).values()),
                traffic_counters=tuple((self.counters.data or {}).values()),
                notices=tuple(self.notices.data or ()),
                road_corridor_km=self.road_corridor_km,
                point_corridor_km=self.point_corridor_km,
            )
        )

    async def _async_route_for(
        self,
        target_entity_id: str,
        origin: Coordinate,
        destination: Coordinate,
    ) -> OsrmRoute:
        cached = self._route_cache.get(target_entity_id)
        if (
            cached is not None
            and coordinate_distance_km(cached.origin, origin) < 0.5
            and coordinate_distance_km(cached.destination, destination) < 0.5
        ):
            return cached.route
        route = await self.route_client.async_get_route(origin, destination)
        self._route_cache[target_entity_id] = _CachedRoute(
            origin=origin,
            destination=destination,
            route=route,
        )
        return route


def _state_coordinate(state: Any) -> Coordinate | None:
    """Return WGS84 coordinates from an HA state."""
    if state is None:
        return None
    try:
        latitude = float(state.attributes.get("latitude"))
        longitude = float(state.attributes.get("longitude"))
    except (TypeError, ValueError):
        return None
    return Coordinate(latitude=latitude, longitude=longitude)


def _state_name(state: Any) -> str:
    """Return a useful display name for an HA state."""
    if state is None:
        return "Unknown"
    return str(state.attributes.get("friendly_name") or state.entity_id)
