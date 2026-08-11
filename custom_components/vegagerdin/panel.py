"""Register the Vegagerdin route application panel."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from homeassistant.components import frontend, panel_custom

from .const import (
    PANEL_FRONTEND_URL_PATH,
    PANEL_ICON,
    PANEL_MODULE_FILENAME,
    PANEL_NAME,
    PANEL_TITLE,
)
from .frontend import FRONTEND_URL


async def async_register_panel(hass: Any) -> None:
    """Register the Road Routes sidebar panel."""
    panel_file = Path(__file__).parent / "frontend" / PANEL_MODULE_FILENAME
    try:
        cache_bust = int(panel_file.stat().st_mtime)
    except OSError:
        cache_bust = 0

    await panel_custom.async_register_panel(
        hass,
        webcomponent_name=PANEL_NAME,
        frontend_url_path=PANEL_FRONTEND_URL_PATH,
        module_url=f"{FRONTEND_URL}/{PANEL_MODULE_FILENAME}?v={cache_bust}",
        sidebar_title=PANEL_TITLE,
        sidebar_icon=PANEL_ICON,
        require_admin=False,
        config={},
    )


def async_unregister_panel(hass: Any) -> None:
    """Remove the Road Routes sidebar panel."""
    frontend.async_remove_panel(hass, PANEL_FRONTEND_URL_PATH)

