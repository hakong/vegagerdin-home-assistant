"""Binary sensor platform for the Vegagerdin integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    DOMAIN as BINARY_SENSOR_DOMAIN,
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .api import RoadCondition
from .const import (
    ATTR_LAST_UPDATE,
    ATTR_ROAD_CONDITION_ID,
    ATTR_SOURCE,
    ATTRIBUTION,
    CONF_ENABLE_ROAD_SUMMARIES,
    CONF_ENABLE_ROUTE_SENSORS,
    CONF_ROAD_CONDITION_IDS,
    DEFAULT_ENABLE_ROAD_SUMMARIES,
    DEFAULT_ENABLE_ROUTE_SENSORS,
    DOMAIN,
    INTEGRATION_NAME,
)
from .coordinator import (
    VegagerdinRoadConditionCoordinator,
    VegagerdinRouteCoordinator,
    VegagerdinRuntimeData,
    route_dispatcher_signal,
)
from .routing import RouteDetails, route_entity_object_id, route_unique_id


@dataclass(frozen=True, kw_only=True)
class VegagerdinRoadBinarySensorDescription(BinarySensorEntityDescription):
    """Description for road condition binary sensors."""

    value_fn: Callable[[RoadCondition], bool]


ROAD_BINARY_SENSORS: tuple[VegagerdinRoadBinarySensorDescription, ...] = (
    VegagerdinRoadBinarySensorDescription(
        key="closed",
        name="Closed",
        translation_key="road_closed",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda road: road.is_closed,
    ),
    VegagerdinRoadBinarySensorDescription(
        key="roadwork",
        name="Roadwork",
        translation_key="roadwork",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda road: road.has_roadwork,
    ),
    VegagerdinRoadBinarySensorDescription(
        key="weight_restriction",
        name="Weight restriction",
        translation_key="weight_restriction",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda road: road.has_weight_restriction,
    ),
)


async def async_setup_entry(
    hass: Any,
    entry: Any,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Vegagerdin binary sensors."""
    runtime: VegagerdinRuntimeData = entry.runtime_data
    entry_config = entry.options or entry.data
    entities: list[BinarySensorEntity] = []
    if entry_config.get(
        CONF_ENABLE_ROAD_SUMMARIES,
        DEFAULT_ENABLE_ROAD_SUMMARIES,
    ):
        _async_repair_binary_sensor_registry(hass, runtime.road_conditions)
        for road_condition_id in entry_config.get(CONF_ROAD_CONDITION_IDS, []):
            entities.extend(
                VegagerdinRoadBinarySensor(
                    runtime.road_conditions,
                    str(road_condition_id),
                    description,
                )
                for description in ROAD_BINARY_SENSORS
            )

    if (
        entry_config.get(CONF_ENABLE_ROUTE_SENSORS, DEFAULT_ENABLE_ROUTE_SENSORS)
        and runtime.routes is not None
    ):
        known_targets = set(runtime.routes.target_entity_ids)
        entities.extend(
            VegagerdinRouteProblemBinarySensor(runtime.routes, target)
            for target in sorted(known_targets)
        )

        def async_add_route_targets(target_entity_ids: tuple[str, ...]) -> None:
            new_targets = set(target_entity_ids) - known_targets
            if not new_targets:
                return
            known_targets.update(new_targets)
            async_add_entities(
                VegagerdinRouteProblemBinarySensor(runtime.routes, target)
                for target in sorted(new_targets)
            )

        entry.async_on_unload(
            async_dispatcher_connect(
                hass,
                route_dispatcher_signal(entry.entry_id),
                async_add_route_targets,
            )
        )
    async_add_entities(entities)


class VegagerdinRouteProblemBinarySensor(
    CoordinatorEntity[VegagerdinRouteCoordinator],
    BinarySensorEntity,
):
    """Indicate whether a route has a closure, difficult state, or advisory."""

    _attr_has_entity_name = True
    _attr_name = "Route problem"
    _attr_translation_key = "route_problem"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_attribution = ATTRIBUTION

    def __init__(
        self,
        coordinator: VegagerdinRouteCoordinator,
        destination_entity_id: str,
    ) -> None:
        """Initialize the route problem sensor."""
        super().__init__(coordinator)
        self._destination_entity_id = destination_entity_id
        self._attr_unique_id = route_unique_id(
            coordinator.origin_entity_id,
            destination_entity_id,
            "problem",
        )
        self._attr_suggested_object_id = route_entity_object_id(
            coordinator.origin_entity_id,
            destination_entity_id,
            "problem",
        )

    @property
    def available(self) -> bool:
        return super().available and self._details is not None

    @property
    def is_on(self) -> bool | None:
        details = self._details
        return details.status not in ("clear", "unknown") if details else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        details = self._details
        return {
            "origin_entity_id": self.coordinator.origin_entity_id,
            "destination_entity_id": self._destination_entity_id,
            "status": details.status if details else None,
            "closures": details.closure_count if details else None,
            "roadworks": details.roadwork_count if details else None,
            "weight_restrictions": details.restriction_count if details else None,
            "notices": len(details.notices) if details else None,
            ATTR_SOURCE: "osrm+vegagerdin",
        }

    @property
    def device_info(self) -> DeviceInfo:
        details = self._details
        return DeviceInfo(
            identifiers={
                (
                    DOMAIN,
                    "route:"
                    f"{self.coordinator.origin_entity_id}:"
                    f"{self._destination_entity_id}",
                )
            },
            name=details.route_name if details else self._destination_entity_id,
            manufacturer=INTEGRATION_NAME,
        )

    @property
    def _details(self) -> RouteDetails | None:
        return (self.coordinator.data or {}).get(self._destination_entity_id)


