"""Route planner select entities for the Vegagerdin integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_ENABLE_ROUTE_SENSORS,
    DEFAULT_ENABLE_ROUTE_SENSORS,
    DOMAIN,
    INTEGRATION_NAME,
    SELECTED_ROUTE_ENTITY_PREFIX,
)
from .coordinator import (
    VegagerdinRouteCoordinator,
    VegagerdinRuntimeData,
    route_endpoint_entity_ids,
)


async def async_setup_entry(
    hass: Any,
    entry: Any,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up selected-route endpoint controls."""
    runtime: VegagerdinRuntimeData = entry.runtime_data
    entry_config = entry.options or entry.data
    if not entry_config.get(
        CONF_ENABLE_ROUTE_SENSORS,
        DEFAULT_ENABLE_ROUTE_SENSORS,
    ) or runtime.routes is None:
        return
    async_add_entities(
        (
            VegagerdinRouteEndpointSelect(runtime.routes, "origin"),
            VegagerdinRouteEndpointSelect(runtime.routes, "destination"),
        )
    )


class VegagerdinRouteEndpointSelect(
    CoordinatorEntity[VegagerdinRouteCoordinator],
    RestoreEntity,
    SelectEntity,
):
    """Select one coordinate-bearing HA entity as a route endpoint."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:map-marker"

    def __init__(
        self,
        coordinator: VegagerdinRouteCoordinator,
        endpoint: str,
    ) -> None:
        """Initialize a route endpoint select."""
        super().__init__(coordinator)
        self._endpoint = endpoint
        self._attr_name = endpoint.title()
        self._attr_translation_key = f"route_{endpoint}"
        self._attr_unique_id = f"{SELECTED_ROUTE_ENTITY_PREFIX}_{endpoint}"
        self._attr_suggested_object_id = f"{DOMAIN}_route_{endpoint}"

    async def async_added_to_hass(self) -> None:
        """Restore the endpoint chosen before the last restart."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is None:
            return
        entity_id = str(last_state.attributes.get("selected_entity_id") or "")
        if entity_id not in route_endpoint_entity_ids(self.hass):
            return
        if entity_id == self._selected_entity_id:
            return
        await self._async_set_entity_id(entity_id)

    @property
    def options(self) -> list[str]:
        """Return friendly, unambiguous endpoint options."""
        return list(self._option_map)

    @property
    def current_option(self) -> str | None:
        """Return the current friendly endpoint option."""
        selected = self._selected_entity_id
        return next(
            (
                label
                for label, entity_id in self._option_map.items()
                if entity_id == selected
            ),
            None,
        )

    async def async_select_option(self, option: str) -> None:
        """Select a new route endpoint."""
        entity_id = self._option_map.get(option)
        if entity_id is None:
            raise ValueError(f"Unknown route endpoint option: {option}")
        await self._async_set_entity_id(entity_id)

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Expose the entity ID so selection can be restored reliably."""
        return {"selected_entity_id": self._selected_entity_id}

    @property
    def device_info(self) -> DeviceInfo:
        """Group route planner controls on one device."""
        return DeviceInfo(
            identifiers={(DOMAIN, "route_planner")},
            name="Vegagerðin Route Planner",
            manufacturer=INTEGRATION_NAME,
        )

    @property
    def _selected_entity_id(self) -> str:
        if self._endpoint == "origin":
            return self.coordinator.selected_origin_entity_id
        return self.coordinator.selected_destination_entity_id

    @property
    def _option_map(self) -> dict[str, str]:
        options: dict[str, str] = {}
        for entity_id in route_endpoint_entity_ids(self.hass):
            state = self.hass.states.get(entity_id)
            name = (
                state.attributes.get("friendly_name") if state is not None else None
            )
            options[f"{name or entity_id} [{entity_id}]"] = entity_id
        return options

    async def _async_set_entity_id(self, entity_id: str) -> None:
        if self._endpoint == "origin":
            await self.coordinator.async_set_selected_origin(entity_id)
        else:
            await self.coordinator.async_set_selected_destination(entity_id)

