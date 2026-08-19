const state = {
  selectedId: null,
  chart: null,
  flightModalChart: null,
  cities: {},
  trendDays: 7,
  hiddenFlights: new Set(),
  pinnedFlights: new Set(),
  currentRoute: null,
  sparkCharts: new Map(),
  catalog: [],
  offersCache: [],
  offerRoute: null,
  offerTab: "all",
  offerFilters: {
    maxDuration: null,
    sameDay: null,
    bag20: true,
    directOnly: null,
  },
  offerSort: "price",
  lastFlightSeries: {},
  comparePlatforms: [],
  routes: [],
  checkedRouteIds: new Set(),
  notifyRouteId: null,
  notifyDraftEmails: [],
  hasDefaultMail: false,
};

const PINNED_ROUTES_KEY = "gofly.pinnedRoutes";

function defaultOfferFilters() {
  return { maxDuration: null, sameDay: null, bag20: true, directOnly: null };
}

function normalizeOfferFilters(raw) {
  const base = defaultOfferFilters();
  if (!raw || typeof raw !== "object") return base;
  const md = raw.maxDuration ?? raw.max_duration;
  if (md == null || md === "" || md === false) base.maxDuration = null;
  else {
    const n = Number(md);
    base.maxDuration = Number.isFinite(n) && n > 0 ? n : null;
  }
  const sd = raw.sameDay ?? raw.same_day;
  if (sd === true || sd === 1 || sd === "1") base.sameDay = true;
  else if (sd === false || sd === 0 || sd === "0") base.sameDay = false;
  else base.sameDay = null;
  const bag = raw.bag20 ?? raw.bag_20;
  if (bag == null) base.bag20 = true;
  else base.bag20 = bag === true || bag === 1 || bag === "1";
  const direct = raw.directOnly ?? raw.direct_only;
  if (direct === true || direct === 1 || direct === "1") base.directOnly = true;
  else if (direct === false || direct === 0 || direct === "0") base.directOnly = false;
  else base.directOnly = null;
  return base;
}

function filtersEqual(a, b) {
  const x = normalizeOfferFilters(a);
  const y = normalizeOfferFilters(b);
  return (
    x.maxDuration === y.maxDuration &&
    x.sameDay === y.sameDay &&
    x.bag20 === y.bag20 &&
    x.directOnly === y.directOnly
  );
}

function applyRouteDefaultFilters(route) {
  state.offerFilters = normalizeOfferFilters(route?.filters);
}

function filtersDirty() {
  return !filtersEqual(state.offerFilters, state.currentRoute?.filters);
}

async function saveRouteFilters() {
  if (!state.currentRoute?.id) {
    toast("请先选择一条监控航线");
    return;
  }
  const routeId = Number(state.currentRoute.id);
  const payload = normalizeOfferFilters(state.offerFilters);
  try {
    const route = await api(`/api/routes/${routeId}`, {
      method: "PATCH",
      body: JSON.stringify({ filters: payload }),
    });
    if (Number(state.currentRoute?.id) === routeId) {
      state.currentRoute = {
        ...state.currentRoute,
        ...route,
        filters: normalizeOfferFilters(route.filters),
      };
    }
    if (Number(state.offerRoute?.id) === routeId) {
      state.offerRoute = {
        ...state.offerRoute,
        filters: normalizeOfferFilters(route.filters),
      };
    }
    paintOfferFilters(
      (state.offersCache || []).length,
      applyOfferFilters(state.offersCache || []).length
    );
    await loadRoutes();
    paintSelectedRoutePrice();
    toast("已保存为该监控默认筛选（推送按此生效）");
  } catch (err) {
    toast(err.message || String(err));
  }
}

function syncAlertThresholdInput(route) {
  const input = document.getElementById("alertThreshold");
  if (!input) return;
  if (document.activeElement === input) return;
  const v = Number(route?.alert_threshold || 0);
  input.value = v > 0 ? String(Math.round(v)) : "";
}

async function saveAlertThreshold() {
  if (!state.currentRoute?.id) return;
  const input = document.getElementById("alertThreshold");
  if (!input) return;
  const raw = String(input.value || "").trim();
  const next = raw === "" ? 0 : Number(raw);
  if (!Number.isFinite(next) || next < 0) {
    toast("提醒限额需为非负数字");
    syncAlertThresholdInput(state.currentRoute);
    return;
  }
  const prev = Number(state.currentRoute.alert_threshold || 0);
  if (Math.round(prev) === Math.round(next)) {
    syncAlertThresholdInput(state.currentRoute);
    return;
  }
  const routeId = Number(state.currentRoute.id);
  try {
    const route = await api(`/api/routes/${routeId}`, {
      method: "PATCH",
      body: JSON.stringify({ alert_threshold: next }),
    });
    if (Number(state.currentRoute?.id) === routeId) {
      state.currentRoute = { ...state.currentRoute, ...route };
      syncAlertThresholdInput(state.currentRoute);
    }
    await loadRoutes();
    paintTrendFromCache();
    toast(next > 0 ? `提醒限额已设为 ¥${Math.round(next)}` : "已取消提醒限额");
  } catch (err) {
    toast(err.message || String(err));
    syncAlertThresholdInput(state.currentRoute);
  }
}

function resetOfferFiltersToSaved() {
  applyRouteDefaultFilters(state.currentRoute);
  refreshFilteredViews();
}

const NO_FREE_BAG_CODES = new Set(["9C", "AQ", "PN"]);
const KNOWN_AIRLINE_CODES = new Set([
  "CA","CZ","MU","HU","3U","SC","MF","ZH","FM","9C","HO","KN","G5","GS","JD",
  "PN","EU","8L","AQ","GY","DR","UQ","TV","NS","FU","CN","BK","QW","KY","GJ",
  "Y8","A6","LT","GX","RY","GT","9H",
]);
/** 国内航司口碑档：5 四大/厦航，4 全服务较好，3 一般全服务，1–2 廉航/区域 */
const AIRLINE_QUALITY = {
  CA: 5, CZ: 5, MU: 5, HU: 5, MF: 5,
  ZH: 4, FM: 4, SC: 4, "3U": 4, HO: 4, TV: 4,
  KN: 3, GS: 3, JD: 3, NS: 3, FU: 3, KY: 3, EU: 3, QW: 3, GJ: 3, CN: 3,
  G5: 2, "8L": 2, GY: 2, DR: 2, UQ: 2, BK: 2, LT: 2, GX: 2, RY: 2, GT: 2,
  "9H": 2, A6: 2, Y8: 2, PN: 1, "9C": 1, AQ: 1,
};
const AIRLINE_NAME_QUALITY = {
  国航: 5, 南航: 5, 东航: 5, 海航: 5, 厦航: 5,
  深航: 4, 上航: 4, 山航: 4, 川航: 4, 吉祥: 4, 西藏航: 4,
  联航: 3, 天津航: 3, 首都航: 3, 河北航: 3, 福州航: 3, 昆航: 3,
  成都航: 3, 青岛航: 3, 长龙: 3,
  华夏: 2, 祥鹏: 2, 多彩贵州: 2, 瑞丽: 2, 乌航: 2, 奥凯: 2,
  春秋: 1, 九元: 1, 西部航: 1,
};

function loadPinnedRouteIds() {
  try {
    const raw = JSON.parse(localStorage.getItem(PINNED_ROUTES_KEY) || "[]");
    if (!Array.isArray(raw)) return [];
    return raw.map(Number).filter((id) => Number.isFinite(id) && id > 0);
  } catch {
    return [];
  }
}

function savePinnedRouteIds(ids) {
  localStorage.setItem(PINNED_ROUTES_KEY, JSON.stringify(ids));
}

function isRoutePinned(id) {
  return loadPinnedRouteIds().includes(Number(id));
}

function sortRoutesByPin(routes) {
  const pinned = loadPinnedRouteIds();
  const rank = new Map(pinned.map((id, i) => [id, i]));
  return [...routes].sort((a, b) => {
    const pa = rank.has(a.id);
    const pb = rank.has(b.id);
    if (pa && pb) return rank.get(a.id) - rank.get(b.id);
    if (pa) return -1;
    if (pb) return 1;
    return a.id - b.id;
  });
}

function setRoutePinned(id, pinned) {
  const rid = Number(id);
  let ids = loadPinnedRouteIds().filter((x) => x !== rid);
  if (pinned) ids = [rid, ...ids];
  savePinnedRouteIds(ids);
}

function syncPinButton() {
  const btn = document.getElementById("btnPin");
  if (!btn || !state.selectedId) return;
  const pinned = isRoutePinned(state.selectedId);
  btn.textContent = pinned ? "取消置顶" : "置顶";
  btn.classList.toggle("primary", pinned);
  btn.classList.toggle("ghost", !pinned);
}

const PLATFORM_LABEL = {
  mock: "演示",
  fliggy: "飞猪",
  ctrip: "携程",
  qunar: "去哪儿",
};

function money(v) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  return `¥${Math.round(Number(v))}`;
}

function deltaText(d) {
  if (d == null) return { html: "较上期 —", cls: "" };
  const cls = d <= 0 ? "down" : "up";
  const sign = d > 0 ? "+" : "";
  return { html: `较上期 ${sign}${Math.round(d)}`, cls };
}

/** 统一按北京时间展示（与调度器 Asia/Shanghai 一致） */
function fmtTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso).slice(0, 16);
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Shanghai",
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(d);
  const get = (type) => parts.find((p) => p.type === type)?.value || "";
  const hour = get("hour") === "24" ? "00" : get("hour");
  return `${get("month")}/${get("day")} ${hour}:${get("minute")}`;
}

function toast(msg, opts = {}) {
  const el = document.getElementById("toast");
  const kind = opts.type === "error" ? "error" : opts.type === "warn" ? "warn" : "";
  el.textContent = msg;
  el.classList.toggle("toast-error", kind === "error");
  el.classList.toggle("toast-warn", kind === "warn");
  el.hidden = false;
  clearTimeout(toast._t);
  const ms = Number(opts.duration) || (kind === "error" ? 5200 : 2800);
  toast._t = setTimeout(() => {
    el.hidden = true;
    el.classList.remove("toast-error", "toast-warn");
  }, ms);
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = j.detail || JSON.stringify(j);
    } catch {
      msg = (await res.text()) || msg;
    }
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  if (res.status === 204) return null;
  return res.json();
}

function cityLabel(codeOrName) {
  const raw = String(codeOrName || "").trim();
  if (!raw) return "输入城市名";
  if (raw.length === 3 && /^[A-Za-z]+$/.test(raw)) {
    const code = raw.toUpperCase();
    return state.cities[code] ? `${state.cities[code]}（${code}）` : `未收录 ${code}`;
  }
  const hit = (state.catalog || []).find(
    (c) => c.name === raw || c.name.includes(raw) || raw.includes(c.name)
  );
  if (hit) return `${hit.name} · ${hit.code}`;
  return raw.length >= 2 ? `将识别「${raw}」` : "输入城市名";
}

function bindCityHints() {
  const origin = document.getElementById("origin");
  const dest = document.getElementById("destination");
  const oh = document.getElementById("originHint");
  const dh = document.getElementById("destHint");
  const paint = (input, hint) => {
    const v = input.value.trim();
    const known =
      (v.length === 3 && /^[A-Za-z]+$/.test(v) && state.cities[v.toUpperCase()]) ||
      (state.catalog || []).some((c) => c.name === v || c.name.includes(v));
    hint.textContent = cityLabel(v);
    hint.classList.toggle("unknown", v.length >= 2 && !known);
  };
  origin.addEventListener("input", () => paint(origin, oh));
  dest.addEventListener("input", () => paint(dest, dh));
}

async function loadCities() {
  try {
    state.cities = await api("/api/cities");
  } catch {
    state.cities = {};
  }
  state.catalog = await api("/api/cities/catalog");
  if (!state.cities || !Object.keys(state.cities).length) {
    state.cities = Object.fromEntries((state.catalog || []).map((c) => [c.code, c.name]));
  }
  const list = document.getElementById("cityList");
  if (list) {
    list.innerHTML = state.catalog
      .map((c) => `<option value="${c.name}"></option>`)
      .join("");
  }
  bindCityHints();
}

