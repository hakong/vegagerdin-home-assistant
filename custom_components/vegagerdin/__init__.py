"""The Vegagerdin integration."""

from __future__ import annotations

import logging
from typing import Any

from .api import filter_notices
from .const import (
    ATTR_BBOX,
    ATTR_CATEGORIES,
    ATTR_DESTINATION_ENTITY_ID,
    ATTR_LANGUAGE,
    ATTR_NOTICE_KEYS,
    ATTR_ORIGIN_ENTITY_ID,
    ATTR_ROAD_CONDITION_IDS,
    ATTR_ROAD_NUMBERS,
    ATTR_TAGS,
    ATTRIBUTION,
    CONF_CAMERA_IDS,
    CONF_ENABLE_CAMERAS,
    CONF_ENABLE_ROUTE_SENSORS,
    CONF_ENABLE_ROAD_SUMMARIES,
    CONF_ENABLE_TRAFFIC_COUNTER_SENSORS,
    CONF_ENABLE_WEATHER_STATION_SENSORS,
    CONF_NOTICE_REGION_KEYS,
    CONF_OSRM_URL,
    CONF_ROAD_CONDITION_IDS,
    CONF_ROUTE_ORIGIN_ENTITY_ID,
    CONF_TRAFFIC_COUNTER_IDS,
    CONF_WEATHER_STATION_IDS,
    DEFAULT_ENABLE_CAMERAS,
    DEFAULT_ENABLE_ROUTE_SENSORS,
    DEFAULT_ENABLE_ROAD_SUMMARIES,
    DEFAULT_ENABLE_TRAFFIC_COUNTER_SENSORS,
    DEFAULT_ENABLE_WEATHER_STATION_SENSORS,
    DEFAULT_LANGUAGE,
    DEFAULT_OSRM_URL,
    DEFAULT_ROUTE_ORIGIN_ENTITY_ID,
    DOMAIN,
    ENTRY_TITLE,
    PLATFORMS,
    SERVICE_GET_CAMERA_IMAGES,
    SERVICE_GET_ROAD_DETAILS,
    SERVICE_GET_ROAD_NOTIFICATIONS,
    SERVICE_GET_ROUTE_DETAILS,
    SERVICE_GET_TRAFFIC_COUNTER_DETAILS,
    SERVICE_GET_WEATHER_STATION_MEASUREMENTS,
    SELECTED_ROUTE_ENTITY_PREFIX,
)

_LOGGER = logging.getLogger(__name__)

_ROAD_BINARY_SENSOR_NAMES = {
    "closed": ("Closed", "road_closed"),
    "roadwork": ("Roadwork", "roadwork"),
    "weight_restriction": ("Weight restriction", "weight_restriction"),
}

_WEATHER_STATION_SENSOR_NAMES = {
    "temperature": "Air temperature",
    "road_temperature": "Road temperature",
    "humidity": "Humidity",
    "wind_speed": "Wind speed",
    "wind_gust": "Wind gust",
    "wind_direction": "Wind direction",
    "traffic": "Station traffic",
}

_TRAFFIC_COUNTER_SENSOR_NAMES = {
    "traffic_15min": "Traffic last 15 minutes",
    "traffic_today": "Traffic today",
    "average_speed_15min": "Average speed last 15 minutes",
}

_ROUTE_ENTITY_KEYS = ("status", "notices", "cameras", "problem")


async def async_migrate_entry(hass: Any, entry: Any) -> bool:
    """Migrate old Vegagerdin config entries."""
    if entry.version < 2:
        _async_repair_entity_registry(hass, entry)
        hass.config_entries.async_update_entry(entry, version=2)
    if entry.version < 3:
        _async_prefix_route_entity_ids(hass)
        hass.config_entries.async_update_entry(entry, version=3)
    return True


