const state = {
  config: null,
  expandedUpstreams: new Set(),
  logPage: 1,
  hideFallbackLogs: true,
};
const DEFAULT_LOG_RANGE_SECONDS = 86400;
const LOG_PAGE_SIZE = 12;
let nextUpstreamUiId = 1;

const navLinks = [...document.querySelectorAll(".nav-link")];
const sectionPanels = [...document.querySelectorAll(".section-panel")];
const pageToolbar = document.getElementById("pageToolbar");
const overviewSwitcher = document.getElementById("overviewSwitcher");
const toolbarScopedItems = [...document.querySelectorAll("[data-pages]")];
const reloadRouteMapBtn = document.getElementById("reloadRouteMapBtn");
const reloadOverviewStatsBtn = document.getElementById("reloadOverviewStatsBtn");
const reloadLogBtn = document.getElementById("reloadLogBtn");
const upstreamList = document.getElementById("upstreamList");
const rawEditor = document.getElementById("rawEditor");
const upstreamTemplate = document.getElementById("upstreamTemplate");
const mappingTemplate = document.getElementById("mappingTemplate");
const runtimeUpstreams = document.getElementById("runtimeUpstreams");
const healthcheckUpstream = document.getElementById("healthcheckUpstream");
const testUpstream = document.getElementById("testUpstream");
const actionResult = document.getElementById("actionResult");
const resultStatus = document.getElementById("resultStatus");
const resultElapsed = document.getElementById("resultElapsed");
const resultUpstream = document.getElementById("resultUpstream");
const resultParsed = document.getElementById("resultParsed");
const resultParseMode = document.getElementById("resultParseMode");
const statsSummary = document.getElementById("statsSummary");
const statsRecent = document.getElementById("statsRecent");
const statsLogPath = document.getElementById("statsLogPath");
const statsRange = document.getElementById("statsRange");
const logRange = document.getElementById("logRange");
const hideFallbackLogs = document.getElementById("hideFallbackLogs");
const logPrevBtn = document.getElementById("logPrevBtn");
const logNextBtn = document.getElementById("logNextBtn");
const logPageInfo = document.getElementById("logPageInfo");
const configTabs = [...document.querySelectorAll(".config-tab")];
const configPanes = {
  global: document.getElementById("config-pane-global"),
  upstreams: document.getElementById("config-pane-upstreams"),
  raw: document.getElementById("config-pane-raw"),
};
const overviewTabs = [...document.querySelectorAll(".overview-tab")];
const overviewPanes = {
  map: document.getElementById("overview-pane-map"),
  stats: document.getElementById("overview-pane-stats"),
};
const routeRouterTitle = document.getElementById("routeRouterTitle");
const routeModeLabel = document.getElementById("routeModeLabel");
const routeGraph = document.getElementById("routeGraph");
const routeGraphSvg = document.getElementById("routeGraphSvg");
const routeRouterNode = document.getElementById("routeRouterNode");
const routeHub = document.getElementById("routeHub");
const routeLeftStack = document.querySelector(".route-left-stack");
const routeMapList = document.getElementById("routeMapList");
let routeGraphFrame = 0;
let currentOverviewPane = "map";

function setStatus(message, tone = "neutral") {
  const el = document.getElementById("statusLine");
  if (!el) {
    return;
  }
  el.textContent = message;
  el.dataset.tone = tone;
}

function parseNumberList(text) {
  return text
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean)
    .map((value) => Number(value))
    .filter((value) => Number.isFinite(value));
}

function parseStringList(text) {
  return text
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);
}

function allocateUpstreamUiId() {
  const value = `upstream-${nextUpstreamUiId}`;
  nextUpstreamUiId += 1;
  return value;
}

function ensureUpstreamUiIds(upstreams) {
  upstreams.forEach((upstream) => {
    if (!upstream._ui_id) {
      upstream._ui_id = allocateUpstreamUiId();
    }
  });
}

function bindNavigation() {
  navLinks.forEach((button) => {
    button.addEventListener("click", () => {
      const target = button.dataset.target;
      navLinks.forEach((item) => item.classList.toggle("active", item === button));
      sectionPanels.forEach((panel) => {
        panel.classList.toggle("hidden", panel.id !== `section-${target}`);
      });
      updateToolbarForSection(target);
      if (target === "overview") {
        queueRouteGraphDraw();
      }
    });
  });
}

function updateToolbarForSection(target) {
  if (!pageToolbar) {
    return;
  }

  if (overviewSwitcher) {
    overviewSwitcher.classList.toggle("hidden", target !== "overview");
  }
  if (reloadRouteMapBtn) {
    reloadRouteMapBtn.classList.toggle("hidden", target !== "overview" || currentOverviewPane !== "map");
  }
  if (reloadOverviewStatsBtn) {
    reloadOverviewStatsBtn.classList.toggle("hidden", target !== "overview" || currentOverviewPane !== "stats");
  }

  let visibleActionCount = 0;
  toolbarScopedItems.forEach((item) => {
    if (item === reloadRouteMapBtn || item === reloadOverviewStatsBtn) {
      return;
    }
    const rawPages = item.dataset.pages || "";
    const pages = rawPages
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean);
    const visible = pages.includes(target);
    item.classList.toggle("hidden", !visible);
    if (visible) {
      visibleActionCount += 1;
    }
  });

  const showToolbar = target === "overview" || visibleActionCount > 0;
  pageToolbar.classList.toggle("hidden", !showToolbar);
}