function sparkSvg(values) {
  if (!values || !values.length) {
    return `<svg class="spark" viewBox="0 0 90 36" aria-hidden="true"></svg>`;
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = Math.max(max - min, 1);
  const xAt = (i) =>
    values.length === 1 ? 80 : (i / (values.length - 1)) * 88 + 1;
  const yAt = (v) => 30 - ((v - min) / span) * 24;
  const pts = values.map((v, i) => `${xAt(i).toFixed(1)},${yAt(v).toFixed(1)}`).join(" ");
  const last = values[values.length - 1];
  const down = last <= values[0];
  const color = down ? "#156b4f" : "#b42318";
  const lastX = xAt(values.length - 1).toFixed(1);
  const lastY = yAt(last).toFixed(1);
  const line =
    values.length >= 2
      ? `<polyline fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" points="${pts}" />`
      : "";
  return `<svg class="spark" viewBox="0 0 90 36" aria-hidden="true">
    ${line}
    <circle cx="${lastX}" cy="${lastY}" r="2.4" fill="${color}" />
  </svg>`;
}

async function loadHealth() {
  try {
    const h = await api("/api/health");
    const names = h.platforms.map((p) => PLATFORM_LABEL[p] || p).join(" · ");
    const health = document.getElementById("health");
    const next = document.getElementById("nextRun");
    if (h.scanning) {
      health.classList.add("busy");
      const rid = h.scan_route_id != null ? Number(h.scan_route_id) : null;
      if (rid && String(h.scan_progress || "") === "1/1") {
        const r = (state.routes || []).find((x) => Number(x.id) === rid);
        const label = r
          ? `${r.origin_name || r.origin}→${r.destination_name || r.destination}`
          : `航线 #${rid}`;
        health.textContent = `扫描中 · ${label}`;
      } else {
        health.textContent = `扫描中 ${h.scan_progress || ""}`;
      }
    } else {
      health.classList.remove("busy");
      health.textContent = `${names || "无平台"} · 每 ${h.interval_minutes} 分钟`;
    }
    const last = document.getElementById("lastRun");
    if (last) {
      last.textContent = h.last_scan?.finished_at
        ? `上次检测 ${fmtTime(h.last_scan.finished_at)}`
        : "上次检测 —";
    }
    next.textContent = h.next_run_at
      ? `下次 ${fmtTime(h.next_run_at)}`
      : "下次扫描 —";
    syncScanIntervalSelect(h.interval_minutes);
    state.hasDefaultMail = Boolean(h.notify?.has_default_mail);
    return h;
  } catch {
    document.getElementById("health").textContent = "服务异常";
    return null;
  }
}

function syncScanIntervalSelect(minutes) {
  const sel = document.getElementById("scanInterval");
  if (!sel || minutes == null) return;
  const v = String(minutes);
  if (![...sel.options].some((o) => o.value === v)) {
    const opt = document.createElement("option");
    opt.value = v;
    opt.textContent = `每 ${minutes} 分钟`;
    sel.appendChild(opt);
  }
  if (document.activeElement !== sel) sel.value = v;
}

async function loadAlerts() {
  const alerts = await api("/api/alerts?limit=40");
  const sheet = document.getElementById("alertSheet");
  const box = document.getElementById("alertList");
  if (!alerts.length) {
    sheet.hidden = true;
    return;
  }
  sheet.hidden = false;
  box.innerHTML = alerts
    .map((a) => {
      const od = `${a.origin_name || a.origin} → ${a.destination_name || a.destination}`;
      const dayRaw = String(a.depart_date || "").trim() || String(a.date_label || "").trim();
      const dayCap = dayRaw.includes("~")
        ? dayRaw
        : formatRouteDateCapsule(dayRaw);
      const prev = a.threshold != null ? Number(a.threshold) : null;
      const cur = Number(a.price);
      const dropAmt =
        prev != null && Number.isFinite(prev) && Number.isFinite(cur) && cur < prev
          ? Math.round(prev - cur)
          : null;
      const fn = String(a.flight_no || "").trim();
      const airline = String(a.airline || "").trim();
      let flightLabel = "";
      if (fn) {
        flightLabel =
          airline && !fn.toUpperCase().startsWith(airline.slice(0, 2).toUpperCase())
            ? `${airline} ${fn}`
            : fn;
      } else if (airline) {
        flightLabel = airline;
      }
      const dep = String(a.depart_time || "").slice(-5);
      const platform = PLATFORM_LABEL[a.platform] || a.platform || "";
      const pills = [
        dayCap && dayCap !== "—" ? `<span class="alert-pill">${dayCap}</span>` : "",
        flightLabel
          ? `<span class="alert-pill">${flightLabel}</span>`
          : `<span class="alert-pill muted">未识别航班</span>`,
        dep ? `<span class="alert-pill">${dep}</span>` : "",
        platform ? `<span class="alert-pill">${platform}</span>` : "",
        `<span class="alert-pill muted">${fmtTime(a.observed_at)}</span>`,
      ]
        .filter(Boolean)
        .join("");
      const rid = Number(a.route_id);
      const dayAttr = escapeAttr(String(a.depart_date || "").trim());
      const fnAttr = escapeAttr(fn);
      const dropHtml =
        dropAmt != null
          ? `<span class="alert-drop">↓${dropAmt}</span><span class="alert-prev">原 ${money(prev)}</span>`
          : `<span class="alert-drop">降价</span>`;
      return `<div class="alert-item" role="button" tabindex="0" data-route-id="${rid}" data-flight-no="${fnAttr}" data-depart-date="${dayAttr}" title="查看对应航班">
        <div class="alert-main">
          <div class="alert-route">${od}</div>
          <div class="alert-pills">${pills}</div>
        </div>
        <div class="alert-price">
          <strong>${money(a.price)}</strong>
          <div class="alert-price-meta">${dropHtml}</div>
        </div>
      </div>`;
    })
    .join("");

  box.querySelectorAll(".alert-item").forEach((el) => {
    const open = () => {
      const id = Number(el.dataset.routeId);
      if (!Number.isFinite(id) || id <= 0) return;
      openDetail(id, {
        focusFlight: el.dataset.flightNo || "",
        focusDate: el.dataset.departDate || "",
        requireFocus: true,
      });
    };
    el.addEventListener("click", open);
    el.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        open();
      }
    });
  });
}

function formatRouteDateCapsule(v) {
  const dt = parseDateValue(v);
  if (!dt) return "—";
  const week = ["日", "一", "二", "三", "四", "五", "六"][dt.getDay()];
  return `${dt.getMonth() + 1}/${dt.getDate()} 周${week}`;
}

function formatRouteDateMeta(r) {
  if (!r) return "—";
  if (r.date_label) return r.date_label;
  const start = r.depart_date || "";
  const end = r.depart_date_end || start;
  if (!start) return "—";
  if (!end || end === start) return start;
  const n = Number(r.date_count) || 0;
  return n > 1 ? `${start} ~ ${end}（${n}天）` : `${start} ~ ${end}`;
}

function formatRouteDateCapsuleRange(r) {
  const start = r?.depart_date || "";
  const end = r?.depart_date_end || start;
  if (!start) return "—";
  if (!end || end === start) return formatRouteDateCapsule(start);
  const a = parseDateValue(start);
  const b = parseDateValue(end);
  if (!a || !b) return formatRouteDateMeta(r);
  const days = Math.round((b - a) / 86400000) + 1;
  return `${a.getMonth() + 1}/${a.getDate()}–${b.getMonth() + 1}/${b.getDate()} · ${days}天`;
}

function syncRouteBatchBar() {
  const bar = document.getElementById("routeBatchBar");
  const btnAll = document.getElementById("btnSelectAllRoutes");
  const btnDel = document.getElementById("btnBatchDelete");
  if (!bar || !btnAll || !btnDel) return;
  const total = (state.routes || []).length;
  const n = state.checkedRouteIds.size;
  btnDel.hidden = n === 0;
  btnDel.textContent = n > 0 ? `删除所选 (${n})` : "删除所选";
  btnAll.textContent = total && n === total ? "取消全选" : "全选";
  btnAll.disabled = total === 0;
}

function setRouteChecked(id, checked) {
  const n = Number(id);
  if (!Number.isFinite(n)) return;
  if (checked) state.checkedRouteIds.add(n);
  else state.checkedRouteIds.delete(n);
  const card = document.querySelector(`#routeList .route[data-id="${n}"]`);
  if (card) {
    card.classList.toggle("checked", checked);
    const cb = card.querySelector(".route-check-input");
    if (cb) cb.checked = checked;
  }
  syncRouteBatchBar();
}

async function toggleRouteEnabled(routeId) {
  const id = Number(routeId);
  const cur =
    (state.routes || []).find((r) => Number(r.id) === id) ||
    (Number(state.currentRoute?.id) === id ? state.currentRoute : null);
  if (!cur) return;
  const enabled = !cur.enabled;
  try {
    const route = await api(`/api/routes/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ enabled }),
    });
    if (Number(state.currentRoute?.id) === id) {
      state.currentRoute = route;
      document.getElementById("btnToggle").textContent = route.enabled
        ? "暂停监控"
        : "恢复监控";
    }
    toast(route.enabled ? "已恢复监控" : "已暂停监控");
    await loadRoutes();
  } catch (err) {
    toast(err.message || String(err));
  }
}

async function scanOneRoute(routeId, triggerBtn) {
  const id = Number(routeId);
  if (!id) return;
  if (triggerBtn) {
    triggerBtn.disabled = true;
    triggerBtn.textContent = "扫描中";
  }
  toast("正在扫描该航线…");
  try {
    const result = await api(`/api/routes/${id}/scan`, { method: "POST" });
    await patchRouteCard(id);
    await loadAlerts();
    if (Number(state.selectedId) === id || !state.selectedId) {
      await openDetail(id, { scroll: false, soft: true });
    }
    const hits = (result.drops || result.alerts || []).length;
    toast(hits ? `本航线扫描完成，${hits} 班降价` : "本航线扫描完成");
  } catch (err) {
    toast(err.message || String(err));
  } finally {
    if (triggerBtn) {
      triggerBtn.disabled = false;
      triggerBtn.textContent = "扫描";
    }
    loadHealth();
  }
}

/** 只刷新某一航线卡片的价格/状态，不重绘整列表（避免误以为扫描了全部）。 */
async function patchRouteCard(routeId) {
  const id = Number(routeId);
  if (!id) return null;
  const routes = sortRoutesByPin(await api("/api/routes"));
  state.routes = routes;
  const r = routes.find((x) => Number(x.id) === id);
  const card = document.querySelector(`#routeList .route[data-id="${id}"]`);
  if (!r || !card) {
    await loadRoutes();
    return r || null;
  }
  const d = deltaText(r.delta_vs_prev);
  const priceEl = card.querySelector(".price");
  if (priceEl) priceEl.textContent = money(r.best_price);
  const deltaEl = card.querySelector(".delta");
  if (deltaEl) {
    deltaEl.className = `delta ${d.cls}`;
    deltaEl.textContent = d.html.replace("较上期 ", "");
  }
  const hit = card.querySelector(".badge-hit");
  const shouldHit = r.delta_vs_prev != null && Number(r.delta_vs_prev) < 0;
  if (shouldHit && !hit) {
    const badges = card.querySelector(".route-badges");
    if (badges) {
      badges.insertAdjacentHTML("beforeend", `<span class="badge-hit">降价</span>`);
    }
  } else if (!shouldHit && hit) {
    hit.remove();
  }
  card.classList.toggle("paused", !r.enabled);
  return r;
}

async function deleteRoutesByIds(ids, { confirmMsg } = {}) {
  const list = [...new Set((ids || []).map(Number).filter(Boolean))];
  if (!list.length) return;
  const msg =
    confirmMsg ||
    (list.length === 1
      ? "确定删除这条监控航线？"
      : `确定删除所选 ${list.length} 条监控航线？`);
  if (!confirm(msg)) return;

  try {
    for (const id of list) {
      await api(`/api/routes/${id}`, { method: "DELETE" });
      setRoutePinned(id, false);
      state.checkedRouteIds.delete(id);
    }
    const selectedGone = list.includes(Number(state.selectedId));
    if (selectedGone) {
      document.getElementById("detail").hidden = true;
      state.selectedId = null;
      state.currentRoute = null;
      hideOfferFilters();
      hideRecommendBoard();
    }
    toast(list.length === 1 ? "已删除" : `已删除 ${list.length} 条`);
    const routes = await loadRoutes();
    if (selectedGone && routes.length) {
      await openDetail(routes[0].id, { scroll: false });
    }
  } catch (err) {
    toast(err.message || String(err));
    await loadRoutes();
  }
}

async function handleRouteQuickAct(act, routeId, triggerBtn) {
  const id = Number(routeId);
  if (!id) return;
  if (act === "notify") return openNotifyGroupModal(id);
  if (act === "toggle") return toggleRouteEnabled(id);
  if (act === "scan") return scanOneRoute(id, triggerBtn);
  if (act === "delete") return deleteRoutesByIds([id]);
}

async function loadRoutes() {
  const routes = sortRoutesByPin(await api("/api/routes"));
  state.routes = routes;
  const known = new Set(routes.map((r) => Number(r.id)));
  state.checkedRouteIds = new Set(
    [...state.checkedRouteIds].filter((id) => known.has(id))
  );
  const pinnedIds = loadPinnedRouteIds();
  const cleaned = pinnedIds.filter((id) => known.has(id));
  if (cleaned.length !== pinnedIds.length) savePinnedRouteIds(cleaned);

  const box = document.getElementById("routeList");
  if (!routes.length) {
    box.innerHTML = `<div class="empty" style="flex:1 1 100%">还没有航线。上方填出发、到达和日期即可添加。</div>`;
    syncRouteBatchBar();
    return routes;
  }

  box.innerHTML = routes
    .map((r) => {
      const d = deltaText(r.delta_vs_prev);
      const active = state.selectedId === r.id ? "active" : "";
      const paused = r.enabled ? "" : "paused";
      const pinned = cleaned.includes(r.id);
      const checked = state.checkedRouteIds.has(Number(r.id));
      const hit =
        r.delta_vs_prev != null && Number(r.delta_vs_prev) < 0
          ? `<span class="badge-hit">降价</span>`
          : "";
      const pausedMark = r.enabled ? "" : `<span class="badge-paused">暂停</span>`;
      const pinMark = pinned ? `<span class="badge-pin">置顶</span>` : "";
      const statusMark = r.enabled
        ? `<span class="badge-on">监控中</span>`
        : "";
      const threshold = Number(r.alert_threshold || 0);
      const thresholdText = threshold > 0 ? `限额 ¥${Math.round(threshold)}` : "";
      const emails = Array.isArray(r.notify_emails) ? r.notify_emails : [];
      const notifyCls = emails.length ? "has-notify" : "";
      const notifyTitle = emails.length
        ? `接收组：${emails.join("、")}`
        : "配置推送接收组";
      const dateLabel = formatRouteDateCapsuleRange(r);
      const dateTitle = formatRouteDateMeta(r);
      const toggleLabel = r.enabled ? "暂停" : "恢复";
      return `
        <div class="route ${active} ${paused} ${pinned ? "pinned" : ""} ${checked ? "checked" : ""}" data-id="${r.id}" role="button" tabindex="0" title="${r.origin}–${r.destination} · ${dateTitle}">
          <label class="route-check" title="选择以便批量删除">
            <input class="route-check-input" type="checkbox" data-id="${r.id}" ${checked ? "checked" : ""} />
          </label>
          <span class="route-main">
            <span class="route-body">
              <span class="route-top">
                <span class="od">${r.origin_name || r.origin} → ${r.destination_name || r.destination}</span>
              </span>
              <span class="route-date" title="${dateTitle}">
                <button type="button" class="date-capsule" data-act="edit-date" data-id="${r.id}" title="点击修改日期范围">${dateLabel}</button>
              </span>
              <span class="route-actions">
                <button type="button" class="act-pill ${notifyCls}" data-act="notify" data-id="${r.id}" title="${notifyTitle}">接收</button>
                <button type="button" class="act-pill" data-act="toggle" data-id="${r.id}" title="${toggleLabel}监控">${toggleLabel}</button>
                <button type="button" class="act-pill" data-act="scan" data-id="${r.id}" title="重新扫描">扫描</button>
                <button type="button" class="act-pill danger" data-act="delete" data-id="${r.id}" title="删除">删除</button>
              </span>
              <span class="route-mid">
                <span class="route-price-group">
                  <span class="price">${money(r.best_price)}</span>
                  <span class="delta ${d.cls}">${d.html.replace("较上期 ", "")}</span>
                </span>
                <span class="route-threshold">${thresholdText}</span>
              </span>
            </span>
            <span class="route-badges">${statusMark}${pinMark}${hit}${pausedMark}</span>
          </span>
        </div>`;
    })
    .join("");

  const isQuickTarget = (t) => t.closest(".route-check, .act-pill, .date-capsule");

  box.querySelectorAll(".route").forEach((el) => {
    const open = () => openDetail(Number(el.dataset.id));
    el.addEventListener("click", (e) => {
      if (isQuickTarget(e.target)) return;
      open();
    });
    el.addEventListener("keydown", (e) => {
      if (isQuickTarget(e.target)) return;
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        open();
      }
    });
  });

  box.querySelectorAll(".route-check-input").forEach((cb) => {
    cb.addEventListener("click", (e) => e.stopPropagation());
    cb.addEventListener("change", (e) => {
      e.stopPropagation();
      setRouteChecked(cb.dataset.id, cb.checked);
    });
  });

  box.querySelectorAll(".act-pill, .date-capsule[data-act]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      handleRouteQuickAct(btn.dataset.act, btn.dataset.id, btn);
    });
  });

  syncRouteBatchBar();
  syncPinButton();
  paintSelectedRoutePrice();
  return routes;
}

