const CARD_TAG = "vegagerdin-route-planner-card";
const STATIC_ROOT = "/vegagerdin_static";
const DEFAULT_STATUS =
  "sensor.vegagerdin_route_planner_selected_route_status";

let leafletPromise;
function loadLeaflet() {
  if (window.L) return Promise.resolve(window.L);
  if (!leafletPromise) {
    leafletPromise = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = `${STATIC_ROOT}/leaflet.js`;
      script.onload = () => resolve(window.L);
      script.onerror = () => reject(new Error("Could not load the map"));
      document.head.appendChild(script);
    });
  }
  return leafletPromise;
}

class VegagerdinRoutePlannerCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._endpoints = { origin: null, destination: null };
    this._results = { origin: [], destination: [] };
    this._searchCache = new Map();
    this._searching = { origin: false, destination: false };
    this._dirty = { origin: false, destination: false };
    this._pickMode = null;
    this._markers = {};
    this._routeLayer = null;
    this._routeGeometry = [];
    this._roadGeometries = [];
    this._roadLayers = new Map();
    this._lastRouteSignature = "";
    this._loadedRouteKey = "";
    this._routeLoading = false;
  }

  setConfig(config) {
    this._config = {
      title: "Route planner",
      status_entity: DEFAULT_STATUS,
      ...config,
    };
    if (!this._built) this._build();
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._built) this._build();
    this._syncFromState();
    this._renderStatus();
    this._updateMap();
  }

  getCardSize() {
    return 7;
  }

  _build() {
    if (!this._config || this._built) return;
    this._built = true;
    this.shadowRoot.innerHTML = `
      <link rel="stylesheet" href="${STATIC_ROOT}/leaflet.css">
      <style>
        :host { display: block; }
        ha-card {
          overflow: hidden;
          border-radius: var(--ha-card-border-radius, 8px);
        }
        .header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          min-height: 52px;
          padding: 0 16px;
          border-bottom: 1px solid var(--divider-color);
        }
        h2 {
          margin: 0;
          font-size: 18px;
          line-height: 24px;
          font-weight: 500;
          letter-spacing: 0;
        }
        .toolbar { display: flex; gap: 4px; }
        button {
          font: inherit;
          color: var(--primary-text-color);
        }
        .icon-button {
          display: inline-grid;
          place-items: center;
          width: 40px;
          height: 40px;
          padding: 0;
          border: 0;
          border-radius: 50%;
          background: transparent;
          cursor: pointer;
        }
        .icon-button:hover {
          background: color-mix(in srgb, var(--primary-text-color) 8%, transparent);
        }
        .icon-button.active {
          color: var(--primary-color);
          background: color-mix(in srgb, var(--primary-color) 14%, transparent);
        }
        .icon-button.loading ha-icon {
          animation: search-spin 1s linear infinite;
        }
        @keyframes search-spin {
          to { transform: rotate(360deg); }
        }
        .controls {
          display: grid;
          grid-template-columns: minmax(0, 1fr) 40px minmax(0, 1fr) auto;
          align-items: start;
          gap: 10px;
          padding: 14px 16px;
          border-bottom: 1px solid var(--divider-color);
        }
        .field { position: relative; min-width: 0; }
        .field-row {
          display: grid;
          grid-template-columns: 24px minmax(0, 1fr) 40px 40px;
          align-items: center;
          min-height: 48px;
          border: 1px solid var(--outline-color, var(--divider-color));
          border-radius: 6px;
          background: var(--card-background-color);
        }
        .field-row:focus-within {
          border-color: var(--primary-color);
          box-shadow: inset 0 0 0 1px var(--primary-color);
        }
        .field-row > ha-icon {
          margin-left: 8px;
          color: var(--secondary-text-color);
        }
        input {
          min-width: 0;
          height: 46px;
          border: 0;
          outline: 0;
          padding: 0 8px;
          color: var(--primary-text-color);
          background: transparent;
          font: inherit;
          letter-spacing: 0;
        }
        input::placeholder { color: var(--secondary-text-color); }
        .results {
          position: absolute;
          z-index: 1001;
          top: calc(100% + 4px);
          left: 0;
          right: 0;
          display: none;
          max-height: 280px;
          overflow: auto;
          border: 1px solid var(--divider-color);
          border-radius: 6px;
          background: var(--card-background-color);
          box-shadow: var(--ha-card-box-shadow);
        }
        .results.open { display: block; }
        .result {
          display: grid;
          grid-template-columns: 28px minmax(0, 1fr);
          gap: 8px;
          width: 100%;
          padding: 10px 12px;
          border: 0;
          border-bottom: 1px solid var(--divider-color);
          border-radius: 0;
          text-align: left;
          background: transparent;
          cursor: pointer;
        }
        .result:last-child { border-bottom: 0; }
        .result:hover { background: var(--secondary-background-color); }
        .result-label {
          overflow: hidden;
          font-size: 14px;
          line-height: 19px;
          text-overflow: ellipsis;
        }
        .result-kind {
          color: var(--secondary-text-color);
          font-size: 12px;
          line-height: 16px;
        }
        .swap { margin-top: 4px; }
        .calculate {
          min-height: 48px;
          padding: 0 18px;
          border: 0;
          border-radius: 6px;
          color: var(--text-primary-color, white);
          background: var(--primary-color);
          font-weight: 500;
          cursor: pointer;
        }
        .calculate[disabled] { opacity: .55; cursor: wait; }
        .map-wrap { position: relative; }
        #map {
          width: 100%;
          height: 360px;
          background: var(--secondary-background-color);
        }
        .map-mode {
          position: absolute;
          z-index: 500;
          top: 10px;
          left: 50%;
          display: none;
          transform: translateX(-50%);
          padding: 7px 10px;
          border-radius: 6px;
          color: var(--primary-text-color);
          background: var(--card-background-color);
          box-shadow: var(--ha-card-box-shadow);
          font-size: 13px;
          pointer-events: none;
        }
        .map-mode.open { display: block; }
        .summary {
          display: grid;
          grid-template-columns: minmax(160px, 2fr) repeat(4, minmax(70px, 1fr));
          gap: 0;
          border-top: 1px solid var(--divider-color);
        }
        .summary > div {
          min-width: 0;
          padding: 10px 14px;
          border-right: 1px solid var(--divider-color);
        }
        .summary > div:last-child { border-right: 0; }
        .summary strong, .summary span {
          display: block;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .summary strong { font-size: 14px; line-height: 20px; }
        .summary span {
          color: var(--secondary-text-color);
          font-size: 12px;
          line-height: 17px;
        }
        .message {
          display: none;
          padding: 9px 16px;
          color: var(--error-color);
          border-top: 1px solid var(--divider-color);
          font-size: 13px;
        }
        .message.open { display: block; }
        .route-marker {
          display: grid;
          place-items: center;
          width: 24px;
          height: 24px;
          border: 3px solid white;
          border-radius: 50%;
          color: white;
          background: var(--primary-color, #03a9f4);
          box-shadow: 0 1px 4px rgba(0, 0, 0, .45);
          font: 700 12px/1 sans-serif;
        }
        .route-marker.destination { background: #d84315; }
        .leaflet-control-attribution { font-size: 10px; }
        @media (max-width: 700px) {
          .controls {
            grid-template-columns: minmax(0, 1fr) 40px;
          }
          .field.origin { grid-column: 1; grid-row: 1; }
          .field.destination { grid-column: 1; grid-row: 2; }
          .swap { grid-column: 2; grid-row: 1 / span 2; align-self: center; }
          .calculate { grid-column: 1 / -1; grid-row: 3; }
          #map { height: 300px; }
          .summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
          .summary > div:first-child { grid-column: 1 / -1; }
          .summary > div:nth-child(2n) { border-right: 0; }
        }
      </style>
      <ha-card>
        <div class="header">
          <h2></h2>
          <div class="toolbar">
            <button class="icon-button refresh" title="Refresh route" aria-label="Refresh route">
              <ha-icon icon="mdi:refresh"></ha-icon>
            </button>
          </div>
        </div>
        <div class="controls">
          ${this._fieldTemplate("origin", "Origin", "mdi:map-marker")}
          <button class="icon-button swap" title="Swap endpoints" aria-label="Swap endpoints">
            <ha-icon icon="mdi:swap-horizontal"></ha-icon>
          </button>
          ${this._fieldTemplate("destination", "Destination", "mdi:flag-checkered")}
          <button class="calculate">Calculate route</button>
        </div>
        <div class="map-wrap">
          <div class="map-mode"></div>
          <div id="map"></div>
        </div>
        <div class="summary">
          <div><strong class="route-name">No route selected</strong><span class="route-state">Waiting for route data</span></div>
          <div><strong class="distance">-</strong><span>Distance</span></div>
          <div><strong class="duration">-</strong><span>Drive time</span></div>
          <div><strong class="closures">-</strong><span>Closures</span></div>
          <div><strong class="roadworks">-</strong><span>Roadworks</span></div>
        </div>
        <div class="message"></div>
      </ha-card>
    `;
    this.shadowRoot.querySelector("h2").textContent = this._config.title;
    for (const endpoint of ["origin", "destination"]) {
      const field = this.shadowRoot.querySelector(`.${endpoint}`);
      const input = field.querySelector("input");
      input.addEventListener("input", () => this._localSearch(endpoint));
      input.addEventListener("focus", () => this._localSearch(endpoint));
      input.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          this._remoteSearch(endpoint);
        }
        if (event.key === "Escape") this._closeResults(endpoint);
      });
      field.querySelector(".search").addEventListener(
        "click",
        () => this._remoteSearch(endpoint),
      );
      field.querySelector(".pick").addEventListener(
        "click",
        () => this._togglePick(endpoint),
      );
    }
    this.shadowRoot.querySelector(".swap").addEventListener(
      "click",
      () => this._swap(),
    );
    this.shadowRoot.querySelector(".calculate").addEventListener(
      "click",
      () => this._calculate(),
    );
    this.shadowRoot.querySelector(".refresh").addEventListener(
      "click",
      () => this._calculate(),
    );
    this.addEventListener("mouseleave", () => {
      if (!this._pickMode) this._closeResults();
    });
    this._initMap();
  }

  _fieldTemplate(endpoint, placeholder, icon) {
    return `
      <div class="field ${endpoint}">
        <div class="field-row">
          <ha-icon icon="${icon}"></ha-icon>
          <input type="text" autocomplete="off" placeholder="${placeholder}" aria-label="${placeholder}">
          <button class="icon-button search" title="Search OpenStreetMap" aria-label="Search OpenStreetMap for ${placeholder.toLowerCase()}">
            <ha-icon icon="mdi:magnify"></ha-icon>
          </button>
          <button class="icon-button pick" title="Choose on map" aria-label="Choose ${placeholder.toLowerCase()} on map">
            <ha-icon icon="mdi:map-marker-plus"></ha-icon>
          </button>
        </div>
        <div class="results"></div>
      </div>
    `;
  }

  async _initMap() {
    try {
      const L = await loadLeaflet();
      if (!this.isConnected || this._map) return;
      this._map = L.map(this.shadowRoot.querySelector("#map"), {
        zoomControl: true,
        attributionControl: true,
      }).setView([64.96, -19.02], 6);
      L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19,
        referrerPolicy: "origin",
        attribution:
          '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      }).addTo(this._map);
      this._map.on("click", (event) => this._mapClicked(event.latlng));
      this._updateMap(true);
      setTimeout(() => this._map?.invalidateSize(), 0);
    } catch (error) {
      this._showMessage(error.message);
    }
  }

  _syncFromState() {
    const state = this._hass?.states?.[this._config.status_entity];
    if (!state) return;
    for (const endpoint of ["origin", "destination"]) {
      if (this._dirty[endpoint]) continue;
      const value = state.attributes?.[endpoint];
      if (!value || value.latitude == null || value.longitude == null) continue;
      this._endpoints[endpoint] = { ...value };
      const input = this.shadowRoot?.querySelector(`.${endpoint} input`);
      if (input) input.value = value.label || value.entity_id || "";
    }
    const routeKey = JSON.stringify([
      state.attributes?.route_name,
      state.attributes?.distance_km,
      state.attributes?.origin,
      state.attributes?.destination,
    ]);
    if (
      state.state !== "unavailable" &&
      routeKey !== this._loadedRouteKey &&
      !this._routeLoading
    ) {
      this._loadSelectedRoute(routeKey);
    }
  }

  async _loadSelectedRoute(routeKey) {
    this._routeLoading = true;
    try {
      const result = await this._hass.callWS({
        type: "call_service",
        domain: "vegagerdin",
        service: "get_selected_route",
        service_data: {},
        return_response: true,
      });
      this._applyRouteResponse(result);
      this._loadedRouteKey = routeKey;
    } catch (error) {
      this._showMessage(error.message || "Could not load route geometry");
    } finally {
      this._routeLoading = false;
    }
  }

  _applyRouteResponse(result) {
    const response = result?.response || result || {};
    const details = response.route_details || {};
    const coordinates = details.route?.geometry?.coordinates || [];
    this._routeGeometry = coordinates
      .filter(
        (point) =>
          Array.isArray(point) &&
          Number.isFinite(Number(point[0])) &&
          Number.isFinite(Number(point[1])),
      )
      .map((point) => [Number(point[1]), Number(point[0])]);
    this._roadGeometries = Array.isArray(details.road_geometries)
      ? details.road_geometries
      : (Array.isArray(details.issue_geometries) ? details.issue_geometries : []);
    this._updateMap(true);
    this.dispatchEvent(
      new CustomEvent("vegagerdin-route-response", {
        detail: response,
        bubbles: true,
        composed: true,
      }),
    );
  }

  _localSearch(endpoint) {
    const input = this.shadowRoot.querySelector(`.${endpoint} input`);
    const rawQuery = input.value.trim();
    const query = rawQuery.toLocaleLowerCase();
    this._dirty[endpoint] = true;
    if (!query) {
      this._closeResults(endpoint);
      return;
    }
    const domains = new Set(["zone", "person", "device_tracker"]);
    const matches = Object.values(this._hass?.states || {})
      .filter((state) => {
        const domain = state.entity_id.split(".")[0];
        const attrs = state.attributes || {};
        const label = String(attrs.friendly_name || state.entity_id);
        return (
          domains.has(domain) &&
          Number.isFinite(Number(attrs.latitude)) &&
          Number.isFinite(Number(attrs.longitude)) &&
          (label.toLocaleLowerCase().includes(query) ||
            state.entity_id.toLocaleLowerCase().includes(query))
        );
      })
      .slice(0, 8)
      .map((state) => ({
        label: state.attributes.friendly_name || state.entity_id,
        detail: state.entity_id,
        icon: state.attributes.icon || "mdi:home-map-marker",
        endpoint: {
          label: state.attributes.friendly_name || state.entity_id,
          entity_id: state.entity_id,
          latitude: Number(state.attributes.latitude),
          longitude: Number(state.attributes.longitude),
        },
      }));
    matches.push({
      label: `Search OpenStreetMap for "${rawQuery}"`,
      detail: "External place search",
      icon: "mdi:magnify",
      search: true,
    });
    this._showResults(endpoint, matches);
  }

  async _remoteSearch(endpoint) {
    const field = this.shadowRoot.querySelector(`.${endpoint}`);
    const input = field.querySelector("input");
    const button = field.querySelector(".search");
    const icon = button.querySelector("ha-icon");
    const query = input.value.trim();
    if (query.length < 2 || this._searching[endpoint]) return;

    const cacheKey = query.toLocaleLowerCase();
    if (this._searchCache.has(cacheKey)) {
      this._showResults(endpoint, this._searchCache.get(cacheKey));
      return;
    }

    this._searching[endpoint] = true;
    button.disabled = true;
    button.classList.add("loading");
    icon.setAttribute("icon", "mdi:loading");
    this._showMessage("");
    try {
      const result = await this._hass.callWS({
        type: "call_service",
        domain: "vegagerdin",
        service: "search_locations",
        service_data: { query },
        return_response: true,
      });
      const response = result?.response || result || {};
      const matches = (response.locations || []).map((location) => ({
        label: location.label,
        detail: [location.category, location.type].filter(Boolean).join(" · "),
        icon: "mdi:map-marker-outline",
        endpoint: location,
      }));
      this._searchCache.set(cacheKey, matches);
      if (input.value.trim() !== query) return;
      this._showResults(endpoint, matches);
      if (!matches.length) {
        this._showMessage(`No OpenStreetMap locations found for "${query}"`);
      }
    } catch (error) {
      this._showMessage(error.message || "Location search failed");
    } finally {
      this._searching[endpoint] = false;
      button.disabled = false;
      button.classList.remove("loading");
      icon.setAttribute("icon", "mdi:magnify");
    }
  }

  _showResults(endpoint, results) {
    const container = this.shadowRoot.querySelector(`.${endpoint} .results`);
    container.replaceChildren();
    for (const result of results) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "result";
      const icon = document.createElement("ha-icon");
      icon.setAttribute("icon", result.icon);
      const text = document.createElement("div");
      const label = document.createElement("div");
      label.className = "result-label";
      label.textContent = result.label;
      const detail = document.createElement("div");
      detail.className = "result-kind";
      detail.textContent = result.detail || "Map location";
      text.append(label, detail);
      button.append(icon, text);
      button.addEventListener("click", () => {
        if (result.search) {
          this._remoteSearch(endpoint);
          return;
        }
        this._setEndpoint(endpoint, result.endpoint);
        this._closeResults(endpoint);
      });
      container.append(button);
    }
    container.classList.toggle("open", results.length > 0);
  }

  _closeResults(endpoint) {
    const endpoints = endpoint ? [endpoint] : ["origin", "destination"];
    for (const key of endpoints) {
      this.shadowRoot
        ?.querySelector(`.${key} .results`)
        ?.classList.remove("open");
    }
  }

  _setEndpoint(endpoint, value) {
    this._endpoints[endpoint] = {
      label: value.label || "Selected point",
      ...(value.entity_id ? { entity_id: value.entity_id } : {}),
      latitude: Number(value.latitude),
      longitude: Number(value.longitude),
    };
    this._dirty[endpoint] = true;
    this.shadowRoot.querySelector(`.${endpoint} input`).value =
      this._endpoints[endpoint].label;
    this._updateMap(true);
  }

  _togglePick(endpoint) {
    this._pickMode = this._pickMode === endpoint ? null : endpoint;
    for (const key of ["origin", "destination"]) {
      this.shadowRoot
        .querySelector(`.${key} .pick`)
        .classList.toggle("active", this._pickMode === key);
    }
    const mode = this.shadowRoot.querySelector(".map-mode");
    mode.textContent =
      this._pickMode === "origin"
        ? "Choose origin on map"
        : "Choose destination on map";
    mode.classList.toggle("open", Boolean(this._pickMode));
    if (this._map) {
      this._map.getContainer().style.cursor =
        this._pickMode ? "crosshair" : "";
    }
  }

  _mapClicked(latlng) {
    if (!this._pickMode) return;
    const endpoint = this._pickMode;
    const label =
      this.shadowRoot.querySelector(`.${endpoint} input`).value.trim() ||
      `Map point ${latlng.lat.toFixed(5)}, ${latlng.lng.toFixed(5)}`;
    this._setEndpoint(endpoint, {
      label,
      latitude: latlng.lat,
      longitude: latlng.lng,
    });
    this._togglePick(endpoint);
  }

  _markerIcon(endpoint) {
    return window.L.divIcon({
      className: "",
      html: `<div class="route-marker ${endpoint}">${endpoint === "origin" ? "A" : "B"}</div>`,
      iconSize: [24, 24],
      iconAnchor: [12, 12],
    });
  }

  _roadColor(severity) {
    return {
      closed: "#c62828",
      warning: "#ef6c00",
      caution: "#f9a825",
      unknown: "#757575",
      normal: "#546e7a",
    }[severity] || "#757575";
  }

  _roadPopup(issue) {
    const content = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = issue.name || "Road segment";
    content.appendChild(title);
    for (const value of [issue.condition, issue.alert]) {
      if (!value) continue;
      const line = document.createElement("div");
      line.textContent = value;
      content.appendChild(line);
    }
    if (issue.url) {
      const link = document.createElement("a");
      link.href = issue.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = "Open on umferdin.is";
      content.appendChild(link);
    }
    return content;
  }

  focusIssue(roadId) {
    const layer = this._roadLayers.get(String(roadId));
    if (!layer || !this._map) return;
    const bounds = layer.getBounds();
    if (bounds?.isValid()) {
      this._map.fitBounds(bounds, { padding: [36, 36], maxZoom: 14 });
    }
    layer.openPopup();
    layer.bringToFront();
  }

  _updateMap(force = false) {
    if (!this._map || !window.L) return;
    const geometry = this._routeGeometry;
    const signature = JSON.stringify([
      geometry,
      this._roadGeometries,
      this._endpoints.origin,
      this._endpoints.destination,
    ]);
    if (!force && signature === this._lastRouteSignature) return;
    this._lastRouteSignature = signature;

    for (const endpoint of ["origin", "destination"]) {
      const value = this._endpoints[endpoint];
      if (!value || !Number.isFinite(value.latitude) || !Number.isFinite(value.longitude)) {
        if (this._markers[endpoint]) {
          this._markers[endpoint].remove();
          delete this._markers[endpoint];
        }
        continue;
      }
      const latlng = [value.latitude, value.longitude];
      if (!this._markers[endpoint]) {
        this._markers[endpoint] = window.L.marker(latlng, {
          draggable: true,
          icon: this._markerIcon(endpoint),
        })
          .on("dragend", (event) => {
            const point = event.target.getLatLng();
            this._setEndpoint(endpoint, {
              label: this._endpoints[endpoint]?.label || "Pinned point",
              latitude: point.lat,
              longitude: point.lng,
            });
          })
          .addTo(this._map);
      } else {
        this._markers[endpoint].setLatLng(latlng);
      }
      this._markers[endpoint].bindTooltip(value.label || endpoint);
    }

    if (this._routeLayer) {
      this._routeLayer.remove();
      this._routeLayer = null;
    }
    for (const layer of this._roadLayers.values()) layer.remove();
    this._roadLayers.clear();
    const validGeometry = geometry.filter(
      (point) =>
        Array.isArray(point) &&
        Number.isFinite(Number(point[0])) &&
        Number.isFinite(Number(point[1])),
    );
    if (validGeometry.length > 1) {
      this._routeLayer = window.L.polyline(validGeometry, {
        color: "#1976d2",
        weight: 5,
        opacity: 0.72,
      }).addTo(this._map);
    }
    const roadGeometries = [...this._roadGeometries].sort((first, second) =>
      Number(first?.severity !== "normal") - Number(second?.severity !== "normal")
    );
    for (const issue of roadGeometries) {
      if (!issue?.geometry || !issue.id) continue;
      const normal = issue.severity === "normal";
      const color = this._roadColor(issue.severity);
      const layer = window.L.geoJSON(issue.geometry, {
        style: {
          color,
          weight: normal ? 7 : (issue.severity === "closed" ? 8 : 7),
          opacity: normal ? 0.24 : 0.92,
        },
      })
        .bindTooltip(issue.name || "Road segment")
        .bindPopup(this._roadPopup(issue))
        .addTo(this._map);
      if (normal) {
        layer.on("mouseover", () => layer.setStyle({ opacity: 0.72 }));
        layer.on("mouseout", () => layer.setStyle({ opacity: 0.24 }));
      }
      this._roadLayers.set(String(issue.id), layer);
    }
    const layers = [
      this._routeLayer,
      this._markers.origin,
      this._markers.destination,
    ].filter(Boolean);
    if (layers.length) {
      const group = window.L.featureGroup(layers);
      this._map.fitBounds(group.getBounds(), {
        padding: [28, 28],
        maxZoom: 14,
      });
    }
    setTimeout(() => this._map?.invalidateSize(), 0);
  }

  _swap() {
    [this._endpoints.origin, this._endpoints.destination] = [
      this._endpoints.destination,
      this._endpoints.origin,
    ];
    for (const endpoint of ["origin", "destination"]) {
      this._dirty[endpoint] = true;
      this.shadowRoot.querySelector(`.${endpoint} input`).value =
        this._endpoints[endpoint]?.label || "";
    }
    this._updateMap(true);
  }

  _serviceEndpoint(endpoint) {
    const value = this._endpoints[endpoint];
    if (!value) return null;
    if (value.entity_id) {
      return { entity_id: value.entity_id, label: value.label };
    }
    return {
      label: value.label,
      latitude: value.latitude,
      longitude: value.longitude,
    };
  }

  async _calculate() {
    const origin = this._serviceEndpoint("origin");
    const destination = this._serviceEndpoint("destination");
    if (!origin || !destination) {
      this._showMessage("Choose both route endpoints");
      return;
    }
    const button = this.shadowRoot.querySelector(".calculate");
    button.disabled = true;
    this._showMessage("");
    try {
      const result = await this._hass.callWS({
        type: "call_service",
        domain: "vegagerdin",
        service: "set_selected_route",
        service_data: { origin, destination },
        return_response: true,
      });
      this._applyRouteResponse(result);
      this._loadedRouteKey = "";
      this._dirty = { origin: false, destination: false };
    } catch (error) {
      this._showMessage(error.message || "Route calculation failed");
    } finally {
      button.disabled = false;
    }
  }

  _renderStatus() {
    if (!this.shadowRoot || !this._hass) return;
    const state = this._hass.states[this._config.status_entity];
    if (!state) {
      this._showMessage(`Entity not found: ${this._config.status_entity}`);
      return;
    }
    const attrs = state.attributes || {};
    this.shadowRoot.querySelector(".route-name").textContent =
      attrs.route_name || "Selected route";
    this.shadowRoot.querySelector(".route-state").textContent =
      state.state === "unavailable" ? attrs.error || "Unavailable" : state.state;
    this.shadowRoot.querySelector(".distance").textContent =
      attrs.distance_km == null ? "-" : `${attrs.distance_km} km`;
    this.shadowRoot.querySelector(".duration").textContent =
      attrs.duration_minutes == null
        ? "-"
        : `${Math.round(attrs.duration_minutes)} min`;
    this.shadowRoot.querySelector(".closures").textContent =
      attrs.closures ?? "-";
    this.shadowRoot.querySelector(".roadworks").textContent =
      attrs.roadworks ?? "-";
  }

  _showMessage(message) {
    const element = this.shadowRoot?.querySelector(".message");
    if (!element) return;
    element.textContent = message || "";
    element.classList.toggle("open", Boolean(message));
  }
}

if (!customElements.get(CARD_TAG)) {
  customElements.define(CARD_TAG, VegagerdinRoutePlannerCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: CARD_TAG,
    name: "Vegagerdin Route Planner",
    description: "Search, map, and calculate a Vegagerdin road route",
    preview: false,
  });
}
