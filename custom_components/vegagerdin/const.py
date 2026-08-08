"""Constants for the Vegagerdin integration."""

from __future__ import annotations

DOMAIN = "vegagerdin"
INTEGRATION_NAME = "Vegagerðin Road Conditions"
ENTRY_TITLE = INTEGRATION_NAME
ATTRIBUTION = "Byggt á gögnum frá Vegagerðinni."

PLATFORMS: list[str] = ["sensor", "binary_sensor", "camera"]

CONF_LANGUAGE = "language"
CONF_ROAD_CONDITION_IDS = "road_condition_ids"
CONF_WEATHER_STATION_IDS = "weather_station_ids"
CONF_CAMERA_IDS = "camera_ids"
CONF_TRAFFIC_COUNTER_IDS = "traffic_counter_ids"
CONF_NOTICE_REGION_KEYS = "notice_region_keys"
CONF_COVERAGE_CENTER = "coverage_center"
CONF_ROAD_CONDITION_RADIUS_KM = "road_condition_radius_km"
CONF_CAMERA_RADIUS_KM = "camera_radius_km"
CONF_WEATHER_STATION_RADIUS_KM = "weather_station_radius_km"
CONF_TRAFFIC_COUNTER_RADIUS_KM = "traffic_counter_radius_km"
CONF_ENABLE_ROAD_SUMMARIES = "enable_road_summaries"
CONF_ENABLE_WEATHER_STATION_SENSORS = "enable_weather_station_sensors"
CONF_ENABLE_TRAFFIC_COUNTER_SENSORS = "enable_traffic_counter_sensors"
CONF_ENABLE_CAMERAS = "enable_cameras"
CONF_ENABLE_ROUTE_SENSORS = "enable_route_sensors"
CONF_OSRM_URL = "osrm_url"
CONF_ROUTE_ORIGIN_ENTITY_ID = "route_origin_entity_id"
CONF_ROUTE_INCLUDE_ZONES = "route_include_zones"
CONF_ROUTE_TRACKER_ENTITY_IDS = "route_tracker_entity_ids"
CONF_ROUTE_ROAD_CORRIDOR_KM = "route_road_corridor_km"
CONF_ROUTE_POINT_CORRIDOR_KM = "route_point_corridor_km"

DEFAULT_LANGUAGE = "en"
DEFAULT_ENABLE_ROAD_SUMMARIES = True
DEFAULT_ENABLE_WEATHER_STATION_SENSORS = False
DEFAULT_ENABLE_TRAFFIC_COUNTER_SENSORS = False
DEFAULT_ENABLE_CAMERAS = False
DEFAULT_ENABLE_ROUTE_SENSORS = False
DEFAULT_OSRM_URL = ""
DEFAULT_ROUTE_ORIGIN_ENTITY_ID = "zone.home"
DEFAULT_ROUTE_INCLUDE_ZONES = True
DEFAULT_ROUTE_TRACKER_ENTITY_IDS: tuple[str, ...] = ()
DEFAULT_ROUTE_ROAD_CORRIDOR_KM = 0.25
DEFAULT_ROUTE_POINT_CORRIDOR_KM = 2.0
DEFAULT_NOTICE_REGION_KEYS: tuple[str, ...] = ()
DEFAULT_COVERAGE_CENTER = "home"
DEFAULT_ROAD_CONDITION_RADIUS_KM = 0.0
DEFAULT_CAMERA_RADIUS_KM = 0.0
DEFAULT_WEATHER_STATION_RADIUS_KM = 0.0
DEFAULT_TRAFFIC_COUNTER_RADIUS_KM = 0.0