async function openDetail(id, opts = {}) {
  const {
    scroll = true,
    soft = false,
    focusFlight = "",
    focusDate = "",
    requireFocus = false,
  } = opts;
  const focusFn = String(focusFlight || "").trim();
  const focusDay = String(focusDate || "").trim();

  const data = await api(`/api/routes/${id}/compare`);
  const r = data.route;
  const priced = (data.platforms || [])
    .filter((p) => p.min_price != null)
    .sort((a, b) => a.min_price - b.min_price);
  const merged = priced.flatMap((p) =>
    (p.offers || []).map((o) => {
      const meta = normalizeMeta(o.meta);
      return {
        ...o,
        meta,
        platform: p.platform,
        origin: r.origin,
        destination: r.destination,
        depart_date: p.depart_date || o.depart_date || r.depart_date,
        _complete: !!(o.depart_time && o.arrive_time && o.flight_no),
      };
    })
  );

  const matchFocusOffer = (list) => {
    if (!focusFn) return null;
    const exact = list.find((o) => {
      const sameFn =
        String(o.flight_no || "").trim().toUpperCase() === focusFn.toUpperCase();
      if (!sameFn) return false;
      if (!focusDay) return true;
      return String(o.depart_date || "").trim() === focusDay;
    });
    if (exact) return exact;
    if (focusDay) return null;
    return list.find(
      (o) =>
        String(o.flight_no || "").trim().toUpperCase() === focusFn.toUpperCase()
    );
  };

  if (requireFocus && focusFn) {
    const hit = matchFocusOffer(merged);
    if (!hit) {
      toast(
        `未找到航班 ${focusFn}${focusDay ? ` · ${focusDay}` : ""}：当前报价里没有这班，可能已下架或尚未扫到该日`,
        { type: "error" }
      );
      return false;
    }
  }

  const focusHit = focusFn ? matchFocusOffer(merged) : null;

  state.selectedId = id;
  if (!soft) {
    state.hiddenFlights = new Set();
    state.pinnedFlights = new Set();
    state.lastFlightSeries = {};
  }
  const detail = document.getElementById("detail");
  detail.hidden = false;
  syncPinButton();

  state.currentRoute = r;
  if (!soft) applyRouteDefaultFilters(r);
  let filtersRelaxed = false;
  if (focusHit) {
    const next = filtersToRevealOffer(focusHit, state.offerFilters);
    if (!filtersEqual(next, state.offerFilters)) {
      state.offerFilters = next;
      filtersRelaxed = true;
    }
  }
  document.getElementById("detailTitle").textContent =
    `${r.origin_name || r.origin} → ${r.destination_name || r.destination}`;
  const odEl = document.getElementById("detailOd");
  const dateBtn = document.getElementById("detailDateBtn");
  if (odEl) odEl.textContent = `${r.origin}–${r.destination}`;
  if (dateBtn) {
    dateBtn.textContent = formatRouteDateMeta(r);
    dateBtn.hidden = false;
    dateBtn.dataset.routeId = String(r.id);
  } else {
    document.getElementById("detailSub").textContent =
      `${r.origin}–${r.destination} · ${formatRouteDateMeta(r)}`;
  }
  syncAlertThresholdInput(r);
  document.getElementById("btnToggle").textContent = r.enabled
    ? "暂停监控"
    : "恢复监控";
  syncPinButton();

  if (!soft) await loadRoutes();
  state.comparePlatforms = data.platforms || [];

  const offerBox = document.getElementById("offerTable");
  const complete = merged.filter((o) => o._complete);
  const pool = (complete.length >= 3 ? complete : merged).sort(
    (a, b) => a.price - b.price
  );
  // 直飞/中转都保留，避免被低价中转挤掉直飞或反之
  const direct = pool.filter((o) => !isTransferOffer(o)).slice(0, 20);
  const transfer = pool.filter((o) => isTransferOffer(o)).slice(0, 30);
  if (focusFn) {
    const hit = matchFocusOffer(pool) || matchFocusOffer(merged);
    if (hit) {
      const bucket = isTransferOffer(hit) ? transfer : direct;
      const already = bucket.some(
        (o) =>
          String(o.flight_no || "").trim().toUpperCase() ===
            String(hit.flight_no || "").trim().toUpperCase() &&
          String(o.depart_date || "") === String(hit.depart_date || "")
      );
      if (!already) bucket.unshift(hit);
    }
  }
  const allOffers = [...direct, ...transfer];
  state.offersCache = allOffers;
  state.offerRoute = r;
  if (!soft) state.offerTab = "all";

  if (!allOffers.length) {
    hideOfferFilters();
    hideRecommendBoard();
    offerBox.innerHTML = `<div class="empty">暂无航班明细，请点「重新扫描」</div>`;
    paintCompareTable();
  } else {
    paintFlightBoard();
    paintCompareTable();
    paintSelectedRoutePrice();
  }

  await renderTrend(id);
  if (scroll) {
    document.getElementById("monitorPanel").scrollIntoView({ behavior: "smooth", block: "start" });
  }
  if (focusFn) {
    window.setTimeout(() => scrollToFlight(focusFn, focusDay), scroll ? 280 : 60);
  }
  if (filtersRelaxed) {
    toast("已临时放宽筛选以显示该航班");
  }
  return true;
}

function offerDurationMin(o) {
  const dep = String(o.depart_time || "").slice(-5);
  const arr = String(o.arrive_time || "").slice(-5);
  const d = Number(o.duration_min);
  if (d && d > 0) return d;
  return estimateDuration(dep, arr);
}

function isSameDayArrival(o) {
  const m = normalizeMeta(o.meta);
  const cross = Number(m.cross_days || 0);
  if (cross > 0) return false;
  if (m.cross_days_label) return false;
  const dep = String(o.depart_time || "").slice(-5);
  const arr = String(o.arrive_time || "").slice(-5);
  if (dep.includes(":") && arr.includes(":")) {
    const [dh, dm] = dep.split(":").map(Number);
    const [ah, am] = arr.split(":").map(Number);
    const depM = dh * 60 + dm;
    const arrM = ah * 60 + am;
    const dur = offerDurationMin(o);
    // 到达时刻早于出发且总时长明显跨日
    if (arrM < depM && dur != null && dur > 8 * 60) return false;
  }
  return true;
}

function applyOfferFilters(offers) {
  const { maxDuration, sameDay, bag20, directOnly } = state.offerFilters;
  return offers.filter((o) => {
    if (maxDuration != null) {
      const dur = offerDurationMin(o);
      if (dur == null || dur > maxDuration) return false;
    }
    if (sameDay === true && !isSameDayArrival(o)) return false;
    if (sameDay === false && isSameDayArrival(o)) return false;
    if (bag20 && !offerHas20kg(o)) return false;
    if (directOnly === true && isTransferOffer(o)) return false;
    if (directOnly === false && !isTransferOffer(o)) return false;
    return true;
  });
}

/** 仅放宽挡住目标航班的筛选项，其余保持不变（不写回监控默认）。 */
function filtersToRevealOffer(offer, base) {
  const f = normalizeOfferFilters(base || state.offerFilters);
  if (!offer) return f;
  if (f.bag20 && !offerHas20kg(offer)) f.bag20 = false;
  if (f.directOnly === true && isTransferOffer(offer)) f.directOnly = null;
  if (f.directOnly === false && !isTransferOffer(offer)) f.directOnly = null;
  if (f.sameDay === true && !isSameDayArrival(offer)) f.sameDay = null;
  if (f.sameDay === false && isSameDayArrival(offer)) f.sameDay = null;
  if (f.maxDuration != null) {
    const dur = offerDurationMin(offer);
    if (dur == null || dur > f.maxDuration) f.maxDuration = null;
  }
  return f;
}

function iataCodesFromFlight(flightNo) {
  const s = String(flightNo || "")
    .toUpperCase()
    .replace(/[-_]/g, "/");
  const out = [];
  for (const token of s.split(/[/\s,;+]+/)) {
    const m = token.match(/^([A-Z0-9]{2})\d{2,4}/);
    const code = m ? m[1] : token.length === 2 ? token : "";
    if (code && /^[A-Z0-9]{2}$/.test(code) && !out.includes(code)) out.push(code);
  }
  return out;
}

function inferBaggageFromCodes(codes) {
  if (!codes.length) {
    return { kg: null, has20: false, status: "unknown", text: "行李未知" };
  }
  let minKg = null;
  let unknown = false;
  for (const code of codes) {
    if (NO_FREE_BAG_CODES.has(code)) {
      minKg = minKg == null ? 0 : Math.min(minKg, 0);
    } else if (KNOWN_AIRLINE_CODES.has(code)) {
      minKg = minKg == null ? 20 : Math.min(minKg, 20);
    } else {
      unknown = true;
    }
  }
  if (unknown || minKg == null) {
    return { kg: minKg, has20: false, status: "unknown", text: "行李未知" };
  }
  if (minKg >= 20) {
    return { kg: minKg, has20: true, status: "ok", text: `托运${minKg}kg` };
  }
  return { kg: minKg, has20: false, status: "none", text: minKg > 0 ? `托运${minKg}kg` : "不含托运" };
}

function offerBaggage(o) {
  const m = normalizeMeta(o.meta);
  if (m.baggage_kg != null && m.baggage_kg !== "") {
    const kg = Number(m.baggage_kg);
    if (!Number.isNaN(kg)) {
      const status = m.baggage_status || (kg >= 20 ? "ok" : kg > 0 ? "none" : "none");
      const has20 = m.has_20kg === true || (status !== "unknown" && kg >= 20);
      return {
        kg,
        has20: !!has20 && status !== "unknown",
        status: status === "unknown" ? "unknown" : kg >= 20 ? "ok" : "none",
        text: m.baggage_text || (kg >= 20 ? `托运${kg}kg` : kg > 0 ? `托运${kg}kg` : "不含托运"),
      };
    }
  }
  if (m.has_20kg === true && m.baggage_status !== "unknown") {
    return { kg: 20, has20: true, status: "ok", text: m.baggage_text || "托运20kg" };
  }
  if (m.baggage_status === "unknown" || m.has_20kg == null) {
    return inferBaggageFromCodes(iataCodesFromFlight(o.flight_no));
  }
  return {
    kg: 0,
    has20: false,
    status: "none",
    text: m.baggage_text || "不含托运",
  };
}

function offerHas20kg(o) {
  return offerBaggage(o).has20 === true;
}

function medianNum(arr) {
  const s = arr.filter((n) => n != null && Number.isFinite(n)).sort((a, b) => a - b);
  if (!s.length) return null;
  const mid = Math.floor(s.length / 2);
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
}

function offerAirlineCodes(o) {
  const meta = normalizeMeta(o.meta);
  const fromNo = iataCodesFromFlight(o.flight_no);
  const extra = (meta.leg_flights || []).flatMap((fn) => iataCodesFromFlight(fn));
  const out = [];
  for (const code of [...fromNo, ...extra]) {
    if (code && !out.includes(code)) out.push(code);
  }
  return out;
}

function airlineQuality(o) {
  const codes = offerAirlineCodes(o);
  if (codes.length) {
    return Math.min(...codes.map((c) => AIRLINE_QUALITY[c] ?? 2));
  }
  const name = String(resolveAirline(o) || "").replace(/航空|公司|\|/g, "").trim();
  if (AIRLINE_NAME_QUALITY[name] != null) return AIRLINE_NAME_QUALITY[name];
  const hit = Object.keys(AIRLINE_NAME_QUALITY).find((k) => name.includes(k));
  return hit ? AIRLINE_NAME_QUALITY[hit] : 2;
}

function uniqueOffersByFlight(offers) {
  const map = new Map();
  for (const o of offers) {
    const key = o.flight_no || `${o.airline}-${o.depart_time}-${o.price}`;
    const prev = map.get(key);
    if (!prev || Number(o.price) < Number(prev.price)) map.set(key, o);
  }
  return [...map.values()];
}

function departHourKey(o) {
  const t = String(o.depart_time || "").match(/(\d{1,2}):/);
  return t ? String(Number(t[1])).padStart(2, "0") : "";
}

function pickRecommendedOffers(offers, limit = 3) {
  const uniq = uniqueOffersByFlight(offers).filter(
    (o) => o.price != null && Number.isFinite(Number(o.price)) && Number(o.price) > 0
  );
  if (!uniq.length) return [];
  const rows = uniq.map((o) => ({
    o,
    dur: offerDurationMin(o),
    q: airlineQuality(o),
    xfer: isTransferOffer(o),
  }));
  if (rows.length === 1) {
    return [{ offer: rows[0].o, reasons: ["当前仅此报价"] }];
  }

  const prices = rows.map((x) => Number(x.o.price));
  const durs = rows.map((x) => x.dur).filter((d) => d != null && d > 0);
  const minP = Math.min(...prices);
  const medP = medianNum(prices);
  const minD = durs.length ? Math.min(...durs) : null;
  const medD = durs.length ? medianNum(durs) : null;
  const maxP = Math.max(...prices);
  const maxD = durs.length ? Math.max(...durs) : null;
  const directs = rows.filter((x) => !x.xfer);
  const priceCap = Math.max(medP ?? minP, minP * 1.28);
  const durCap = minD == null ? Infinity : Math.max(medD ?? minD, minD * 1.35);

  const reasonable = (x) => {
    if (Number(x.o.price) > priceCap * 1.08) return false;
    if (x.dur != null && x.dur > durCap * 1.08) return false;
    return true;
  };

  const reasonableDirects = directs.filter(reasonable);
  const goodDirects = reasonableDirects.filter((x) => x.q >= 4);
  const poolBase = goodDirects.length
    ? directs
    : reasonableDirects.length
      ? directs
      : rows;

  let cand = poolBase.filter((x) => x.q >= 4 && reasonable(x));
  if (!cand.length) cand = poolBase.filter((x) => x.q >= 3 && reasonable(x));
  if (!cand.length) cand = poolBase.filter(reasonable);
  if (!cand.length) cand = poolBase;

  cand = cand.filter((a) => {
    return !cand.some((b) => {
      if (b === a) return false;
      const betterPrice = Number(b.o.price) <= Number(a.o.price);
      const betterDur = (b.dur ?? 1e9) <= (a.dur ?? 1e9);
      const betterQ = b.q >= a.q;
      const strictly =
        Number(b.o.price) < Number(a.o.price) ||
        (b.dur != null && a.dur != null && b.dur < a.dur) ||
        b.q > a.q;
      return betterPrice && betterDur && betterQ && strictly;
    });
  });

  const spanP = Math.max(maxP - minP, 1);
  const spanD = minD == null ? 1 : Math.max((maxD ?? minD) - minD, 1);
  cand.sort((a, b) => {
    const score = (x) => {
      const p = (Number(x.o.price) - minP) / spanP;
      const d = x.dur == null || minD == null ? 0.45 : (x.dur - minD) / spanD;
      const q = (5 - x.q) / 5;
      const xfer = x.xfer ? 0.1 : 0;
      const bag = offerHas20kg(x.o) ? 0 : 0.06;
      const overnight = isSameDayArrival(x.o) ? 0 : 0.04;
      return 0.34 * p + 0.34 * d + 0.26 * q + xfer + bag + overnight;
    };
    return score(a) - score(b);
  });

  const picked = [];
  for (const x of cand) {
    if (picked.length >= limit) break;
    const hour = departHourKey(x.o);
    const clash = picked.some(
      (p) =>
        departHourKey(p.o) === hour &&
        hour &&
        resolveAirline(p.o) === resolveAirline(x.o)
    );
    if (clash) continue;
    picked.push(x);
  }
  if (!picked.length && cand.length) picked.push(cand[0]);
  if (picked.length < Math.min(2, cand.length)) {
    for (const x of cand) {
      if (picked.length >= Math.min(limit, 2)) break;
      if (!picked.includes(x)) picked.push(x);
    }
  }

  return picked.map((x) => ({
    offer: x.o,
    reasons: recommendReasons(x, minP, minD, medP, medD),
  }));
}