function setOverviewPane(target) {
  currentOverviewPane = target;
  overviewTabs.forEach((button) => {
    button.classList.toggle("active", button.dataset.overviewTarget === target);
  });
  Object.entries(overviewPanes).forEach(([key, pane]) => {
    if (!pane) return;
    pane.classList.toggle("hidden", key !== target);
  });
  updateToolbarForSection("overview");
  if (target === "map") {
    queueRouteGraphDraw();
  }
}

function bindOverviewTabs() {
  overviewTabs.forEach((button) => {
    button.addEventListener("click", () => {
      setOverviewPane(button.dataset.overviewTarget || "map");
    });
  });
}

function setConfigPane(target) {
  configTabs.forEach((button) => {
    button.classList.toggle("active", button.dataset.configTarget === target);
  });
  Object.entries(configPanes).forEach(([key, pane]) => {
    if (!pane) return;
    pane.classList.toggle("hidden", key !== target);
  });
}

function bindConfigTabs() {
  configTabs.forEach((button) => {
    button.addEventListener("click", () => {
      setConfigPane(button.dataset.configTarget || "global");
    });
  });
}

function createMappingRow(from = "", to = "") {
  const fragment = mappingTemplate.content.cloneNode(true);
  const row = fragment.querySelector(".mapping-row");
  row.querySelector(".mapping-from").value = from;
  row.querySelector(".mapping-to").value = to;
  row.querySelector(".remove-mapping").addEventListener("click", () => row.remove());
  return row;
}

function renderUpstreams() {
  upstreamList.innerHTML = "";
  ensureUpstreamUiIds(state.config.upstreams);
  state.config.upstreams.forEach((upstream, index) => {
    const fragment = upstreamTemplate.content.cloneNode(true);
    const block = fragment.querySelector(".upstream-block");
    const uiId = upstream._ui_id || allocateUpstreamUiId();
    const expanded = state.expandedUpstreams.has(uiId);
    block.draggable = true;
    block.dataset.index = String(index);
    block.dataset.uiId = uiId;
    block.classList.toggle("collapsed", !expanded);
    block.querySelector(".upstream-index").textContent = `Upstream ${index + 1}`;
    block.querySelector("h3").textContent = upstream.name || `Upstream ${index + 1}`;
    block.querySelector(".upstream-summary").textContent = `${upstream.base_url || "-"} | P${upstream.priority ?? 100} | ${upstream.enabled ? "Enabled" : "Disabled"}`;
    block.querySelector(".toggle-upstream").textContent = expanded ? "Collapse" : "Expand";

    block.querySelector('[data-key="name"]').value = upstream.name ?? "";
    block.querySelector('[data-key="base_url"]').value = upstream.base_url ?? "";
    block.querySelector('[data-key="api_key"]').value = upstream.api_key ?? "";
    block.querySelector('[data-key="priority"]').value = upstream.priority ?? 100;
    block.querySelector('[data-key="healthcheck_path"]').value = upstream.healthcheck_path ?? "/v1/models";
    block.querySelector('[data-key="enabled"]').checked = Boolean(upstream.enabled);
    block.querySelector('[data-key="supports_stream"]').checked = Boolean(upstream.supports_stream);
    block.querySelector('[data-key="supported_models"]').value = (upstream.supported_models || []).join(", ");

    const mappingList = block.querySelector(".mapping-list");
    Object.entries(upstream.model_map || {}).forEach(([from, to]) => {
      mappingList.appendChild(createMappingRow(from, to));
    });

    block.querySelector(".add-mapping").addEventListener("click", () => {
      mappingList.appendChild(createMappingRow("", ""));
    });

    block.querySelector(".toggle-upstream").addEventListener("click", () => {
      if (state.expandedUpstreams.has(uiId)) {
        state.expandedUpstreams.delete(uiId);
      } else {
        state.expandedUpstreams.add(uiId);
      }
      renderUpstreams();
    });

    block.querySelector(".remove-upstream").addEventListener("click", () => {
      state.config.upstreams.splice(index, 1);
      state.expandedUpstreams.delete(uiId);
      renderUpstreams();
      updateRawEditor();
      syncSummary();
    });

    block.addEventListener("dragstart", (event) => {
      event.dataTransfer?.setData("text/plain", String(index));
      block.classList.add("dragging");
    });
    block.addEventListener("dragend", () => {
      block.classList.remove("dragging");
    });
    block.addEventListener("dragover", (event) => {
      event.preventDefault();
      block.classList.add("drag-over");
    });
    block.addEventListener("dragleave", () => {
      block.classList.remove("drag-over");
    });
    block.addEventListener("drop", (event) => {
      event.preventDefault();
      block.classList.remove("drag-over");
      const fromIndex = Number(event.dataTransfer?.getData("text/plain"));
      const toIndex = index;
      if (!Number.isFinite(fromIndex) || fromIndex === toIndex) return;
      const [moved] = state.config.upstreams.splice(fromIndex, 1);
      state.config.upstreams.splice(toIndex, 0, moved);
      renderUpstreams();
      updateRawEditor();
      syncSummary();
    });

    upstreamList.appendChild(block);
  });
}

