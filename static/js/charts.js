/* 原生 SVG 图表：折线/柱状/环形/横向条形/迷你趋势 */

import { esc, fmtNum } from "./ui.js";

function niceMax(value) {
  if (!value || value <= 0) return 1;
  const exponent = Math.floor(Math.log10(value));
  const fraction = value / 10 ** exponent;
  const nice = fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 5 ? 5 : 10;
  return nice * 10 ** exponent;
}

function labelStep(count, max = 7) {
  return Math.max(1, Math.ceil(count / max));
}

export function comboChart({
  labels = [],
  bars = [],
  barLabel = "订单",
  barColor = "#a7e3c9",
  line = [],
  lineLabel = "收入",
  lineColor = "#0e9f6e",
  height = 250,
  barFormatter = (v) => fmtNum(v),
  lineFormatter = (v) => `¥${fmtNum(v, 0)}`,
} = {}) {
  if (!labels.length) return `<div class="chart-empty">暂无趋势数据</div>`;
  const W = 860;
  const H = height;
  const pad = { l: 46, r: 48, t: 16, b: 30 };
  const innerW = W - pad.l - pad.r;
  const innerH = H - pad.t - pad.b;
  const n = labels.length;
  const step = innerW / Math.max(1, n);
  const barMax = niceMax(Math.max(...bars, 0));
  const lineMax = niceMax(Math.max(...line, 0));
  const x = (i) => pad.l + step * i + step / 2;
  const yBar = (v) => pad.t + innerH - (v / barMax) * innerH;
  const yLine = (v) => pad.t + innerH - (v / lineMax) * innerH;
  const barW = Math.max(5, Math.min(24, step * 0.42));

  const grid = [0, 0.25, 0.5, 0.75, 1]
    .map((ratio) => {
      const y = pad.t + innerH * ratio;
      const leftValue = barMax * (1 - ratio);
      const rightValue = lineMax * (1 - ratio);
      return `<line class="grid-line" x1="${pad.l}" y1="${y}" x2="${W - pad.r}" y2="${y}"/>
        <text x="${pad.l - 8}" y="${y + 3}" text-anchor="end" style="font-size:9px">${esc(barFormatter(this === undefined ? leftValue : leftValue))}</text>
        <text x="${W - pad.r + 8}" y="${y + 3}" text-anchor="start" style="font-size:9px">${esc(lineFormatter(rightValue))}</text>`;
    })
    .join("");

  const barsSvg = bars
    .map((value, i) => {
      const y = yBar(value);
      return `<rect x="${x(i) - barW / 2}" y="${y}" width="${barW}" height="${Math.max(0, pad.t + innerH - y)}" rx="4" fill="${barColor}" opacity=".8">
        <title>${esc(labels[i])} · ${esc(barLabel)} ${esc(barFormatter(value))}</title></rect>`;
    })
    .join("");

  const points = line.map((value, i) => [x(i), yLine(value)]);
  const linePath = points.map(([px, py], i) => `${i === 0 ? "M" : "L"}${px.toFixed(1)},${py.toFixed(1)}`).join(" ");
  const areaPath = `${linePath} L${points[points.length - 1][0].toFixed(1)},${pad.t + innerH} L${points[0][0].toFixed(1)},${pad.t + innerH} Z`;
  const dots = points
    .map(
      ([px, py], i) =>
        `<circle class="dot" cx="${px}" cy="${py}" r="${n > 14 ? 2.4 : 3.2}" fill="${lineColor}"><title>${esc(labels[i])} · ${esc(lineLabel)} ${esc(lineFormatter(line[i]))}</title></circle>`
    )
    .join("");

  const stepLabel = labelStep(n, 7);
  const xLabels = labels
    .map((label, i) =>
      i % stepLabel === 0 || i === n - 1
        ? `<text x="${x(i)}" y="${H - 8}" text-anchor="middle" style="font-size:9px">${esc(label)}</text>`
        : ""
    )
    .join("");

  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="运营趋势图" preserveAspectRatio="none" style="height:${height}px">
    <defs>
      <linearGradient id="combo-area" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="${lineColor}" stop-opacity=".22"/>
        <stop offset="1" stop-color="${lineColor}" stop-opacity="0"/>
      </linearGradient>
    </defs>
    ${grid}
    ${barsSvg}
    <path d="${areaPath}" fill="url(#combo-area)"/>
    <path class="line" d="${linePath}" stroke="${lineColor}"/>
    ${dots}
    ${xLabels}
    <line class="axis-line" x1="${pad.l}" y1="${pad.t + innerH}" x2="${W - pad.r}" y2="${pad.t + innerH}"/>
    <g transform="translate(${pad.l}, 8)">
      <rect x="0" y="0" width="8" height="8" rx="2" fill="${barColor}" opacity=".9"/>
      <text x="13" y="7" style="font-size:9px">${esc(barLabel)}</text>
      <line x1="56" y1="4" x2="70" y2="4" stroke="${lineColor}" stroke-width="2.4"/>
      <text x="75" y="7" style="font-size:9px">${esc(lineLabel)}</text>
    </g>
  </svg>`;
}

export function barChart({
  labels = [],
  values = [],
  color = "#0e9f6e",
  height = 220,
  formatter = (v) => fmtNum(v),
} = {}) {
  if (!labels.length) return `<div class="chart-empty">暂无数据</div>`;
  const W = 860;
  const H = height;
  const pad = { l: 46, r: 14, t: 16, b: 30 };
  const innerW = W - pad.l - pad.r;
  const innerH = H - pad.t - pad.b;
  const max = niceMax(Math.max(...values, 0));
  const step = innerW / Math.max(1, labels.length);
  const barW = Math.max(8, Math.min(42, step * 0.55));
  const grid = [0, 0.25, 0.5, 0.75, 1]
    .map((ratio) => {
      const y = pad.t + innerH * ratio;
      return `<line class="grid-line" x1="${pad.l}" y1="${y}" x2="${W - pad.r}" y2="${y}"/>
        <text x="${pad.l - 8}" y="${y + 3}" text-anchor="end" style="font-size:9px">${esc(formatter(max * (1 - ratio)))}</text>`;
    })
    .join("");
  const bars = values
    .map((value, i) => {
      const h = (value / max) * innerH;
      const px = pad.l + step * i + (step - barW) / 2;
      return `<rect x="${px}" y="${pad.t + innerH - h}" width="${barW}" height="${Math.max(0, h)}" rx="5" fill="${color}">
        <title>${esc(labels[i])} · ${esc(formatter(value))}</title></rect>`;
    })
    .join("");
  const stepLabel = labelStep(labels.length, 7);
  const xLabels = labels
    .map((label, i) =>
      i % stepLabel === 0 || i === labels.length - 1
        ? `<text x="${pad.l + step * i + step / 2}" y="${H - 8}" text-anchor="middle" style="font-size:9px">${esc(label)}</text>`
        : ""
    )
    .join("");
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="柱状图" preserveAspectRatio="none" style="height:${height}px">
    ${grid}${bars}${xLabels}
    <line class="axis-line" x1="${pad.l}" y1="${pad.t + innerH}" x2="${W - pad.r}" y2="${pad.t + innerH}"/>
  </svg>`;
}