function recommendReasons(x, minP, minD, medP, medD) {
  const reasons = [];
  if (x.q >= 4) reasons.push("航司较好");
  else if (x.q >= 3) reasons.push("航司口碑尚可");
  const extra = Number(x.o.price) - minP;
  if (extra <= Math.max(30, minP * 0.05)) reasons.push("接近最低价");
  else if (medP != null && Number(x.o.price) <= medP * 1.02) reasons.push("价格适中");
  else reasons.push(`比最低价高 ¥${Math.round(extra)}`);
  if (x.dur != null && minD != null) {
    const dExtra = x.dur - minD;
    if (dExtra <= 25) reasons.push("时长接近最短");
    else if (medD != null && x.dur <= medD * 1.05) reasons.push("总时长适中");
    else reasons.push(`比最短多 ${formatDuration(dExtra)}`);
  }
  if (!x.xfer) reasons.push("直飞");
  return reasons.slice(0, 3);
}

function hideRecommendBoard() {
  const el = document.getElementById("recommendBoard");
  if (!el) return;
  el.hidden = true;
  el.innerHTML = "";
}

function renderRecommendBoard(recs, route) {
  const items = recs
    .map(({ offer, reasons }) => {
      const row = isTransferOffer(offer)
        ? renderTransferRow(offer, route)
        : renderDirectRow(offer, route);
      const why = reasons
        .map((r) => `<span class="rec-pill">${r}</span>`)
        .join("");
      return `<div class="rec-item" title="点击跳到下方列表">
        <div class="rec-why">${why}</div>
        ${row}
      </div>`;
    })
    .join("");
  return `
    <div class="rec-head">
      <h3 class="block-title">推荐航班</h3>
      <p class="rec-sub">航司较好，价格与总时长相对均衡</p>
    </div>
    <div class="rec-list">${items}</div>`;
}

function paintRecommendBoard() {
  const box = document.getElementById("recommendBoard");
  if (!box) return;
  const cache = applyOfferFilters(state.offersCache || []);
  const route = state.offerRoute || state.currentRoute;
  const recs = pickRecommendedOffers(cache, 3);
  if (!recs.length) {
    hideRecommendBoard();
    return;
  }
  box.hidden = false;
  box.innerHTML = renderRecommendBoard(recs, route);
  bindFlightTrendOpen(box);
}

function bindRecommendUi() {
  const box = document.getElementById("recommendBoard");
  if (!box || box.dataset.uiBound === "1") return;
  box.dataset.uiBound = "1";
  box.addEventListener("click", (e) => {
    if (e.target.closest("a, .flight-trend, button")) return;
    const row = e.target.closest(".fb-row");
    if (!row || !box.contains(row)) return;
    const fn = row.getAttribute("data-flight-no");
    if (fn) scrollToFlight(fn);
  });
}

function baggagePill(o) {
  const b = offerBaggage(o);
  return `<span class="bag-pill ${b.status}" title="${b.text}">${b.text}</span>`;
}

function timeMinutes(value) {
  const m = String(value || "").match(/(\d{1,2}):(\d{2})/);
  if (!m) return 1e9;
  return Number(m[1]) * 60 + Number(m[2]);
}

function sortOffers(list) {
  const key = state.offerSort || "price";
  const copy = [...list];
  const dur = (o) => offerDurationMin(o) ?? 1e9;
  const dep = (o) => timeMinutes(o.depart_time);
  const delta = (o) => (o.price_delta == null ? 1e9 : Number(o.price_delta));
  if (key === "duration") copy.sort((a, b) => dur(a) - dur(b) || a.price - b.price);
  else if (key === "depart") copy.sort((a, b) => dep(a) - dep(b) || a.price - b.price);
  else if (key === "depart_desc") copy.sort((a, b) => dep(b) - dep(a) || a.price - b.price);
  else if (key === "delta") copy.sort((a, b) => delta(a) - delta(b) || a.price - b.price);
  else copy.sort((a, b) => a.price - b.price);
  return copy;
}

function hideOfferFilters() {
  const el = document.getElementById("fbFilters");
  if (!el) return;
  el.hidden = true;
  el.innerHTML = "";
}

function paintOfferFilters(total, filteredN) {
  const el = document.getElementById("fbFilters");
  if (!el) return;
  const f = state.offerFilters;
  const durOpts = [
    { v: "", label: "不限" },
    { v: "360", label: "≤6小时" },
    { v: "480", label: "≤8小时" },
    { v: "600", label: "≤10小时" },
    { v: "720", label: "≤12小时" },
    { v: "1440", label: "≤24小时" },
  ];
  const dayOpts = [
    { v: "", label: "不限" },
    { v: "1", label: "当天到达" },
    { v: "0", label: "跨天到达" },
  ];
  const bagOpts = [
    { v: "1", label: "含20kg托运" },
    { v: "", label: "不限" },
  ];
  const directOpts = [
    { v: "", label: "不限" },
    { v: "1", label: "仅直飞" },
    { v: "0", label: "仅中转" },
  ];
  const sortOpts = [
    { v: "price", label: "价格" },
    { v: "duration", label: "时长" },
    { v: "depart", label: "出发早" },
    { v: "depart_desc", label: "出发晚" },
    { v: "delta", label: "降幅" },
  ];
  el.innerHTML = renderOfferFilters(
    durOpts,
    dayOpts,
    bagOpts,
    directOpts,
    sortOpts,
    f,
    total,
    filteredN
  );
  el.hidden = false;
  bindOfferFiltersUi(el);
}

function renderOfferFilters(durOpts, dayOpts, bagOpts, directOpts, sortOpts, f, total, filteredN) {
  const bagCur = f.bag20 ? "1" : "";
  const sortCur = state.offerSort || "price";
  const dirty = filtersDirty();
  let directCur = "";
  if (f.directOnly === true) directCur = "1";
  else if (f.directOnly === false) directCur = "0";
  return `
      <div class="fb-filter-group">
        <span class="fb-filter-label">总时长</span>
        <div class="fb-filter-seg" data-filter="maxDuration">
          ${durOpts
            .map((opt) => {
              const cur = f.maxDuration == null ? "" : String(f.maxDuration);
              const active = cur === opt.v ? "active" : "";
              return `<button type="button" class="fb-chip ${active}" data-value="${opt.v}">${opt.label}</button>`;
            })
            .join("")}
        </div>
      </div>
      <div class="fb-filter-group">
        <span class="fb-filter-label">到达日</span>
        <div class="fb-filter-seg" data-filter="sameDay">
          ${dayOpts
            .map((opt) => {
              let cur = "";
              if (f.sameDay === true) cur = "1";
              else if (f.sameDay === false) cur = "0";
              const active = cur === opt.v ? "active" : "";
              return `<button type="button" class="fb-chip ${active}" data-value="${opt.v}">${opt.label}</button>`;
            })
            .join("")}
        </div>
      </div>
      <div class="fb-filter-group">
        <span class="fb-filter-label">直飞</span>
        <div class="fb-filter-seg" data-filter="directOnly">
          ${directOpts
            .map((opt) => {
              const active = directCur === opt.v ? "active" : "";
              return `<button type="button" class="fb-chip ${active}" data-value="${opt.v}">${opt.label}</button>`;
            })
            .join("")}
        </div>
      </div>
      <div class="fb-filter-group">
        <span class="fb-filter-label">行李</span>
        <div class="fb-filter-seg" data-filter="bag20">
          ${bagOpts
            .map((opt) => {
              const active = bagCur === opt.v ? "active" : "";
              return `<button type="button" class="fb-chip ${active}" data-value="${opt.v}">${opt.label}</button>`;
            })
            .join("")}
        </div>
      </div>
      <div class="fb-filter-group">
        <span class="fb-filter-label">排序</span>
        <div class="fb-filter-seg" data-filter="offerSort">
          ${sortOpts
            .map((opt) => {
              const active = sortCur === opt.v ? "active" : "";
              return `<button type="button" class="fb-chip ${active}" data-value="${opt.v}">${opt.label}</button>`;
            })
            .join("")}
        </div>
      </div>
      <div class="fb-filter-meta">
        <span>显示 ${filteredN} / ${total}</span>
        <span class="fb-filter-hint">${dirty ? "未保存 · 仅预览" : "推送按已保存筛选"}</span>
        ${dirty ? `<button type="button" class="btn ghost fb-filter-reset" data-filter-act="reset">还原</button>` : ""}
        <button type="button" class="btn primary fb-filter-save" data-filter-act="save" ${dirty ? "" : "disabled"}>保存默认</button>
      </div>`;
}

function paintFlightBoard() {
  const offerBox = document.getElementById("offerTable");
  if (!offerBox) return;
  const route = state.offerRoute || state.currentRoute;
  const cache = state.offersCache || [];
  const filtered = applyOfferFilters(cache);
  paintOfferFilters(cache.length, filtered.length);
  offerBox.innerHTML = renderFlightBoard(filtered, route, cache.length);
  bindFlightBoardUi(offerBox);
  applyOfferTab(offerBox, state.offerTab || "all");
  bindFlightTrendOpen(offerBox);
  paintRecommendBoard();
}

function cheapestOffer(list) {
  if (!list.length) return null;
  return list.reduce((a, b) => (Number(a.price) <= Number(b.price) ? a : b));
}

function paintCompareTable() {
  const compare = document.getElementById("compareTable");
  if (!compare) return;
  const platforms = state.comparePlatforms || [];
  if (!platforms.length) {
    compare.innerHTML = `<div class="empty">暂无比价数据，点「重新扫描」拉取真实报价。</div>`;
    return;
  }
  const cache = state.offersCache || [];
  const filtered = cache.length ? applyOfferFilters(cache) : [];
  const byPlat = new Map();
  for (const o of filtered) {
    const key = o.platform || "";
    if (!byPlat.has(key)) byPlat.set(key, []);
    byPlat.get(key).push(o);
  }
  const rows = platforms.map((p) => {
    if (!cache.length) return p;
    const list = byPlat.get(p.platform) || [];
    const cheapest = cheapestOffer(list);
    return {
      ...p,
      min_price: cheapest ? Number(cheapest.price) : null,
      offer_count: list.length,
      delta_vs_prev: cheapest ? cheapest.price_delta : null,
    };
  });
  const ok = rows.filter((p) => p.min_price != null);
  const best = ok.length ? Math.min(...ok.map((p) => p.min_price)) : null;
  compare.innerHTML = rows
    .map((p) => {
      const isBest = p.min_price != null && p.min_price === best;
      const d = deltaText(p.delta_vs_prev);
      return `
          <div class="card ${isBest ? "best" : ""}">
            <div class="name">${PLATFORM_LABEL[p.platform] || p.platform}${isBest ? " · 最低" : ""}</div>
            <div class="val">${money(p.min_price)}</div>
            <div class="meta"><span class="delta ${d.cls}">${d.html}</span></div>
            ${
              p.error
                ? `<div class="err">${p.error}</div>`
                : `<div class="meta" style="margin-top:.35rem;color:var(--muted);font-size:.78rem">${p.offer_count || 0} 条报价 · ${fmtTime(p.observed_at)}</div>`
            }
          </div>`;
    })
    .join("");
}

function paintSelectedRoutePrice() {
  const btn = document.querySelector("#routeList .route.active");
  if (!btn || !(state.offersCache || []).length) return;
  const routeId = Number(state.offerRoute?.id || state.currentRoute?.id || state.selectedId);
  if (Number(btn.dataset.id) !== routeId) return;
  const cheapest = cheapestOffer(applyOfferFilters(state.offersCache));
  const priceEl = btn.querySelector(".price");
  if (priceEl) priceEl.textContent = money(cheapest?.price ?? null);
  const deltaEl = btn.querySelector(".delta");
  if (deltaEl) {
    const d = deltaText(cheapest?.price_delta);
    deltaEl.className = `delta ${d.cls}`;
    deltaEl.textContent = d.html.replace("较上期 ", "");
  }
}

function refreshFilteredViews() {
  paintFlightBoard();
  paintCompareTable();
  paintSelectedRoutePrice();
  paintTrendFromCache();
}

function normalizeMeta(meta) {
  if (!meta) return {};
  if (typeof meta === "string") {
    try {
      return JSON.parse(meta) || {};
    } catch {
      return {};
    }
  }
  return meta;
}

function isTransferOffer(o) {
  const m = normalizeMeta(o.meta);
  if (m.is_transfer === true || m.is_transfer === 1 || m.is_transfer === "true") {
    return true;
  }
  if (Number(o.stops) > 0) return true;
  if (String(o.flight_no || "").includes("/")) return true;
  if (m.transfer_city || m.transfer_flight_no) return true;
  return false;
}

