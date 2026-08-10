"""Route planner button entities for the Vegagerdin integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_ENABLE_ROUTE_SENSORS,
    DEFAULT_ENABLE_ROUTE_SENSORS,
    DOMAIN,
    INTEGRATION_NAME,
    SELECTED_ROUTE_ENTITY_PREFIX,
)
from .coordinator import VegagerdinRouteCoordinator, VegagerdinRuntimeData


async def async_setup_entry(
    hass: Any,
    entry: Any,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up route planner buttons."""
    runtime: VegagerdinRuntimeData = entry.runtime_data
    entry_config = entry.options or entry.data
    if not entry_config.get(
        CONF_ENABLE_ROUTE_SENSORS,
        DEFAULT_ENABLE_ROUTE_SENSORS,
    ) or runtime.routes is None:
        return
    async_add_entities(
        (
            VegagerdinRoutePlannerButton(runtime.routes, "swap"),
            VegagerdinRoutePlannerButton(runtime.routes, "refresh"),
        )
    )


class VegagerdinRoutePlannerButton(
    CoordinatorEntity[VegagerdinRouteCoordinator],
    ButtonEntity,
):
    """Perform an action on the selected route."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: VegagerdinRouteCoordinator,
        action: str,
    ) -> None:
        """Initialize a route planner button."""
        super().__init__(coordinator)
        self._action = action
        self._attr_name = action.title()
        self._attr_translation_key = f"route_{action}"
        self._attr_unique_id = f"{SELECTED_ROUTE_ENTITY_PREFIX}_{action}"
        self._attr_suggested_object_id = f"{DOMAIN}_route_{action}"
        self._attr_icon = {
            "swap": "mdi:swap-horizontal",
            "refresh": "mdi:refresh",
        }[action]

    async def async_press(self) -> None:
        """Perform the configured route planner action."""
        if self._action == "swap":
            await self.coordinator.async_swap_selected_route()
        else:
            await self.coordinator.async_refresh_selected_route()

    @property
    def device_info(self) -> DeviceInfo:
        """Group route planner controls on one device."""
        return DeviceInfo(
            identifiers={(DOMAIN, "route_planner")},
            name="Vegagerðin Route Planner",
            manufacturer=INTEGRATION_NAME,
        )