function fillForm() {
  const { listen, routing, health } = state.config;
  document.getElementById("listenHost").value = listen.host ?? "127.0.0.1";
  document.getElementById("listenPort").value = listen.port ?? 8330;

  document.getElementById("routingStrategy").value = routing.mode ?? "strict_priority";
  document.getElementById("connectTimeout").value = routing.connect_timeout_seconds ?? 10;
  document.getElementById("readTimeout").value = routing.read_timeout_seconds ?? 120;
  document.getElementById("circuitThreshold").value = routing.circuit_breaker_threshold ?? 3;
  document.getElementById("circuitCooldown").value = routing.circuit_breaker_cooldown_seconds ?? 60;
  document.getElementById("failoverStatuses").value = (routing.failover_statuses || []).join(", ");

  document.getElementById("healthEnabled").checked = Boolean(health.enabled);
  document.getElementById("healthInterval").value = health.interval_seconds ?? 120;
  document.getElementById("healthTimeout").value = health.timeout_seconds ?? 5;
  document.getElementById("healthyStatuses").value = (health.healthy_statuses || []).join(", ");

  renderUpstreams();
  updateRawEditor();
  syncSummary();
}

function readUpstreamsFromDOM() {
  return [...document.querySelectorAll(".upstream-block")].map((block) => {
    const modelMap = {};
    block.querySelectorAll(".mapping-row").forEach((row) => {
      const from = row.querySelector(".mapping-from").value.trim();
      const to = row.querySelector(".mapping-to").value.trim();
      if (from && to) {
        modelMap[from] = to;
      }
    });

    return {
      name: block.querySelector('[data-key="name"]').value.trim(),
      base_url: block.querySelector('[data-key="base_url"]').value.trim(),
      api_key: block.querySelector('[data-key="api_key"]').value.trim(),
      priority: Number(block.querySelector('[data-key="priority"]').value || 100),
      enabled: block.querySelector('[data-key="enabled"]').checked,
      supports_stream: block.querySelector('[data-key="supports_stream"]').checked,
      supported_models: parseStringList(block.querySelector('[data-key="supported_models"]').value),
      model_map: modelMap,
      healthcheck_path: block.querySelector('[data-key="healthcheck_path"]').value.trim() || "/v1/models",
    };
  });
}

function collectForm() {
  state.config = {
    listen: {
      host: document.getElementById("listenHost").value.trim(),
      port: Number(document.getElementById("listenPort").value || 8330),
    },
    routing: {
      mode: document.getElementById("routingStrategy").value.trim() || "strict_priority",
      connect_timeout_seconds: Number(document.getElementById("connectTimeout").value || 10),
      read_timeout_seconds: Number(document.getElementById("readTimeout").value || 120),
      failover_statuses: parseNumberList(document.getElementById("failoverStatuses").value),
      circuit_breaker_threshold: Number(document.getElementById("circuitThreshold").value || 3),
      circuit_breaker_cooldown_seconds: Number(document.getElementById("circuitCooldown").value || 60),
    },
    health: {
      enabled: document.getElementById("healthEnabled").checked,
      interval_seconds: Number(document.getElementById("healthInterval").value || 120),
      timeout_seconds: Number(document.getElementById("healthTimeout").value || 5),
      healthy_statuses: parseNumberList(document.getElementById("healthyStatuses").value),
    },
    upstreams: readUpstreamsFromDOM(),
  };
  updateRawEditor();
  syncSummary();
  return state.config;
}

function updateRawEditor() {
  rawEditor.value = JSON.stringify(state.config, null, 2);
}

function syncSummary() {
  document.getElementById("configPath").textContent = "router_config.json";
  document.getElementById("upstreamCount").textContent = String(state.config.upstreams.length);
  fillActionSelectors();
}

function fillActionSelectors() {
  const upstreams = state.config?.upstreams || [];
  const options = ['<option value="">All / none</option>']
    .concat(
      upstreams.map(
        (upstream) => `<option value="${upstream.name}">${upstream.name}</option>`
      )
    )
    .join("");
  healthcheckUpstream.innerHTML = options;
  testUpstream.innerHTML = upstreams
    .map((upstream) => `<option value="${upstream.name}">${upstream.name}</option>`)
    .join("");
  if (!testUpstream.value && upstreams.length > 0) {
    testUpstream.value = upstreams[0].name;
  }
}