function renderFlightBoard(offers, route, totalCount) {
  const direct = sortOffers(offers.filter((o) => !isTransferOffer(o)));
  const transfer = sortOffers(offers.filter((o) => isTransferOffer(o)));
  const parts = [];
  if (direct.length) {
    parts.push(renderFlightSection("直飞航班", direct.length, direct, route, false));
  }
  if (transfer.length) {
    parts.push(renderFlightSection("中转航班", transfer.length, transfer, route, true));
  }
  const total = totalCount != null ? totalCount : offers.length;
  const filteredN = offers.length;
  const emptyMsg =
    total > 0 && filteredN === 0
      ? `<div class="empty">当前筛选无结果，试试放宽总时长、到达日或关掉「含20kg托运」</div>`
      : `<div class="empty">暂无航班明细，请点「重新扫描」</div>`;
  if (!parts.length && filteredN === 0) {
    return emptyMsg;
  }
  const tab = state.offerTab || "all";
  return `
    <div class="fb-tabs" id="fbTabs">
      <button type="button" class="fb-tab ${tab === "all" ? "active" : ""}" data-tab="all">全部 ${filteredN}</button>
      <button type="button" class="fb-tab ${tab === "direct" ? "active" : ""}" data-tab="direct" ${direct.length ? "" : "disabled"}>直飞 ${direct.length}</button>
      <button type="button" class="fb-tab ${tab === "xfer" ? "active" : ""}" data-tab="xfer" ${transfer.length ? "" : "disabled"}>中转 ${transfer.length}</button>
    </div>
    <div class="fb-panels">
      ${parts.join("")}
    </div>`;
}

function applyOfferTab(box, tab) {
  const cur = tab || "all";
  box.querySelectorAll(".fb-section").forEach((sec) => {
    const isXfer = sec.dataset.kind === "xfer";
    if (cur === "all") sec.hidden = false;
    else if (cur === "xfer") sec.hidden = !isXfer;
    else sec.hidden = isXfer;
  });
}

function applyOfferChip(key, raw) {
  if (key === "maxDuration") {
    state.offerFilters.maxDuration = raw ? Number(raw) : null;
    return true;
  }
  if (key === "sameDay") {
    state.offerFilters.sameDay = raw === "" ? null : raw === "1";
    return true;
  }
  if (key === "directOnly") {
    state.offerFilters.directOnly = raw === "" ? null : raw === "1";
    return true;
  }
  if (key === "bag20") {
    state.offerFilters.bag20 = raw === "1";
    return true;
  }
  if (key === "offerSort") {
    state.offerSort = raw || "price";
    return true;
  }
  return false;
}

function onOfferFilterClick(e) {
  const box = e.currentTarget;
  const actBtn = e.target.closest("[data-filter-act]");
  if (actBtn && box.contains(actBtn)) {
    const act = actBtn.getAttribute("data-filter-act");
    if (act === "save") saveRouteFilters();
    else if (act === "reset") resetOfferFiltersToSaved();
    return;
  }
  const chip = e.target.closest(".fb-chip");
  if (!chip || !box.contains(chip)) return;
  const seg = chip.closest(".fb-filter-seg");
  if (!seg) return;
  const key = seg.getAttribute("data-filter") || "";
  const raw = chip.getAttribute("data-value") ?? "";
  if (!applyOfferChip(key, raw)) return;
  if (key === "offerSort") {
    paintFlightBoard();
    return;
  }
  refreshFilteredViews();
}

function onFlightBoardClick(e) {
  const box = e.currentTarget;
  const tabBtn = e.target.closest(".fb-tab");
  if (!tabBtn || !box.contains(tabBtn) || tabBtn.disabled) return;
  const tab = tabBtn.getAttribute("data-tab") || "all";
  state.offerTab = tab;
  box.querySelectorAll(".fb-tab").forEach((b) => b.classList.toggle("active", b === tabBtn));
  applyOfferTab(box, tab);
}

function bindOfferFiltersUi(root) {
  const box = root || document.getElementById("fbFilters");
  if (!box || box.dataset.uiBound === "1") return;
  box.dataset.uiBound = "1";
  box.addEventListener("click", onOfferFilterClick);
}

function bindFlightBoardUi(root) {
  const box = root || document.getElementById("offerTable");
  if (!box || box.dataset.uiBound === "1") return;
  box.dataset.uiBound = "1";
  box.addEventListener("click", onFlightBoardClick);
}

function renderFlightSection(title, count, list, route, isTransfer) {
  const head = isTransfer
    ? `<div class="fb-head xfer">
        <div>航班组合</div><div>价格</div><div>行程</div><div>信息</div><div></div>
      </div>`
    : `<div class="fb-head">
        <div>航空公司 / 航班</div><div>价格</div><div>起降时间</div><div>信息</div><div></div>
      </div>`;
  return `
    <section class="fb-section" data-kind="${isTransfer ? "xfer" : "direct"}">
      <div class="fb-section-title">
        <h4>${title}</h4>
        <span class="fb-count">${count}个航班</span>
      </div>
      ${head}
      <div class="fb-list">
        ${list.map((o) => (isTransfer ? renderTransferRow(o, route) : renderDirectRow(o, route))).join("")}
      </div>
    </section>`;
}

function formatDuration(min) {
  if (min == null || Number.isNaN(Number(min)) || Number(min) <= 0) return "—";
  const m = Math.round(Number(min));
  const h = Math.floor(m / 60);
  const mm = m % 60;
  if (h && mm) return `${h}小时${mm}分`;
  if (h) return `${h}小时`;
  return `${mm}分`;
}

function estimateDuration(dep, arr) {
  if (!dep || !arr || !String(dep).includes(":") || !String(arr).includes(":")) return null;
  const [dh, dm] = String(dep).slice(-5).split(":").map(Number);
  const [ah, am] = String(arr).slice(-5).split(":").map(Number);
  if ([dh, dm, ah, am].some((x) => Number.isNaN(x))) return null;
  let mins = ah * 60 + am - (dh * 60 + dm);
  if (mins < 0) mins += 24 * 60;
  return mins;
}

function splitAircraft(raw) {
  const s = String(raw || "").trim();
  if (!s) return { brand: "—", model: "" };
  if (/空客|A\d/i.test(s)) {
    const m = s.replace(/空客/g, "").trim() || s;
    return { brand: "空客", model: /A\d/i.test(m) ? m : `A${m}` };
  }
  if (/波音|B\d/i.test(s)) {
    const m = s.replace(/波音/g, "").trim() || s;
    return { brand: "波音", model: /B\d/i.test(m) ? m : `B${m}` };
  }
  if (/^320|^321|^319|^330|^350/.test(s)) return { brand: "空客", model: `A${s}` };
  if (/^737|^787|^777/.test(s)) return { brand: "波音", model: `B${s}` };
  return { brand: s, model: "" };
}

function seatClass(hint) {
  const s = seatStatus(hint);
  if (s === "未知") return "unknown";
  if (s === "紧张") return "tight";
  return "ok";
}

function seatStatus(hint) {
  const s = String(hint || "").trim();
  if (!s || s === "null" || s === "—") return "未知";
  if (/充足|A\b|>9/i.test(s)) return "充足";
  if (/正常|B\b/.test(s)) return "正常";
  if (/紧张|少|C\b|^[1-4]$/.test(s)) return "紧张";
  if (/^\d+$/.test(s)) {
    const n = Number(s);
    if (n > 9) return "充足";
    if (n >= 5) return "正常";
    return "紧张";
  }
  if (/未知/.test(s)) return "未知";
  return "未知";
}

function seatLabel(hint) {
  return `余票${seatStatus(hint)}`;
}

function airlineShort(name) {
  const s = String(name || "").replace(/航空|公司|\|/g, "");
  return (s.slice(0, 2) || "航").toUpperCase();
}

function logoColor(name) {
  const palette = ["#e11d48", "#0f766e", "#1d4ed8", "#c2410c", "#7c3aed", "#047857"];
  let h = 0;
  for (const ch of String(name || "")) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return palette[h % palette.length];
}

function resolveAirline(o) {
  let airline = o.airline || "";
  if (!airline && o.flight_no) {
    const code = String(o.flight_no).split("/")[0].replace(/\d.*/, "").slice(0, 2).toUpperCase();
    airline = ({
      CA:"国航",CZ:"南航",MU:"东航",HU:"海航",MF:"厦航",SC:"山航",ZH:"深航",
      "3U":"川航","9C":"春秋",FM:"上航",HO:"吉祥",GS:"天津航",FU:"福州航",TV:"西藏航",UQ:"乌航",BK:"奥凯",NS:"河北航"
    })[code] || "";
  }
  return airline || "未知航司";
}

function airlineLogoHtml(name, iconUrl) {
  if (iconUrl) {
    return `<div class="airline-logo img"><img src="${iconUrl}" alt="" loading="lazy" referrerpolicy="no-referrer"/></div>`;
  }
  return `<div class="airline-logo" style="background:${logoColor(name)}">${airlineShort(name)}</div>`;
}

function fliggySearchUrl(route, departDate) {
  const dep = encodeURIComponent(route.origin || "");
  const arr = encodeURIComponent(route.destination || "");
  const date = encodeURIComponent(departDate || route.depart_date || "");
  return `https://sjipiao.fliggy.com/flight_search_result.htm?tripType=0&depCity=${dep}&arrCity=${arr}&depDate=${date}&searchBy=1280`;
}

function priceDeltaBadge(o) {
  const d = o.price_delta;
  if (d == null) return "";
  const n = Math.round(Math.abs(Number(d)));
  if (n === 0) return `<span class="price-delta flat">→0</span>`;
  const up = Number(d) > 0;
  return `<span class="price-delta ${up ? "up" : "down"}">${up ? "↑" : "↓"}${n}</span>`;
}

