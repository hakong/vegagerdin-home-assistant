"""Sensor platform for the Vegagerdin integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    DEGREE,
    EntityCategory,
    PERCENTAGE,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import RoadCondition, RoadNotice, TrafficCounter, WeatherStation
from .const import (
    ATTR_CONDITION_CATEGORY,
    ATTR_CONDITION_CODE,
    ATTR_COUNTER_ID,
    ATTR_LAST_UPDATE,
    ATTR_NOTICE_COUNT,
    ATTR_NOTICE_KEYS,
    ATTR_ROAD_CONDITION_ID,
    ATTR_ROAD_NAMES,
    ATTR_ROAD_NUMBERS,
    ATTR_SOURCE,
    ATTR_STATION_ID,
    ATTRIBUTION,
    CONF_NOTICE_REGION_KEYS,
    CONF_ENABLE_ROAD_SUMMARIES,
    CONF_ENABLE_ROUTE_SENSORS,
    CONF_ENABLE_TRAFFIC_COUNTER_SENSORS,
    CONF_ENABLE_WEATHER_STATION_SENSORS,
    CONF_ROAD_CONDITION_IDS,
    CONF_TRAFFIC_COUNTER_IDS,
    CONF_WEATHER_STATION_IDS,
    DEFAULT_ENABLE_ROAD_SUMMARIES,
    DEFAULT_ENABLE_ROUTE_SENSORS,
    DEFAULT_ENABLE_TRAFFIC_COUNTER_SENSORS,
    DEFAULT_ENABLE_WEATHER_STATION_SENSORS,
    DEFAULT_NOTICE_REGION_KEYS,
    DOMAIN,
    IMPORTANT_NOTICE_KEYS,
    INTEGRATION_NAME,
)
from .coordinator import (
    VegagerdinNoticeCoordinator,
    VegagerdinRoadConditionCoordinator,
    VegagerdinRouteCoordinator,
    VegagerdinRuntimeData,
    VegagerdinTrafficCounterCoordinator,
    VegagerdinWeatherStationCoordinator,
    route_dispatcher_signal,
)
from .notice_regions import suggest_notice_regions
from .routing import RouteDetails, route_entity_object_id, route_unique_id

NOTICE_ATTRIBUTE_LIMIT = 5


@dataclass(frozen=True, kw_only=True)
class WeatherStationSensorDescription(SensorEntityDescription):
    """Description for a weather station sensor."""

    value_fn: Callable[[WeatherStation], Any]


@dataclass(frozen=True, kw_only=True)
class TrafficCounterSensorDescription(SensorEntityDescription):
    """Description for a traffic counter sensor."""

    value_fn: Callable[[TrafficCounter], Any]


WEATHER_STATION_SENSORS: tuple[WeatherStationSensorDescription, ...] = (
    WeatherStationSensorDescription(
        key="temperature",
        name="Air temperature",
        translation_key="air_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda station: station.temperature,
    ),
    WeatherStationSensorDescription(
        key="road_temperature",
        name="Road temperature",
        translation_key="road_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda station: station.road_temperature,
    ),
    WeatherStationSensorDescription(
        key="humidity",
        name="Humidity",
        translation_key="humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda station: station.humidity,
    ),
    WeatherStationSensorDescription(
        key="wind_speed",
        name="Wind speed",
        translation_key="wind_speed",
        device_class=SensorDeviceClass.WIND_SPEED,
        native_unit_of_measurement=UnitOfSpeed.METERS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda station: station.wind.speed,
    ),
    WeatherStationSensorDescription(
        key="wind_gust",
        name="Wind gust",
        translation_key="wind_gust",
        device_class=SensorDeviceClass.WIND_SPEED,
        native_unit_of_measurement=UnitOfSpeed.METERS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda station: station.wind.gust,
    ),
    WeatherStationSensorDescription(
        key="wind_direction",
        name="Wind direction",
        translation_key="wind_direction",
        native_unit_of_measurement=DEGREE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda station: station.wind_direction.degrees,
    ),
    WeatherStationSensorDescription(
        key="traffic",
        name="Station traffic",
        translation_key="station_traffic",
        native_unit_of_measurement="vehicles",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda station: station.traffic,
    ),
)

TRAFFIC_COUNTER_SENSORS: tuple[TrafficCounterSensorDescription, ...] = (
    TrafficCounterSensorDescription(
        key="traffic_15min",
        name="Traffic last 15 minutes",
        translation_key="traffic_15min",
        native_unit_of_measurement="vehicles",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda counter: counter.traffic_15min,
    ),
    TrafficCounterSensorDescription(
        key="traffic_today",
        name="Traffic today",
        translation_key="traffic_today",
        native_unit_of_measurement="vehicles",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda counter: counter.traffic_today,
    ),
    TrafficCounterSensorDescription(
        key="average_speed_15min",
        name="Average speed last 15 minutes",
        translation_key="average_speed_15min",
        native_unit_of_measurement="km/h",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda counter: counter.average_speed_15min,
    ),
)


async def async_setup_entry(
    hass: Any,
    entry: Any,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Vegagerdin sensors from a config entry."""
    runtime: VegagerdinRuntimeData = entry.runtime_data
    entry_config = entry.options or entry.data

    entities: list[SensorEntity] = [
        VegagerdinNoticeCountSensor(runtime.notices),
        VegagerdinImportantNoticeSensor(runtime.notices),
    ]
    notice_region_keys = [
        str(item)
        for item in entry_config.get(
            CONF_NOTICE_REGION_KEYS,
            suggest_notice_regions(hass) or DEFAULT_NOTICE_REGION_KEYS,
        )
    ]
    if notice_region_keys:
        entities.append(
            VegagerdinRegionalNoticeSensor(runtime.notices, notice_region_keys),
        )
    _async_repair_sensor_registry_names(hass, entry_config)

    if entry_config.get(CONF_ENABLE_ROAD_SUMMARIES, DEFAULT_ENABLE_ROAD_SUMMARIES):
        entities.extend(
            VegagerdinRoadConditionSensor(runtime.road_conditions, road_id)
            for road_id in entry_config.get(CONF_ROAD_CONDITION_IDS, [])
        )

    if entry_config.get(
        CONF_ENABLE_WEATHER_STATION_SENSORS,
        DEFAULT_ENABLE_WEATHER_STATION_SENSORS,
    ):
        for station_id in entry_config.get(CONF_WEATHER_STATION_IDS, []):
            entities.extend(
                VegagerdinWeatherStationSensor(
                    runtime.weather_stations,
                    int(station_id),
                    description,
                )
                for description in WEATHER_STATION_SENSORS
            )

    if entry_config.get(
        CONF_ENABLE_TRAFFIC_COUNTER_SENSORS,
        DEFAULT_ENABLE_TRAFFIC_COUNTER_SENSORS,
    ):
        for counter_id in entry_config.get(CONF_TRAFFIC_COUNTER_IDS, []):
            entities.extend(
                VegagerdinTrafficCounterSensor(
                    runtime.traffic_counters,
                    int(counter_id),
                    description,
                )
                for description in TRAFFIC_COUNTER_SENSORS
            )

    if (
        entry_config.get(CONF_ENABLE_ROUTE_SENSORS, DEFAULT_ENABLE_ROUTE_SENSORS)
        and runtime.routes is not None
    ):
        known_targets = set(runtime.routes.target_entity_ids)
        entities.extend(
            entity
            for target_entity_id in sorted(known_targets)
            for entity in _route_sensor_entities(runtime.routes, target_entity_id)
        )

        def async_add_route_targets(target_entity_ids: tuple[str, ...]) -> None:
            new_targets = set(target_entity_ids) - known_targets
            if not new_targets:
                return
            known_targets.update(new_targets)
            async_add_entities(
                entity
                for target_entity_id in sorted(new_targets)
                for entity in _route_sensor_entities(
                    runtime.routes,
                    target_entity_id,
                )
            )

        entry.async_on_unload(
            async_dispatcher_connect(
                hass,
                route_dispatcher_signal(entry.entry_id),
                async_add_route_targets,
            )
        )

    async_add_entities(entities)