def _async_prefix_route_entity_ids(hass: Any) -> None:
    """Prefix route entity IDs created before config-entry version 3."""
    from homeassistant.helpers import entity_registry as er

    entity_registry = er.async_get(hass)
    for entity in list(entity_registry.entities.values()):
        if (
            entity.platform != DOMAIN
            or not entity.unique_id
            or not entity.unique_id.startswith(f"{DOMAIN}_route_")
        ):
            continue
        entity_domain, _, object_id = entity.entity_id.partition(".")
        if object_id.startswith(f"{DOMAIN}_route_"):
            continue
        key = entity.unique_id.rsplit("_", 1)[-1]
        legacy_suffix = f"_route_{key}"
        if not object_id.endswith(legacy_suffix):
            continue
        route_name = object_id.removesuffix(legacy_suffix)
        new_entity_id = f"{entity_domain}.{DOMAIN}_route_{route_name}_{key}"
        if entity_registry.async_get(new_entity_id) is None:
            entity_registry.async_update_entity(
                entity.entity_id,
                new_entity_id=new_entity_id,
            )


async def async_setup_entry(hass: Any, entry: Any) -> bool:
    """Set up Vegagerdin from a config entry."""
    from homeassistant.helpers import aiohttp_client

    from .api import VegagerdinApiClient
    from .coordinator import (
        VegagerdinMetadataCoordinator,
        VegagerdinNoticeCoordinator,
        VegagerdinRoadConditionCoordinator,
        VegagerdinRouteCoordinator,
        VegagerdinRuntimeData,
        VegagerdinTrafficCounterCoordinator,
        VegagerdinWebcamCoordinator,
        VegagerdinWeatherStationCoordinator,
    )
    from .routing import VegagerdinRouteApiClient

    _async_register_services(hass)

    if entry.title != ENTRY_TITLE:
        hass.config_entries.async_update_entry(entry, title=ENTRY_TITLE)

    _async_repair_entity_registry(hass, entry)
    _async_prefix_route_entity_ids(hass)
    _async_cleanup_stale_registry_entries(
        hass,
        entry,
        selected_webcams=None,
    )

    session = aiohttp_client.async_get_clientsession(hass)
    client = VegagerdinApiClient(session)
    entry_config = entry.options or entry.data
    route_enabled = entry_config.get(
        CONF_ENABLE_ROUTE_SENSORS,
        DEFAULT_ENABLE_ROUTE_SENSORS,
    )
    route_client = (
        VegagerdinRouteApiClient(
            session,
            str(entry_config.get(CONF_OSRM_URL, DEFAULT_OSRM_URL)),
        )
        if route_enabled
        else None
    )
    metadata = VegagerdinMetadataCoordinator(hass, client, entry, route_client)
    road_conditions = VegagerdinRoadConditionCoordinator(hass, client, entry)
    notices = VegagerdinNoticeCoordinator(hass, client, entry)
    weather_stations = VegagerdinWeatherStationCoordinator(hass, client, entry)
    webcams = VegagerdinWebcamCoordinator(hass, client, entry)
    traffic_counters = VegagerdinTrafficCounterCoordinator(hass, client, entry)

    await metadata.async_config_entry_first_refresh()
    await road_conditions.async_config_entry_first_refresh()
    await notices.async_config_entry_first_refresh()

    if route_enabled or entry_config.get(
        CONF_ENABLE_WEATHER_STATION_SENSORS,
        DEFAULT_ENABLE_WEATHER_STATION_SENSORS,
    ):
        await weather_stations.async_config_entry_first_refresh()
    if route_enabled or entry_config.get(CONF_ENABLE_CAMERAS, DEFAULT_ENABLE_CAMERAS):
        await webcams.async_config_entry_first_refresh()
    if route_enabled or entry_config.get(
        CONF_ENABLE_TRAFFIC_COUNTER_SENSORS,
        DEFAULT_ENABLE_TRAFFIC_COUNTER_SENSORS,
    ):
        await traffic_counters.async_config_entry_first_refresh()

    routes = None
    if route_client is not None:
        routes = VegagerdinRouteCoordinator(
            hass,
            route_client,
            entry,
            metadata,
            road_conditions,
            notices,
            weather_stations,
            webcams,
            traffic_counters,
        )
        await routes.async_refresh()

    _async_cleanup_stale_registry_entries(
        hass,
        entry,
        selected_webcams=(
            camera
            for camera in (webcams.data or {}).values()
            if camera.camera_id
            in {int(item) for item in entry_config.get(CONF_CAMERA_IDS, [])}
        )
        if entry_config.get(CONF_ENABLE_CAMERAS, DEFAULT_ENABLE_CAMERAS)
        else (),
    )

    entry.runtime_data = VegagerdinRuntimeData(
        client=client,
        metadata=metadata,
        road_conditions=road_conditions,
        notices=notices,
        weather_stations=weather_stations,
        webcams=webcams,
        traffic_counters=traffic_counters,
        routes=routes,
        route_client=route_client,
    )

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    if routes is not None:
        entry.async_on_unload(routes.async_start_tracking())
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: Any, entry: Any) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(hass: Any, entry: Any) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