function escapeAttr(s) {
  return String(s || "")
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function flightRowId(flightNo) {
  return encodeURIComponent(String(flightNo || "")).replace(/%/g, "_");
}

function scrollToFlight(flightNo, departDate = "") {
  if (!flightNo) return;
  const board = document.getElementById("offerTable");
  if (!board) return;
  const fn = String(flightNo).trim();
  const day = String(departDate || "").trim();

  const findRow = () => {
    if (day) {
      const exact = board.querySelector(
        `.fb-row[data-flight-no="${CSS.escape(fn)}"][data-depart-date="${CSS.escape(day)}"]`
      );
      if (exact) return exact;
    }
    return board.querySelector(`.fb-row[data-flight-no="${CSS.escape(fn)}"]`);
  };

  let row = findRow();
  if (!row) {
    const inCache = (state.offersCache || []).some((o) => {
      const sameFn =
        String(o.flight_no || "").trim().toUpperCase() === fn.toUpperCase();
      if (!sameFn) return false;
      if (!day) return true;
      return String(o.depart_date || "").trim() === day;
    });
    if (inCache) {
      const prevFilters = { ...state.offerFilters };
      state.offerFilters = { maxDuration: null, sameDay: null, bag20: false, directOnly: null };
      state.offerTab = "all";
      paintFlightBoard();
      row = findRow();
      state.offerFilters = prevFilters;
      // 定位后再恢复默认筛选展示，避免把临时放宽写回监控
      window.setTimeout(() => paintFlightBoard(), 1700);
    }
  }
  if (!row) {
    toast(
      `未找到航班 ${fn}${day ? ` · ${day}` : ""}：当前报价列表里没有这班，可能已下架、被筛选掉，或尚未扫到该日`,
      { type: "error" }
    );
    return;
  }

  const section = row.closest(".fb-section");
  const kind = section?.dataset.kind;
  const tab = state.offerTab || "all";
  if (tab !== "all" && kind) {
    const want = kind === "xfer" ? "xfer" : "direct";
    if (tab !== want) {
      const tabs = board.querySelector("#fbTabs");
      const btn = tabs?.querySelector(`.fb-tab[data-tab="all"]`);
      if (btn) {
        tabs.querySelectorAll(".fb-tab").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        state.offerTab = "all";
        board.querySelectorAll(".fb-section").forEach((sec) => {
          sec.hidden = false;
        });
      }
    }
  }

  row.scrollIntoView({ behavior: "smooth", block: "center" });
  board.querySelectorAll(".fb-row.is-flash").forEach((el) => el.classList.remove("is-flash"));
  row.classList.add("is-flash");
  window.clearTimeout(scrollToFlight._timer);
  scrollToFlight._timer = window.setTimeout(() => row.classList.remove("is-flash"), 1600);
}

function bindTrendChartJump(chart) {
  if (!chart || chart.__jumpBound) return;
  chart.__jumpBound = true;
  chart.on("click", (params) => {
    if (params.componentType !== "series") return;
    const fn = params.seriesName;
    if (fn) scrollToFlight(fn);
  });
}

function flightTrendCell(o) {
  const hist = o.price_history || [];
  const fn = o.flight_no || "";
  if (!fn) return "";
  return `
    <div class="flight-trend is-clickable" role="button" tabindex="0" data-flight="${fn}" title="点击查看完整价格走势">
      ${sparkSvg(hist)}
    </div>`;
}

function renderDirectRow(o, route) {
  const meta = normalizeMeta(o.meta);
  const dep = String(o.depart_time || "").slice(-5) || "—";
  const arr = String(o.arrive_time || "").slice(-5) || "—";
  const dur = formatDuration(o.duration_min ?? estimateDuration(dep, arr));
  const craft = splitAircraft(o.aircraft);
  const craftLabel =
    craft.brand === "—"
      ? "—"
      : craft.model
        ? `${craft.brand}${craft.model.replace(/^(空客|波音)/, "")}`
        : craft.brand;
  const airline = resolveAirline(o);
  const sCls = seatClass(o.seats_hint);
  const typeText = meta.is_stop ? `经停${meta.stop_city || ""}`.trim() : "直飞";
  const typeCls = meta.is_stop ? "stop" : "";
  const cross = meta.cross_days_label
    ? `<span class="day-badge">${meta.cross_days_label}</span>`
    : "";
  const depCode = meta.dep_airport || o.origin || "";
  const arrCode = meta.arr_airport || o.destination || "";
  const fn = o.flight_no || "";
  const datePill =
    route?.depart_date_end &&
    route.depart_date_end !== route.depart_date &&
    o.depart_date
      ? `<span class="offer-date-pill">${formatRouteDateCapsule(o.depart_date)}</span>`
      : "";
  return `
    <article class="fb-row direct" data-flight-no="${escapeAttr(fn)}" data-depart-date="${escapeAttr(o.depart_date || "")}" id="flight-row-${flightRowId(fn)}">
      <div class="flight-airline">
        ${airlineLogoHtml(airline, meta.airline_icon)}
        <div>
          <div class="airline-name">${airline}${datePill}</div>
          <div class="airline-no">${fn || "—"}</div>
        </div>
      </div>
      <div class="price-main"><span class="yen">¥</span>${Math.round(o.price)}${priceDeltaBadge(o)}</div>
      <div class="flight-times">
        <div class="time-block">
          <div class="time-big">${dep}</div>
          <div class="time-code">${depCode}</div>
        </div>
        <div class="time-mid">
          <span class="dur-text">${dur}</span>
          <div class="route-line"></div>
        </div>
        <div class="time-block arr">
          <div class="time-big">${arr}${cross}</div>
          <div class="time-code">${arrCode}</div>
        </div>
      </div>
      <div class="xfer-meta">
        <div class="xfer-meta-line">
          <div class="xfer-info-row"><span class="k">机型</span><span class="v">${craftLabel}</span></div>
          <span class="type-pill ${typeCls}">${typeText || "直飞"}</span>
          ${baggagePill(o)}
          <span class="seat-pill ${sCls}">${seatLabel(o.seats_hint)}</span>
        </div>
        ${flightTrendCell(o)}
      </div>
      <div class="action-col">
        <a class="btn-fliggy" href="${fliggySearchUrl(route, o.depart_date)}" target="_blank" rel="noopener">飞猪查余票 →</a>
      </div>
    </article>`;
}

function renderTransferRow(o, route) {
  const meta = normalizeMeta(o.meta);
  const dep = String(o.depart_time || "").slice(-5) || "—";
  const arr = String(o.arrive_time || "").slice(-5) || "—";
  const dur = formatDuration(o.duration_min ?? estimateDuration(dep, arr));
  const sCls = seatClass(o.seats_hint);
  const legs = (meta.leg_flights && meta.leg_flights.length
    ? meta.leg_flights
    : String(o.flight_no || "").split("/").filter(Boolean));
  const airs = meta.leg_airlines || [];
  const icons = [meta.airline_icon, meta.transfer_airline_icon];
  const city = meta.transfer_city || "中转";
  const wait = meta.layover_text || formatDuration(o.layover_min) || "—";
  const cross = meta.cross_days_label
    ? `<span class="day-badge">${meta.cross_days_label}</span>`
    : "";
  const depCode = meta.dep_airport || o.origin || "";
  const arrCode = meta.arr_airport || o.destination || "";
  const cabin = meta.cabin || "经济舱";

  const shortName = (name) =>
    String(name || "")
      .split("|")[0]
      .replace(/航空|公司/g, "")
      .trim() || name;

  const combo = (legs.length ? legs : ["—"])
    .map((fn, i) => {
      const name =
        airs[i] ||
        resolveAirline({ flight_no: fn, airline: airs[0] || o.airline });
      return `
      <div class="xfer-leg-air">
        ${airlineLogoHtml(name, icons[i])}
        <div>
          <div class="airline-name">${shortName(name)}</div>
          <div class="airline-no">${fn}</div>
        </div>
      </div>`;
    })
    .join("");

  const fn = o.flight_no || "";
  const datePill =
    route?.depart_date_end &&
    route.depart_date_end !== route.depart_date &&
    o.depart_date
      ? `<span class="offer-date-pill">${formatRouteDateCapsule(o.depart_date)}</span>`
      : "";
  return `
    <article class="fb-row xfer" data-flight-no="${escapeAttr(fn)}" data-depart-date="${escapeAttr(o.depart_date || "")}" id="flight-row-${flightRowId(fn)}">
      <div class="xfer-combo">
        <div class="xfer-combo-legs">${combo}</div>
        ${datePill}
      </div>
      <div class="price-main"><span class="yen">¥</span>${Math.round(o.price)}${priceDeltaBadge(o)}</div>
      <div class="xfer-journey">
        <div class="xfer-times">
          <div class="time-block">
            <div class="time-big">${dep}</div>
            <div class="time-code">${depCode}</div>
          </div>
          <div class="xfer-mid">
            <div class="xfer-line"></div>
            <div class="xfer-stop">
              <span class="xfer-city">${city}</span>
              <span class="xfer-wait">停 ${wait}</span>
            </div>
          </div>
          <div class="time-block arr">
            <div class="time-big">${arr}${cross}</div>
            <div class="time-code">${arrCode}</div>
          </div>
        </div>
      </div>
      <div class="xfer-meta">
        <div class="xfer-meta-line">
          <div class="xfer-info-row"><span class="k">总时长</span><span class="v">${dur}</span></div>
          <div class="xfer-info-row"><span class="k">舱位</span><span class="v">${cabin}</span></div>
          ${baggagePill(o)}
          <span class="seat-pill ${sCls}">${seatLabel(o.seats_hint)}</span>
        </div>
        ${flightTrendCell(o)}
      </div>
      <div class="action-col">
        <a class="btn-fliggy" href="${fliggySearchUrl(route, o.depart_date)}" target="_blank" rel="noopener">飞猪查余票 →</a>
      </div>
    </article>`;
}

function statsFromFlights(seriesMap, plotted) {
  const lasts = [];
  const all = [];
  let samples = 0;
  for (const fn of plotted) {
    const pts = seriesMap[fn] || [];
    samples = Math.max(samples, pts.length);
    for (const p of pts) all.push(Number(p.price));
    if (pts.length) lasts.push(Number(pts[pts.length - 1].price));
  }
  if (!all.length) return null;
  const current = lasts.length ? Math.min(...lasts) : null;
  return {
    flight_count: plotted.length,
    sample_count: samples,
    current,
    history_min: Math.min(...all),
    history_max: Math.max(...all),
    avg: Math.round((all.reduce((a, b) => a + b, 0) / all.length) * 10) / 10,
  };
}

function renderStats(stats) {
  const box = document.getElementById("trendStats");
  if (!stats || !stats.sample_count) {
    box.innerHTML = "";
    return;
  }
  box.innerHTML = `
    <div class="stat"><div class="k">图中航班</div><div class="v">${stats.flight_count || 0}</div></div>
    <div class="stat"><div class="k">当前最低</div><div class="v">${money(stats.current)}</div></div>
    <div class="stat"><div class="k">历史最低</div><div class="v down">${money(stats.history_min)}</div></div>
    <div class="stat"><div class="k">历史最高</div><div class="v up">${money(stats.history_max)}</div></div>
    <div class="stat"><div class="k">区间均价</div><div class="v">${money(stats.avg)}</div></div>
    <div class="stat"><div class="k">采样点</div><div class="v">${stats.sample_count}</div></div>
  `;
}

function flightSeriesFor(flightNo) {
  const fromTrend = state.lastFlightSeries[flightNo];
  if (fromTrend && fromTrend.length) return fromTrend;
  const offer = (state.offersCache || []).find((o) => o.flight_no === flightNo);
  if (offer?.price_history_full?.length) return offer.price_history_full;
  if (offer?.price_history?.length) {
    return offer.price_history.map((price, i) => ({
      t: String(i),
      price,
    }));
  }
  return [];
}

function flightTrendModalTitle(flightNo) {
  const offer = (state.offersCache || []).find((o) => o.flight_no === flightNo);
  const route = state.offerRoute || state.currentRoute;
  const airline = offer ? resolveAirline(offer) : "";
  const parts = [];
  if (airline) parts.push(airline);
  if (flightNo) parts.push(flightNo);
    if (route) {
    const od = `${route.origin_name || route.origin} → ${route.destination_name || route.destination}`;
    parts.push(od);
    const dateTxt = offer?.depart_date || formatRouteDateMeta(route);
    if (dateTxt && dateTxt !== "—") parts.push(dateTxt);
  }
  return parts.join(" · ") || "航班价格走势";
}

function closeFlightTrendModal() {
  const modal = document.getElementById("flightTrendModal");
  if (!modal || modal.hidden) return;
  modal.hidden = true;
  document.body.classList.remove("modal-open");
}

function openFlightTrendModal(flightNo) {
  if (!flightNo) return;
  const pts = flightSeriesFor(flightNo);
  const modal = document.getElementById("flightTrendModal");
  const titleEl = document.getElementById("flightTrendModalTitle");
  const chartEl = document.getElementById("flightTrendModalChart");
  if (!modal || !chartEl) return;

  titleEl.textContent = flightTrendModalTitle(flightNo);
  modal.hidden = false;
  document.body.classList.add("modal-open");

  if (!state.flightModalChart) {
    state.flightModalChart = echarts.init(chartEl);
  }
  state.flightModalChart.resize();

  if (!pts.length) {
    state.flightModalChart.clear();
    state.flightModalChart.setOption({
      title: {
        text: "暂无该航班价格历史，扫描几轮后再看",
        left: "center",
        top: "middle",
        textStyle: { color: "#66756d", fontSize: 14, fontWeight: 400 },
      },
    });
    return;
  }

  const ts = pts.map((p) => p.t);
  const prices = pts.map((p) => Number(p.price));
  const threshold = Number(state.currentRoute?.alert_threshold || 0);
  const markLine =
    threshold > 0
      ? {
          symbol: "none",
          label: {
            formatter: `限额 ¥${Math.round(threshold)}`,
            position: "insideEndTop",
          },
          lineStyle: { color: "#b42318", type: "dashed" },
          data: [{ yAxis: threshold }],
        }
      : undefined;

  state.flightModalChart.setOption(
    {
      color: ["#156b4f"],
      tooltip: {
        trigger: "axis",
        valueFormatter: (v) => (v == null ? "—" : `¥${Math.round(v)}`),
      },
      grid: { left: 52, right: 24, top: 36, bottom: 40 },
      xAxis: {
        type: "category",
        boundaryGap: false,
        data: ts,
        axisLabel: {
          formatter: (v) => {
            const d = new Date(v.length === 16 ? `${v}:00Z` : v);
            if (Number.isNaN(d.getTime())) return String(v).slice(5, 16);
            return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
          },
        },
      },
      yAxis: {
        type: "value",
        name: "¥",
        scale: true,
        splitLine: { lineStyle: { color: "#e6eee9" } },
      },
      series: [
        {
          name: flightNo,
          type: "line",
          smooth: true,
          showSymbol: pts.length < 18,
          symbolSize: 7,
          lineStyle: { width: 2.5 },
          areaStyle: {
            color: {
              type: "linear",
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: "rgba(21,107,79,0.22)" },
                { offset: 1, color: "rgba(21,107,79,0.02)" },
              ],
            },
          },
          data: prices,
          markLine,
        },
      ],
    },
    true
  );
}

function bindFlightTrendOpen(root) {
  const box = root || document.getElementById("offerTable");
  if (!box) return;
  box.querySelectorAll(".flight-trend.is-clickable").forEach((el) => {
    const open = (e) => {
      e.preventDefault();
      e.stopPropagation();
      openFlightTrendModal(el.dataset.flight);
    };
    el.addEventListener("click", open);
    el.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") open(e);
    });
  });
}

function bindFlightTrendModal() {
  const modal = document.getElementById("flightTrendModal");
  if (!modal) return;
  modal.querySelectorAll("[data-close-trend-modal]").forEach((el) => {
    el.addEventListener("click", closeFlightTrendModal);
  });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    closeNotifyGroupModal();
    closeFlightTrendModal();
  });
  window.addEventListener("resize", () => {
    if (!modal.hidden) state.flightModalChart?.resize();
  });
}

function normalizeEmailList(list) {
  const out = [];
  const seen = new Set();
  for (const raw of list || []) {
    const email = String(raw || "").trim().toLowerCase();
    if (!email || !email.includes("@") || seen.has(email)) continue;
    seen.add(email);
    out.push(email);
  }
  return out;
}

function renderNotifyChips() {
  const box = document.getElementById("notifyEmailChips");
  if (!box) return;
  const emails = state.notifyDraftEmails || [];
  if (!emails.length) {
    box.innerHTML = `<div class="notify-empty">尚未添加邮箱，将使用全局默认</div>`;
    return;
  }
  box.innerHTML = emails
    .map(
      (email) => `
      <span class="notify-chip">
        ${escapeHtml(email)}
        <button type="button" data-remove-email="${escapeAttr(email)}" aria-label="移除">×</button>
      </span>`
    )
    .join("");
  box.querySelectorAll("[data-remove-email]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const email = btn.getAttribute("data-remove-email");
      state.notifyDraftEmails = state.notifyDraftEmails.filter((x) => x !== email);
      renderNotifyChips();
    });
  });
}