def _route_sensor_entities(
    coordinator: VegagerdinRouteCoordinator,
    destination_entity_id: str,
) -> tuple[VegagerdinRouteSensor, ...]:
    """Return dashboard sensors for one route destination."""
    return tuple(
        VegagerdinRouteSensor(coordinator, destination_entity_id, key)
        for key in ("status", "notices", "cameras")
    )


class VegagerdinRouteSensor(
    CoordinatorEntity[VegagerdinRouteCoordinator],
    SensorEntity,
):
    """Compact route status, notice count, or camera count sensor."""

    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION

    def __init__(
        self,
        coordinator: VegagerdinRouteCoordinator,
        destination_entity_id: str,
        key: str,
    ) -> None:
        """Initialize a route sensor."""
        super().__init__(coordinator)
        self._destination_entity_id = destination_entity_id
        self._key = key
        self._attr_unique_id = route_unique_id(
            coordinator.origin_entity_id,
            destination_entity_id,
            key,
        )
        self._attr_suggested_object_id = route_entity_object_id(
            coordinator.origin_entity_id,
            destination_entity_id,
            key,
        )
        self._attr_name = {
            "status": "Route status",
            "notices": "Route notices",
            "cameras": "Route cameras",
        }[key]
        self._attr_translation_key = f"route_{key}"
        self._attr_icon = {
            "status": "mdi:routes",
            "notices": "mdi:alert-road",
            "cameras": "mdi:cctv",
        }[key]

    @property
    def available(self) -> bool:
        """Return whether route details are available."""
        return super().available and self._details is not None

    @property
    def native_value(self) -> str | int | None:
        """Return the compact route value."""
        details = self._details
        if details is None:
            return None
        if self._key == "status":
            return details.status
        if self._key == "notices":
            return len(details.notices)
        return len(details.cameras)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return compact route metadata without heavy result lists."""
        details = self._details
        attributes: dict[str, Any] = {
            "origin_entity_id": self.coordinator.origin_entity_id,
            "destination_entity_id": self._destination_entity_id,
            ATTR_SOURCE: "osrm+vegagerdin",
        }
        if details is None:
            error = self.coordinator.errors.get(self._destination_entity_id)
            if error:
                attributes["error"] = error
            return attributes

        attributes.update(
            {
                "distance_km": round(details.route.distance_km, 2),
                "duration_minutes": round(details.route.duration_minutes, 1),
            }
        )
        if self._key == "status":
            attributes.update(_route_status_attributes(details))
        elif self._key == "notices" and details.notices:
            latest = details.notices[0]
            attributes.update(
                {
                    "latest_notice": latest.text,
                    "latest_notice_category": latest.category,
                    "latest_notice_date": latest.date.isoformat()
                    if latest.date
                    else None,
                }
            )
        elif self._key == "cameras" and details.cameras:
            nearest = details.cameras[0]
            attributes.update(
                {
                    "nearest_camera": nearest.name,
                    "nearest_camera_id": nearest.item_id,
                    "nearest_camera_image_url": nearest.data.get("image_url"),
                }
            )
        return attributes

    @property
    def device_info(self) -> DeviceInfo:
        """Return one device for the route."""
        details = self._details
        name = details.route_name if details else self._fallback_route_name
        return DeviceInfo(
            identifiers={
                (
                    DOMAIN,
                    "route:"
                    f"{self.coordinator.origin_entity_id}:"
                    f"{self._destination_entity_id}",
                )
            },
            name=name,
            manufacturer=INTEGRATION_NAME,
        )

    @property
    def _fallback_route_name(self) -> str:
        origin = self.coordinator.hass.states.get(self.coordinator.origin_entity_id)
        destination = self.coordinator.hass.states.get(self._destination_entity_id)
        origin_name = origin.attributes.get("friendly_name") if origin else None
        destination_name = (
            destination.attributes.get("friendly_name") if destination else None
        )
        return (
            f"{origin_name or self.coordinator.origin_entity_id} to "
            f"{destination_name or self._destination_entity_id}"
        )

    @property
    def _details(self) -> RouteDetails | None:
        return (self.coordinator.data or {}).get(self._destination_entity_id)


def _route_status_attributes(details: RouteDetails) -> dict[str, Any]:
    """Return dashboard-sized route status details."""
    return {
        "road_sections": len(details.roads),
        "closures": details.closure_count,
        "roadworks": details.roadwork_count,
        "weight_restrictions": details.restriction_count,
        "notices": len(details.notices),
        "weather_stations": len(details.weather_stations),
        "cameras": len(details.cameras),
        "traffic_counters": len(details.traffic_counters),
        "maximum_wind_gust": details.maximum_wind_gust,
        "minimum_road_temperature": details.minimum_road_temperature,
        "road_segments": details.segment_summaries,
    }


class VegagerdinNoticeCountSensor(
    CoordinatorEntity[VegagerdinNoticeCoordinator],
    SensorEntity,
):
    """Sensor for active road notice count."""

    _attr_has_entity_name = False
    _attr_name = "Vegagerðin road notices"
    _attr_translation_key = "road_notices"
    _attr_unique_id = f"{DOMAIN}_road_notices"
    _attr_icon = "mdi:alert-road"
    _attr_attribution = ATTRIBUTION

    @property
    def native_value(self) -> int | None:
        """Return the active notice count."""
        if self.coordinator.data is None:
            return None
        return len(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return compact notice metadata."""
        notices = self.coordinator.data or ()
        categories = sorted(
            {notice.category for notice in notices if notice.category}
        )
        return {
            ATTR_NOTICE_COUNT: len(notices),
            "categories": categories,
            ATTR_SOURCE: "umferdin_is_graphql",
        }