function renderRuntimeStatus(payload) {
  const routingMode = payload.routing?.mode || "strict_priority";
  const runtimeProxyState = document.getElementById("runtimeProxyState");
  const runtimeCaptureState = document.getElementById("runtimeCaptureState");
  const runtimeUpstreams = document.getElementById("runtimeUpstreams");
  if (runtimeProxyState) {
    runtimeProxyState.textContent = payload.running ? `Running (${routingMode})` : "Stopped";
  }
  const capture = payload.capture || {};
  const captureParts = [];
  if (capture.enabled) {
    if (capture.request) captureParts.push("request");
    if (capture.response) captureParts.push("response");
    if (capture.headers_only) captureParts.push("headers-only");
  }
  if (runtimeCaptureState) {
    runtimeCaptureState.textContent = capture.enabled ? captureParts.join(" / ") : "Disabled";
  }

  if (!runtimeUpstreams) {
    return;
  }

  runtimeUpstreams.innerHTML = "";
  (payload.upstreams || []).forEach((upstream) => {
    const stateLabel = upstream.state === "circuit_open"
      ? "Circuit Open"
      : upstream.state === "unhealthy"
        ? "Unhealthy"
        : upstream.state === "disabled"
          ? "Disabled"
          : "Healthy";
    const badgeTone = upstream.state === "circuit_open" ? "warn" : upstream.state === "healthy" ? "ok" : "dim";
    const item = document.createElement("article");
    item.className = "runtime-item";
    item.innerHTML = `
      <div class="runtime-item-header">
        <strong>${upstream.name}</strong>
        <span class="runtime-badge ${badgeTone}">
          ${stateLabel}
        </span>
      </div>
      <div class="runtime-meta">
        <span>Priority ${upstream.priority}</span>
        <span>${upstream.base_url}</span>
        <span>Failures ${upstream.consecutive_failures ?? 0}</span>
        <span>Last check ${formatTimestamp(upstream.last_checked_at)}</span>
      </div>
      <div class="runtime-meta">
        <span>Health status ${upstream.last_health_status ?? "-"}</span>
        <span>Cooldown ${upstream.cooldown_remaining_seconds ?? 0}s</span>
        <span>Runtime score ${upstream.runtime_score ?? 0}</span>
        <span>Sort score ${upstream.effective_sort_score ?? upstream.priority}</span>
      </div>
      <div class="runtime-meta">
        <span>Success ${upstream.success_count ?? 0}</span>
        <span>Failure ${upstream.failure_count ?? 0}</span>
        <span>Last latency ${upstream.last_latency_ms ?? "-"} ms</span>
      </div>
      <div class="runtime-meta">
        <span>Verified ${upstream.health_source || "-"}</span>
        <span>Failure source ${upstream.last_failure_source || "-"}</span>
        <span>Circuit trips ${upstream.circuit_trip_count ?? 0}</span>
      </div>
      <div class="runtime-error">${upstream.last_error || ""}</div>
      <div class="actions inline runtime-actions">
        <button class="ghost run-inline-health" data-upstream="${upstream.name}">Check</button>
        <button class="ghost reset-inline-upstream" data-upstream="${upstream.name}">Reset</button>
      </div>
    `;
    runtimeUpstreams.appendChild(item);
  });
}

function routeLineClass(upstream) {
  if (!upstream.enabled) return "disabled";
  if (upstream.circuit_open) return "circuit";
  if (upstream.state === "unhealthy" || upstream.healthy === false) return "degraded";
  if (upstream.healthy) return "healthy";
  return "degraded";
}

function routeStatusLabel(lineClass) {
  if (lineClass === "healthy") return "Healthy";
  if (lineClass === "circuit") return "Circuit Open";
  if (lineClass === "disabled") return "Disabled";
  return "Unhealthy";
}

function routeBadgeTone(lineClass) {
  if (lineClass === "healthy") return "ok";
  if (lineClass === "circuit") return "warn";
  return "dim";
}

function routeWeight(upstream, index) {
  if (upstream.circuit_open || !upstream.enabled) return 1;
  return Math.max(2, 5 - index);
}

function routePathData(startX, startY, endX, endY) {
  const distance = Math.max(60, endX - startX);
  const c1x = startX + Math.min(90, distance * 0.35);
  const c2x = endX - Math.min(140, distance * 0.45);
  return `M ${startX} ${startY} C ${c1x} ${startY}, ${c2x} ${endY}, ${endX} ${endY}`;
}

function queueRouteGraphDraw() {
  if (routeGraphFrame) {
    cancelAnimationFrame(routeGraphFrame);
  }
  routeGraphFrame = requestAnimationFrame(drawRouteGraphLines);
}

