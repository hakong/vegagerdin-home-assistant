import "./vegagerdin-route-planner-card.js?v=0.2.6";

const STATUS_ENTITY = "sensor.vegagerdin_route_planner_selected_route_status";
const PREF_PREFIX = "vegagerdinPanel.";

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function finiteNumber(value) {
  if (value == null || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function formatNumber(value, digits = 1) {
  const number = finiteNumber(value);
  return number == null ? "-" : number.toFixed(digits);
}

function safeUrl(value) {
  try {
    const url = new URL(String(value || ""), window.location.origin);
    return ["http:", "https:"].includes(url.protocol) ? url.href : "";
  } catch (_error) {
    return "";
  }
}

class VegagerdinPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._details = null;
    this._response = null;
    this._loading = false;
    this._error = "";
    this._routeKey = "";
    this._activeTab = this._loadPreference("tab", "overview");
    this._showAll = {
      roads: this._loadPreference("showAllRoads", "0") === "1",
      weather: this._loadPreference("showAllWeather", "0") === "1",
      traffic: this._loadPreference("showAllTraffic", "0") === "1",
      cameras: this._loadPreference("showAllCameras", "0") === "1",
    };
    this._cameraViews = new Map();
  }

  connectedCallback() {
    this._build();
  }

  set hass(hass) {
    this._hass = hass;
    this._build();
    const planner = this.shadowRoot.querySelector("vegagerdin-route-planner-card");
    if (planner) planner.hass = hass;

    const state = hass?.states?.[STATUS_ENTITY];
    const routeKey = JSON.stringify([
      state?.state,
      state?.last_updated,
      state?.attributes?.route_name,
      state?.attributes?.distance_km,
    ]);
    if (state && routeKey !== this._routeKey && !this._loading) {
      this._routeKey = routeKey;
      this._loadRoute();
    } else if (!state) {
      this._renderContent();
    }
  }

  get hass() {
    return this._hass;
  }

  _loadPreference(key, fallback) {
    try {
      return localStorage.getItem(PREF_PREFIX + key) || fallback;
    } catch (_error) {
      return fallback;
    }
  }

  _savePreference(key, value) {
    try {
      localStorage.setItem(PREF_PREFIX + key, value);
    } catch (_error) {
      // Browser privacy settings may disable local storage.
    }
  }

  _build() {
    if (this._built || !this.isConnected) return;
    this._built = true;
    this.shadowRoot.innerHTML = [
      "<style>",
      ":host { display:block; min-height:100vh; box-sizing:border-box; color:var(--primary-text-color); background:var(--primary-background-color); }",
      ".page { width:min(1500px, calc(100% - 32px)); margin:0 auto; padding:24px 0 48px; }",
      ".app-head { display:flex; align-items:center; justify-content:space-between; gap:16px; margin-bottom:18px; }",
      ".app-head h1 { margin:0; font-size:28px; font-weight:500; letter-spacing:0; }",
      ".app-head .route-name { margin-top:4px; color:var(--secondary-text-color); font-size:14px; }",
      "button { font:inherit; letter-spacing:0; }",
      ".icon-button { width:40px; height:40px; border:1px solid var(--divider-color); border-radius:4px; background:transparent; color:var(--primary-text-color); cursor:pointer; display:grid; place-items:center; }",
      ".icon-button:hover, .secondary:hover, .tab:hover { background:rgba(var(--rgb-primary-text-color), .07); }",
      ".planner { margin-bottom:18px; }",
      ".tabs { display:flex; gap:2px; overflow-x:auto; border-bottom:1px solid var(--divider-color); margin-top:18px; }",
      ".tab { border:0; border-bottom:3px solid transparent; background:transparent; color:var(--secondary-text-color); padding:12px 16px 10px; cursor:pointer; white-space:nowrap; }",
      ".tab.active { color:var(--primary-text-color); border-bottom-color:var(--primary-color); font-weight:600; }",
      "#content { min-height:260px; }",
      ".summary { display:grid; grid-template-columns:repeat(6, minmax(110px, 1fr)); border:1px solid var(--divider-color); margin:18px 0 22px; }",
      ".metric { min-width:0; padding:12px 14px; border-right:1px solid var(--divider-color); }",
      ".metric:last-child { border-right:0; }",
      ".metric .value { display:block; font-size:20px; font-weight:600; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }",
      ".metric .label { display:block; margin-top:3px; color:var(--secondary-text-color); font-size:12px; }",
      ".section { padding:18px 0 24px; border-top:1px solid var(--divider-color); }",
      ".section:first-child { border-top:0; }",
      ".section-head { display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:10px; }",
      ".section-head h2 { margin:0; font-size:19px; font-weight:600; letter-spacing:0; }",
      ".section-meta { color:var(--secondary-text-color); font-size:13px; }",
      ".secondary { min-height:36px; padding:7px 11px; border:1px solid var(--divider-color); border-radius:4px; background:transparent; color:var(--primary-text-color); cursor:pointer; display:inline-flex; align-items:center; gap:7px; white-space:nowrap; }",
      ".message { padding:16px; border-left:4px solid var(--success-color, #2e7d32); background:rgba(46,125,50,.08); }",
      ".message.error { border-left-color:var(--error-color, #c62828); background:rgba(198,40,40,.08); }",
      ".loading { padding:42px 0; text-align:center; color:var(--secondary-text-color); }",
      ".table-wrap { overflow:auto; border:1px solid var(--divider-color); }",
      "table { width:100%; border-collapse:collapse; font-size:13px; }",
      "th, td { padding:8px 10px; border-bottom:1px solid var(--divider-color); text-align:left; vertical-align:top; }",
      "th { background:var(--secondary-background-color); font-weight:600; white-space:nowrap; position:sticky; top:0; z-index:1; }",
      "tr:last-child td { border-bottom:0; }",
      "tbody tr[data-road-id] { cursor:pointer; }",
      "tbody tr[data-road-id]:hover td { background:rgba(var(--rgb-primary-color), .08); }",
      "tr.severity-closed td:first-child { box-shadow:inset 4px 0 #c62828; }",
      "tr.severity-warning td:first-child { box-shadow:inset 4px 0 #ef6c00; }",
      "tr.severity-caution td:first-child { box-shadow:inset 4px 0 #f9a825; }",
      "tr.severity-unknown td:first-child { box-shadow:inset 4px 0 #757575; }",
      ".km, .number { text-align:right; white-space:nowrap; font-variant-numeric:tabular-nums; }",
      ".condition { white-space:nowrap; }",
      ".road-link { color:var(--primary-text-color); text-decoration:underline; text-decoration-color:var(--divider-color); text-underline-offset:2px; }",
      ".road-link:hover { text-decoration-color:currentColor; }",
      ".legend { display:flex; flex-wrap:wrap; gap:14px; margin:8px 0 2px; color:var(--secondary-text-color); font-size:12px; }",
      ".legend span { display:inline-flex; align-items:center; gap:6px; }",
      ".swatch { width:18px; height:4px; display:inline-block; }",
      ".weather-summary { display:grid; grid-template-columns:repeat(4, minmax(130px, 1fr)); border:1px solid var(--divider-color); margin-bottom:14px; }",
      ".weather-summary .metric { padding:10px 12px; }",
      ".weather-summary .value { font-size:17px; }",
      ".notice-list { display:grid; gap:1px; border:1px solid var(--divider-color); background:var(--divider-color); }",
      ".notice { padding:11px 12px; background:var(--card-background-color); }",
      ".notice strong { display:block; margin-bottom:3px; }",
      ".camera-grid { display:grid; grid-template-columns:repeat(3, minmax(0, 1fr)); gap:12px; }",
      ".camera { border:1px solid var(--divider-color); border-radius:6px; overflow:hidden; background:var(--card-background-color); }",
      ".camera-media { position:relative; aspect-ratio:16/9; background:var(--secondary-background-color); }",
      ".camera-media img { width:100%; height:100%; display:block; object-fit:cover; }",
      ".camera-nav { position:absolute; inset:0; display:flex; align-items:center; justify-content:space-between; pointer-events:none; }",
      ".camera-nav button { pointer-events:auto; margin:6px; width:34px; height:34px; border:0; border-radius:4px; color:white; background:rgba(0,0,0,.62); cursor:pointer; display:grid; place-items:center; }",
      ".camera-body { padding:10px 11px; }",
      ".camera-title { font-weight:600; overflow-wrap:anywhere; }",
      ".camera-meta { display:flex; justify-content:space-between; gap:8px; margin-top:5px; color:var(--secondary-text-color); font-size:12px; }",
      ".tag { display:inline-block; margin-top:7px; color:#bf360c; font-size:12px; font-weight:600; }",
      ".camera-count { font-variant-numeric:tabular-nums; }",
      "@media (max-width: 900px) { .summary { grid-template-columns:repeat(3, minmax(100px, 1fr)); } .metric:nth-child(3) { border-right:0; } .metric:nth-child(-n+3) { border-bottom:1px solid var(--divider-color); } .camera-grid { grid-template-columns:repeat(2, minmax(0, 1fr)); } }",
      "@media (max-width: 600px) { .page { width:calc(100% - 20px); padding-top:14px; } .app-head h1 { font-size:24px; } .summary { grid-template-columns:repeat(2, minmax(0, 1fr)); } .metric { border-bottom:1px solid var(--divider-color); } .metric:nth-child(2n) { border-right:0; } .metric:nth-last-child(-n+2) { border-bottom:0; } .weather-summary { grid-template-columns:repeat(2, minmax(0, 1fr)); } .camera-grid { grid-template-columns:1fr; } .section-head { align-items:flex-start; } th, td { padding:8px; } }",
      "</style>",
      '<main class="page">',
      '<header class="app-head"><div><h1>Road Routes</h1><div class="route-name">Selected route</div></div><button class="icon-button refresh" type="button" title="Refresh route data" aria-label="Refresh route data"><ha-icon icon="mdi:refresh"></ha-icon></button></header>',
      '<div class="planner"><vegagerdin-route-planner-card></vegagerdin-route-planner-card></div>',
      '<nav class="tabs" aria-label="Road route views">',
      '<button class="tab" data-tab="overview" type="button">Overview</button>',
      '<button class="tab" data-tab="roads" type="button">Roads</button>',
      '<button class="tab" data-tab="weather" type="button">Weather</button>',
      '<button class="tab" data-tab="traffic" type="button">Traffic</button>',
      '<button class="tab" data-tab="cameras" type="button">Cameras</button>',
      "</nav>",
      '<div id="content"></div>',
      "</main>",
    ].join("");

    const planner = this.shadowRoot.querySelector("vegagerdin-route-planner-card");
    planner.setConfig({
      title: "Route planner",
      status_entity: STATUS_ENTITY,
    });
    if (this._hass) planner.hass = this._hass;

    this.shadowRoot.querySelector(".refresh").addEventListener("click", () => {
      this._loadRoute(true);
    });
    for (const tab of this.shadowRoot.querySelectorAll(".tab")) {
      tab.addEventListener("click", () => this._setTab(tab.dataset.tab));
    }
    this.addEventListener("vegagerdin-route-response", (event) => {
      this._applyResponse(event.detail);
    });
    this._renderContent();
  }

  _setTab(tab) {
    if (!["overview", "roads", "weather", "traffic", "cameras"].includes(tab)) {
      return;
    }
    this._activeTab = tab;
    this._savePreference("tab", tab);
    this._renderContent();
  }

  async _loadRoute(force = false) {
    if (!this._hass || this._loading) return;
    const state = this._hass.states?.[STATUS_ENTITY];
    if (!state) {
      this._error = "Route entities are unavailable. Enable route devices in the Vegagerðin integration options.";
      this._renderContent();
      return;
    }
    if (!force && state.state === "unavailable") {
      this._error = state.attributes?.error || "No selected route is available.";
      this._renderContent();
      return;
    }
    this._loading = true;
    this._error = "";
    this._renderContent();
    try {
      const result = await this._hass.callWS({
        type: "call_service",
        domain: "vegagerdin",
        service: "get_selected_route",
        service_data: {},
        return_response: true,
      });
      this._applyResponse(result?.response || result || {});
    } catch (error) {
      this._error = error?.message || "Could not load route details.";
      this._renderContent();
    } finally {
      this._loading = false;
      this._renderContent();
    }
  }

  _applyResponse(response) {
    const details = response?.route_details;
    if (!details) return;
    this._response = response;
    this._details = details;
    this._error = "";
    this._loading = false;
    this._renderContent();
  }

  _renderContent() {
    if (!this._built) return;
    for (const tab of this.shadowRoot.querySelectorAll(".tab")) {
      tab.classList.toggle("active", tab.dataset.tab === this._activeTab);
    }
    const name = this._details?.route_name || "Selected route";
    this.shadowRoot.querySelector(".route-name").textContent = name;

    const content = this.shadowRoot.querySelector("#content");
    if (!this._hass?.states?.[STATUS_ENTITY]) {
      content.innerHTML = '<div class="message error">Route entities are unavailable. Enable route devices in the Vegagerðin integration options.</div>';
      return;
    }
    if (this._loading && !this._details) {
      content.innerHTML = '<div class="loading">Loading route details…</div>';
      return;
    }
    if (this._error && !this._details) {
      content.innerHTML = '<div class="message error">' + escapeHtml(this._error) + "</div>";
      return;
    }
    if (!this._details) {
      content.innerHTML = '<div class="loading">Choose an origin and destination to calculate a route.</div>';
      return;
    }

    if (this._activeTab === "roads") {
      content.innerHTML = this._renderRoadsView();
    } else if (this._activeTab === "weather") {
      content.innerHTML = this._renderWeatherView();
    } else if (this._activeTab === "traffic") {
      content.innerHTML = this._renderTrafficView();
    } else if (this._activeTab === "cameras") {
      content.innerHTML = this._renderCamerasView();
    } else {
      content.innerHTML = this._renderOverview();
    }
    this._bindContentEvents();
  }

  _summaryHtml() {
    const details = this._details;
    const summary = details.summary || {};
    const route = details.route || {};
    const issues = (details.road_segments || []).filter((item) => item.has_issue).length;
    return [
      '<div class="summary">',
      this._metric(formatNumber(route.distance_km, 1) + " km", "Distance"),
      this._metric(formatNumber(route.duration_minutes, 0) + " min", "Drive time"),
      this._metric(String(summary.road_sections ?? 0), "Road segments"),
      this._metric(String(issues), "Segments needing attention"),
      this._metric(String(summary.notices ?? 0), "Route notices"),
      this._metric(String(details.camera_sites ?? 0), "Camera sites"),
      "</div>",
    ].join("");
  }

  _metric(value, label) {
    return '<div class="metric"><span class="value">' + escapeHtml(value) + '</span><span class="label">' + escapeHtml(label) + "</span></div>";
  }

  _renderOverview() {
    const roads = this._details.road_segments || [];
    const issues = roads.filter((item) => item.has_issue);
    const weather = this._weatherHighlights();
    const cameras = this._selectCameraGroups(6);
    return [
      this._summaryHtml(),
      '<section class="section">',
      this._sectionHeading("Road attention", issues.length + " of " + roads.length + " segments"),
      this._legend(),
      issues.length
        ? this._roadTable(issues)
        : '<div class="message">No reported road issues across ' + roads.length + " matched segments.</div>",
      "</section>",
      '<section class="section">',
      this._sectionHeading("Route notices", String((this._details.notices || []).length)),
      this._noticesHtml(),
      "</section>",
      '<section class="section">',
      this._sectionHeading("Weather highlights", weather.length + " of " + (this._details.route_weather || []).length + " stations"),
      this._weatherSummary(),
      this._weatherTable(weather),
      "</section>",
      '<section class="section">',
      this._sectionHeading("Camera highlights", cameras.length + " of " + this._cameraGroups().length + " sites"),
      this._cameraGrid(cameras),
      "</section>",
    ].join("");
  }

  _renderRoadsView() {
    const roads = this._details.road_segments || [];
    const issues = roads.filter((item) => item.has_issue);
    const visible = this._showAll.roads ? roads : issues;
    const button = roads.length > issues.length
      ? this._toggleButton("roads", this._showAll.roads ? "Show issues only" : "Show all " + roads.length + " segments", this._showAll.roads ? "mdi:filter-alert" : "mdi:format-list-bulleted")
      : "";
    return [
      this._summaryHtml(),
      '<section class="section">',
      this._sectionHeading("Road segments", (this._showAll.roads ? roads.length : issues.length) + " shown", button),
      this._legend(),
      visible.length
        ? this._roadTable(visible)
        : '<div class="message">No reported road issues across ' + roads.length + " matched segments.</div>",
      "</section>",
    ].join("");
  }

  _renderWeatherView() {
    const all = this._details.route_weather || [];
    const highlights = this._weatherHighlights();
    const visible = this._showAll.weather ? all : highlights;
    const button = all.length > highlights.length
      ? this._toggleButton("weather", this._showAll.weather ? "Show highlights" : "Show all " + all.length + " stations", this._showAll.weather ? "mdi:weather-windy" : "mdi:format-list-bulleted")
      : "";
    return [
      this._summaryHtml(),
      '<section class="section">',
      this._sectionHeading("Road weather", (this._showAll.weather ? all.length : highlights.length) + " shown", button),
      this._weatherSummary(),
      this._weatherTable(visible),
      "</section>",
    ].join("");
  }

  _renderTrafficView() {
    const all = this._details.route_traffic || [];
    const highlights = this._trafficHighlights();
    const visible = this._showAll.traffic ? all : highlights;
    const button = all.length > highlights.length
      ? this._toggleButton("traffic", this._showAll.traffic ? "Show highlights" : "Show all " + all.length + " counters", this._showAll.traffic ? "mdi:speedometer" : "mdi:format-list-bulleted")
      : "";
    return [
      this._summaryHtml(),
      '<section class="section">',
      this._sectionHeading("Traffic counters", (this._showAll.traffic ? all.length : highlights.length) + " shown", button),
      this._trafficSummary(),
      this._trafficTable(visible),
      "</section>",
    ].join("");
  }

  _renderCamerasView() {
    const allGroups = this._cameraGroups();
    const visible = this._showAll.cameras ? allGroups : this._selectCameraGroups(12);
    const button = allGroups.length > visible.length || this._showAll.cameras
      ? this._toggleButton("cameras", this._showAll.cameras ? "Show highlights" : "Show all " + allGroups.length + " sites", this._showAll.cameras ? "mdi:cctv" : "mdi:format-list-bulleted")
      : "";
    const imageCount = allGroups.reduce((total, group) => total + group.views.length, 0);
    return [
      this._summaryHtml(),
      '<section class="section">',
      this._sectionHeading("Road cameras", visible.length + " of " + allGroups.length + " sites · " + imageCount + " images", button),
      this._cameraGrid(visible),
      "</section>",
    ].join("");
  }

  _sectionHeading(title, meta, action = "") {
    return '<div class="section-head"><div><h2>' + escapeHtml(title) + '</h2><div class="section-meta">' + escapeHtml(meta) + "</div></div>" + action + "</div>";
  }

  _toggleButton(kind, label, icon) {
    return '<button class="secondary toggle" data-kind="' + escapeHtml(kind) + '" type="button"><ha-icon icon="' + escapeHtml(icon) + '"></ha-icon>' + escapeHtml(label) + "</button>";
  }

  _legend() {
    return [
      '<div class="legend">',
      '<span><i class="swatch" style="background:#c62828"></i>Closed</span>',
      '<span><i class="swatch" style="background:#ef6c00"></i>Alert or restriction</span>',
      '<span><i class="swatch" style="background:#f9a825"></i>Difficult condition</span>',
      '<span><i class="swatch" style="background:#757575"></i>Unknown</span>',
      "</div>",
    ].join("");
  }

  _roadTable(roads) {
    const rows = roads.map((road) => {
      const url = safeUrl(road.url);
      const name = url
        ? '<a class="road-link" href="' + escapeHtml(url) + '" target="_blank" rel="noopener noreferrer">' + escapeHtml(road.name) + "</a>"
        : escapeHtml(road.name);
      return [
        '<tr class="severity-' + escapeHtml(road.severity || "unknown") + '" data-road-id="' + escapeHtml(road.id) + '">',
        '<td class="km">' + formatNumber(road.distance_km, 1) + "</td>",
        "<td>" + name + "</td>",
        '<td class="condition">' + escapeHtml(road.condition || "-") + "</td>",
        "<td>" + escapeHtml(road.alert || "-") + "</td>",
        "</tr>",
      ].join("");
    }).join("");
    return [
      '<div class="table-wrap"><table>',
      "<thead><tr><th class=\"km\">km</th><th>Road segment</th><th>Condition</th><th>Alert / restriction</th></tr></thead>",
      "<tbody>" + rows + "</tbody></table></div>",
    ].join("");
  }

  _noticesHtml() {
    const notices = this._details.notices || [];
    if (!notices.length) return '<div class="message">No active notices matched to this route.</div>';
    return '<div class="notice-list">' + notices.map((notice) => {
      const heading = [notice.category, notice.sub_category].filter(Boolean).join(" · ") || "Road notice";
      return '<article class="notice"><strong>' + escapeHtml(heading) + "</strong><div>" + escapeHtml(notice.text || "-") + "</div></article>";
    }).join("") + "</div>";
  }

  _weatherSeverity(station) {
    const gust = finiteNumber(station.wind_gust);
    const roadTemperature = finiteNumber(station.road_temperature);
    if (station.wind_alert || (gust != null && gust >= 20) || (roadTemperature != null && roadTemperature <= 0)) return "closed";
    if ((gust != null && gust >= 15) || (roadTemperature != null && roadTemperature <= 2)) return "caution";
    return "normal";
  }

  _weatherHighlights() {
    const stations = this._details.route_weather || [];
    if (stations.length <= 8) return stations;
    const chosen = new Map();
    const add = (station) => {
      if (station) chosen.set(String(station.id || station.name), station);
    };
    for (const station of stations.filter((item) => item.wind_alert)) add(station);
    add(this._minimumBy(stations, "road_temperature"));
    add(this._maximumBy(stations, "wind_gust"));
    const issueDistances = (this._details.road_segments || [])
      .filter((item) => item.has_issue)
      .map((item) => finiteNumber(item.distance_km))
      .filter((item) => item != null);
    for (const distance of issueDistances) {
      add(stations.reduce((best, station) => {
        if (!best) return station;
        return Math.abs(Number(station.distance_km) - distance) < Math.abs(Number(best.distance_km) - distance) ? station : best;
      }, null));
    }
    add(stations[0]);
    add(stations[Math.floor(stations.length / 2)]);
    add(stations[stations.length - 1]);
    return [...chosen.values()]
      .sort((a, b) => Number(a.distance_km) - Number(b.distance_km))
      .slice(0, 8);
  }

  _weatherSummary() {
    const stations = this._details.route_weather || [];
    const minimum = this._minimumBy(stations, "road_temperature");
    const maximum = this._maximumBy(stations, "wind_gust");
    const alerts = stations.filter((item) => item.wind_alert).length;
    const temperatures = stations.map((item) => finiteNumber(item.temperature)).filter((item) => item != null);
    const range = temperatures.length
      ? Math.min(...temperatures).toFixed(1) + "–" + Math.max(...temperatures).toFixed(1) + " °C"
      : "-";
    return [
      '<div class="weather-summary">',
      this._metric(minimum ? formatNumber(minimum.road_temperature, 1) + " °C" : "-", "Minimum road temperature"),
      this._metric(maximum ? formatNumber(maximum.wind_gust, 1) + " m/s" : "-", "Maximum gust"),
      this._metric(range, "Air temperature range"),
      this._metric(String(alerts), "Official wind alerts"),
      "</div>",
    ].join("");
  }

  _weatherTable(stations) {
    if (!stations.length) return '<div class="message">No road weather stations matched this route.</div>';
    const rows = stations.map((station) => [
      '<tr class="severity-' + this._weatherSeverity(station) + '">',
      '<td class="km">' + formatNumber(station.distance_km, 1) + "</td>",
      "<td>" + escapeHtml(station.name) + (station.wind_alert ? '<div class="tag">Official wind alert</div>' : "") + "</td>",
      '<td class="number">' + this._measurement(station.temperature, "°C") + "</td>",
      '<td class="number">' + this._measurement(station.road_temperature, "°C") + "</td>",
      '<td class="number">' + this._measurement(station.wind_speed, "m/s") + "</td>",
      '<td class="number">' + this._measurement(station.wind_gust, "m/s") + "</td>",
      '<td class="number">' + this._measurement(station.wind_direction, "°", 0) + "</td>",
      "</tr>",
    ].join("")).join("");
    return '<div class="table-wrap"><table><thead><tr><th class="km">km</th><th>Station</th><th>Air</th><th>Road</th><th>Wind</th><th>Gust</th><th>Direction</th></tr></thead><tbody>' + rows + "</tbody></table></div>";
  }

  _trafficHighlights() {
    const counters = this._details.route_traffic || [];
    if (counters.length <= 6) return counters;
    const chosen = new Map();
    const add = (counter) => {
      if (counter) chosen.set(String(counter.id || counter.name), counter);
    };
    add(counters[0]);
    add(counters[Math.floor(counters.length / 2)]);
    add(counters[counters.length - 1]);
    add(this._minimumBy(counters, "average_speed_15min"));
    add(this._maximumBy(counters, "traffic_15min"));
    add(this._maximumBy(counters, "traffic_today"));
    return [...chosen.values()].sort((a, b) => Number(a.distance_km) - Number(b.distance_km));
  }

  _trafficSummary() {
    const counters = this._details.route_traffic || [];
    const slowest = this._minimumBy(counters, "average_speed_15min");
    const busiest = this._maximumBy(counters, "traffic_15min");
    const totalRecent = counters.reduce((sum, item) => sum + (finiteNumber(item.traffic_15min) || 0), 0);
    return [
      '<div class="weather-summary">',
      this._metric(String(counters.length), "Counters on route"),
      this._metric(slowest ? formatNumber(slowest.average_speed_15min, 0) + " km/h" : "-", "Lowest observed speed"),
      this._metric(busiest ? formatNumber(busiest.traffic_15min, 0) : "-", "Highest 15-minute count"),
      this._metric(formatNumber(totalRecent, 0), "Vehicles in latest samples"),
      "</div>",
    ].join("");
  }

  _trafficTable(counters) {
    if (!counters.length) return '<div class="message">No traffic counters matched this route.</div>';
    const rows = counters.map((counter) => [
      "<tr>",
      '<td class="km">' + formatNumber(counter.distance_km, 1) + "</td>",
      "<td>" + escapeHtml(counter.name) + "</td>",
      "<td>" + escapeHtml(counter.direction || "-") + "</td>",
      '<td class="number">' + formatNumber(counter.traffic_15min, 0) + "</td>",
      '<td class="number">' + (finiteNumber(counter.average_speed_15min) == null ? "-" : formatNumber(counter.average_speed_15min, 0) + " km/h") + "</td>",
      '<td class="number">' + formatNumber(counter.traffic_today, 0) + "</td>",
      "</tr>",
    ].join("")).join("");
    return '<div class="table-wrap"><table><thead><tr><th class="km">km</th><th>Counter</th><th>Direction</th><th>15 min</th><th>Average speed</th><th>Today</th></tr></thead><tbody>' + rows + "</tbody></table></div>";
  }

  _cameraGroups() {
    const groups = new Map();
    for (const camera of this._details.cameras || []) {
      if (!camera.image_url) continue;
      const key = String(camera.id || camera.camera_site_id || camera.name);
      if (!groups.has(key)) {
        groups.set(key, {
          id: key,
          name: camera.name,
          distance_km: finiteNumber(camera.distance_from_start_km),
          road_name: camera.road_name,
          road_number: camera.road_number,
          views: [],
          near_alert: false,
        });
      }
      groups.get(key).views.push(camera);
    }
    const alertSiteIds = new Set(
      (this._details.route_cameras || [])
        .filter((item) => item.near_alert)
        .map((item) => String(item.camera_site_id)),
    );
    for (const group of groups.values()) {
      group.views.sort((a, b) => String(a.description || a.name).localeCompare(String(b.description || b.name)));
      group.near_alert = alertSiteIds.has(group.id);
    }
    return [...groups.values()].sort((a, b) => Number(a.distance_km) - Number(b.distance_km));
  }

  _selectCameraGroups(limit = 12) {
    const groups = this._cameraGroups();
    if (groups.length <= limit) return groups;
    const priority = groups.filter((item) => item.near_alert);
    const chosen = new Map(priority.map((item) => [item.id, item]));
    const add = (item) => {
      if (item) chosen.set(item.id, item);
    };
    add(groups[0]);
    add(groups[groups.length - 1]);
    const remaining = groups.filter((item) => !chosen.has(item.id));
    const slots = Math.max(0, limit - chosen.size);
    for (let index = 0; index < slots && remaining.length; index += 1) {
      const position = slots === 1 ? 0 : Math.round(index * (remaining.length - 1) / (slots - 1));
      add(remaining[position]);
    }
    return [...chosen.values()]
      .sort((a, b) => Number(a.distance_km) - Number(b.distance_km))
      .slice(0, Math.max(limit, priority.length));
  }

  _cameraGrid(groups) {
    if (!groups.length) return '<div class="message">No road cameras matched this route.</div>';
    return '<div class="camera-grid">' + groups.map((group) => {
      const selected = Math.min(this._cameraViews.get(group.id) || 0, group.views.length - 1);
      const view = group.views[selected];
      const imageUrl = safeUrl(view.image_url);
      const title = view.description || group.name || "Road camera";
      const navigation = group.views.length > 1
        ? '<div class="camera-nav"><button type="button" data-camera="' + escapeHtml(group.id) + '" data-step="-1" title="Previous camera view" aria-label="Previous camera view"><ha-icon icon="mdi:chevron-left"></ha-icon></button><button type="button" data-camera="' + escapeHtml(group.id) + '" data-step="1" title="Next camera view" aria-label="Next camera view"><ha-icon icon="mdi:chevron-right"></ha-icon></button></div>'
        : "";
      return [
        '<article class="camera">',
        '<div class="camera-media">',
        imageUrl ? '<a href="' + escapeHtml(imageUrl) + '" target="_blank" rel="noopener noreferrer"><img loading="lazy" src="' + escapeHtml(imageUrl) + '" alt="' + escapeHtml(title) + '"></a>' : "",
        navigation,
        "</div>",
        '<div class="camera-body"><div class="camera-title">' + escapeHtml(title) + "</div>",
        '<div class="camera-meta"><span>' + formatNumber(group.distance_km, 1) + ' km · ' + escapeHtml(group.road_name || group.road_number || "-") + '</span><span class="camera-count">' + (selected + 1) + " / " + group.views.length + "</span></div>",
        group.near_alert ? '<div class="tag">Near a road issue</div>' : "",
        "</div></article>",
      ].join("");
    }).join("") + "</div>";
  }

  _measurement(value, unit, digits = 1) {
    const number = finiteNumber(value);
    return number == null ? "-" : number.toFixed(digits) + " " + unit;
  }

  _minimumBy(items, key) {
    return items.reduce((best, item) => {
      const value = finiteNumber(item[key]);
      if (value == null) return best;
      if (!best || value < finiteNumber(best[key])) return item;
      return best;
    }, null);
  }

  _maximumBy(items, key) {
    return items.reduce((best, item) => {
      const value = finiteNumber(item[key]);
      if (value == null) return best;
      if (!best || value > finiteNumber(best[key])) return item;
      return best;
    }, null);
  }

  _bindContentEvents() {
    for (const button of this.shadowRoot.querySelectorAll("#content .toggle")) {
      button.addEventListener("click", () => {
        const kind = button.dataset.kind;
        this._showAll[kind] = !this._showAll[kind];
        const preference = "showAll" + kind[0].toUpperCase() + kind.slice(1);
        this._savePreference(preference, this._showAll[kind] ? "1" : "0");
        this._renderContent();
      });
    }
    for (const row of this.shadowRoot.querySelectorAll("tr[data-road-id]")) {
      row.addEventListener("click", (event) => {
        if (event.target.closest("a")) return;
        const planner = this.shadowRoot.querySelector("vegagerdin-route-planner-card");
        planner?.focusIssue(row.dataset.roadId);
      });
    }
    for (const button of this.shadowRoot.querySelectorAll("[data-camera][data-step]")) {
      button.addEventListener("click", () => {
        const id = button.dataset.camera;
        const group = this._cameraGroups().find((item) => item.id === id);
        if (!group) return;
        const current = this._cameraViews.get(id) || 0;
        const next = (current + Number(button.dataset.step) + group.views.length) % group.views.length;
        this._cameraViews.set(id, next);
        this._renderContent();
      });
    }
  }
}

if (!customElements.get("vegagerdin-panel")) {
  customElements.define("vegagerdin-panel", VegagerdinPanel);
}