class VegagerdinImportantNoticeSensor(
    CoordinatorEntity[VegagerdinNoticeCoordinator],
    SensorEntity,
):
    """Sensor for high-priority and countrywide notices."""

    _attr_has_entity_name = False
    _attr_name = "Vegagerðin important notices"
    _attr_translation_key = "important_notices"
    _attr_unique_id = f"{DOMAIN}_important_notices"
    _attr_icon = "mdi:alert-decagram"
    _attr_attribution = ATTRIBUTION

    @property
    def native_value(self) -> int | None:
        """Return the important notice count."""
        if self.coordinator.data is None:
            return None
        return len(_filter_notices_by_key(self.coordinator.data, IMPORTANT_NOTICE_KEYS))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return useful important notice details."""
        notices = _filter_notices_by_key(
            self.coordinator.data or (),
            IMPORTANT_NOTICE_KEYS,
        )
        return _notice_attributes(
            notices,
            notice_keys=IMPORTANT_NOTICE_KEYS,
        )


class VegagerdinRegionalNoticeSensor(
    CoordinatorEntity[VegagerdinNoticeCoordinator],
    SensorEntity,
):
    """Sensor for notices in selected user regions."""

    _attr_has_entity_name = False
    _attr_name = "Vegagerðin regional notices"
    _attr_translation_key = "regional_notices"
    _attr_unique_id = f"{DOMAIN}_regional_notices"
    _attr_icon = "mdi:map-alert"
    _attr_attribution = ATTRIBUTION

    def __init__(
        self,
        coordinator: VegagerdinNoticeCoordinator,
        notice_region_keys: list[str],
    ) -> None:
        """Initialize the regional notice sensor."""
        super().__init__(coordinator)
        self._notice_region_keys = tuple(dict.fromkeys(notice_region_keys))

    @property
    def native_value(self) -> int | None:
        """Return the selected-region notice count."""
        if self.coordinator.data is None:
            return None
        return len(
            _filter_notices_by_key(
                self.coordinator.data,
                self._notice_region_keys,
            )
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return useful regional notice details."""
        notices = _filter_notices_by_key(
            self.coordinator.data or (),
            self._notice_region_keys,
        )
        return _notice_attributes(
            notices,
            notice_keys=self._notice_region_keys,
        )