function drawRouteGraphLines() {
  routeGraphFrame = 0;
  if (!routeGraph || !routeGraphSvg || !routeRouterNode || !routeHub || !routeLeftStack) {
    return;
  }

  routeLeftStack.style.transform = "";

  const initialGraphRect = routeGraph.getBoundingClientRect();
  const initialRouterRect = routeRouterNode.getBoundingClientRect();
  const initialBranchRects = [...routeMapList.querySelectorAll(".route-branch")].map((node) => ({
    node,
    rect: node.getBoundingClientRect(),
    lineClass: node.dataset.lineClass || "healthy",
    lineWeight: Number(node.dataset.lineWeight || 2),
  }));

  if (initialBranchRects.length) {
    const firstCenterY = initialBranchRects[0].rect.top - initialGraphRect.top + initialBranchRects[0].rect.height / 2;
    const lastCenterY =
      initialBranchRects[initialBranchRects.length - 1].rect.top -
      initialGraphRect.top +
      initialBranchRects[initialBranchRects.length - 1].rect.height / 2;
    const desiredRouterCenterY = (firstCenterY + lastCenterY) / 2;
    const currentRouterCenterY = initialRouterRect.top - initialGraphRect.top + initialRouterRect.height / 2;
    const routerOffsetY = desiredRouterCenterY - currentRouterCenterY;
    routeLeftStack.style.transform = `translateY(${Math.round(routerOffsetY)}px)`;
    routeHub.style.alignSelf = "start";
    routeHub.style.transform = `translateY(${Math.round(desiredRouterCenterY - routeHub.offsetHeight / 2)}px)`;
  } else {
    routeHub.style.alignSelf = "";
    routeHub.style.transform = "";
  }

  const graphRect = routeGraph.getBoundingClientRect();
  const routerRect = routeRouterNode.getBoundingClientRect();
  const hubRect = routeHub.getBoundingClientRect();
  const branchRects = [...routeMapList.querySelectorAll(".route-branch")].map((node) => ({
    node,
    rect: node.getBoundingClientRect(),
    lineClass: node.dataset.lineClass || "healthy",
    lineWeight: Number(node.dataset.lineWeight || 2),
  }));

  routeGraphSvg.setAttribute("viewBox", `0 0 ${Math.round(graphRect.width)} ${Math.round(graphRect.height)}`);
  routeGraphSvg.innerHTML = "";

  const trunkStartX = routerRect.right - graphRect.left;
  const trunkStartY = routerRect.top - graphRect.top + routerRect.height / 2;
  const hubX = hubRect.left - graphRect.left + hubRect.width / 2;
  const hubY = hubRect.top - graphRect.top + hubRect.height / 2;

  const trunk = document.createElementNS("http://www.w3.org/2000/svg", "path");
  trunk.setAttribute("d", `M ${trunkStartX} ${trunkStartY} L ${hubX} ${hubY}`);
  trunk.setAttribute("class", "route-line trunk");
  routeGraphSvg.appendChild(trunk);

  branchRects.forEach(({ rect, lineClass, lineWeight }) => {
    const endX = rect.left - graphRect.left;
    const endY = rect.top - graphRect.top + rect.height / 2;
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", routePathData(hubX, hubY, endX, endY));
    path.setAttribute("class", `route-line ${lineClass}`);
    path.style.setProperty("--line-weight", String(lineWeight));
    routeGraphSvg.appendChild(path);
  });
}

