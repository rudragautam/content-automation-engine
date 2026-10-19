// Small SVG chart kit for the hub: line (with crosshair + table view), bar list, heatmap, sparkline.
// Labels come from data, so all text goes in with textContent.

const SVG = "http://www.w3.org/2000/svg";
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function compact(n) {
  if (n === null || n === undefined) return "—";
  const a = Math.abs(n);
  for (const [size, s] of [[1e9, "B"], [1e6, "M"], [1e3, "K"]]) {
    if (a >= size) return (n / size).toFixed(1).replace(/\.0$/, "") + s;
  }
  // Small fractions (a few watch hours) keep one decimal instead of rounding to 0.
  if (a < 10 && !Number.isInteger(n)) return n.toFixed(1).replace(/\.0$/, "");
  return Math.round(n).toLocaleString();
}
const dayLabel = (iso) => { const [, m, d] = iso.split("-"); return `${+d} ${MONTHS[+m - 1]}`; };
const el = (name, attrs = {}, parent) => {
  const node = document.createElementNS(SVG, name);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (parent) parent.appendChild(node);
  return node;
};
function niceStep(range, ticks) {
  const raw = range / ticks, mag = 10 ** Math.floor(Math.log10(raw || 1));
  for (const f of [1, 2, 2.5, 5, 10]) if (raw <= f * mag) return f * mag;
  return 10 * mag;
}
function tooltipFor(container) {
  let tip = container.querySelector(":scope > .tooltip");
  if (!tip) { tip = document.createElement("div"); tip.className = "tooltip"; container.appendChild(tip); }
  return tip;
}
function fillTip(tip, value, label) {
  tip.replaceChildren();
  const v = document.createElement("div"); v.className = "tv"; v.textContent = value;
  const l = document.createElement("div"); l.className = "tl";
  const key = document.createElement("span"); key.className = "key";
  l.append(key, document.createTextNode(label));
  tip.append(v, l);
}
function placeTip(container, tip, x, y) {
  const w = container.clientWidth, tw = tip.offsetWidth;
  tip.style.left = Math.min(Math.max(0, x + 12), w - tw) + "px";
  tip.style.top = Math.max(0, y - 52) + "px";
  tip.style.opacity = 1;
}
function tableView(container, headers, rows) {
  const details = document.createElement("details");
  details.className = "table-view";
  const summary = document.createElement("summary"); summary.textContent = "Show as table";
  const wrap = document.createElement("div"); wrap.className = "table-wrap";
  const table = document.createElement("table");
  const thead = table.createTHead().insertRow();
  headers.forEach((h, i) => { const th = document.createElement("th"); th.textContent = h; if (i) th.className = "r"; thead.appendChild(th); });
  const body = table.createTBody();
  rows.forEach((r) => { const tr = body.insertRow(); r.forEach((c, i) => { const td = tr.insertCell(); td.textContent = c; if (i) td.className = "r num"; }); });
  wrap.appendChild(table); details.append(summary, wrap);
  container.after(details);
}