class VegagerdinRoadBinarySensor(
    CoordinatorEntity[VegagerdinRoadConditionCoordinator],
    BinarySensorEntity,
):
    """Road condition binary sensor."""

    entity_description: VegagerdinRoadBinarySensorDescription
    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION

    def __init__(
        self,
        coordinator: VegagerdinRoadConditionCoordinator,
        road_condition_id: str,
        description: VegagerdinRoadBinarySensorDescription,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._road_condition_id = road_condition_id
        self.entity_description = description
        self._attr_name = str(description.name)
        self._attr_unique_id = (
            f"{DOMAIN}_{road_condition_id}_{description.key}"
        )

    @property
    def is_on(self) -> bool | None:
        """Return whether the problem is active."""
        road = self._road
        if road is None:
            return None
        return self.entity_description.value_fn(road)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return compact road attributes."""
        road = self._road
        attributes: dict[str, Any] = {
            ATTR_ROAD_CONDITION_ID: self._road_condition_id,
            ATTR_LAST_UPDATE: road.last_update.isoformat()
            if road and road.last_update
            else None,
            ATTR_SOURCE: road.source if road else None,
        }
        if road is None:
            return attributes

        match self.entity_description.key:
            case "closed":
                attributes.update(_closed_attributes(road))
            case "roadwork":
                attributes.update(_roadwork_attributes(road))
            case "weight_restriction":
                attributes.update(_weight_restriction_attributes(road))

        return attributes

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


def _closed_attributes(road: RoadCondition) -> dict[str, Any]:
    """Return detail attributes for closed/impassable road sensors."""
    return {
        "condition_description": road.condition.description,
        "condition_code": road.condition.code,
        "condition_category": road.condition.category,
        "condition_date": road.condition.date.isoformat()
        if road.condition.date
        else None,
    }


def _roadwork_attributes(road: RoadCondition) -> dict[str, Any]:
    """Return detail attributes for roadwork sensors."""
    markers = road.roadwork_markers
    descriptions = [
        marker.description for marker in markers if marker.description
    ]
    titles = [marker.title for marker in markers if marker.title]
    return {
        "description": descriptions[0] if descriptions else None,
        "details": descriptions,
        "marker_titles": titles,
        "roadwork_markers": [marker.as_dict() for marker in markers],
    }


def _weight_restriction_attributes(road: RoadCondition) -> dict[str, Any]:
    """Return detail attributes for weight restriction sensors."""
    restriction = road.weight_restriction
    if restriction is None:
        return {
            "weight_limit": None,
            "weight_restriction_description": None,
        }
    return {
        "weight_limit": restriction.limit,
        "weight_restriction_description": restriction.description,
        "weight_restriction": restriction.as_dict(),
    }


def _async_repair_binary_sensor_registry(
    hass: Any,
    coordinator: VegagerdinRoadConditionCoordinator,
) -> None:
    """Repair existing binary sensors created with fallback names/entity IDs."""
    entity_registry = er.async_get(hass)
    roads = coordinator.data or {}
    descriptions = {description.key: description for description in ROAD_BINARY_SENSORS}
    suffixes = sorted(descriptions, key=len, reverse=True)

    for entity in list(entity_registry.entities.values()):
        if entity.platform != DOMAIN or not entity.unique_id:
            continue
        prefix = f"{DOMAIN}_"
        if not entity.unique_id.startswith(prefix):
            continue
        unique_tail = entity.unique_id.removeprefix(prefix)
        key = next(
            (
                candidate
                for candidate in suffixes
                if unique_tail.endswith(f"_{candidate}")
            ),
            None,
        )
        if key is None:
            continue
        road_id = unique_tail[: -(len(key) + 1)]
        description = descriptions.get(key)
        if description is None:
            continue
        if entity.original_name != description.name:
            entity_registry.async_update_entity(
                entity.entity_id,
                original_name=description.name,
                translation_key=description.translation_key,
            )
        road = roads.get(road_id)
        if road is None or "undefinedtype_singleton" not in entity.entity_id:
            continue
        road_slug = slugify(road.name)
        new_entity_id = f"{BINARY_SENSOR_DOMAIN}.{road_slug}_{description.key}"
        if entity_registry.async_get(new_entity_id) is not None:
            continue
        entity_registry.async_update_entity(
            entity.entity_id,
            new_entity_id=new_entity_id,
        )
