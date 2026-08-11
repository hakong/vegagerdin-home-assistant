"""Register the route planner custom card."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig

from .const import DOMAIN

FRONTEND_URL = "/vegagerdin_static"
_REGISTERED_KEY = f"{DOMAIN}_frontend_registered"


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
    add_extra_js_url(
        hass,
        f"{FRONTEND_URL}/{card_file.name}?v={cache_bust}",
    )
    hass.data[_REGISTERED_KEY] = True