export function lineChart(container, data, { height = 220, unit = "" } = {}) {
  const values = data.map((d) => d.value);
  if (!data.length || values.every((v) => !v)) { container.textContent = "Nothing yet for this period."; container.className += " empty"; return; }
  const fmt = (v) => compact(v) + unit;
  tableView(container, ["Date", "Value"], data.map((d) => [d.date, fmt(d.value)]));

  function draw() {
    container.querySelector("svg")?.remove();
    const width = container.clientWidth || 600;
    const m = { l: 54, r: 60, t: 14, b: 30 };
    const w = width - m.l - m.r, h = height - m.t - m.b;
    let lo = Math.min(0, ...values), hi = Math.max(...values);
    // Whole-number series (views, subscribers) never get fractional gridlines like 0.25.
    const whole = values.every((v) => Number.isInteger(v));
    // Labels show at most one decimal, so gridlines are never closer than 0.1 (or 1 for whole numbers).
    const step = Math.max(whole ? 1 : 0.1, niceStep(hi - lo || 1, 4));
    lo = Math.floor(lo / step) * step; hi = Math.ceil(hi / step) * step || step;
    const x = (i) => m.l + (data.length === 1 ? w / 2 : (i / (data.length - 1)) * w);
    const y = (v) => m.t + h - ((v - lo) / (hi - lo)) * h;

    const svg = el("svg", { viewBox: `0 0 ${width} ${height}`, height, tabindex: 0, role: "img", "aria-label": container.dataset.label || "Line chart" });
    for (let v = lo; v <= hi + 1e-9; v += step) {
      el("line", { x1: m.l, x2: m.l + w, y1: y(v), y2: y(v), style: `stroke:${v === 0 ? "var(--chart-axis)" : "var(--chart-grid)"};stroke-width:1` }, svg);
      const t = el("text", { x: m.l - 8, y: y(v) + 4, "text-anchor": "end", class: "axis-text" }, svg); t.textContent = compact(v);
    }
    // As many date labels as fit without touching (about 72px each).
    const ticks = Math.min(5, data.length, Math.max(2, Math.floor(w / 72)));
    for (let k = 0; k < ticks; k++) {
      const i = Math.round((k / Math.max(1, ticks - 1)) * (data.length - 1));
      const t = el("text", { x: x(i), y: height - 6, "text-anchor": k === 0 ? "start" : k === ticks - 1 ? "end" : "middle", class: "axis-text" }, svg);
      t.textContent = dayLabel(data[i].date);
    }
    const pts = data.map((d, i) => `${x(i).toFixed(1)},${y(d.value).toFixed(1)}`);
    el("path", { d: `M${pts.join("L")}L${x(data.length - 1)},${y(Math.max(lo, 0))}L${x(0)},${y(Math.max(lo, 0))}Z`, style: "fill:var(--chart-line);fill-opacity:0.16;stroke:none" }, svg);
    el("path", { d: `M${pts.join("L")}`, style: "fill:none;stroke:var(--chart-line);stroke-width:3;stroke-linejoin:round;stroke-linecap:round" }, svg);
    const last = data.length - 1;
    el("circle", { cx: x(last), cy: y(values[last]), r: 4, style: "fill:var(--chart-line);stroke:var(--chart-dot-ring);stroke-width:2" }, svg);
    const end = el("text", { x: x(last) + 8, y: y(values[last]) + 4, class: "end-label" }, svg); end.textContent = fmt(values[last]);

    const cross = el("line", { y1: m.t, y2: m.t + h, style: "stroke:var(--chart-axis);stroke-width:1;opacity:0" }, svg);
    const dot = el("circle", { r: 4, style: "fill:var(--chart-line);stroke:var(--chart-dot-ring);stroke-width:2;opacity:0" }, svg);
    const tip = tooltipFor(container);
    let current = -1;
    const show = (i) => {
      current = Math.max(0, Math.min(last, i));
      const cx = x(current), cy = y(values[current]);
      cross.setAttribute("x1", cx); cross.setAttribute("x2", cx); cross.style.opacity = 1;
      dot.setAttribute("cx", cx); dot.setAttribute("cy", cy); dot.style.opacity = 1;
      fillTip(tip, fmt(values[current]), dayLabel(data[current].date));
      placeTip(container, tip, cx, cy);
    };
    const hide = () => { cross.style.opacity = 0; dot.style.opacity = 0; tip.style.opacity = 0; };
    const hit = el("rect", { x: m.l, y: m.t, width: w, height: h, style: "fill:transparent" }, svg);
    hit.addEventListener("pointermove", (e) => {
      const r = svg.getBoundingClientRect(), px = ((e.clientX - r.left) / r.width) * width;
      show(Math.round(((px - m.l) / w) * last));
    });
    hit.addEventListener("pointerleave", hide);
    svg.addEventListener("keydown", (e) => {
      if (e.key === "ArrowRight" || e.key === "ArrowLeft") { e.preventDefault(); show((current < 0 ? last : current) + (e.key === "ArrowRight" ? 1 : -1)); }
    });
    svg.addEventListener("focus", () => show(last));
    svg.addEventListener("blur", hide);
    container.prepend(svg);
  }
  draw();
  new ResizeObserver(() => draw()).observe(container);
}

export function barList(container, items, { unit = "" } = {}) {
  if (!items.length) { container.textContent = "No data for this period."; return; }
  const max = Math.max(...items.map((d) => d.value), 1);
  const tip = tooltipFor(container);
  container.classList.add("bars");
  items.forEach((d) => {
    const row = document.createElement("div"); row.className = "bar-row"; row.tabIndex = 0;
    const label = document.createElement("div"); label.className = "bl"; label.textContent = d.label;
    const track = document.createElement("div"); track.className = "bt";
    const fill = document.createElement("div"); fill.className = "bf"; fill.style.width = (d.value / max) * 100 + "%";
    track.appendChild(fill);
    const value = document.createElement("div"); value.className = "bv"; value.textContent = compact(d.value) + unit;
    row.append(label, track, value);
    const show = () => {
      fillTip(tip, compact(d.value) + unit, d.label);
      const r = row.getBoundingClientRect(), c = container.getBoundingClientRect();
      placeTip(container, tip, r.left - c.left + label.offsetWidth + fill.offsetWidth, r.top - c.top + 8);
    };
    row.addEventListener("pointerenter", show); row.addEventListener("focus", show);
    row.addEventListener("pointerleave", () => (tip.style.opacity = 0)); row.addEventListener("blur", () => (tip.style.opacity = 0));
    container.appendChild(row);
  });
}