def _async_register_services(hass: Any) -> None:
    """Register response-returning actions."""
    if hass.data.setdefault(DOMAIN, {}).get("services_registered"):
        return

    import voluptuous as vol

    from homeassistant.const import CONF_ENTITY_ID
    from homeassistant.core import SupportsResponse
    from homeassistant.exceptions import HomeAssistantError
    import homeassistant.helpers.config_validation as cv
    from homeassistant.helpers import aiohttp_client

    from .api import VegagerdinApiClient

    async def async_road_details(call: Any) -> dict[str, Any]:
        client = VegagerdinApiClient(aiohttp_client.async_get_clientsession(hass))
        language = call.data.get(ATTR_LANGUAGE, DEFAULT_LANGUAGE)
        requested_ids = {
            str(road_id)
            for road_id in call.data.get(ATTR_ROAD_CONDITION_IDS, [])
        }
        roads = await client.async_get_road_conditions(language=language)
        if requested_ids:
            roads = [
                road for road in roads if road.road_condition_id in requested_ids
            ]
        return {
            "attribution": ATTRIBUTION,
            "roads": [road.as_dict() for road in roads],
        }

    async def async_road_notifications(call: Any) -> dict[str, Any]:
        client = VegagerdinApiClient(aiohttp_client.async_get_clientsession(hass))
        language = call.data.get(ATTR_LANGUAGE, DEFAULT_LANGUAGE)
        notices = await client.async_get_road_notifications(language=language)
        notices = filter_notices(
            notices,
            keys=call.data.get(ATTR_NOTICE_KEYS),
            road_numbers=call.data.get(ATTR_ROAD_NUMBERS),
            tags=call.data.get(ATTR_TAGS),
            categories=call.data.get(ATTR_CATEGORIES),
        )
        return {
            "attribution": ATTRIBUTION,
            "notices": [notice.as_dict() for notice in notices],
        }

    async def async_weather_station_measurements(call: Any) -> dict[str, Any]:
        client = VegagerdinApiClient(aiohttp_client.async_get_clientsession(hass))
        stations = await client.async_get_weather_station_measurements(
            call.data.get(CONF_WEATHER_STATION_IDS, []),
        )
        return {
            "attribution": ATTRIBUTION,
            "stations": [station.as_dict() for station in stations],
        }

    async def async_camera_images(call: Any) -> dict[str, Any]:
        client = VegagerdinApiClient(aiohttp_client.async_get_clientsession(hass))
        cameras = await client.async_get_webcams(
            camera_ids=call.data.get(CONF_CAMERA_IDS),
            bbox=call.data.get(ATTR_BBOX),
        )
        return {
            "attribution": ATTRIBUTION,
            "cameras": [camera.as_dict() for camera in cameras],
        }

    async def async_traffic_counter_details(call: Any) -> dict[str, Any]:
        client = VegagerdinApiClient(aiohttp_client.async_get_clientsession(hass))
        counters = await client.async_get_traffic_counters(
            counter_ids=call.data.get(CONF_TRAFFIC_COUNTER_IDS),
            bbox=call.data.get(ATTR_BBOX),
        )
        return {
            "attribution": ATTRIBUTION,
            "traffic_counters": [counter.as_dict() for counter in counters],
        }

    async def async_route_details(call: Any) -> dict[str, Any]:
        origin_entity_id = call.data.get(
            ATTR_ORIGIN_ENTITY_ID,
            DEFAULT_ROUTE_ORIGIN_ENTITY_ID,
        )
        destination_entity_id = call.data[ATTR_DESTINATION_ENTITY_ID]
        for entry in hass.config_entries.async_entries(DOMAIN):
            runtime = getattr(entry, "runtime_data", None)
            if runtime is None or runtime.routes is None:
                continue
            try:
                details = await runtime.routes.async_get_route_details(
                    origin_entity_id,
                    destination_entity_id,
                )
            except Exception as err:  # noqa: BLE001 - action boundary.
                raise HomeAssistantError(str(err)) from err
            return {
                "attribution": ATTRIBUTION,
                "route_details": details.as_dict(),
            }
        raise HomeAssistantError(
            "Enable route sensors and configure an OSRM URL first"
        )

    list_of_strings = vol.All(cv.ensure_list, [cv.string])
    list_of_ints = vol.All(cv.ensure_list, [vol.Coerce(int)])
    bbox_schema = vol.All(cv.ensure_list, vol.Length(min=4, max=4), [vol.Coerce(float)])

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_ROAD_DETAILS,
        async_road_details,
        schema=vol.Schema(
            {
                vol.Optional(ATTR_ROAD_CONDITION_IDS): list_of_strings,
                vol.Optional(ATTR_LANGUAGE, default=DEFAULT_LANGUAGE): cv.string,
                vol.Optional(CONF_ENTITY_ID): cv.entity_ids,
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_ROUTE_DETAILS,
        async_route_details,
        schema=vol.Schema(
            {
                vol.Required(ATTR_DESTINATION_ENTITY_ID): cv.entity_id,
                vol.Optional(
                    ATTR_ORIGIN_ENTITY_ID,
                    default=DEFAULT_ROUTE_ORIGIN_ENTITY_ID,
                ): cv.entity_id,
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_ROAD_NOTIFICATIONS,
        async_road_notifications,
        schema=vol.Schema(
            {
                vol.Optional(ATTR_LANGUAGE, default=DEFAULT_LANGUAGE): cv.string,
                vol.Optional(ATTR_NOTICE_KEYS): list_of_strings,
                vol.Optional(ATTR_ROAD_NUMBERS): list_of_strings,
                vol.Optional(ATTR_TAGS): list_of_strings,
                vol.Optional(ATTR_CATEGORIES): list_of_strings,
                vol.Optional(CONF_ENTITY_ID): cv.entity_ids,
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_WEATHER_STATION_MEASUREMENTS,
        async_weather_station_measurements,
        schema=vol.Schema({vol.Required(CONF_WEATHER_STATION_IDS): list_of_ints}),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_CAMERA_IMAGES,
        async_camera_images,
        schema=vol.Schema(
            {
                vol.Optional(CONF_CAMERA_IDS): list_of_ints,
                vol.Optional(ATTR_BBOX): bbox_schema,
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_TRAFFIC_COUNTER_DETAILS,
        async_traffic_counter_details,
        schema=vol.Schema(
            {
                vol.Optional(CONF_TRAFFIC_COUNTER_IDS): list_of_ints,
                vol.Optional(ATTR_BBOX): bbox_schema,
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )

    hass.data[DOMAIN]["services_registered"] = True
    _LOGGER.debug("Registered Vegagerdin response actions")


def _async_repair_entity_registry(hass: Any, entry: Any) -> None:
    """Remove bad registry entries created by early development versions."""
    from homeassistant.components.binary_sensor import DOMAIN as BINARY_SENSOR_DOMAIN
    from homeassistant.components.camera import DOMAIN as CAMERA_DOMAIN
    from homeassistant.helpers import entity_registry as er
    from homeassistant.helpers.entity_registry import RegistryEntryDisabler

    entity_registry = er.async_get(hass)
    entry_config = entry.options or entry.data
    camera_unique_ids = {
        f"{DOMAIN}_camera_{int(camera_id)}"
        for camera_id in entry_config.get(CONF_CAMERA_IDS, [])
    }

    for entity in list(entity_registry.entities.values()):
        if entity.platform != DOMAIN or not entity.unique_id:
            continue

        if (
            entity.entity_id.startswith(f"{CAMERA_DOMAIN}.")
            and entity.unique_id in camera_unique_ids
        ):
            disabled_by = getattr(entity.disabled_by, "value", entity.disabled_by)
            if disabled_by in (RegistryEntryDisabler.INTEGRATION.value, "integration"):
                entity_registry.async_remove(entity.entity_id)
            continue

        if entity.entity_id.startswith(f"{BINARY_SENSOR_DOMAIN}."):
            _async_repair_binary_sensor_entry(entity_registry, entity)
            continue

        _async_repair_sensor_entry(entity_registry, entity)


def _async_cleanup_stale_registry_entries(
    hass: Any,
    entry: Any,
    *,
    selected_webcams: Any | None,
) -> None:
    """Remove entities and devices that are no longer selected."""
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    from .notice_regions import suggest_notice_regions
    from .coordinator import route_target_entity_ids

    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)
    entry_config = entry.options or entry.data
    desired_unique_ids = _desired_entity_unique_ids(
        entry_config,
        selected_webcams=selected_webcams or (),
        suggested_notice_region_keys=suggest_notice_regions(hass),
        route_target_entity_ids=route_target_entity_ids(hass, entry_config),
    )
    cleanup_cameras = selected_webcams is not None
    removed_entities = 0

    for entity in list(entity_registry.entities.values()):
        if (
            entity.platform != DOMAIN
            or not entity.unique_id
            or not _is_managed_entity_unique_id(entity.unique_id)
            or entity.unique_id in desired_unique_ids
            or (
                not cleanup_cameras
                and entity.unique_id.startswith(f"{DOMAIN}_camera_")
            )
        ):
            continue
        entity_registry.async_remove(entity.entity_id)
        removed_entities += 1

    referenced_device_ids = {
        entity.device_id
        for entity in entity_registry.entities.values()
        if entity.device_id is not None
    }
    removed_devices = 0
    for device in list(device_registry.devices.values()):
        if (
            entry.entry_id not in device.config_entries
            or device.id in referenced_device_ids
            or not any(identifier[0] == DOMAIN for identifier in device.identifiers)
            or (not cleanup_cameras and _is_camera_device(device))
        ):
            continue
        device_registry.async_remove_device(device.id)
        removed_devices += 1

    if removed_entities or removed_devices:
        _LOGGER.debug(
            "Removed %s stale Vegagerdin entities and %s stale devices",
            removed_entities,
            removed_devices,
        )


def _is_camera_device(device: Any) -> bool:
    """Return whether a device registry entry is a Vegagerdin camera device."""
    return any(
        identifier[0] == DOMAIN and str(identifier[1]).startswith("camera:")
        for identifier in device.identifiers
    )


def _desired_entity_unique_ids(
    entry_config: dict[str, Any],
    *,
    selected_webcams: Any,
    suggested_notice_region_keys: list[str] | tuple[str, ...] = (),
    route_target_entity_ids: list[str] | tuple[str, ...] = (),
) -> set[str]:
    """Return entity unique IDs that should exist for the current options."""
    desired = {
        f"{DOMAIN}_road_notices",
        f"{DOMAIN}_important_notices",
    }
    notice_region_keys = entry_config.get(
        CONF_NOTICE_REGION_KEYS,
        suggested_notice_region_keys,
    )
    if notice_region_keys:
        desired.add(f"{DOMAIN}_regional_notices")

    if entry_config.get(CONF_ENABLE_ROAD_SUMMARIES, DEFAULT_ENABLE_ROAD_SUMMARIES):
        for road_id in entry_config.get(CONF_ROAD_CONDITION_IDS, []):
            road_id = str(road_id)
            desired.add(f"{DOMAIN}_{road_id}_condition")
            for key in _ROAD_BINARY_SENSOR_NAMES:
                desired.add(f"{DOMAIN}_{road_id}_{key}")

    if entry_config.get(
        CONF_ENABLE_WEATHER_STATION_SENSORS,
        DEFAULT_ENABLE_WEATHER_STATION_SENSORS,
    ):
        for station_id in entry_config.get(CONF_WEATHER_STATION_IDS, []):
            for key in _WEATHER_STATION_SENSOR_NAMES:
                desired.add(f"{DOMAIN}_station_{int(station_id)}_{key}")

    if entry_config.get(
        CONF_ENABLE_TRAFFIC_COUNTER_SENSORS,
        DEFAULT_ENABLE_TRAFFIC_COUNTER_SENSORS,
    ):
        for counter_id in entry_config.get(CONF_TRAFFIC_COUNTER_IDS, []):
            for key in _TRAFFIC_COUNTER_SENSOR_NAMES:
                desired.add(f"{DOMAIN}_counter_{int(counter_id)}_{key}")

    if entry_config.get(CONF_ENABLE_CAMERAS, DEFAULT_ENABLE_CAMERAS):
        for camera in selected_webcams:
            desired.add(f"{DOMAIN}_camera_{camera.image_id}")

    if entry_config.get(CONF_ENABLE_ROUTE_SENSORS, DEFAULT_ENABLE_ROUTE_SENSORS):
        from .routing import route_unique_id

        desired.update(
            f"{SELECTED_ROUTE_ENTITY_PREFIX}_{key}"
            for key in (
                "origin",
                "destination",
                "swap",
                "refresh",
                "status",
                "problem",
            )
        )

        origin_entity_id = str(
            entry_config.get(
                CONF_ROUTE_ORIGIN_ENTITY_ID,
                DEFAULT_ROUTE_ORIGIN_ENTITY_ID,
            )
        )
        for destination_entity_id in route_target_entity_ids:
            for key in _ROUTE_ENTITY_KEYS:
                desired.add(
                    route_unique_id(origin_entity_id, destination_entity_id, key)
                )

    return desired


def _is_managed_entity_unique_id(unique_id: str) -> bool:
    """Return whether this integration owns cleanup for the unique ID."""
    if unique_id in {
        f"{DOMAIN}_road_notices",
        f"{DOMAIN}_important_notices",
        f"{DOMAIN}_regional_notices",
    }:
        return True
    if unique_id.startswith(
        (
            f"{DOMAIN}_station_",
            f"{DOMAIN}_counter_",
            f"{DOMAIN}_camera_",
            f"{DOMAIN}_route_",
        )
    ):
        return True
    return (
        _match_unique_id_suffix(unique_id, _ROAD_BINARY_SENSOR_NAMES) is not None
        or (unique_id.startswith(f"{DOMAIN}_") and unique_id.endswith("_condition"))
    )


def _async_repair_binary_sensor_entry(entity_registry: Any, entity: Any) -> None:
    """Repair one road binary sensor registry entry."""
    match = _match_unique_id_suffix(entity.unique_id, _ROAD_BINARY_SENSOR_NAMES)
    if match is None:
        return

    road_id, key = match
    name, _ = _ROAD_BINARY_SENSOR_NAMES[key]
    update: dict[str, Any] = {}
    if (
        entity.name is None
        and entity.original_name != name
    ):
        update["original_name"] = name
    if "undefinedtype_singleton" in entity.entity_id:
        new_entity_id = f"binary_sensor.vegagerdin_{road_id}_{key}"
        if entity_registry.async_get(new_entity_id) is None:
            update["new_entity_id"] = new_entity_id
    if update:
        entity_registry.async_update_entity(entity.entity_id, **update)


def _async_repair_sensor_entry(entity_registry: Any, entity: Any) -> None:
    """Repair one sensor registry entry's integration-provided name."""
    weather_match = _match_unique_id_suffix(
        entity.unique_id,
        _WEATHER_STATION_SENSOR_NAMES,
    )
    if weather_match is not None:
        _, key = weather_match
        if (
            entity.name is None
            and entity.original_name != _WEATHER_STATION_SENSOR_NAMES[key]
        ):
            entity_registry.async_remove(entity.entity_id)
        return

    counter_match = _match_unique_id_suffix(
        entity.unique_id,
        _TRAFFIC_COUNTER_SENSOR_NAMES,
    )
    if counter_match is not None:
        _, key = counter_match
        if (
            entity.name is None
            and entity.original_name != _TRAFFIC_COUNTER_SENSOR_NAMES[key]
        ):
            entity_registry.async_remove(entity.entity_id)
        return


def _match_unique_id_suffix(
    unique_id: str,
    names: dict[str, Any],
) -> tuple[str, str] | None:
    """Return the object id and matched key for a Vegagerdin unique id."""
    prefix = f"{DOMAIN}_"
    if not unique_id.startswith(prefix):
        return None
    unique_tail = unique_id.removeprefix(prefix)
    for key in sorted(names, key=len, reverse=True):
        suffix = f"_{key}"
        if unique_tail.endswith(suffix):
            return unique_tail[: -len(suffix)], key
    return None