def _filter_notices_by_key(
    notices: tuple[RoadNotice, ...],
    notice_keys: tuple[str, ...],
) -> list[RoadNotice]:
    """Return notices whose API key matches one of the requested keys."""
    wanted_keys = {key.casefold() for key in notice_keys}
    return sorted(
        [
            notice
            for notice in notices
            if (notice.key or "").casefold() in wanted_keys
        ],
        key=lambda notice: notice.date.timestamp() if notice.date else 0,
        reverse=True,
    )


def _notice_attributes(
    notices: list[RoadNotice],
    *,
    notice_keys: tuple[str, ...],
) -> dict[str, Any]:
    """Return compact notice attributes for dashboards and templates."""
    latest_notice = _notice_summary(notices[0]) if notices else None
    return {
        ATTR_NOTICE_COUNT: len(notices),
        ATTR_NOTICE_KEYS: list(notice_keys),
        "latest_notice": latest_notice,
        "notices": [
            _notice_summary(notice)
            for notice in notices[:NOTICE_ATTRIBUTE_LIMIT]
        ],
        "categories": sorted(
            {notice.category for notice in notices if notice.category}
        ),
        ATTR_SOURCE: "umferdin_is_graphql",
    }


def _notice_summary(notice: RoadNotice) -> dict[str, Any]:
    """Return a compact notice dictionary."""
    return {
        "id": notice.notice_id,
        "key": notice.key,
        "category": notice.category,
        "sub_category": notice.sub_category,
        "text": notice.text,
        "tags": list(notice.tags),
        "date": notice.date.isoformat() if notice.date else None,
    }