export function heatmap(container, data) {
  const flat = data.values.flat().filter((v) => v !== null);
  if (!flat.length) { container.textContent = "Not enough published videos yet."; return; }
  const max = Math.max(...flat), bins = 6;
  const level = (v) => Math.min(bins - 1, Math.floor((v / max) * bins));
  const tip = tooltipFor(container);
  const grid = document.createElement("div"); grid.className = "heat";
  grid.style.gridTemplateColumns = `36px repeat(${data.cols.length}, minmax(28px, 1fr))`;
  grid.appendChild(document.createElement("div"));
  data.cols.forEach((c) => { const h = document.createElement("div"); h.className = "hh"; h.textContent = c; grid.appendChild(h); });
  let best = null;
  data.rows.forEach((rowLabel, r) => {
    const l = document.createElement("div"); l.className = "hl"; l.textContent = rowLabel; grid.appendChild(l);
    data.cols.forEach((col, c) => {
      const v = data.values[r][c], n = data.counts[r][c];
      const cell = document.createElement("div"); cell.className = "hc"; cell.tabIndex = v === null ? -1 : 0;
      if (v !== null) {
        cell.style.background = `var(--heat-${level(v)})`;
        if (!best || v > best.v) best = { v, label: `${rowLabel} ${col}` };
        const show = () => {
          fillTip(tip, `${compact(v)} avg views`, `${rowLabel} ${col} · ${n} video${n === 1 ? "" : "s"}`);
          const cr = cell.getBoundingClientRect(), k = container.getBoundingClientRect();
          placeTip(container, tip, cr.left - k.left + cr.width / 2, cr.top - k.top);
        };
        cell.addEventListener("pointerenter", show); cell.addEventListener("focus", show);
        cell.addEventListener("pointerleave", () => (tip.style.opacity = 0)); cell.addEventListener("blur", () => (tip.style.opacity = 0));
      }
      grid.appendChild(cell);
    });
  });
  container.appendChild(grid);
  const legend = document.createElement("div"); legend.className = "heat-legend";
  legend.append(document.createTextNode("Fewer views"));
  for (let i = 0; i < bins; i++) { const s = document.createElement("span"); s.className = "sw"; s.style.background = `var(--heat-${i})`; legend.appendChild(s); }
  legend.append(document.createTextNode("More views"));
  if (best) { const b = document.createElement("strong"); b.style.marginLeft = "auto"; b.style.color = "var(--text)"; b.textContent = `Best slot: ${best.label} (${compact(best.v)} avg)`; legend.appendChild(b); }
  container.appendChild(legend);
  const rows = [];
  data.rows.forEach((r, i) => data.cols.forEach((c, j) => { if (data.values[i][j] !== null) rows.push([`${r} ${c}`, compact(data.values[i][j]), String(data.counts[i][j])]); }));
  tableView(container, ["Slot", "Avg views", "Videos"], rows);
}

export function sparkline(container, values) {
  if (values.length < 2) return;
  const w = 96, h = 26, lo = Math.min(...values), hi = Math.max(...values) || 1;
  const x = (i) => 2 + (i / (values.length - 1)) * (w - 6), y = (v) => h - 3 - ((v - lo) / (hi - lo || 1)) * (h - 6);
  const svg = el("svg", { viewBox: `0 0 ${w} ${h}`, class: "spark", "aria-hidden": "true" });
  el("path", { d: "M" + values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("L"), style: "fill:none;stroke:var(--muted);stroke-width:1.5;stroke-linejoin:round;stroke-linecap:round" }, svg);
  el("circle", { cx: x(values.length - 1), cy: y(values[values.length - 1]), r: 2.5, style: "fill:var(--chart-line)" }, svg);
  container.appendChild(svg);
}

// Mount every [data-chart] element from the JSON in its data-src script.
export function mountAll(root = document) {
  root.querySelectorAll("[data-chart]").forEach((node) => {
    const data = JSON.parse(document.getElementById(node.dataset.src).textContent);
    const opts = { unit: node.dataset.unit || "", height: +(node.dataset.height || 220) };
    ({ line: lineChart, bars: barList, heatmap })[node.dataset.chart](node, data, opts);
  });
  root.querySelectorAll("[data-spark]").forEach((node) => sparkline(node, JSON.parse(node.dataset.spark)));
}
