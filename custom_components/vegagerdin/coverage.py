"""Coverage helper functions for Vegagerdin selections."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from math import asin, cos, radians, sin, sqrt
from typing import Any, TypeVar

EARTH_RADIUS_KM = 6371.0088

_T = TypeVar("_T")


def distance_km(
    latitude_a: float,
    longitude_a: float,
    latitude_b: float,
    longitude_b: float,
) -> float:
    """Return the great-circle distance between two coordinates."""
    lat_a = radians(latitude_a)
    lon_a = radians(longitude_a)
    lat_b = radians(latitude_b)
    lon_b = radians(longitude_b)
    delta_lat = lat_b - lat_a
    delta_lon = lon_b - lon_a
    haversine = (
        sin(delta_lat / 2) ** 2
        + cos(lat_a) * cos(lat_b) * sin(delta_lon / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * asin(sqrt(haversine))


def objects_within_radius(
    items: Iterable[_T],
    *,
    center: tuple[float, float] | None,
    radius_km: float,
    latitude_fn: Callable[[_T], Any],
    longitude_fn: Callable[[_T], Any],
) -> list[_T]:
    """Return items with coordinates within radius of center."""
    if center is None or radius_km <= 0:
        return []
    center_latitude, center_longitude = center
    results: list[_T] = []
    for item in items:
        latitude = _optional_float(latitude_fn(item))
        longitude = _optional_float(longitude_fn(item))
        if latitude is None or longitude is None:
            continue
        if (
            distance_km(center_latitude, center_longitude, latitude, longitude)
            <= radius_km
        ):
            results.append(item)
    return results


def _optional_float(value: Any) -> float | None:
    """Return value as float if possible."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
