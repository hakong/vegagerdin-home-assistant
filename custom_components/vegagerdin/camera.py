"""Camera platform for Vegagerdin webcams."""

from __future__ import annotations

from typing import Any

from homeassistant.components.camera import Camera
from homeassistant.components.camera import DOMAIN as CAMERA_DOMAIN
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_registry import RegistryEntryDisabler
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import VegagerdinCamera
from .const import (
    ATTR_CAMERA_ID,
    ATTR_SOURCE,
    ATTRIBUTION,
    CONF_CAMERA_IDS,
    CONF_ENABLE_CAMERAS,
    DEFAULT_ENABLE_CAMERAS,
    DOMAIN,
    INTEGRATION_NAME,
)
from .coordinator import VegagerdinRuntimeData, VegagerdinWebcamCoordinator


async def async_setup_entry(
    hass: Any,
    entry: Any,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Vegagerdin cameras."""
    entry_config = entry.options or entry.data
    if not entry_config.get(CONF_ENABLE_CAMERAS, DEFAULT_ENABLE_CAMERAS):
        return

    runtime: VegagerdinRuntimeData = entry.runtime_data
    selected_ids = {
        int(camera_id) for camera_id in entry_config.get(CONF_CAMERA_IDS, [])
    }
    cameras = tuple(
        camera
        for camera in (runtime.webcams.data or {}).values()
        if camera.camera_id in selected_ids
    )
    _async_remove_unselected_cameras(hass, cameras)
    _async_enable_integration_disabled_cameras(hass, cameras)
    async_add_entities(
        VegagerdinWebcam(runtime.webcams, camera.image_id) for camera in cameras
    )


def _async_remove_unselected_cameras(
    hass: Any,
    cameras: tuple[VegagerdinCamera, ...],
) -> None:
    """Remove camera registry entries outside the current site selection."""
    entity_registry = er.async_get(hass)
    selected_unique_ids = {
        f"{DOMAIN}_camera_{camera.image_id}" for camera in cameras
    }
    for entity in list(entity_registry.entities.values()):
        if (
            entity.platform == DOMAIN
            and entity.entity_id.startswith(f"{CAMERA_DOMAIN}.")
            and entity.unique_id.startswith(f"{DOMAIN}_camera_")
            and entity.unique_id not in selected_unique_ids
        ):
            entity_registry.async_remove(entity.entity_id)


class VegagerdinWebcam(
    CoordinatorEntity[VegagerdinWebcamCoordinator],
    Camera,
):
    """Vegagerdin webcam entity."""

    _attr_has_entity_name = False
    _attr_entity_registry_enabled_default = True
    _attr_attribution = ATTRIBUTION

    def __init__(
        self,
        coordinator: VegagerdinWebcamCoordinator,
        image_id: str,
    ) -> None:
        """Initialize the camera."""
        super().__init__(coordinator)
        Camera.__init__(self)
        self._image_id = str(image_id)
        self._attr_unique_id = f"{DOMAIN}_camera_{image_id}"

    @property
    def name(self) -> str | None:
        """Return entity name."""
        camera = self._camera
        if camera is None:
            return f"Vegagerðin camera {self._image_id}"
        return _camera_entity_name(camera)

    @property
    def entity_registry_enabled_default(self) -> bool:
        """Return whether this camera should be enabled by default."""
        return True

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return compact camera metadata."""
        camera = self._camera
        return {
            ATTR_CAMERA_ID: camera.camera_id if camera else None,
            "image_id": self._image_id,
            "road_number": camera.road_number if camera else None,
            "road_name": camera.road_name if camera else None,
            "description": camera.description if camera else None,
            "image_url": camera.image_url if camera else None,
            ATTR_SOURCE: camera.source if camera else None,
        }

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        camera = self._camera
        return DeviceInfo(
            identifiers={
                (
                    DOMAIN,
                    f"camera:{camera.camera_id if camera else self._image_id}",
                )
            },
            name=camera.name if camera else f"Camera {self._image_id}",
            manufacturer=INTEGRATION_NAME,
        )

    async def async_camera_image(
        self,
        width: int | None = None,
        height: int | None = None,
    ) -> bytes | None:
        """Return the latest camera image."""
        camera = self._camera
        if camera is None or camera.image_url is None:
            return None
        session = aiohttp_client.async_get_clientsession(self.hass)
        async with session.get(camera.image_url) as response:
            if response.status != 200:
                return None
            return await response.read()

    @property
    def _camera(self) -> VegagerdinCamera | None:
        return (self.coordinator.data or {}).get(self._image_id)


def _async_enable_integration_disabled_cameras(
    hass: Any,
    cameras: tuple[VegagerdinCamera, ...],
) -> None:
    """Enable cameras that an earlier version disabled by integration default."""
    entity_registry = er.async_get(hass)
    unique_ids = {f"{DOMAIN}_camera_{camera.image_id}" for camera in cameras}
    legacy_unique_ids = {f"{DOMAIN}_camera_{camera.camera_id}" for camera in cameras}
    for entity in list(entity_registry.entities.values()):
        if (
            entity.platform != DOMAIN
            or entity.unique_id not in unique_ids | legacy_unique_ids
            or not entity.entity_id.startswith(f"{CAMERA_DOMAIN}.")
        ):
            continue
        disabled_by = getattr(entity.disabled_by, "value", entity.disabled_by)
        if disabled_by not in (RegistryEntryDisabler.INTEGRATION.value, "integration"):
            continue
        if entity.unique_id in legacy_unique_ids:
            entity_registry.async_remove(entity.entity_id)
        else:
            entity_registry.async_update_entity(entity.entity_id, disabled_by=None)


def _camera_entity_name(camera: VegagerdinCamera) -> str:
    """Return a readable name for one webcam image."""
    if not camera.description:
        return camera.name
    description = camera.description.strip()
    prefix = camera.name.strip()
    if description.casefold().startswith(prefix.casefold()):
        description = description[len(prefix) :].strip(" -:–")
    return f"{camera.name} {description}" if description else camera.name
