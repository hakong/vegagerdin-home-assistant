"""Register the route planner custom card."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig

from .const import DOMAIN

FRONTEND_URL = "/vegagerdin_static"
_REGISTERED_KEY = f"{DOMAIN}_frontend_registered"
_LOGGER = logging.getLogger(__name__)


async def async_register_frontend(hass: Any) -> None:
    """Serve and load the route planner card once."""
    if hass.data.get(_REGISTERED_KEY):
        return
    frontend_dir = Path(__file__).parent / "frontend"
    card_file = frontend_dir / "vegagerdin-route-planner-card.js"
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                FRONTEND_URL,
                str(frontend_dir),
                cache_headers=False,
            )
        ]
    )
    try:
        cache_bust = int(card_file.stat().st_mtime)
    except OSError:
        cache_bust = 0
    namespace = f"{FRONTEND_URL}/{card_file.name}"
    resource_url = f"{namespace}?v={cache_bust}"
    if not await _async_register_lovelace_resource(hass, namespace, resource_url):
        # YAML-mode Lovelace has no writable resource collection.
        add_extra_js_url(hass, resource_url)
    hass.data[_REGISTERED_KEY] = True


async def _async_register_lovelace_resource(
    hass: Any,
    namespace: str,
    resource_url: str,
) -> bool:
    """Register the card as a module so Lovelace waits for it to load."""
    lovelace_data = hass.data.get("lovelace")
    resources = getattr(lovelace_data, "resources", None)
    if resources is None and isinstance(lovelace_data, dict):
        resources = lovelace_data.get("resources")
    if resources is None or not hasattr(resources, "store"):
        return False

    if not resources.loaded:
        await resources.async_load()
    existing = next(
        (
            item
            for item in resources.async_items()
            if str(item.get("url", "")).startswith(namespace)
        ),
        None,
    )
    if existing is None:
        await resources.async_create_item({"res_type": "module", "url": resource_url})
        _LOGGER.debug("Registered Lovelace resource %s", resource_url)
    elif existing.get("url") != resource_url:
        await resources.async_update_item(existing["id"], {"url": resource_url})
        _LOGGER.debug("Updated Lovelace resource %s", resource_url)
    return True