function escapeHtml(s) {
  return String(s || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function closeNotifyGroupModal() {
  const modal = document.getElementById("notifyGroupModal");
  if (!modal || modal.hidden) return;
  modal.hidden = true;
  const trendOpen = document.getElementById("flightTrendModal")?.hidden === false;
  if (!trendOpen) document.body.classList.remove("modal-open");
  state.notifyRouteId = null;
  state.notifyDraftEmails = [];
}

async function openNotifyGroupModal(routeId) {
  const route =
    (state.routes || []).find((r) => Number(r.id) === Number(routeId)) ||
    (Number(state.currentRoute?.id) === Number(routeId) ? state.currentRoute : null);
  if (!route) {
    toast("未找到该航线");
    return;
  }
  if (!state.hasDefaultMail) {
    try {
      await loadHealth();
    } catch {
      /* ignore */
    }
  }
  const modal = document.getElementById("notifyGroupModal");
  if (!modal) return;
  state.notifyRouteId = Number(route.id);
  state.notifyDraftEmails = normalizeEmailList(route.notify_emails);
  const sub = document.getElementById("notifyGroupSub");
  if (sub) {
    sub.textContent = `${route.origin_name || route.origin} → ${
      route.destination_name || route.destination
    } · ${formatRouteDateMeta(route)}`;
  }
  const hint = document.getElementById("notifyGroupHint");
  if (hint) {
    hint.textContent = state.hasDefaultMail
      ? "已配置全局默认邮箱（本航线留空时使用）"
      : "尚未配置全局默认邮箱，请至少为本航线添加一个接收邮箱";
  }
  renderNotifyChips();
  const input = document.getElementById("notifyEmailInput");
  if (input) input.value = "";
  modal.hidden = false;
  document.body.classList.add("modal-open");
  input?.focus();
}

async function saveNotifyGroupModal() {
  const id = Number(state.notifyRouteId);
  if (!id) return;
  const emails = normalizeEmailList(state.notifyDraftEmails);
  try {
    const route = await api(`/api/routes/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ notify_emails: emails }),
    });
    const idx = (state.routes || []).findIndex((r) => Number(r.id) === id);
    if (idx >= 0) state.routes[idx] = { ...state.routes[idx], ...route };
    if (Number(state.currentRoute?.id) === id) {
      state.currentRoute = { ...state.currentRoute, ...route };
    }
    closeNotifyGroupModal();
    await loadRoutes();
    toast(emails.length ? `已保存 ${emails.length} 个接收邮箱` : "已改用全局默认邮箱");
  } catch (err) {
    toast(err.message || String(err));
  }
}

async function testNotifyGroupModal() {
  const emails = normalizeEmailList(state.notifyDraftEmails);
  const btn = document.getElementById("btnTestNotifyGroup");
  if (btn) btn.disabled = true;
  try {
    const res = await api("/api/notify/test", {
      method: "POST",
      body: JSON.stringify({ emails }),
    });
    const recipients = Array.isArray(res?.recipients) ? res.recipients : [];
    const who = recipients.length
      ? recipients.join("、")
      : res?.channel === "email"
        ? "邮箱"
        : "推送通道";
    toast(`测试推送已发送至 ${who}`);
  } catch (err) {
    toast(err.message || String(err));
  } finally {
    if (btn) btn.disabled = false;
  }
}

function bindNotifyGroupModal() {
  const modal = document.getElementById("notifyGroupModal");
  if (!modal) return;
  modal.querySelectorAll("[data-close-notify-modal]").forEach((el) => {
    el.addEventListener("click", closeNotifyGroupModal);
  });
  document.getElementById("btnSaveNotifyGroup")?.addEventListener("click", () => {
    saveNotifyGroupModal().catch(() => {});
  });
  document.getElementById("btnTestNotifyGroup")?.addEventListener("click", () => {
    testNotifyGroupModal().catch(() => {});
  });
  document.getElementById("notifyEmailForm")?.addEventListener("submit", (e) => {
    e.preventDefault();
    const input = document.getElementById("notifyEmailInput");
    const email = String(input?.value || "").trim().toLowerCase();
    if (!email) return;
    if (!email.includes("@") || !email.includes(".")) {
      toast("请输入有效邮箱");
      return;
    }
    state.notifyDraftEmails = normalizeEmailList([
      ...state.notifyDraftEmails,
      email,
    ]);
    if (input) input.value = "";
    renderNotifyChips();
    input?.focus();
  });
}

function renderFlightFilter(flightNos) {
  const box = document.getElementById("platformFilter");
  if (!flightNos.length) {
    box.innerHTML = "";
    return;
  }
  const tags = flightNos.map((fn) => {
    const off = state.hiddenFlights.has(fn) ? "off" : "";
    const pin = state.pinnedFlights.has(fn) ? "best" : "";
    return `<span class="tag ${pin} ${off}" data-flight="${fn}">${fn}</span>`;
  });
  box.innerHTML = tags.join("");
  box.querySelectorAll(".tag").forEach((el) => {
    el.addEventListener("click", () => {
      const fn = el.dataset.flight;
      if (state.hiddenFlights.has(fn)) state.hiddenFlights.delete(fn);
      else state.hiddenFlights.add(fn);
      paintTrendFromCache();
    });
  });
}

function pickTrendFlights(seriesMap) {
  const visible = applyOfferFilters(state.offersCache || []);
  const boardNos = [
    ...new Set(visible.map((o) => o.flight_no).filter(Boolean)),
  ].filter((fn) => seriesMap[fn]);
  const pinned = [...state.pinnedFlights].filter((fn) => seriesMap[fn]);
  if (pinned.length) return pinned;
  return boardNos.slice(0, 6);
}

function setTrendEmpty(text) {
  state.chart.clear();
  state.chart.setOption({
    title: {
      text,
      left: "center",
      top: "middle",
      textStyle: { color: "#66756d", fontSize: 14, fontWeight: 400 },
    },
  });
}

function paintTrendFromCache() {
  const el = document.getElementById("trendChart");
  if (!el) return;
  if (!state.chart) state.chart = echarts.init(el);
  bindTrendChartJump(state.chart);

  const seriesMap = state.lastFlightSeries || {};
  const candidates = pickTrendFlights(seriesMap);
  renderFlightFilter(candidates);
  const plotted = candidates.filter((fn) => !state.hiddenFlights.has(fn));
  renderStats(statsFromFlights(seriesMap, plotted));

  if (!Object.keys(seriesMap).length) {
    setTrendEmpty("扫描几轮后将按航班号画出各自价格走势");
    return;
  }

  if (!plotted.length) {
    setTrendEmpty(candidates.length ? "请至少选择一条航班曲线" : "当前筛选下暂无航班曲线");
    return;
  }

  const allTs = [
    ...new Set(plotted.flatMap((fn) => (seriesMap[fn] || []).map((x) => x.t))),
  ].sort();

  const colors = [
    "#156b4f",
    "#c5672b",
    "#2f5d8c",
    "#7a4f9a",
    "#b42318",
    "#0f766e",
    "#9333ea",
    "#ca8a04",
  ];
  const series = plotted.map((fn) => {
    const pts = seriesMap[fn] || [];
    const map = Object.fromEntries(pts.map((x) => [x.t, x.price]));
    return {
      name: fn,
      type: "line",
      smooth: true,
      cursor: "pointer",
      triggerLineEvent: true,
      showSymbol: allTs.length < 18 || pts.length < 4,
      symbolSize: state.pinnedFlights.has(fn) ? 8 : 6,
      lineStyle: { width: state.pinnedFlights.has(fn) ? 3 : 2 },
      emphasis: { focus: "series", lineStyle: { width: 3.5 } },
      data: allTs.map((t) => map[t] ?? null),
      connectNulls: true,
    };
  });

  const threshold = Number(state.currentRoute?.alert_threshold || 0);
  const markLine =
    threshold > 0
      ? {
          symbol: "none",
          label: { formatter: `限额 ¥${Math.round(threshold)}`, position: "insideEndTop" },
          lineStyle: { color: "#b42318", type: "dashed" },
          data: [{ yAxis: threshold }],
        }
      : undefined;

  if (markLine && series.length) {
    series[0].markLine = markLine;
  }

  state.chart.setOption(
    {
      color: colors,
      tooltip: {
        trigger: "axis",
        valueFormatter: (v) => (v == null ? "—" : `¥${Math.round(v)}`),
      },
      legend: { top: 8, type: "scroll", data: series.map((s) => s.name) },
      grid: { left: 52, right: 20, top: 48, bottom: 36 },
      xAxis: {
        type: "category",
        boundaryGap: false,
        data: allTs,
        axisLabel: {
          formatter: (v) => {
            const d = new Date(v.length === 16 ? `${v}:00Z` : v);
            if (Number.isNaN(d.getTime())) return String(v).slice(5, 16);
            return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
          },
        },
      },
      yAxis: {
        type: "value",
        name: "¥",
        scale: true,
        splitLine: { lineStyle: { color: "#e6eee9" } },
      },
      series,
    },
    true
  );
  state.chart.resize();
}

async function renderTrend(id) {
  const days = state.trendDays;
  const qs = new URLSearchParams({ limit: "300" });
  if (days) qs.set("days", String(days));
  const trend = await api(`/api/routes/${id}/trend?${qs}`);
  state.lastFlightSeries = trend.flight_series || {};
  paintTrendFromCache();
}

function defaultDate() {
  const d = new Date();
  d.setDate(d.getDate() + 21);
  return toDateValue(d);
}

function toDateValue(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function parseDateValue(v) {
  if (!v || !/^\d{4}-\d{2}-\d{2}$/.test(v)) return null;
  const [y, m, d] = v.split("-").map(Number);
  const dt = new Date(y, m - 1, d);
  if (Number.isNaN(dt.getTime())) return null;
  return dt;
}

function formatDateZh(v) {
  const dt = parseDateValue(v);
  if (!dt) return "选择日期";
  const week = ["日", "一", "二", "三", "四", "五", "六"][dt.getDay()];
  return `${dt.getFullYear()}年${dt.getMonth() + 1}月${dt.getDate()}日 周${week}`;
}

function formatDateZhShort(v) {
  const dt = parseDateValue(v);
  if (!dt) return "";
  return `${dt.getMonth() + 1}月${dt.getDate()}日`;
}

function formatDateRangeZh(start, end) {
  if (!start) return "选择日期";
  if (!end || end === start) return formatDateZh(start);
  const a = parseDateValue(start);
  const b = parseDateValue(end);
  if (!a || !b) return formatDateZh(start);
  const days = Math.round((b - a) / 86400000) + 1;
  if (a.getFullYear() === b.getFullYear()) {
    return `${a.getFullYear()}年${formatDateZhShort(start)} – ${formatDateZhShort(end)}（${days}天）`;
  }
  return `${formatDateZh(start).replace(/ 周.$/, "")} – ${formatDateZh(end).replace(/ 周.$/, "")}（${days}天）`;
}

function expandDateRange(start, end, maxDays = 31) {
  const a = parseDateValue(start);
  const b = parseDateValue(end || start);
  if (!a || !b) return [];
  const from = a <= b ? a : b;
  const to = a <= b ? b : a;
  const days = Math.round((to - from) / 86400000) + 1;
  if (days > maxDays) {
    throw new Error(`日期范围最多 ${maxDays} 天，当前 ${days} 天`);
  }
  const out = [];
  const cur = new Date(from);
  while (cur <= to) {
    out.push(toDateValue(cur));
    cur.setDate(cur.getDate() + 1);
  }
  return out;
}

function initDatePicker() {
  const root = document.getElementById("datePicker");
  const input = document.getElementById("depart_date");
  const inputEnd = document.getElementById("depart_date_end");
  const trigger = document.getElementById("depart_date_display");
  const pop = document.getElementById("datePopover");
  const title = document.getElementById("dateTitle");
  const grid = document.getElementById("dateGrid");
  const hint = document.getElementById("dateRangeHint");
  if (!root || !input || !trigger || !pop || !title || !grid) return;

  let rangeStart = input.value || "";
  let rangeEnd = (inputEnd && inputEnd.value) || rangeStart;
  let pickingEnd = false;
  let hoverDate = null;
  let editingRouteId = null;
  let formBackup = null;
  let popAnchor = null;
  let view = parseDateValue(rangeStart) || new Date();
  view = new Date(view.getFullYear(), view.getMonth(), 1);
  const popHomeParent = pop.parentElement;

  function orderedRange(start, end) {
    if (!start) return { start: "", end: "" };
    if (!end) return { start, end: start };
    return start <= end ? { start, end } : { start: end, end: start };
  }

  function clearPopPosition() {
    pop.classList.remove("is-floating");
    pop.style.position = "";
    pop.style.left = "";
    pop.style.top = "";
    pop.style.zIndex = "";
    pop.style.width = "";
  }

  function mountPopToBody() {
    if (pop.parentElement !== document.body) {
      document.body.appendChild(pop);
    }
  }

  function restorePopHome() {
    if (popHomeParent && pop.parentElement !== popHomeParent) {
      popHomeParent.appendChild(pop);
    }
    clearPopPosition();
    popAnchor = null;
  }

  function placePopNear(anchorEl) {
    popAnchor = anchorEl || trigger;
    mountPopToBody();
    const rect = popAnchor.getBoundingClientRect();
    const width = Math.min(320, window.innerWidth - 16);
    const left = Math.max(8, Math.min(rect.left, window.innerWidth - width - 8));
    let top = rect.bottom + 6;
    // Prefer below; if not enough room, flip above.
    const estHeight = Math.min(360, window.innerHeight - 24);
    if (top + estHeight > window.innerHeight - 8) {
      top = Math.max(8, rect.top - estHeight - 6);
    }
    pop.classList.add("is-floating");
    pop.style.position = "fixed";
    pop.style.left = `${left}px`;
    pop.style.top = `${top}px`;
    pop.style.width = `${width}px`;
    pop.style.zIndex = "4000";
  }

  function repositionPop() {
    if (pop.hidden || !popAnchor) return;
    placePopNear(popAnchor);
  }

  function syncInputs() {
    const { start, end } = orderedRange(rangeStart, rangeEnd || rangeStart);
    input.value = start;
    if (inputEnd) inputEnd.value = end && end !== start ? end : "";
    const text = trigger.querySelector(".date-trigger-text");
    if (text && !editingRouteId) text.textContent = formatDateRangeZh(start, end);
    if (hint) {
      if (editingRouteId) {
        if (pickingEnd && rangeStart) {
          hint.textContent = `修改监控日期：已选 ${formatDateZhShort(rangeStart)}，再点结束日`;
        } else {
          hint.textContent = "修改监控日期：点击开始日，再点结束日";
        }
      } else if (pickingEnd && rangeStart) {
        hint.textContent = `已选 ${formatDateZhShort(rangeStart)}，再点结束日`;
      } else if (start && end && end !== start) {
        hint.textContent = `已选 ${formatDateRangeZh(start, end)}`;
      } else {
        hint.textContent = "点击选择开始日，再点结束日";
      }
    }
  }

  function restoreFormBackup() {
    if (!formBackup) return;
    rangeStart = formBackup.start || defaultDate();
    rangeEnd = formBackup.end || rangeStart;
    formBackup = null;
    syncInputs();
  }

  async function finishEditRouteDates(start, end) {
    const id = editingRouteId;
    editingRouteId = null;
    try {
      const route = await api(`/api/routes/${id}`, {
        method: "PATCH",
        body: JSON.stringify({
          depart_date: start,
          depart_date_end: end || start,
        }),
      });
      toast(`已更新日期：${formatRouteDateMeta(route)}`);
      restoreFormBackup();
      await loadRoutes();
      if (Number(state.selectedId) === Number(id)) await openDetail(id, { scroll: false });
    } catch (err) {
      toast(err.message || String(err));
      restoreFormBackup();
      await loadRoutes();
    }
  }

  function setRange(start, end, { close = true, picking = false } = {}) {
    rangeStart = start || "";
    rangeEnd = end || start || "";
    pickingEnd = picking;
    hoverDate = null;
    syncInputs();
    render();
    if (!close) return;
    const { start: s, end: e } = orderedRange(rangeStart, rangeEnd);
    pop.hidden = true;
    trigger.setAttribute("aria-expanded", "false");
    restorePopHome();
    if (editingRouteId) {
      void finishEditRouteDates(s, e);
      return;
    }
  }

  function openPop(anchorEl) {
    const cur = parseDateValue(rangeStart) || new Date();
    view = new Date(cur.getFullYear(), cur.getMonth(), 1);
    pickingEnd = false;
    hoverDate = null;
    render();
    syncInputs();
    pop.hidden = false;
    trigger.setAttribute("aria-expanded", "true");
    placePopNear(anchorEl || trigger);
  }

  function closePop({ commitSingle = false } = {}) {
    if (editingRouteId) {
      // Cancel edit unless user finished a single-day reselect mid-flow with commitSingle
      if (commitSingle && rangeStart && !pickingEnd) {
        const { start, end } = orderedRange(rangeStart, rangeEnd || rangeStart);
        pop.hidden = true;
        trigger.setAttribute("aria-expanded", "false");
        restorePopHome();
        void finishEditRouteDates(start, end);
        return;
      }
      editingRouteId = null;
      pickingEnd = false;
      hoverDate = null;
      pop.hidden = true;
      trigger.setAttribute("aria-expanded", "false");
      restorePopHome();
      restoreFormBackup();
      return;
    }
    if (pickingEnd && rangeStart) {
      rangeEnd = rangeStart;
      pickingEnd = false;
      syncInputs();
    }
    pop.hidden = true;
    trigger.setAttribute("aria-expanded", "false");
    restorePopHome();
  }

  function previewBounds() {
    if (pickingEnd && rangeStart) {
      const end = hoverDate || rangeStart;
      return orderedRange(rangeStart, end);
    }
    return orderedRange(rangeStart, rangeEnd || rangeStart);
  }

  function render() {
    const y = view.getFullYear();
    const m = view.getMonth();
    title.textContent = `${y}年${m + 1}月`;
    const first = new Date(y, m, 1);
    // Monday-based week: Mon=0 ... Sun=6
    let startPad = (first.getDay() + 6) % 7;
    const daysInMonth = new Date(y, m + 1, 0).getDate();
    const { start, end } = previewBounds();
    const multi = start && end && start !== end;
    const today = toDateValue(new Date());
    const cells = [];
    for (let i = 0; i < startPad; i++) cells.push(`<button type="button" class="date-cell muted" disabled></button>`);
    for (let d = 1; d <= daysInMonth; d++) {
      const val = `${y}-${String(m + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
      const isStart = val === start;
      const isEnd = val === end;
      const inRange = multi && start && end && val >= start && val <= end;
      const cls = [
        "date-cell",
        isStart ? "range-start" : "",
        isEnd ? "range-end" : "",
        inRange ? "in-range" : "",
        !multi && val === start ? "selected" : "",
        val === today ? "today" : "",
      ]
        .filter(Boolean)
        .join(" ");
      cells.push(`<button type="button" class="${cls}" data-date="${val}">${d}</button>`);
    }
    grid.innerHTML = cells.join("");
  }

  function beginEditRouteDates(route, anchorEl) {
    if (!route?.id) return;
    if (!formBackup) {
      formBackup = {
        start: input.value || defaultDate(),
        end: (inputEnd && inputEnd.value) || "",
      };
    }
    editingRouteId = Number(route.id);
    rangeStart = route.depart_date || "";
    rangeEnd = route.depart_date_end || route.depart_date || "";
    pickingEnd = false;
    hoverDate = null;
    openPop(anchorEl);
  }

  trigger.addEventListener("click", () => {
    if (editingRouteId) {
      closePop();
      return;
    }
    if (pop.hidden) openPop(trigger);
    else closePop();
  });
  pop.addEventListener("click", (e) => {
    const nav = e.target.closest("[data-nav]");
    if (nav) {
      view = new Date(view.getFullYear(), view.getMonth() + Number(nav.dataset.nav), 1);
      render();
      return;
    }
    const quick = e.target.closest("[data-quick]");
    if (quick) {
      const d = new Date();
      d.setDate(d.getDate() + Number(quick.dataset.quick));
      const v = toDateValue(d);
      setRange(v, v);
      return;
    }
    const cell = e.target.closest(".date-cell[data-date]");
    if (!cell) return;
    const val = cell.dataset.date;
    if (!pickingEnd) {
      rangeStart = val;
      rangeEnd = val;
      pickingEnd = true;
      hoverDate = null;
      syncInputs();
      render();
      return;
    }
    const { start, end } = orderedRange(rangeStart, val);
    setRange(start, end);
  });
  pop.addEventListener("mousemove", (e) => {
    if (!pickingEnd) return;
    const cell = e.target.closest(".date-cell[data-date]");
    if (!cell) return;
    if (hoverDate === cell.dataset.date) return;
    hoverDate = cell.dataset.date;
    render();
  });
  document.addEventListener("pointerdown", (e) => {
    if (pop.hidden) return;
    const path = typeof e.composedPath === "function" ? e.composedPath() : [];
    if (path.includes(pop) || path.includes(root) || pop.contains(e.target) || root.contains(e.target)) {
      return;
    }
    if (e.target.closest?.(".date-capsule[data-act='edit-date'], #detailDateBtn, #depart_date_display")) {
      return;
    }
    closePop();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !pop.hidden) closePop();
  });
  // Keep floating calendar on screen while scrolling; do not close.
  window.addEventListener(
    "scroll",
    () => {
      if (!pop.hidden) repositionPop();
    },
    true
  );
  window.addEventListener("resize", () => {
    if (!pop.hidden) repositionPop();
  });

  initDatePicker.setValue = (v, close = true) => setRange(v, v, { close });
  initDatePicker.setRange = setRange;
  initDatePicker.getRange = () => orderedRange(rangeStart, rangeEnd || rangeStart);
  initDatePicker.editRouteDates = beginEditRouteDates;
  setRange(input.value || defaultDate(), (inputEnd && inputEnd.value) || input.value || defaultDate(), {
    close: false,
  });
}

document.getElementById("rangeSeg").addEventListener("click", (e) => {
  const btn = e.target.closest(".seg-btn");
  if (!btn) return;
  document.querySelectorAll("#rangeSeg .seg-btn").forEach((b) => b.classList.remove("active"));
  btn.classList.add("active");
  const raw = btn.dataset.days;
  state.trendDays = raw === "" ? null : Number(raw);
  if (state.selectedId) renderTrend(state.selectedId);
});

document.getElementById("detailDateBtn")?.addEventListener("click", (e) => {
  e.preventDefault();
  e.stopPropagation();
  const route = state.currentRoute;
  if (!route) return;
  initDatePicker.editRouteDates?.(route, e.currentTarget);
});

document.getElementById("addForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const origin = String(fd.get("origin") || "").trim();
  const destination = String(fd.get("destination") || "").trim();
  const range = initDatePicker.getRange?.() || {
    start: String(fd.get("depart_date") || ""),
    end: String(fd.get("depart_date_end") || fd.get("depart_date") || ""),
  };
  if (!range.start) {
    toast("请选择出发日期");
    return;
  }
  let dates;
  try {
    dates = expandDateRange(range.start, range.end || range.start);
  } catch (err) {
    toast(err.message || String(err));
    return;
  }
  if (!dates.length) {
    toast("请选择出发日期");
    return;
  }
  const body = {
    origin,
    destination,
    depart_date: dates[0],
    depart_date_end: dates[dates.length - 1],
  };
  try {
    const route = await api("/api/routes", {
      method: "POST",
      body: JSON.stringify(body),
    });
    e.target.reset();
    initDatePicker.setValue?.(defaultDate(), false);
    document.getElementById("originHint").textContent = "输入城市名";
    document.getElementById("destHint").textContent = "输入城市名";
    const days = dates.length;
    const dayLabel = days > 1 ? `（${dates[0]} ~ ${dates[dates.length - 1]}，${days}天）` : "";
    toast(
      route._upsert === "updated"
        ? `已更新监控：${route.origin_name} → ${route.destination_name}${dayLabel}`
        : `已添加 ${route.origin_name} → ${route.destination_name}${dayLabel}`
    );
    await loadRoutes();
    await openDetail(route.id);
  } catch (err) {
    toast(err.message || String(err));
  }
});

document.getElementById("btnPin").addEventListener("click", async () => {
  if (!state.selectedId) return;
  const next = !isRoutePinned(state.selectedId);
  setRoutePinned(state.selectedId, next);
  toast(next ? "已置顶，下次进入会优先显示" : "已取消置顶");
  await loadRoutes();
});

document.getElementById("alertThreshold")?.addEventListener("change", () => {
  saveAlertThreshold();
});
document.getElementById("alertThreshold")?.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    e.currentTarget.blur();
  }
});

