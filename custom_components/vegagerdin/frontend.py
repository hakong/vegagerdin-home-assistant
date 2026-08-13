"""Register the route planner custom card."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from homeassistant.components.frontend import add_extra_js_url, remove_extra_js_url
from homeassistant.components.http import StaticPathConfig

from .const import DOMAIN

FRONTEND_URL = "/vegagerdin_static"
_REGISTERED_KEY = f"{DOMAIN}_frontend_registered"
_LOGGER = logging.getLogger(__name__)


async def async_register_frontend(
    hass: Any,
    *,
    register_lovelace_card: bool = False,
) -> None:
    """Serve route frontend files and optionally load the Lovelace card."""
    frontend_dir = Path(__file__).parent / "frontend"
    card_file = frontend_dir / "vegagerdin-route-planner-card.js"
    if not hass.data.get(_REGISTERED_KEY):
        await hass.http.async_register_static_paths(
            [
                StaticPathConfig(
                    FRONTEND_URL,
                    str(frontend_dir),
                    cache_headers=False,
                )
            ]
        )
        hass.data[_REGISTERED_KEY] = True
    try:
        cache_bust = int(card_file.stat().st_mtime)
    except OSError:
        cache_bust = 0
    namespace = f"{FRONTEND_URL}/{card_file.name}"
    resource_url = f"{namespace}?v={cache_bust}"
    if not await _async_sync_lovelace_resource(
        hass,
        namespace,
        resource_url,
        enabled=register_lovelace_card,
    ):
        # YAML-mode Lovelace has no writable resource collection.
        if register_lovelace_card:
            add_extra_js_url(hass, resource_url)
        else:
            try:
                remove_extra_js_url(hass, resource_url)
            except (KeyError, ValueError):
                pass


async def _async_sync_lovelace_resource(
    hass: Any,
    namespace: str,
    resource_url: str,
    *,
    enabled: bool,
) -> bool:
    """Add or remove the optional Lovelace card resource."""
    lovelace_data = hass.data.get("lovelace")
    resources = getattr(lovelace_data, "resources", None)
    if resources is None and isinstance(lovelace_data, dict):
        resources = lovelace_data.get("resources")
    if resources is None or not hasattr(resources, "store"):
        return False

    if not resources.loaded:
        await resources.async_load()
    existing = [
        item
        for item in resources.async_items()
        if str(item.get("url", "")).startswith(namespace)
    ]
    if not enabled:
        for item in existing:
            await resources.async_delete_item(item["id"])
            _LOGGER.debug("Removed Lovelace resource %s", item.get("url"))
        return True

    if not existing:
        await resources.async_create_item({"res_type": "module", "url": resource_url})
        _LOGGER.debug("Registered Lovelace resource %s", resource_url)
    elif existing[0].get("url") != resource_url:
        await resources.async_update_item(existing[0]["id"], {"url": resource_url})
        _LOGGER.debug("Updated Lovelace resource %s", resource_url)
    for duplicate in existing[1:]:
        await resources.async_delete_item(duplicate["id"])
    return True
