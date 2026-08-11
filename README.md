# Vegagerðin Road Conditions for Home Assistant

> [!WARNING]
> **Development preview:** This integration is a draft intended for development,
> testing, and early feedback. Entity models, configuration options, and data
> handling may change between releases. Do not rely on it as the only source of
> safety-critical travel information.

A custom Home Assistant integration for road information published by the
Icelandic Road and Coastal Administration (Vegagerðin) and `umferdin.is`.

This project is not affiliated with or endorsed by Vegagerðin. Data attribution:

```text
Byggt á gögnum frá Vegagerðinni.
```

## Features

- Explicit selection of road sections, weather stations, webcam sites, traffic
  counters, and notice regions.
- Compact road-condition and active-notice entities suitable for dashboards.
- Optional weather, traffic-counter, and multi-image webcam entities.
- Optional route devices from a configurable origin to Home Assistant zones or
  selected destination trackers.
- Route matching for road conditions, notices, weather stations, camera images,
  and traffic counters using a user-configured OSRM server.
- Response-returning Home Assistant actions for detailed payloads that should
  not live in entity attributes.
- UI configuration flow and options flow.
- No Vegagerðin API key required.

## Important Limitations

- This is an unofficial, in-development integration using public interfaces
  that may change without notice.
- Conditions and notices may be delayed, incomplete, translated, or matched to
  a wider area than expected.
- Carefully review radius suggestions before saving. Large radii can create a
  substantial number of devices and entities.
- Always consult official sources and local authorities before travelling in
  hazardous conditions.

## Installation With HACS

This development version is distributed as a custom HACS repository and is not
part of the default HACS catalog.

1. Open HACS in Home Assistant and select **Integrations**.
2. Open the menu and choose **Custom repositories**.
3. Add `https://github.com/hakong/vegagerdin-home-assistant` with category
   **Integration**.
4. Download **Vegagerðin Road Conditions**.
5. Restart Home Assistant.
6. Open **Settings > Devices & services > Add integration**, then search for
   **Vegagerðin Road Conditions**.

Manual installation is also possible by copying
`custom_components/vegagerdin` into the Home Assistant `custom_components`
directory and restarting Home Assistant.

## Basic Configuration

The config flow first chooses which entity groups are enabled, then offers
optional coverage suggestions, and finally lets the user select favorites.
Nothing needs to be selected Iceland-wide.

Road and notice summaries are the intended starting point. Weather-station,
traffic-counter, and camera entities are optional. Camera selection is by site;
all image directions published for a selected site become separate camera
entities.

## Route Devices

Route devices are optional and require an OSRM-compatible driving router. Enter
the router's base URL, such as `https://router.example.com`, in the integration
options. The default origin is `zone.home`.

- **Create routes to all zones** creates one stable device per Home Assistant
  zone other than the origin, including zones added later.
- **Destination trackers** accepts changing `device_tracker` entities, such as
  a navigation destination supplied by another integration.
- The road corridor defaults to `0.25 km`; the point-source corridor for
  weather, cameras, and counters defaults to `2 km`.
- OSRM routes are cached until the origin or destination moves at least
  `0.5 km`. Vegagerðin matches continue to refresh independently.
- Route entity IDs use the searchable `vegagerdin_route_` prefix.
- Route status entities include compact `road_segments`, `route_weather`, and
  `route_traffic` attributes ordered from origin to destination for dashboards.
- A route planner device provides origin and destination selects populated from
  coordinate-bearing zones, people, and device trackers. It also provides swap
  and refresh buttons plus selected-route status entities on the same device.
- Planner selections are shared Home Assistant state and are restored after a
  restart. Moving selected trackers automatically recalculates the route.
- The bundled Lovelace card adds free-text Icelandic place search, local Home
  Assistant entity suggestions, map-picked or draggable endpoints, and a route
  preview. Add it to a dashboard with:

```yaml
type: custom:vegagerdin-route-planner-card
status_entity: sensor.vegagerdin_route_planner_selected_route_status
```

The card is served and registered automatically by the integration. Map tiles
and free-text search results come from OpenStreetMap services; searches only run
when submitted.

Only endpoint coordinates are sent to the configured OSRM server. Home
Assistant credentials, entity IDs, and Vegagerðin results are not sent to it.
Use a router whose privacy and retention policy you accept.

The response-returning `vegagerdin.get_route_details` action returns ordered
road, weather, camera, counter, and notice records plus GeoJSON route geometry:

```yaml
action: vegagerdin.get_route_details
data:
  origin_entity_id: zone.home
  destination_entity_id: zone.destination
response_variable: route_information
```

## Detailed Actions

- `vegagerdin.get_road_details`
- `vegagerdin.get_road_notifications`
- `vegagerdin.get_weather_station_measurements`
- `vegagerdin.get_camera_images`
- `vegagerdin.get_traffic_counter_details`
- `vegagerdin.get_route_details`
- `vegagerdin.get_selected_route`
- `vegagerdin.search_locations`
- `vegagerdin.set_selected_route`

These actions return the complete structured response data for automations,
scripts, and custom dashboards. Entities retain compact summaries only.

## Data Sources

- `https://umferdin.is/graphql` for road conditions, road notices, and weather
  stations.
- Vegagerðin's public webcam REST service for webcam metadata and image URLs.
- Vegagerðin's public GeoServer WFS for traffic counters and road-section
  geometry.
- A user-configured OSRM server for optional driving routes.

DATEX II is not required by the current runtime and remains a possible future
official-backend enhancement.

## Development

The lightweight test suite does not require a complete Home Assistant test
harness:

```bash
python3 -m unittest discover -s tests
```

Optional development dependencies are declared in `pyproject.toml`:

```bash
python3 -m pip install -e '.[homeassistant,test]'
```

Bug reports and test feedback are welcome, but compatibility and upgrade
stability are not yet guaranteed.
