"use strict";

const tg = window.Telegram?.WebApp;
const initData = tg?.initData || "";
const COLORS = { good: "var(--good)", fair: "var(--fair)", bad: "var(--bad)", none: "var(--none)" };
const VERDICT = {
  good: "Климат в норме",
  fair: "Климат удовлетворительный",
  bad: "Климат плохой",
  none: "Нет оценки",
};
const SCALE = { co2: 2000, pm25: 75, pm10: 150, tvoc: 1000, tvoc_index: 500, humidity: 100, temperature: 35, noise: 90, battery: 100, pressure: 110 };

const state = { devices: [], mac: null, metric: "co2", hours: 24 };
const $ = (id) => document.getElementById(id);

if (tg) {
  tg.ready();
  tg.expand();
  tg.setHeaderColor?.("secondary_bg_color");
  tg.setBackgroundColor?.("secondary_bg_color");
}

async function api(path) {
  const res = await fetch(path, { headers: { "X-Telegram-Init-Data": initData } });
  if (!res.ok) throw new Error((await res.text()) || `HTTP ${res.status}`);
  return res.json();
}

function showError(text) {
  $("error").textContent = text;
  $("error").hidden = !text;
}

function timeAgo(ts) {
  const min = Math.round((Date.now() / 1000 - ts) / 60);
  if (min < 1) return "только что";
  if (min < 60) return `${min} мин назад`;
  const h = Math.round(min / 60);
  if (h < 24) return `${h} ч назад`;
  return new Date(ts * 1000).toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

function current() {
  return state.devices.find((d) => d.mac === state.mac) || state.devices[0];
}

function renderDevices() {
  const nav = $("devices");
  nav.hidden = state.devices.length < 2;
  nav.replaceChildren(
    ...state.devices.map((d) => {
      const b = document.createElement("button");
      b.textContent = d.name;
      b.className = d.mac === state.mac ? "active" : "";
      b.onclick = () => select(d.mac, state.metric);
      return b;
    })
  );
}

function renderDevice() {
  const d = current();
  if (!d) {
    $("updated").textContent = "Нет данных с датчиков";
    $("verdict").textContent = "Ждём данные…";
    $("hero").classList.remove("skeleton");
    return;
  }
  $("updated").textContent = `${d.name} · ${timeAgo(d.ts)}${d.stale ? " · ⚠️ данные устарели" : ""}`;
  const hero = $("hero");
  hero.classList.remove("skeleton");
  hero.dataset.state = d.overall;
  $("verdict").textContent = VERDICT[d.overall];
  $("advice").replaceChildren(
    ...d.advice.map((t) => Object.assign(document.createElement("li"), { textContent: t }))
  );

  if (!d.metrics.some((m) => m.key === state.metric)) state.metric = d.metrics[0]?.key;
  $("metrics").replaceChildren(
    ...d.metrics.map((m) => {
      const el = document.createElement("button");
      el.className = "metric" + (m.key === state.metric ? " selected" : "");
      el.style.setProperty("--c", COLORS[m.rating]);
      const pct = Math.max(3, Math.min(100, (m.value / (SCALE[m.key] || 100)) * 100));
      el.innerHTML = `
        <div class="label"><span class="dot"></span>${m.title}</div>
        <div class="value">${m.value}<span class="unit">${m.unit}</span></div>
        <div class="bar"><i style="width:${pct}%"></i></div>`;
      el.onclick = () => {
        tg?.HapticFeedback?.selectionChanged();
        select(d.mac, m.key);
      };
      return el;
    })
  );
}

function select(mac, metric) {
  state.mac = mac;
  state.metric = metric;
  renderDevices();
  renderDevice();
  loadChart();
}

async function loadState() {
  const btn = $("refresh");
  btn.classList.add("spin");
  try {
    const data = await api("/api/state");
    state.devices = data.devices;
    if (!state.devices.some((d) => d.mac === state.mac)) state.mac = state.devices[0]?.mac || null;
    renderDevices();
    renderDevice();
    showError("");
    await loadChart();
  } catch (e) {
    showError(initData ? `Ошибка: ${e.message}` : "Откройте это приложение из Telegram.");
  } finally {
    btn.classList.remove("spin");
  }
}

async function loadChart() {
  const d = current();
  const m = d?.metrics.find((x) => x.key === state.metric);
  $("chart-title").textContent = m ? `${m.title}${m.unit ? ", " + m.unit : ""}` : "График";
  if (!d || !m) return drawChart([], m);
  try {
    const data = await api(`/api/history?mac=${encodeURIComponent(d.mac)}&metric=${m.key}&hours=${state.hours}`);
    drawChart(data.points, m);
  } catch (e) {
    showError(`Ошибка графика: ${e.message}`);
  }
}

function drawChart(points, metric) {
  const box = $("chart");
  const stats = $("chart-stats");
  if (points.length < 2) {
    box.innerHTML = '<div class="empty">Недостаточно данных</div>';
    stats.textContent = "";
    return;
  }
  const W = box.clientWidth || 320, H = box.clientHeight || 180, pad = 8;
  const xs = points.map((p) => p[0]), ys = points.map((p) => p[1]);
  const x0 = xs[0], x1 = xs[xs.length - 1];
  let y0 = Math.min(...ys), y1 = Math.max(...ys);
  if (y1 - y0 < 1e-9) { y0 -= 1; y1 += 1; }
  const sx = (t) => ((t - x0) / (x1 - x0)) * W;
  const sy = (v) => H - pad - ((v - y0) / (y1 - y0)) * (H - pad * 2);
  const line = points.map((p, i) => `${i ? "L" : "M"}${sx(p[0]).toFixed(1)},${sy(p[1]).toFixed(1)}`).join("");
  const color = COLORS[metric.rating];

  box.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
      <defs>
        <linearGradient id="fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="${color}" stop-opacity=".35"/>
          <stop offset="1" stop-color="${color}" stop-opacity="0"/>
        </linearGradient>
      </defs>
      <path d="${line}L${W},${H}L0,${H}Z" fill="url(#fill)"/>
      <path d="${line}" fill="none" stroke="${color}" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/>
      <line id="cursor" y1="0" y2="${H}" stroke="var(--muted)" stroke-dasharray="3 3" visibility="hidden"/>
      <circle id="cursor-dot" r="4" fill="${color}" stroke="var(--card)" stroke-width="2" visibility="hidden"/>
    </svg>
    <div class="tip" hidden></div>`;

  const fmt = (v) => (Math.round(v * 10) / 10).toLocaleString("ru-RU");
  const avg = ys.reduce((a, b) => a + b, 0) / ys.length;
  stats.innerHTML = `<span>мин ${fmt(Math.min(...ys))}</span><span>сред ${fmt(avg)}</span><span>макс ${fmt(Math.max(...ys))}</span>`;

  const svg = box.querySelector("svg"), tip = box.querySelector(".tip");
  const cursor = svg.getElementById("cursor"), dot = svg.getElementById("cursor-dot");
  const move = (ev) => {
    const rect = box.getBoundingClientRect();
    const t = x0 + ((ev.clientX - rect.left) / rect.width) * (x1 - x0);
    let best = points[0];
    for (const p of points) if (Math.abs(p[0] - t) < Math.abs(best[0] - t)) best = p;
    const px = sx(best[0]), py = sy(best[1]);
    cursor.setAttribute("x1", px); cursor.setAttribute("x2", px);
    dot.setAttribute("cx", px); dot.setAttribute("cy", py);
    cursor.setAttribute("visibility", "visible"); dot.setAttribute("visibility", "visible");
    const when = new Date(best[0] * 1000).toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
    tip.textContent = `${fmt(best[1])} ${metric.unit} · ${when}`;
    tip.style.left = `${Math.min(Math.max((px / W) * rect.width, 70), rect.width - 70)}px`;
    tip.hidden = false;
  };
  const leave = () => {
    tip.hidden = true;
    cursor.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden");
  };
  box.onpointermove = move;
  box.onpointerdown = move;
  box.onpointerleave = leave;
}

$("ranges").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  state.hours = Number(b.dataset.h);
  for (const x of $("ranges").children) x.classList.toggle("active", x === b);
  tg?.HapticFeedback?.selectionChanged();
  loadChart();
});
$("refresh").onclick = () => {
  tg?.HapticFeedback?.impactOccurred("light");
  loadState();
};
window.addEventListener("resize", () => loadChart());

loadState();
setInterval(loadState, 60000);