IMPORTANT_NOTICE_KEYS = ("alert", "notice", "entire_iceland")
NOTICE_REGION_OPTIONS: tuple[dict[str, object], ...] = (
    {
        "key": "capital",
        "label": "Capital region",
        "bbox": (
            -22.067711594126166,
            64.02718766604315,
            -21.604587963912735,
            64.19329097630043,
        ),
    },
    {
        "key": "southwest",
        "label": "Southwest",
        "bbox": (-23.029429, 64.567333, -20.3665124, 63.738049),
    },
    {
        "key": "west",
        "label": "West",
        "bbox": (-24.237535, 65.41346, -20.375544, 64.223431),
    },
    {
        "key": "westfjords",
        "label": "Westfjords",
        "bbox": (-24.875194, 66.552432, -20.423233, 65.245614),
    },
    {
        "key": "north",
        "label": "North",
        "bbox": (-21.206169, 66.407282, -16.516537, 65.013436),
    },
    {
        "key": "northeast",
        "label": "Northeast",
        "bbox": (-17.730709, 66.560672, -12.733297, 65.011085),
    },
    {
        "key": "east",
        "label": "East",
        "bbox": (-17.29289, 65.610708, -12.587422, 64.175336),
    },
    {
        "key": "southeast",
        "label": "Southeast",
        "bbox": (-18.9981, 64.900289, -13.884167, 63.313077),
    },
    {
        "key": "south",
        "label": "South",
        "bbox": (-21.3007613, 64.407933, -17.9876173, 63.351179),
    },
    {
        "key": "highlands",
        "label": "Highlands",
        "bbox": (-20.642371, 65.375424, -15.949638, 63.933878),
    },
)

METADATA_SCAN_INTERVAL_HOURS = 12
ROAD_SCAN_INTERVAL_SECONDS = 60
NOTICE_SCAN_INTERVAL_MINUTES = 5
WEATHER_SCAN_INTERVAL_SECONDS = 60
TRAFFIC_SCAN_INTERVAL_MINUTES = 15
WEBCAM_SCAN_INTERVAL_HOURS = 1
ROUTE_SCAN_INTERVAL_SECONDS = 60
ROUTE_REFRESH_DEBOUNCE_SECONDS = 5

ATTR_SOURCE = "source"
ATTR_LAST_UPDATE = "last_update"
ATTR_ROAD_CONDITION_ID = "road_condition_id"
ATTR_ROAD_CONDITION_IDS = "road_condition_ids"
ATTR_ROAD_NUMBERS = "road_numbers"
ATTR_ROAD_NAMES = "road_names"
ATTR_CONDITION_CODE = "condition_code"
ATTR_CONDITION_CATEGORY = "condition_category"
ATTR_NOTICE_COUNT = "notice_count"
ATTR_STATION_ID = "station_id"
ATTR_CAMERA_ID = "camera_id"
ATTR_COUNTER_ID = "counter_id"
ATTR_BBOX = "bbox"
ATTR_LANGUAGE = "language"
ATTR_TAGS = "tags"
ATTR_CATEGORIES = "categories"
ATTR_NOTICE_KEYS = "notice_keys"
ATTR_DESTINATION_ENTITY_ID = "destination_entity_id"
ATTR_ORIGIN_ENTITY_ID = "origin_entity_id"

SERVICE_GET_ROAD_DETAILS = "get_road_details"
SERVICE_GET_ROAD_NOTIFICATIONS = "get_road_notifications"
SERVICE_GET_WEATHER_STATION_MEASUREMENTS = "get_weather_station_measurements"
SERVICE_GET_CAMERA_IMAGES = "get_camera_images"
SERVICE_GET_TRAFFIC_COUNTER_DETAILS = "get_traffic_counter_details"
SERVICE_GET_ROUTE_DETAILS = "get_route_details"

SOURCE_GRAPHQL = "umferdin_is_graphql"
SOURCE_WEBCAM_REST = "vegagerdin_webcam_rest"
SOURCE_TRAFFIC_WFS = "vegagerdin_traffic_wfs"
SOURCE_ROAD_GEOMETRY_WFS = "vegagerdin_road_geometry_wfs"
SOURCE_OSRM = "osrm"
