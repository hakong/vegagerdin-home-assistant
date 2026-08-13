"""Config flow for the Vegagerdin integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import aiohttp_client, selector

from .api import (
    CannotConnect,
    InvalidResponse,
    RoadCondition,
    TrafficCounter,
    VegagerdinApiClient,
    VegagerdinCamera,
    WeatherStation,
)
from .const import (
    CONF_CAMERA_IDS,
    CONF_CAMERA_RADIUS_KM,
    CONF_COVERAGE_CENTER,
    CONF_ENABLE_CAMERAS,
    CONF_ENABLE_ROUTE_SENSORS,
    CONF_ENABLE_ROAD_SUMMARIES,
    CONF_ENABLE_TRAFFIC_COUNTER_SENSORS,
    CONF_ENABLE_WEATHER_STATION_SENSORS,
    CONF_LANGUAGE,
    CONF_NOTICE_REGION_KEYS,
    CONF_OSRM_URL,
    CONF_REGISTER_LOVELACE_CARD,
    CONF_ROAD_CONDITION_IDS,
    CONF_ROAD_CONDITION_RADIUS_KM,
    CONF_ROUTE_INCLUDE_ZONES,
    CONF_ROUTE_ORIGIN_ENTITY_ID,
    CONF_ROUTE_POINT_CORRIDOR_KM,
    CONF_ROUTE_ROAD_CORRIDOR_KM,
    CONF_ROUTE_TRACKER_ENTITY_IDS,
    CONF_TRAFFIC_COUNTER_IDS,
    CONF_TRAFFIC_COUNTER_RADIUS_KM,
    CONF_WEATHER_STATION_IDS,
    CONF_WEATHER_STATION_RADIUS_KM,
    DEFAULT_CAMERA_RADIUS_KM,
    DEFAULT_COVERAGE_CENTER,
    DEFAULT_ENABLE_CAMERAS,
    DEFAULT_ENABLE_ROUTE_SENSORS,
    DEFAULT_ENABLE_ROAD_SUMMARIES,
    DEFAULT_ENABLE_TRAFFIC_COUNTER_SENSORS,
    DEFAULT_ENABLE_WEATHER_STATION_SENSORS,
    DEFAULT_LANGUAGE,
    DEFAULT_NOTICE_REGION_KEYS,
    DEFAULT_OSRM_URL,
    DEFAULT_REGISTER_LOVELACE_CARD,
    DEFAULT_ROAD_CONDITION_RADIUS_KM,
    DEFAULT_ROUTE_INCLUDE_ZONES,
    DEFAULT_ROUTE_ORIGIN_ENTITY_ID,
    DEFAULT_ROUTE_POINT_CORRIDOR_KM,
    DEFAULT_ROUTE_ROAD_CORRIDOR_KM,
    DEFAULT_ROUTE_TRACKER_ENTITY_IDS,
    DEFAULT_TRAFFIC_COUNTER_RADIUS_KM,
    DEFAULT_WEATHER_STATION_RADIUS_KM,
    DOMAIN,
    ENTRY_TITLE,
    NOTICE_REGION_OPTIONS,
)
from .coverage import objects_within_radius
from .notice_regions import suggest_notice_regions

CONF_START_EMPTY = "start_empty"


@dataclass(slots=True)
class MetadataSelection:
    """Metadata held during a config/options flow."""

    roads: dict[str, RoadCondition]
    weather_stations: dict[int, WeatherStation]
    cameras: dict[int, VegagerdinCamera]
    camera_image_counts: dict[int, int]
    traffic_counters: dict[int, TrafficCounter]


@dataclass(slots=True)
class FlowSettings:
    """Settings chosen before selecting favorites."""

    language: str = DEFAULT_LANGUAGE
    enable_road_summaries: bool = DEFAULT_ENABLE_ROAD_SUMMARIES
    enable_weather_station_sensors: bool = DEFAULT_ENABLE_WEATHER_STATION_SENSORS
    enable_traffic_counter_sensors: bool = DEFAULT_ENABLE_TRAFFIC_COUNTER_SENSORS
    enable_cameras: bool = DEFAULT_ENABLE_CAMERAS
    enable_route_sensors: bool = DEFAULT_ENABLE_ROUTE_SENSORS
    register_lovelace_card: bool = DEFAULT_REGISTER_LOVELACE_CARD
    osrm_url: str = DEFAULT_OSRM_URL
    route_origin_entity_id: str = DEFAULT_ROUTE_ORIGIN_ENTITY_ID
    route_include_zones: bool = DEFAULT_ROUTE_INCLUDE_ZONES
    route_tracker_entity_ids: tuple[str, ...] = DEFAULT_ROUTE_TRACKER_ENTITY_IDS
    route_road_corridor_km: float = DEFAULT_ROUTE_ROAD_CORRIDOR_KM
    route_point_corridor_km: float = DEFAULT_ROUTE_POINT_CORRIDOR_KM
    start_empty: bool = False

    def as_dict(self) -> dict[str, Any]:
        """Return settings in config-entry format."""
        return {
            CONF_LANGUAGE: self.language,
            CONF_ENABLE_ROAD_SUMMARIES: self.enable_road_summaries,
            CONF_ENABLE_WEATHER_STATION_SENSORS: (
                self.enable_weather_station_sensors
            ),
            CONF_ENABLE_TRAFFIC_COUNTER_SENSORS: (
                self.enable_traffic_counter_sensors
            ),
            CONF_ENABLE_CAMERAS: self.enable_cameras,
            CONF_ENABLE_ROUTE_SENSORS: self.enable_route_sensors,
            CONF_REGISTER_LOVELACE_CARD: self.register_lovelace_card,
            CONF_OSRM_URL: self.osrm_url,
            CONF_ROUTE_ORIGIN_ENTITY_ID: self.route_origin_entity_id,
            CONF_ROUTE_INCLUDE_ZONES: self.route_include_zones,
            CONF_ROUTE_TRACKER_ENTITY_IDS: list(self.route_tracker_entity_ids),
            CONF_ROUTE_ROAD_CORRIDOR_KM: self.route_road_corridor_km,
            CONF_ROUTE_POINT_CORRIDOR_KM: self.route_point_corridor_km,
        }


@dataclass(slots=True)
class CoverageSettings:
    """Coverage settings used to generate favorite suggestions."""

    center: str = DEFAULT_COVERAGE_CENTER
    road_condition_radius_km: float = DEFAULT_ROAD_CONDITION_RADIUS_KM
    camera_radius_km: float = DEFAULT_CAMERA_RADIUS_KM
    weather_station_radius_km: float = DEFAULT_WEATHER_STATION_RADIUS_KM
    traffic_counter_radius_km: float = DEFAULT_TRAFFIC_COUNTER_RADIUS_KM

    def as_dict(self) -> dict[str, Any]:
        """Return settings in config-entry format."""
        return {
            CONF_COVERAGE_CENTER: self.center,
            CONF_ROAD_CONDITION_RADIUS_KM: self.road_condition_radius_km,
            CONF_CAMERA_RADIUS_KM: self.camera_radius_km,
            CONF_WEATHER_STATION_RADIUS_KM: self.weather_station_radius_km,
            CONF_TRAFFIC_COUNTER_RADIUS_KM: self.traffic_counter_radius_km,
        }


class VegagerdinConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Vegagerdin."""

    VERSION = 3

    def __init__(self) -> None:
        """Initialize the flow."""
        self._metadata: MetadataSelection | None = None
        self._settings = FlowSettings()
        self._coverage = CoverageSettings()

    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry) -> VegagerdinOptionsFlow:
        """Create the options flow."""
        return VegagerdinOptionsFlow(config_entry)

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Choose entity settings before fetching metadata."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=_settings_schema(self.hass, self._settings),
                errors={},
            )

        self._settings = _settings_from_input(user_input)
        errors: dict[str, str] = {}
        if self._settings.enable_route_sensors and not self._settings.osrm_url:
            errors[CONF_OSRM_URL] = "required"
            return self.async_show_form(
                step_id="user",
                data_schema=_settings_schema(self.hass, self._settings),
                errors=errors,
            )
        try:
            self._metadata = await self._async_fetch_metadata(
                self._settings.language,
            )
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidResponse:
            errors["base"] = "invalid_response"
        else:
            return await self.async_step_coverage()

        return self.async_show_form(
            step_id="user",
            data_schema=_settings_schema(self.hass, self._settings),
            errors=errors,
        )

    async def async_step_coverage(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Choose coverage suggestions before selecting favorites."""
        if self._metadata is None:
            return await self.async_step_user()

        if user_input is not None:
            self._coverage = _coverage_from_input(user_input)
            return await self.async_step_select()

        return self.async_show_form(
            step_id="coverage",
            data_schema=_coverage_schema(self.hass, self._coverage),
            errors={},
        )

    async def async_step_select(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Select favorite roads/stations/cameras/counters."""
        metadata = self._metadata
        if metadata is None:
            return await self.async_step_user()

        if user_input is not None:
            entry_data = _entry_data(self._settings, self._coverage, user_input)
            return self.async_create_entry(title=ENTRY_TITLE, data=entry_data)

        return self.async_show_form(
            step_id="select",
            data_schema=_selection_schema(
                metadata,
                defaults=_generated_defaults(
                    metadata,
                    self.hass,
                    self._coverage,
                    _empty_defaults(self.hass),
                ),
            ),
            errors={},
        )

    async def _async_fetch_metadata(self, language: str) -> MetadataSelection:
        client = VegagerdinApiClient(aiohttp_client.async_get_clientsession(self.hass))
        roads = await client.async_get_road_conditions(language=language)
        weather_stations = await client.async_get_weather_stations()
        cameras = await client.async_get_webcams()
        counters = await client.async_get_traffic_counters()
        return MetadataSelection(
            roads={road.road_condition_id: road for road in roads},
            weather_stations={
                station.station_id: station for station in weather_stations
            },
            cameras={camera.camera_id: camera for camera in cameras},
            camera_image_counts=_camera_image_counts(cameras),
            traffic_counters={counter.counter_id: counter for counter in counters},
        )


class VegagerdinOptionsFlow(config_entries.OptionsFlow):
    """Handle Vegagerdin options."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize the options flow."""
        self._config_entry = config_entry
        self._metadata: MetadataSelection | None = None
        self._settings = _settings_from_entry(config_entry)
        self._coverage = _coverage_from_entry(config_entry)

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Choose entity settings before selecting favorites."""
        if user_input is None:
            return self.async_show_form(
                step_id="init",
                data_schema=_settings_schema(
                    self.hass,
                    self._settings,
                    include_start_empty=True,
                ),
                errors={},
            )

        self._settings = _settings_from_input(user_input)
        errors: dict[str, str] = {}
        if self._settings.enable_route_sensors and not self._settings.osrm_url:
            errors[CONF_OSRM_URL] = "required"
            return self.async_show_form(
                step_id="init",
                data_schema=_settings_schema(
                    self.hass,
                    self._settings,
                    include_start_empty=True,
                ),
                errors=errors,
            )
        try:
            self._metadata = await self._async_fetch_metadata(
                self._settings.language,
            )
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidResponse:
            errors["base"] = "invalid_response"
        else:
            return await self.async_step_coverage()

        return self.async_show_form(
            step_id="init",
            data_schema=_settings_schema(
                self.hass,
                self._settings,
                include_start_empty=True,
            ),
            errors=errors,
        )

    async def async_step_coverage(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Choose coverage suggestions before selecting favorites."""
        if self._metadata is None:
            return await self.async_step_init()

        if user_input is not None:
            self._coverage = _coverage_from_input(user_input)
            return await self.async_step_select()

        return self.async_show_form(
            step_id="coverage",
            data_schema=_coverage_schema(self.hass, self._coverage),
            errors={},
        )

    async def async_step_select(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Update favorite selections."""
        metadata = self._metadata
        if metadata is None:
            return await self.async_step_init()

        if user_input is not None:
            entry_data = _entry_data(self._settings, self._coverage, user_input)
            self.hass.config_entries.async_update_entry(
                self._config_entry,
                title=ENTRY_TITLE,
                data=entry_data,
                options=entry_data,
            )
            return self.async_create_entry(title="", data=entry_data)

        defaults = (
            _empty_defaults()
            if self._settings.start_empty
            else _stored_favorite_defaults(self._config_entry, self.hass)
        )
        defaults = _generated_defaults(
            metadata,
            self.hass,
            self._coverage,
            defaults,
        )
        return self.async_show_form(
            step_id="select",
            data_schema=_selection_schema(
                metadata,
                defaults=defaults,
            ),
            errors={},
        )

    async def _async_fetch_metadata(self, language: str) -> MetadataSelection:
        client = VegagerdinApiClient(aiohttp_client.async_get_clientsession(self.hass))
        roads = await client.async_get_road_conditions(language=language)
        weather_stations = await client.async_get_weather_stations()
        cameras = await client.async_get_webcams()
        counters = await client.async_get_traffic_counters()
        return MetadataSelection(
            roads={road.road_condition_id: road for road in roads},
            weather_stations={
                station.station_id: station for station in weather_stations
            },
            cameras={camera.camera_id: camera for camera in cameras},
            camera_image_counts=_camera_image_counts(cameras),
            traffic_counters={counter.counter_id: counter for counter in counters},
        )


def _selection_schema(
    metadata: MetadataSelection,
    *,
    defaults: dict[str, list[Any]],
) -> vol.Schema:
    """Return the selection form schema."""
    return vol.Schema(
        {
            vol.Optional(
                CONF_ROAD_CONDITION_IDS,
                default=defaults.get(CONF_ROAD_CONDITION_IDS, []),
            ): _multi_select(_road_options(metadata.roads)),
            vol.Optional(
                CONF_WEATHER_STATION_IDS,
                default=defaults.get(CONF_WEATHER_STATION_IDS, []),
            ): _multi_select(_weather_station_options(metadata.weather_stations)),
            vol.Optional(
                CONF_CAMERA_IDS,
                default=defaults.get(CONF_CAMERA_IDS, []),
            ): _multi_select(_camera_options(metadata)),
            vol.Optional(
                CONF_TRAFFIC_COUNTER_IDS,
                default=defaults.get(CONF_TRAFFIC_COUNTER_IDS, []),
            ): _multi_select(_traffic_counter_options(metadata.traffic_counters)),
            vol.Optional(
                CONF_NOTICE_REGION_KEYS,
                default=defaults.get(CONF_NOTICE_REGION_KEYS, []),
            ): _multi_select(_notice_region_options()),
        }
    )


def _coverage_schema(hass: Any, settings: CoverageSettings) -> vol.Schema:
    """Return the coverage suggestion form schema."""
    return vol.Schema(
        {
            vol.Optional(
                CONF_COVERAGE_CENTER,
                default=settings.center,
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_coverage_center_options(hass),
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional(
                CONF_ROAD_CONDITION_RADIUS_KM,
                default=settings.road_condition_radius_km,
            ): _radius_selector(),
            vol.Optional(
                CONF_CAMERA_RADIUS_KM,
                default=settings.camera_radius_km,
            ): _radius_selector(),
            vol.Optional(
                CONF_WEATHER_STATION_RADIUS_KM,
                default=settings.weather_station_radius_km,
            ): _radius_selector(),
            vol.Optional(
                CONF_TRAFFIC_COUNTER_RADIUS_KM,
                default=settings.traffic_counter_radius_km,
            ): _radius_selector(),
        }
    )


def _radius_selector() -> selector.NumberSelector:
    """Return a km radius selector."""
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=0,
            max=250,
            step=1,
            mode=selector.NumberSelectorMode.BOX,
            unit_of_measurement="km",
        )
    )


def _coverage_center_options(hass: Any) -> list[selector.SelectOptionDict]:
    """Return coverage center choices."""
    options = [
        selector.SelectOptionDict(value=DEFAULT_COVERAGE_CENTER, label="Home"),
    ]
    for zone_state in sorted(
        hass.states.async_all("zone"),
        key=lambda state: str(
            state.attributes.get("friendly_name") or state.entity_id
        ).casefold(),
    ):
        label = zone_state.attributes.get("friendly_name") or zone_state.entity_id
        options.append(
            selector.SelectOptionDict(
                value=zone_state.entity_id,
                label=str(label),
            )
        )
    return options


def _settings_schema(
    hass: Any,
    settings: FlowSettings,
    *,
    include_start_empty: bool = False,
) -> vol.Schema:
    """Return the settings form schema."""
    schema: dict[Any, Any] = {
        vol.Optional(
            CONF_LANGUAGE,
            default=settings.language,
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[
                    selector.SelectOptionDict(value="en", label="English"),
                    selector.SelectOptionDict(value="is", label="Íslenska"),
                ],
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        ),
        vol.Optional(
            CONF_ENABLE_ROAD_SUMMARIES,
            default=settings.enable_road_summaries,
        ): bool,
        vol.Optional(
            CONF_ENABLE_WEATHER_STATION_SENSORS,
            default=settings.enable_weather_station_sensors,
        ): bool,
        vol.Optional(
            CONF_ENABLE_TRAFFIC_COUNTER_SENSORS,
            default=settings.enable_traffic_counter_sensors,
        ): bool,
        vol.Optional(
            CONF_ENABLE_CAMERAS,
            default=settings.enable_cameras,
        ): bool,
        vol.Optional(
            CONF_ENABLE_ROUTE_SENSORS,
            default=settings.enable_route_sensors,
        ): bool,
        vol.Optional(
            CONF_REGISTER_LOVELACE_CARD,
            default=settings.register_lovelace_card,
        ): bool,
        vol.Optional(
            CONF_OSRM_URL,
            default=settings.osrm_url,
        ): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.URL)
        ),
        vol.Optional(
            CONF_ROUTE_ORIGIN_ENTITY_ID,
            default=settings.route_origin_entity_id,
        ): selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain=["zone", "person", "device_tracker"],
            )
        ),
        vol.Optional(
            CONF_ROUTE_INCLUDE_ZONES,
            default=settings.route_include_zones,
        ): bool,
        vol.Optional(
            CONF_ROUTE_TRACKER_ENTITY_IDS,
            default=list(settings.route_tracker_entity_ids),
        ): selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain="device_tracker",
                multiple=True,
            )
        ),
        vol.Optional(
            CONF_ROUTE_ROAD_CORRIDOR_KM,
            default=settings.route_road_corridor_km,
        ): _route_corridor_selector(maximum=2),
        vol.Optional(
            CONF_ROUTE_POINT_CORRIDOR_KM,
            default=settings.route_point_corridor_km,
        ): _route_corridor_selector(maximum=25),
    }
    if include_start_empty:
        schema[vol.Optional(CONF_START_EMPTY, default=settings.start_empty)] = bool
    return vol.Schema(schema)


def _route_corridor_selector(*, maximum: float) -> selector.NumberSelector:
    """Return a route matching corridor selector."""
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=0.1,
            max=maximum,
            step=0.1,
            mode=selector.NumberSelectorMode.BOX,
            unit_of_measurement="km",
        )
    )


def _multi_select(
    options: list[selector.SelectOptionDict],
) -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options,
            multiple=True,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def _road_options(
    roads: dict[str, RoadCondition],
) -> list[selector.SelectOptionDict]:
    return [
        selector.SelectOptionDict(
            value=road.road_condition_id,
            label=f"{road.name} ({road.road_condition_id})",
        )
        for road in sorted(roads.values(), key=lambda item: item.name.casefold())
    ]


def _weather_station_options(
    stations: dict[int, WeatherStation],
) -> list[selector.SelectOptionDict]:
    return [
        selector.SelectOptionDict(
            value=str(station.station_id),
            label=f"{station.name} ({station.station_id})",
        )
        for station in sorted(stations.values(), key=lambda item: item.name.casefold())
    ]


def _camera_options(
    metadata: MetadataSelection,
) -> list[selector.SelectOptionDict]:
    return [
        selector.SelectOptionDict(
            value=str(camera.camera_id),
            label=_camera_option_label(
                camera,
                metadata.camera_image_counts.get(camera.camera_id, 1),
            ),
        )
        for camera in sorted(
            metadata.cameras.values(),
            key=lambda item: item.name.casefold(),
        )
    ]


def _camera_option_label(camera: VegagerdinCamera, image_count: int) -> str:
    """Return the camera site selector label."""
    suffix = f", {image_count} images" if image_count > 1 else ""
    return f"{camera.name} ({camera.camera_id}{suffix})"


def _camera_image_counts(cameras: list[VegagerdinCamera]) -> dict[int, int]:
    """Return image counts per camera site."""
    counts: dict[int, int] = {}
    for camera in cameras:
        counts[camera.camera_id] = counts.get(camera.camera_id, 0) + 1
    return counts


def _traffic_counter_options(
    counters: dict[int, TrafficCounter],
) -> list[selector.SelectOptionDict]:
    return [
        selector.SelectOptionDict(
            value=str(counter.counter_id),
            label=f"{counter.name} ({counter.counter_id})",
        )
        for counter in sorted(counters.values(), key=lambda item: item.name.casefold())
    ]


def _notice_region_options() -> list[selector.SelectOptionDict]:
    """Return notice region selector options."""
    return [
        selector.SelectOptionDict(
            value=str(option["key"]),
            label=str(option["label"]),
        )
        for option in NOTICE_REGION_OPTIONS
    ]


def _empty_defaults(hass: Any | None = None) -> dict[str, list[Any]]:
    """Return empty selector defaults."""
    return {
        CONF_ROAD_CONDITION_IDS: [],
        CONF_WEATHER_STATION_IDS: [],
        CONF_CAMERA_IDS: [],
        CONF_TRAFFIC_COUNTER_IDS: [],
        CONF_NOTICE_REGION_KEYS: suggest_notice_regions(hass) if hass else [],
    }


def _generated_defaults(
    metadata: MetadataSelection,
    hass: Any,
    coverage: CoverageSettings,
    defaults: dict[str, list[Any]],
) -> dict[str, list[Any]]:
    """Merge coverage-generated favorites into selector defaults."""
    center = _coverage_center_coordinates(hass, coverage.center)
    generated = {
        CONF_ROAD_CONDITION_IDS: [
            road.road_condition_id
            for road in objects_within_radius(
                metadata.roads.values(),
                center=center,
                radius_km=coverage.road_condition_radius_km,
                latitude_fn=lambda road: road.latitude,
                longitude_fn=lambda road: road.longitude,
            )
        ],
        CONF_CAMERA_IDS: [
            str(camera.camera_id)
            for camera in objects_within_radius(
                metadata.cameras.values(),
                center=center,
                radius_km=coverage.camera_radius_km,
                latitude_fn=lambda camera: camera.latitude,
                longitude_fn=lambda camera: camera.longitude,
            )
        ],
        CONF_WEATHER_STATION_IDS: [
            str(station.station_id)
            for station in objects_within_radius(
                metadata.weather_stations.values(),
                center=center,
                radius_km=coverage.weather_station_radius_km,
                latitude_fn=lambda station: station.latitude,
                longitude_fn=lambda station: station.longitude,
            )
        ],
        CONF_TRAFFIC_COUNTER_IDS: [
            str(counter.counter_id)
            for counter in objects_within_radius(
                metadata.traffic_counters.values(),
                center=center,
                radius_km=coverage.traffic_counter_radius_km,
                latitude_fn=lambda counter: counter.latitude,
                longitude_fn=lambda counter: counter.longitude,
            )
        ],
    }
    return {
        key: _merge_unique(defaults.get(key, []), generated.get(key, []))
        for key in set(defaults) | set(generated)
    }


def _merge_unique(*groups: list[Any]) -> list[Any]:
    """Return a stable unique list."""
    merged: list[Any] = []
    seen: set[str] = set()
    for group in groups:
        for item in group:
            marker = str(item)
            if marker in seen:
                continue
            seen.add(marker)
            merged.append(item)
    return merged


def _coverage_center_coordinates(
    hass: Any,
    center: str,
) -> tuple[float, float] | None:
    """Return coordinates for a coverage center selection."""
    if center == DEFAULT_COVERAGE_CENTER:
        latitude = _optional_float(getattr(hass.config, "latitude", None))
        longitude = _optional_float(getattr(hass.config, "longitude", None))
        if latitude is None or longitude is None:
            return None
        return (latitude, longitude)

    state = hass.states.get(center)
    if state is None:
        return None
    latitude = _optional_float(state.attributes.get("latitude"))
    longitude = _optional_float(state.attributes.get("longitude"))
    if latitude is None or longitude is None:
        return None
    return (latitude, longitude)


def _optional_float(value: Any) -> float | None:
    """Return value as float if possible."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _stored_favorite_defaults(
    config_entry: ConfigEntry,
    hass: Any,
) -> dict[str, list[Any]]:
    """Return stored selections for the options flow."""
    entry_config = _entry_config(config_entry)
    return {
        CONF_ROAD_CONDITION_IDS: [
            str(item) for item in entry_config.get(CONF_ROAD_CONDITION_IDS, [])
        ],
        CONF_WEATHER_STATION_IDS: [
            str(item) for item in entry_config.get(CONF_WEATHER_STATION_IDS, [])
        ],
        CONF_CAMERA_IDS: [
            str(item) for item in entry_config.get(CONF_CAMERA_IDS, [])
        ],
        CONF_TRAFFIC_COUNTER_IDS: [
            str(item) for item in entry_config.get(CONF_TRAFFIC_COUNTER_IDS, [])
        ],
        CONF_NOTICE_REGION_KEYS: [
            str(item)
            for item in _stored_or_suggested_notice_regions(entry_config, hass)
        ],
    }


def _stored_or_suggested_notice_regions(
    entry_config: dict[str, Any],
    hass: Any,
) -> list[str]:
    """Return stored notice regions or suggestions for pre-existing entries."""
    if CONF_NOTICE_REGION_KEYS in entry_config:
        return [str(item) for item in entry_config.get(CONF_NOTICE_REGION_KEYS, [])]
    return suggest_notice_regions(hass) or DEFAULT_NOTICE_REGION_KEYS


def _entry_data(
    settings: FlowSettings,
    coverage: CoverageSettings,
    user_input: dict[str, Any],
) -> dict[str, Any]:
    """Normalize config flow input for storage."""
    return settings.as_dict() | coverage.as_dict() | {
        CONF_ROAD_CONDITION_IDS: [
            str(item) for item in user_input.get(CONF_ROAD_CONDITION_IDS, [])
        ],
        CONF_WEATHER_STATION_IDS: [
            int(item) for item in user_input.get(CONF_WEATHER_STATION_IDS, [])
        ],
        CONF_CAMERA_IDS: [
            int(item) for item in user_input.get(CONF_CAMERA_IDS, [])
        ],
        CONF_TRAFFIC_COUNTER_IDS: [
            int(item) for item in user_input.get(CONF_TRAFFIC_COUNTER_IDS, [])
        ],
        CONF_NOTICE_REGION_KEYS: [
            str(item) for item in user_input.get(CONF_NOTICE_REGION_KEYS, [])
        ],
    }


def _coverage_from_input(user_input: dict[str, Any]) -> CoverageSettings:
    """Return coverage settings from a coverage form payload."""
    return CoverageSettings(
        center=str(user_input.get(CONF_COVERAGE_CENTER, DEFAULT_COVERAGE_CENTER)),
        road_condition_radius_km=_positive_float(
            user_input.get(
                CONF_ROAD_CONDITION_RADIUS_KM,
                DEFAULT_ROAD_CONDITION_RADIUS_KM,
            )
        ),
        camera_radius_km=_positive_float(
            user_input.get(CONF_CAMERA_RADIUS_KM, DEFAULT_CAMERA_RADIUS_KM)
        ),
        weather_station_radius_km=_positive_float(
            user_input.get(
                CONF_WEATHER_STATION_RADIUS_KM,
                DEFAULT_WEATHER_STATION_RADIUS_KM,
            )
        ),
        traffic_counter_radius_km=_positive_float(
            user_input.get(
                CONF_TRAFFIC_COUNTER_RADIUS_KM,
                DEFAULT_TRAFFIC_COUNTER_RADIUS_KM,
            )
        ),
    )


def _coverage_from_entry(config_entry: ConfigEntry) -> CoverageSettings:
    """Return coverage settings stored in an existing config entry."""
    entry_config = _entry_config(config_entry)
    return CoverageSettings(
        center=entry_config.get(CONF_COVERAGE_CENTER, DEFAULT_COVERAGE_CENTER),
        road_condition_radius_km=_positive_float(
            entry_config.get(
                CONF_ROAD_CONDITION_RADIUS_KM,
                DEFAULT_ROAD_CONDITION_RADIUS_KM,
            )
        ),
        camera_radius_km=_positive_float(
            entry_config.get(CONF_CAMERA_RADIUS_KM, DEFAULT_CAMERA_RADIUS_KM)
        ),
        weather_station_radius_km=_positive_float(
            entry_config.get(
                CONF_WEATHER_STATION_RADIUS_KM,
                DEFAULT_WEATHER_STATION_RADIUS_KM,
            )
        ),
        traffic_counter_radius_km=_positive_float(
            entry_config.get(
                CONF_TRAFFIC_COUNTER_RADIUS_KM,
                DEFAULT_TRAFFIC_COUNTER_RADIUS_KM,
            )
        ),
    )


def _positive_float(value: Any) -> float:
    """Return a non-negative float."""
    number = _optional_float(value)
    if number is None or number < 0:
        return 0.0
    return number


def _entry_config(config_entry: ConfigEntry) -> dict[str, Any]:
    return dict(config_entry.options or config_entry.data)


def _settings_from_input(user_input: dict[str, Any]) -> FlowSettings:
    """Return settings from a config/options form payload."""
    return FlowSettings(
        language=user_input.get(CONF_LANGUAGE, DEFAULT_LANGUAGE),
        enable_road_summaries=user_input.get(
            CONF_ENABLE_ROAD_SUMMARIES,
            DEFAULT_ENABLE_ROAD_SUMMARIES,
        ),
        enable_weather_station_sensors=user_input.get(
            CONF_ENABLE_WEATHER_STATION_SENSORS,
            DEFAULT_ENABLE_WEATHER_STATION_SENSORS,
        ),
        enable_traffic_counter_sensors=user_input.get(
            CONF_ENABLE_TRAFFIC_COUNTER_SENSORS,
            DEFAULT_ENABLE_TRAFFIC_COUNTER_SENSORS,
        ),
        enable_cameras=user_input.get(CONF_ENABLE_CAMERAS, DEFAULT_ENABLE_CAMERAS),
        enable_route_sensors=user_input.get(
            CONF_ENABLE_ROUTE_SENSORS,
            DEFAULT_ENABLE_ROUTE_SENSORS,
        ),
        register_lovelace_card=user_input.get(
            CONF_REGISTER_LOVELACE_CARD,
            DEFAULT_REGISTER_LOVELACE_CARD,
        ),
        osrm_url=str(user_input.get(CONF_OSRM_URL, DEFAULT_OSRM_URL)).strip(),
        route_origin_entity_id=str(
            user_input.get(
                CONF_ROUTE_ORIGIN_ENTITY_ID,
                DEFAULT_ROUTE_ORIGIN_ENTITY_ID,
            )
        ),
        route_include_zones=user_input.get(
            CONF_ROUTE_INCLUDE_ZONES,
            DEFAULT_ROUTE_INCLUDE_ZONES,
        ),
        route_tracker_entity_ids=tuple(
            str(item)
            for item in user_input.get(
                CONF_ROUTE_TRACKER_ENTITY_IDS,
                DEFAULT_ROUTE_TRACKER_ENTITY_IDS,
            )
        ),
        route_road_corridor_km=_positive_float(
            user_input.get(
                CONF_ROUTE_ROAD_CORRIDOR_KM,
                DEFAULT_ROUTE_ROAD_CORRIDOR_KM,
            )
        ),
        route_point_corridor_km=_positive_float(
            user_input.get(
                CONF_ROUTE_POINT_CORRIDOR_KM,
                DEFAULT_ROUTE_POINT_CORRIDOR_KM,
            )
        ),
        start_empty=user_input.get(CONF_START_EMPTY, False),
    )


def _settings_from_entry(config_entry: ConfigEntry) -> FlowSettings:
    """Return settings stored in an existing config entry."""
    entry_config = _entry_config(config_entry)
    return FlowSettings(
        language=entry_config.get(CONF_LANGUAGE, DEFAULT_LANGUAGE),
        enable_road_summaries=entry_config.get(
            CONF_ENABLE_ROAD_SUMMARIES,
            DEFAULT_ENABLE_ROAD_SUMMARIES,
        ),
        enable_weather_station_sensors=entry_config.get(
            CONF_ENABLE_WEATHER_STATION_SENSORS,
            DEFAULT_ENABLE_WEATHER_STATION_SENSORS,
        ),
        enable_traffic_counter_sensors=entry_config.get(
            CONF_ENABLE_TRAFFIC_COUNTER_SENSORS,
            DEFAULT_ENABLE_TRAFFIC_COUNTER_SENSORS,
        ),
        enable_cameras=entry_config.get(CONF_ENABLE_CAMERAS, DEFAULT_ENABLE_CAMERAS),
        enable_route_sensors=entry_config.get(
            CONF_ENABLE_ROUTE_SENSORS,
            DEFAULT_ENABLE_ROUTE_SENSORS,
        ),
        register_lovelace_card=entry_config.get(
            CONF_REGISTER_LOVELACE_CARD,
            DEFAULT_REGISTER_LOVELACE_CARD,
        ),
        osrm_url=str(entry_config.get(CONF_OSRM_URL, DEFAULT_OSRM_URL)),
        route_origin_entity_id=str(
            entry_config.get(
                CONF_ROUTE_ORIGIN_ENTITY_ID,
                DEFAULT_ROUTE_ORIGIN_ENTITY_ID,
            )
        ),
        route_include_zones=entry_config.get(
            CONF_ROUTE_INCLUDE_ZONES,
            DEFAULT_ROUTE_INCLUDE_ZONES,
        ),
        route_tracker_entity_ids=tuple(
            str(item)
            for item in entry_config.get(
                CONF_ROUTE_TRACKER_ENTITY_IDS,
                DEFAULT_ROUTE_TRACKER_ENTITY_IDS,
            )
        ),
        route_road_corridor_km=_positive_float(
            entry_config.get(
                CONF_ROUTE_ROAD_CORRIDOR_KM,
                DEFAULT_ROUTE_ROAD_CORRIDOR_KM,
            )
        ),
        route_point_corridor_km=_positive_float(
            entry_config.get(
                CONF_ROUTE_POINT_CORRIDOR_KM,
                DEFAULT_ROUTE_POINT_CORRIDOR_KM,
            )
        ),
    )