document.getElementById("btnClose").addEventListener("click", () => {
  document.getElementById("detail").hidden = true;
  state.selectedId = null;
  state.currentRoute = null;
  hideOfferFilters();
  hideRecommendBoard();
  loadRoutes();
});

document.getElementById("btnToggle").addEventListener("click", async () => {
  if (!state.currentRoute) return;
  await toggleRouteEnabled(state.currentRoute.id);
});

document.getElementById("btnDelete").addEventListener("click", async () => {
  if (!state.selectedId) return;
  await deleteRoutesByIds([state.selectedId]);
});

document.getElementById("btnSelectAllRoutes")?.addEventListener("click", () => {
  const routes = state.routes || [];
  if (!routes.length) return;
  const allOn =
    state.checkedRouteIds.size === routes.length &&
    routes.every((r) => state.checkedRouteIds.has(Number(r.id)));
  if (allOn) {
    state.checkedRouteIds.clear();
  } else {
    state.checkedRouteIds = new Set(routes.map((r) => Number(r.id)));
  }
  document.querySelectorAll("#routeList .route").forEach((el) => {
    const id = Number(el.dataset.id);
    const on = state.checkedRouteIds.has(id);
    el.classList.toggle("checked", on);
    const cb = el.querySelector(".route-check-input");
    if (cb) cb.checked = on;
  });
  syncRouteBatchBar();
});

document.getElementById("btnBatchDelete")?.addEventListener("click", async () => {
  const ids = [...state.checkedRouteIds];
  if (!ids.length) return;
  await deleteRoutesByIds(ids);
});

document.getElementById("btnScanAll").addEventListener("click", async (ev) => {
  const btn = ev.currentTarget;
  btn.disabled = true;
  btn.textContent = "扫描中…";
  toast("正在拉取各平台报价，请稍候");
  try {
    const result = await api("/api/scan", { method: "POST" });
    await Promise.all([loadRoutes(), loadHealth(), loadAlerts()]);
    if (state.selectedId) await openDetail(state.selectedId);
    const n = (result.results || []).length;
    const hits =
      (result.drops || []).length ||
      (result.results || []).flatMap((r) => r.drops || r.alerts || []).length;
    toast(hits ? `扫描完成：${n} 条航线，${hits} 班降价` : `扫描完成：${n} 条航线`);
  } catch (err) {
    toast(err.message || String(err));
  } finally {
    btn.disabled = false;
    btn.textContent = "扫描全部";
    loadHealth();
  }
});

document.getElementById("btnScanOne").addEventListener("click", async (ev) => {
  if (!state.selectedId) return;
  const btn = ev.currentTarget;
  const prev = btn.textContent;
  btn.disabled = true;
  btn.textContent = "扫描中…";
  try {
    await scanOneRoute(state.selectedId);
  } finally {
    btn.disabled = false;
    btn.textContent = prev || "重新扫描";
  }
});

window.addEventListener("resize", () => state.chart?.resize());

document.getElementById("scanInterval")?.addEventListener("change", async (e) => {
  const minutes = Number(e.target.value);
  if (!minutes) return;
  try {
    const r = await api("/api/schedule", {
      method: "PATCH",
      body: JSON.stringify({ interval_minutes: minutes }),
    });
    toast(`扫描频率已设为每 ${r.interval_minutes} 分钟`);
    await loadHealth();
  } catch (err) {
    toast(err.message || String(err));
    loadHealth();
  }
});

const livePoll = {
  timer: null,
  inFlight: false,
  wasScanning: false,
  lastScanKey: null,
  routeStamp: "",
  selectedStamp: "",
};

function routeDataStamp(routes) {
  return (routes || [])
    .map(
      (r) =>
        `${r.id}:${r.best_price ?? ""}:${r.observed_at ?? ""}:${r.enabled ? 1 : 0}:${r.alert_threshold ?? ""}:${(r.notify_emails || []).join(",")}`
    )
    .join("|");
}

function selectedRouteStamp(routes, selectedId) {
  if (selectedId == null) return "";
  const r = (routes || []).find((x) => Number(x.id) === Number(selectedId));
  if (!r) return "";
  return `${r.id}:${r.best_price ?? ""}:${r.observed_at ?? ""}:${r.enabled ? 1 : 0}:${r.alert_threshold ?? ""}:${(r.notify_emails || []).join(",")}`;
}

function isEditingDashboardUi() {
  const el = document.activeElement;
  if (!el || el === document.body) return false;
  const tag = el.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  if (el.isContentEditable) return true;
  return false;
}

function scheduleLivePoll(scanning = false) {
  if (livePoll.timer) clearTimeout(livePoll.timer);
  const hidden = typeof document !== "undefined" && document.hidden;
  const ms = hidden ? 60000 : scanning ? 3000 : 10000;
  livePoll.timer = setTimeout(() => {
    pollDashboard().catch(() => {});
  }, ms);
}

async function pollDashboard() {
  if (livePoll.inFlight) {
    scheduleLivePoll(livePoll.wasScanning);
    return;
  }
  livePoll.inFlight = true;
  let scanning = livePoll.wasScanning;
  try {
    const [, health] = await Promise.all([
      loadRoutes(),
      loadHealth(),
      loadAlerts(),
    ]);
    scanning = !!(health && health.scanning);
    const scanKey =
      health?.last_scan?.id != null
        ? String(health.last_scan.id)
        : health?.last_scan?.finished_at || null;
    const stamp = routeDataStamp(state.routes);
    const selStamp = selectedRouteStamp(state.routes, state.selectedId);
    const scanJustFinished = livePoll.wasScanning && !scanning;
    const scanKeyChanged =
      scanKey != null &&
      livePoll.lastScanKey != null &&
      scanKey !== livePoll.lastScanKey;
    const selectedChanged =
      state.selectedId != null &&
      selStamp !== "" &&
      selStamp !== livePoll.selectedStamp;
    const scanningSelected =
      scanning &&
      state.selectedId != null &&
      Number(health?.scan_route_id) === Number(state.selectedId);

    if (
      state.selectedId &&
      !isEditingDashboardUi() &&
      (scanJustFinished || scanKeyChanged || selectedChanged || scanningSelected)
    ) {
      await openDetail(state.selectedId, { scroll: false, soft: true });
    }

    livePoll.wasScanning = scanning;
    if (scanKey != null) livePoll.lastScanKey = scanKey;
    livePoll.routeStamp = stamp;
    livePoll.selectedStamp = selStamp;
  } catch {
    /* keep polling */
  } finally {
    livePoll.inFlight = false;
    scheduleLivePoll(scanning);
  }
}

(async () => {
  initDatePicker();
  bindOfferFiltersUi();
  bindFlightBoardUi();
  bindRecommendUi();
  bindFlightTrendModal();
  bindNotifyGroupModal();
  const [, , routes] = await Promise.all([
    loadCities().catch(() => {}),
    loadHealth(),
    loadRoutes(),
    loadAlerts(),
  ]);
  if (routes && routes.length) {
    await openDetail(routes[0].id, { scroll: false });
  }
  livePoll.routeStamp = routeDataStamp(state.routes);
  livePoll.selectedStamp = selectedRouteStamp(state.routes, state.selectedId);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
      pollDashboard().catch(() => {});
    } else {
      scheduleLivePoll(livePoll.wasScanning);
    }
  });
  scheduleLivePoll(false);
})();
