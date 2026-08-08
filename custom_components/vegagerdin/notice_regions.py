"""Notice region helpers for Vegagerdin."""

from __future__ import annotations

from typing import Any

from .const import NOTICE_REGION_OPTIONS


def suggest_notice_regions(hass: Any) -> list[str]:
    """Suggest notice regions from Home Assistant's home and zone coordinates."""
    coordinates: list[tuple[float, float]] = []
    home_latitude = _optional_float(getattr(hass.config, "latitude", None))
    home_longitude = _optional_float(getattr(hass.config, "longitude", None))
    if home_latitude is not None and home_longitude is not None:
        coordinates.append((home_latitude, home_longitude))

    for zone_state in hass.states.async_all("zone"):
        latitude = _optional_float(zone_state.attributes.get("latitude"))
        longitude = _optional_float(zone_state.attributes.get("longitude"))
        if latitude is not None and longitude is not None:
            coordinates.append((latitude, longitude))

    suggested = {
        str(option["key"])
        for latitude, longitude in coordinates
        for option in NOTICE_REGION_OPTIONS
        if _point_in_bbox(latitude, longitude, option.get("bbox"))
    }
    return [
        str(option["key"])
        for option in NOTICE_REGION_OPTIONS
        if str(option["key"]) in suggested
    ]


def _point_in_bbox(
    latitude: float,
    longitude: float,
    bbox: object,
) -> bool:
    """Return whether a point is inside a region bbox."""
    if not isinstance(bbox, tuple) or len(bbox) != 4:
        return False
    west, lat_a, east, lat_b = (float(item) for item in bbox)
    south = min(lat_a, lat_b)
    north = max(lat_a, lat_b)
    return (
        min(west, east) <= longitude <= max(west, east)
        and south <= latitude <= north
    )


def _optional_float(value: Any) -> float | None:
    """Return value as float if possible."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