function renderRouteMap(payload) {
  const routingMode = payload.routing?.mode || "strict_priority";
  const listen = payload.listen || { host: "127.0.0.1", port: 8330 };
  routeRouterTitle.textContent = `${listen.host}:${listen.port}`;
  routeModeLabel.textContent = routingMode;

  routeMapList.innerHTML = "";
  const upstreams = payload.upstreams || [];
  upstreams.forEach((upstream, index) => {
    const item = document.createElement("article");
    const lineClass = routeLineClass(upstream);
    const lineWeight = routeWeight(upstream, index);
    const mapEntries = Object.entries(upstream.model_map || {});
    const mapListMarkup = mapEntries.length
      ? `<ul class="route-detail-list">${mapEntries.map(([from, to]) => `<li>${from} -> ${to}</li>`).join("")}</ul>`
      : `<div class="route-detail-empty">No model remap</div>`;
    const supportedModels = (upstream.supported_models || []).length
      ? upstream.supported_models.join(", ")
      : "All";

    item.className = `route-branch ${lineClass}`;
    item.dataset.lineClass = lineClass;
    item.dataset.lineWeight = String(lineWeight);
    item.tabIndex = 0;
    item.innerHTML = `
      <div class="route-branch-order">
        <span class="route-rank">#${index + 1}</span>
      </div>
      <div class="route-branch-body">
        <div class="route-item-header">
          <h3>${upstream.name}</h3>
          <span class="runtime-badge ${routeBadgeTone(lineClass)}">
            ${routeStatusLabel(lineClass)}
          </span>
        </div>
        <div class="route-item-meta">
          <span>${upstream.base_url}</span>
        </div>
        <div class="route-branch-detail" role="tooltip">
          <div class="route-detail-grid">
            <div class="route-detail-cell">
              <span class="route-detail-label">Sort Score</span>
              <strong>${upstream.effective_sort_score ?? upstream.priority}</strong>
            </div>
            <div class="route-detail-cell">
              <span class="route-detail-label">Priority</span>
              <strong>${upstream.priority}</strong>
            </div>
            <div class="route-detail-cell">
              <span class="route-detail-label">Runtime</span>
              <strong>${upstream.runtime_score ?? 0}</strong>
            </div>
            <div class="route-detail-cell">
              <span class="route-detail-label">Latency</span>
              <strong>${upstream.last_latency_ms ?? "-"} ms</strong>
            </div>
            <div class="route-detail-cell">
              <span class="route-detail-label">Health</span>
              <strong>${upstream.last_health_status ?? "-"}</strong>
            </div>
            <div class="route-detail-cell">
              <span class="route-detail-label">Last Check</span>
              <strong>${formatTimestamp(upstream.last_checked_at)}</strong>
            </div>
            <div class="route-detail-cell">
              <span class="route-detail-label">Verified By</span>
              <strong>${upstream.health_source || "-"}</strong>
            </div>
            <div class="route-detail-cell">
              <span class="route-detail-label">Failures</span>
              <strong>${upstream.consecutive_failures ?? 0}</strong>
            </div>
            <div class="route-detail-cell">
              <span class="route-detail-label">Success</span>
              <strong>${upstream.success_count ?? 0}</strong>
            </div>
            <div class="route-detail-cell">
              <span class="route-detail-label">Failure</span>
              <strong>${upstream.failure_count ?? 0}</strong>
            </div>
            <div class="route-detail-cell">
              <span class="route-detail-label">Cooldown</span>
              <strong>${upstream.cooldown_remaining_seconds ?? 0}s</strong>
            </div>
            <div class="route-detail-cell">
              <span class="route-detail-label">Failure Source</span>
              <strong>${upstream.last_failure_source || "-"}</strong>
            </div>
            <div class="route-detail-cell">
              <span class="route-detail-label">Circuit Trips</span>
              <strong>${upstream.circuit_trip_count ?? 0}</strong>
            </div>
            <div class="route-detail-cell">
              <span class="route-detail-label">Models</span>
              <strong>${supportedModels}</strong>
            </div>
          </div>
          <div class="route-detail-section">
            <span class="route-detail-label">Model Map</span>
            ${mapListMarkup}
          </div>
          <div class="route-detail-error">${upstream.last_error || "No recent error."}</div>
        </div>
      </div>
    `;
    routeMapList.appendChild(item);
  });
  queueRouteGraphDraw();
}

function formatTimestamp(value) {
  if (!value) return "-";
  const date = new Date(value * 1000);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleString();
}

function setActionResult(payload) {
  actionResult.textContent = JSON.stringify(payload, null, 2);
  resultStatus.textContent = payload.ok === true ? `OK (${payload.status ?? "-"})` : payload.ok === false ? `Failed (${payload.status ?? "-"})` : "Done";
  resultElapsed.textContent = payload.elapsed_ms ? `${payload.elapsed_ms} ms` : "-";
  resultUpstream.textContent = payload.upstream || "-";
  resultParseMode.textContent = "-";

  let parsed = "";
  let parseMode = "raw";
  if (typeof payload.body_text === "string" && payload.body_text.trim()) {
    try {
      const body = JSON.parse(payload.body_text);
      parseMode = "json";
      const outputs = body.output || [];
      const message = outputs.find((item) => item.type === "message");
      if (message?.content?.length) {
        parsed = message.content
          .filter((part) => part.type === "output_text")
          .map((part) => part.text)
          .join("\n");
      }
    } catch {
      const sse = parseSseOutput(payload.body_text);
      if (sse) {
        parseMode = "sse";
        parsed = sse;
      } else {
        parsed = payload.body_text;
      }
    }
  }
  resultParseMode.textContent = parseMode;
  resultParsed.textContent = parsed || payload.error || "No parsed output.";
}

function parseSseOutput(text) {
  let finalText = "";
  let completedOutput = "";
  const lines = text.split(/\r?\n/);
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed.startsWith("data:")) continue;
    const jsonText = trimmed.slice(5).trim();
    if (!jsonText) continue;
    try {
      const payload = JSON.parse(jsonText);
      if (payload.type === "response.output_text.done" && typeof payload.text === "string") {
        finalText = payload.text;
      }
      if (payload.type === "response.completed") {
        const outputs = payload.response?.output || [];
        const message = outputs.find((item) => item.type === "message");
        if (message?.content?.length) {
          completedOutput = message.content
            .filter((part) => part.type === "output_text")
            .map((part) => part.text)
            .join("\n");
        }
      }
    } catch {
      continue;
    }
  }
  return finalText || completedOutput || "";
}

async function loadStatus() {
  const response = await fetch("/api/status");
  const payload = await response.json();
  renderRuntimeStatus(payload);
  renderRouteMap(payload);
  if (payload.stats_log_path) {
    statsLogPath.textContent = payload.stats_log_path;
  }
}