class VegagerdinRoadConditionSensor(
    CoordinatorEntity[VegagerdinRoadConditionCoordinator],
    SensorEntity,
):
    """Sensor for a selected road section condition."""

    _attr_has_entity_name = True
    _attr_translation_key = "road_condition"
    _attr_icon = "mdi:road-variant"
    _attr_attribution = ATTRIBUTION

    def __init__(
        self,
        coordinator: VegagerdinRoadConditionCoordinator,
        road_condition_id: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._road_condition_id = str(road_condition_id)
        self._attr_unique_id = f"{DOMAIN}_{self._road_condition_id}_condition"

    @property
    def name(self) -> str | None:
        """Return entity name."""
        road = self._road
        if road is None:
            return f"Road {self._road_condition_id} condition"
        return f"{road.name} condition"

    @property
    def native_value(self) -> str | None:
        """Return the condition description/category."""
        road = self._road
        if road is None:
            return None
        return (
            road.condition.description
            or road.condition.category
            or road.condition.code
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return compact road attributes."""
        road = self._road
        if road is None:
            return {ATTR_ROAD_CONDITION_ID: self._road_condition_id}
        return {
            ATTR_ROAD_CONDITION_ID: road.road_condition_id,
            ATTR_ROAD_NUMBERS: list(road.road_numbers),
            ATTR_ROAD_NAMES: list(road.road_names),
            ATTR_CONDITION_CODE: road.condition.code,
            ATTR_CONDITION_CATEGORY: road.condition.category,
            ATTR_LAST_UPDATE: road.last_update.isoformat()
            if road.last_update
            else None,
            ATTR_SOURCE: road.source,
        }

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        road = self._road
        return DeviceInfo(
            identifiers={(DOMAIN, f"road:{self._road_condition_id}")},
            name=road.name if road else f"Road {self._road_condition_id}",
            manufacturer=INTEGRATION_NAME,
        )

    @property
    def _road(self) -> RoadCondition | None:
        return (self.coordinator.data or {}).get(self._road_condition_id)


class VegagerdinWeatherStationSensor(
    CoordinatorEntity[VegagerdinWeatherStationCoordinator],
    SensorEntity,
):
    """Optional weather station diagnostic sensor."""

    entity_description: WeatherStationSensorDescription
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_attribution = ATTRIBUTION

    def __init__(
        self,
        coordinator: VegagerdinWeatherStationCoordinator,
        station_id: int,
        description: WeatherStationSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._station_id = int(station_id)
        self.entity_description = description
        self._attr_name = str(description.name)
        self._attr_unique_id = f"{DOMAIN}_station_{station_id}_{description.key}"

    @property
    def available(self) -> bool:
        """Return if the sensor has a value."""
        return super().available and self.native_value is not None

    @property
    def native_value(self) -> Any:
        """Return the station value."""
        station = self._station
        if station is None:
            return None
        return self.entity_description.value_fn(station)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return station attributes."""
        station = self._station
        return {
            ATTR_STATION_ID: self._station_id,
            ATTR_LAST_UPDATE: station.last_update.isoformat()
            if station and station.last_update
            else None,
            ATTR_SOURCE: station.source if station else None,
        }

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        station = self._station
        return DeviceInfo(
            identifiers={(DOMAIN, f"weather_station:{self._station_id}")},
            name=station.name if station else f"Weather station {self._station_id}",
            manufacturer=INTEGRATION_NAME,
        )

    @property
    def _station(self) -> WeatherStation | None:
        return (self.coordinator.data or {}).get(self._station_id)


class VegagerdinTrafficCounterSensor(
    CoordinatorEntity[VegagerdinTrafficCounterCoordinator],
    SensorEntity,
):
    """Optional traffic counter sensor."""

    entity_description: TrafficCounterSensorDescription
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_attribution = ATTRIBUTION

    def __init__(
        self,
        coordinator: VegagerdinTrafficCounterCoordinator,
        counter_id: int,
        description: TrafficCounterSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._counter_id = int(counter_id)
        self.entity_description = description
        self._attr_name = str(description.name)
        self._attr_unique_id = f"{DOMAIN}_counter_{counter_id}_{description.key}"

    @property
    def available(self) -> bool:
        """Return if the sensor has a value."""
        return super().available and self.native_value is not None

    @property
    def native_value(self) -> Any:
        """Return the counter value."""
        counter = self._counter
        if counter is None:
            return None
        return self.entity_description.value_fn(counter)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return counter attributes."""
        counter = self._counter
        return {
            ATTR_COUNTER_ID: self._counter_id,
            ATTR_LAST_UPDATE: counter.last_data.isoformat()
            if counter and counter.last_data
            else None,
            "direction": counter.direction if counter else None,
            ATTR_SOURCE: counter.source if counter else None,
        }

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        counter = self._counter
        return DeviceInfo(
            identifiers={(DOMAIN, f"traffic_counter:{self._counter_id}")},
            name=counter.name if counter else f"Traffic counter {self._counter_id}",
            manufacturer=INTEGRATION_NAME,
        )

    @property
    def _counter(self) -> TrafficCounter | None:
        return (self.coordinator.data or {}).get(self._counter_id)


def _async_repair_sensor_registry_names(
    hass: Any,
    entry_config: dict[str, Any],
) -> None:
    """Update original names for existing sensors created with fallback names."""
    entity_registry = er.async_get(hass)
    weather_names = {
        description.key: description.name
        for description in WEATHER_STATION_SENSORS
        if description.name
    }
    counter_names = {
        description.key: description.name
        for description in TRAFFIC_COUNTER_SENSORS
        if description.name
    }

    for station_id in entry_config.get(CONF_WEATHER_STATION_IDS, []):
        for key, name in weather_names.items():
            _async_update_original_name(
                entity_registry,
                f"{DOMAIN}_station_{int(station_id)}_{key}",
                name,
            )

    for counter_id in entry_config.get(CONF_TRAFFIC_COUNTER_IDS, []):
        for key, name in counter_names.items():
            _async_update_original_name(
                entity_registry,
                f"{DOMAIN}_counter_{int(counter_id)}_{key}",
                name,
            )


def _async_update_original_name(
    entity_registry: Any,
    unique_id: str,
    name: str,
) -> None:
    """Update an entity's integration-provided display name."""
    for entity in entity_registry.entities.values():
        if entity.platform != DOMAIN or entity.unique_id != unique_id:
            continue
        if entity.original_name == name:
            return
        entity_registry.async_update_entity(
            entity.entity_id,
            original_name=name,
        )
        return