export function donutChart(items = [], { size = 150, thickness = 14, centerValue = "", centerLabel = "" } = {}) {
  const total = items.reduce((sum, item) => sum + Number(item.value || 0), 0);
  const radius = (size - thickness) / 2;
  const circumference = 2 * Math.PI * radius;
  let offset = 0;
  const segments = items
    .filter((item) => Number(item.value) > 0)
    .map((item) => {
      const ratio = total ? Number(item.value) / total : 0;
      const length = ratio * circumference;
      const seg = `<circle cx="${size / 2}" cy="${size / 2}" r="${radius}" fill="none" stroke="${item.color}" stroke-width="${thickness}"
        stroke-dasharray="${length} ${circumference - length}" stroke-dashoffset="${-offset}" stroke-linecap="round" transform="rotate(-90 ${size / 2} ${size / 2})">
        <title>${esc(item.label)} ${fmtNum(item.value)}（${(ratio * 100).toFixed(1)}%）</title></circle>`;
      offset += length;
      return seg;
    })
    .join("");
  const background = `<circle cx="${size / 2}" cy="${size / 2}" r="${radius}" fill="none" stroke="#eef4f1" stroke-width="${thickness}"/>`;
  const center = centerValue
    ? `<text x="${size / 2}" y="${size / 2 - 2}" text-anchor="middle" class="dv">${esc(centerValue)}</text>
       <text x="${size / 2}" y="${size / 2 + 14}" text-anchor="middle" class="dl">${esc(centerLabel)}</text>`
    : "";
  return `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" role="img" aria-label="占比环形图">
    ${background}${segments}${center}
  </svg>`;
}

export function horizontalBars(items = [], { valueFormatter = (v) => fmtNum(v), color = "#0e9f6e" } = {}) {
  if (!items.length) return `<div class="chart-empty">暂无对比数据</div>`;
  const max = Math.max(...items.map((item) => Number(item.value) || 0), 1);
  return items
    .map(
      (item) => `<div class="hbar-row">
        <span class="hbar-label" title="${esc(item.label)}">${esc(item.label)}</span>
        <div class="hbar-track"><div class="hbar-fill" style="width:${Math.max(2, (Number(item.value) / max) * 100)}%;background:${item.color || color}"></div></div>
        <span class="hbar-value">${esc(valueFormatter(item.value))}</span>
      </div>`
    )
    .join("");
}

export function sparkline(values = [], { width = 110, height = 32, color = "#0e9f6e" } = {}) {
  if (!values.length) return "";
  const max = Math.max(...values.map(Number), 1);
  const min = Math.min(...values.map(Number), 0);
  const range = max - min || 1;
  const points = values
    .map((value, i) => {
      const x = (i / Math.max(1, values.length - 1)) * (width - 2) + 1;
      const y = height - 3 - ((Number(value) - min) / range) * (height - 6);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return `<svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" aria-hidden="true">
    <polyline points="${points}" fill="none" stroke="${color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
  </svg>`;
}