function renderStats(payload, options = { summary: true, recent: true }) {
  if (payload.log_path) {
    statsLogPath.textContent = payload.log_path;
  }
  const summaryEntries = Object.entries(payload.summary_by_upstream || {});
  if (options.summary) {
    if (!summaryEntries.length) {
      statsSummary.innerHTML = '<div class="empty-state">No stats available.</div>';
    } else {
      const rows = summaryEntries
        .map(
          ([name, item]) => `
            <tr>
              <td>${name}</td>
              <td>${item.request_count}</td>
              <td>${item.success_count}</td>
              <td>${item.failure_count}</td>
              <td>${item.avg_elapsed_ms} ms</td>
              <td>${item.input_tokens}</td>
              <td>${item.output_tokens}</td>
              <td>${item.total_tokens}</td>
              <td>${item.cached_tokens}</td>
              <td>${item.reasoning_tokens}</td>
            </tr>
          `
        )
        .join("");
      statsSummary.innerHTML = `
        <div class="stats-table-shell">
          <table class="stats-table">
            <thead>
              <tr>
                <th>Upstream</th>
                <th>Requests</th>
                <th>Success</th>
                <th>Failure</th>
                <th>Avg Latency</th>
                <th>Input</th>
                <th>Output</th>
                <th>Total</th>
                <th>Cached</th>
                <th>Reasoning</th>
              </tr>
            </thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
      `;
    }
  }

  if (options.recent) {
    const allRecentRecords = payload.recent || [];
    const pagination = payload.recent_pagination || {};
    const totalPages = Math.max(1, Number(pagination.total_pages) || 1);
    const currentPage = Math.min(Math.max(1, Number(pagination.page) || state.logPage), totalPages);
    const totalRecords = Math.max(0, Number(pagination.total) || 0);
    state.logPage = currentPage;
    const recentRecords = allRecentRecords;
    if (logPageInfo) {
      logPageInfo.textContent = `Page ${currentPage} / ${totalPages} (${totalRecords})`;
    }
    if (logPrevBtn) {
      logPrevBtn.disabled = currentPage <= 1;
    }
    if (logNextBtn) {
      logNextBtn.disabled = currentPage >= totalPages;
    }
    if (!recentRecords.length) {
      statsRecent.innerHTML = '<div class="empty-state">No recent requests.</div>';
    } else {
      const rows = recentRecords
        .map((record) => {
          const usage = record.usage || {};
          return `
            <tr>
              <td>${formatTimestamp(record.timestamp)}</td>
              <td>${record.upstream_name || "-"}</td>
              <td>${record.event_type || "-"}</td>
              <td>${record.model || "-"}</td>
              <td class="${record.success ? "table-status ok" : "table-status warn"}">${record.status}</td>
              <td>${record.elapsed_ms} ms</td>
              <td>${usage.total_tokens || 0}</td>
              <td title="${record.error || ""}">${record.error || "-"}</td>
            </tr>
          `;
        })
        .join("");
      statsRecent.innerHTML = `
        <div class="stats-table-shell">
          <table class="stats-table recent-table">
            <thead>
              <tr>
                <th>Time</th>
                <th>Upstream</th>
                <th>Event</th>
                <th>Model</th>
                <th>Status</th>
                <th>Latency</th>
                <th>Total Tokens</th>
                <th>Error</th>
              </tr>
            </thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
      `;
    }
  }
}

async function loadStats() {
  const sinceSeconds = Number(statsRange.value || 0);
  const response = await fetch(`/api/stats?since_seconds=${sinceSeconds}`);
  const payload = await response.json();
  renderStats(payload, { summary: true, recent: false });
}

async function loadLog() {
  const sinceSeconds = Number(logRange?.value || DEFAULT_LOG_RANGE_SECONDS);
  const params = new URLSearchParams({
    since_seconds: String(sinceSeconds),
    hide_fallback_logs: state.hideFallbackLogs ? "1" : "0",
    page: String(state.logPage),
    page_size: String(LOG_PAGE_SIZE),
  });
  const response = await fetch(`/api/stats?${params.toString()}`);
  const payload = await response.json();
  renderStats(payload, { summary: false, recent: true });
}

async function runHealthcheck(upstreamName) {
  try {
    setStatus("Running health check...");
    const response = await fetch("/api/healthcheck", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ upstream_name: upstreamName || null }),
    });
    const payload = await response.json();
    setActionResult(payload);
    setStatus("Health check completed.", "ok");
    await loadStatus();
  } catch (error) {
    actionResult.textContent = String(error);
    setStatus(error.message, "error");
  }
}

async function runTestRequest() {
  try {
    setStatus("Sending test request...");
    const response = await fetch("/api/test-request", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        upstream_name: testUpstream.value,
        model: document.getElementById("testModel").value.trim(),
        prompt: document.getElementById("testPrompt").value.trim(),
      }),
    });
    const payload = await response.json();
    setActionResult(payload);
    setStatus(payload.ok ? "Test request completed." : "Test request failed.", payload.ok ? "ok" : "error");
    await loadStatus();
  } catch (error) {
    setActionResult({ ok: false, error: String(error) });
    setStatus(error.message, "error");
  }
}

async function resetUpstream(upstreamName) {
  try {
    setStatus(`Resetting ${upstreamName}...`);
    const response = await fetch("/api/upstream/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ upstream_name: upstreamName }),
    });
    const payload = await response.json();
    setActionResult(payload);
    setStatus(`Reset completed for ${upstreamName}.`, "ok");
    await loadStatus();
  } catch (error) {
    setActionResult({ ok: false, error: String(error) });
    setStatus(error.message, "error");
  }
}

async function loadConfig() {
  setStatus("Loading configuration...");
  const response = await fetch("/api/config");
  const payload = await response.json();
  state.config = payload;
  ensureUpstreamUiIds(state.config.upstreams || []);
  state.expandedUpstreams = new Set();
  fillForm();
  setStatus("Configuration loaded.", "ok");
}

async function validateConfig() {
  collectForm();
  const response = await fetch("/api/validate");
  const payload = await response.json();
  const target = document.getElementById("validationState");
  if (payload.ok) {
    target.textContent = "Valid";
    setStatus("Validation succeeded.", "ok");
  } else {
    target.textContent = "Invalid";
    setStatus(payload.error || "Validation failed.", "error");
  }
}

async function saveConfig() {
  try {
    collectForm();
    setStatus("Saving configuration...");
    const response = await fetch("/api/config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(state.config),
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      throw new Error(payload.error || "Save failed.");
    }
    setStatus("Configuration saved.", "ok");
    await validateConfig();
    await loadStatus();
  } catch (error) {
    setStatus(error.message, "error");
  }
}

async function reloadService() {
  try {
    setStatus("Reloading service...");
    const response = await fetch("/api/reload", { method: "POST" });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      throw new Error(payload.error || "Reload failed.");
    }
    setStatus("Service reloaded.", "ok");
    await loadStatus();
  } catch (error) {
    setStatus(error.message, "error");
  }
}

function bindControls() {
  document.getElementById("reloadBtn").addEventListener("click", loadConfig);
  document.getElementById("reloadRouteMapBtn").addEventListener("click", loadStatus);
  if (reloadOverviewStatsBtn) {
    reloadOverviewStatsBtn.addEventListener("click", loadStats);
  }
  if (reloadLogBtn) {
    reloadLogBtn.addEventListener("click", loadLog);
  }
  statsRange.addEventListener("change", loadStats);
  if (logRange) {
    logRange.addEventListener("change", () => {
      state.logPage = 1;
      loadLog();
    });
  }
  if (hideFallbackLogs) {
    hideFallbackLogs.addEventListener("change", () => {
      state.hideFallbackLogs = hideFallbackLogs.checked;
      state.logPage = 1;
      loadLog();
    });
  }
  if (logPrevBtn) {
    logPrevBtn.addEventListener("click", () => {
      if (state.logPage > 1) {
        state.logPage -= 1;
        loadLog();
      }
    });
  }
  if (logNextBtn) {
    logNextBtn.addEventListener("click", () => {
      state.logPage += 1;
      loadLog();
    });
  }
  document.getElementById("reloadServiceBtn").addEventListener("click", reloadService);
  document.getElementById("validateBtn").addEventListener("click", validateConfig);
  document.getElementById("saveBtn").addEventListener("click", saveConfig);
  document.getElementById("runHealthcheckBtn").addEventListener("click", () => {
    runHealthcheck(healthcheckUpstream.value || null);
  });
  document.getElementById("runAllHealthchecksBtn").addEventListener("click", () => {
    runHealthcheck(null);
  });
  document.getElementById("runTestRequestBtn").addEventListener("click", runTestRequest);
  if (runtimeUpstreams) {
    runtimeUpstreams.addEventListener("click", (event) => {
      const target = event.target;
      if (!(target instanceof HTMLElement)) return;
      const upstream = target.dataset.upstream;
      if (!upstream) return;
      if (target.classList.contains("run-inline-health")) {
        runHealthcheck(upstream);
      }
      if (target.classList.contains("reset-inline-upstream")) {
        resetUpstream(upstream);
      }
    });
  }
  document.getElementById("addUpstreamBtn").addEventListener("click", () => {
    const uiId = allocateUpstreamUiId();
    state.config.upstreams.push({
      name: "",
      base_url: "",
      api_key: "",
      priority: 100,
      enabled: true,
      supports_stream: true,
      supported_models: [],
      model_map: {},
      healthcheck_path: "/v1/models",
    });
    state.expandedUpstreams.add(uiId);
    renderUpstreams();
    updateRawEditor();
    syncSummary();
  });

  document.querySelectorAll("input").forEach((input) => {
    input.addEventListener("change", collectForm);
  });

  rawEditor.addEventListener("change", () => {
    try {
      state.config = JSON.parse(rawEditor.value);
      fillForm();
      setStatus("Raw JSON parsed.", "ok");
    } catch (error) {
      setStatus(`Raw JSON error: ${error.message}`, "error");
    }
  });
}

bindNavigation();
bindOverviewTabs();
bindConfigTabs();
bindControls();
updateToolbarForSection("overview");
window.addEventListener("resize", queueRouteGraphDraw);
loadConfig();
loadStatus();
loadStats();
loadLog();
