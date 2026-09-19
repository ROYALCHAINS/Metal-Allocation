/**
 * components/charts.js — the hand-written SVG chart engine from
 * Reports.html. Kept hand-written per CLAUDE.md 7 ("no external library" —
 * replacing it would change the appearance and is out of scope), just
 * factored into its own module since it is now shared by both
 * views/reports.js and views/dashboard.js.
 */

import { esc, fmt0, fmt3, fmtPct } from '../lib/format.js';

export function emptyChart(el, message) {
  el.innerHTML =
    '<div class="empty-state"><div class="empty-state__title">No data</div>' +
    `<div class="empty-state__text">${esc(message)}</div></div>`;
}

export function niceMax(value) {
  if (!(value > 0)) return 1;
  const exp = Math.pow(10, Math.floor(Math.log(value) / Math.LN10));
  const norm = value / exp;
  const step = norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10;
  return step * exp;
}

/**
 * Grouped vertical bar chart: emerald bars for series A, navy for series B,
 * dashed horizontal grid, monospace axis labels. rows: [{label, short, a, b}]
 */
export function groupedBarChart(el, rows) {
  if (!rows.length) {
    emptyChart(el, 'No saved dates in the selected range.');
    return;
  }

  const W = 1000, H = 300, padL = 60, padR = 20, padT = 52, padB = 50;
  const plotW = W - padL - padR, plotH = H - padT - padB;

  let max = 0;
  rows.forEach((r) => { max = Math.max(max, r.a, r.b); });
  max = niceMax(max);
  const axDec = max >= 4 ? 0 : 1;

  const slot = plotW / rows.length;
  const barW = Math.max(4, Math.min(13, slot / 2.8));
  const labelEvery = Math.ceil(rows.length / 10);

  let svg =
    `<svg class="chart-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" role="img">` +
    '<defs>' +
    '<linearGradient id="rmasBarA" x1="0" y1="0" x2="0" y2="1">' +
    '<stop offset="0%" stop-color="#10b981"/><stop offset="100%" stop-color="#059669"/>' +
    '</linearGradient>' +
    '<linearGradient id="rmasBarB" x1="0" y1="0" x2="0" y2="1">' +
    '<stop offset="0%" stop-color="#244570"/><stop offset="100%" stop-color="#132742"/>' +
    '</linearGradient>' +
    '</defs>';

  for (let g = 0; g < 4; g++) {
    const y = padT + (plotH / 4) * g;
    const val = max - (max / 4) * g;
    svg += `<line class="chart-grid-line" x1="${padL}" y1="${y}" x2="${W - padR}" y2="${y}"/>`;
    svg += `<text class="chart-axis-text" x="${padL - 10}" y="${y + 4}" text-anchor="end">${val.toFixed(axDec)}</text>`;
  }
  const base = padT + plotH;
  svg += `<line class="chart-baseline" x1="${padL}" y1="${base}" x2="${W - padR}" y2="${base}"/>`;
  svg += `<text class="chart-axis-text" x="${padL - 10}" y="${base + 4}" text-anchor="end">${(0).toFixed(axDec)}</text>`;

  rows.forEach((r, i) => {
    const cx = padL + slot * i + slot / 2;
    const ha = max > 0 ? (r.a / max) * plotH : 0;
    const hb = max > 0 ? (r.b / max) * plotH : 0;
    svg += '<g class="bar-group">';
    svg += `<title>${esc(r.label)} — Acquired ${fmt3(r.a)} kg | Alloted ${fmt3(r.b)} kg</title>`;
    if (ha > 0) {
      svg += `<rect x="${(cx - barW - 1).toFixed(1)}" y="${(base - ha).toFixed(1)}" width="${barW}" height="${ha.toFixed(1)}" rx="1.5" fill="url(#rmasBarA)"/>`;
    }
    if (hb > 0) {
      svg += `<rect x="${(cx + 1).toFixed(1)}" y="${(base - hb).toFixed(1)}" width="${barW}" height="${hb.toFixed(1)}" rx="1.5" fill="url(#rmasBarB)"/>`;
    }
    svg += '</g>';
    if (ha > 0) {
      const xa = cx - barW / 2 - 1, ya = base - ha - 5;
      svg += `<text class="chart-bar-text" x="${xa.toFixed(1)}" y="${ya.toFixed(1)}" text-anchor="start" transform="rotate(-90 ${xa.toFixed(1)} ${ya.toFixed(1)})">${fmt0(r.a)}</text>`;
    }
    if (hb > 0) {
      const xb = cx + barW / 2 + 1, yb = base - hb - 5;
      svg += `<text class="chart-bar-text" x="${xb.toFixed(1)}" y="${yb.toFixed(1)}" text-anchor="start" transform="rotate(-90 ${xb.toFixed(1)} ${yb.toFixed(1)})">${fmt0(r.b)}</text>`;
    }
    if (i % labelEvery === 0) {
      svg += `<text class="chart-tick-text" x="${cx.toFixed(1)}" y="${base + 22}" text-anchor="middle">${esc(r.short)}</text>`;
    }
  });

  svg += '</svg>';
  el.innerHTML = svg;
}

/** Single-series line chart with an area fill and a callout on the latest point. rows: [{label, short, value}] */
export function lineChart(el, rows, color) {
  if (!rows.length) {
    emptyChart(el, 'No saved dates in the selected range.');
    return;
  }

  const W = 1000, H = 260, padL = 60, padR = 20, padT = 42, padB = 50;
  const plotW = W - padL - padR, plotH = H - padT - padB;

  let max = 0, min = 0;
  rows.forEach((r) => { max = Math.max(max, r.value); min = Math.min(min, r.value); });
  max = niceMax(max);
  min = min < 0 ? -niceMax(Math.abs(min)) : 0;
  const span = max - min || 1;
  const axDec = span >= 4 ? 0 : 1;

  const yFor = (v) => padT + plotH - ((v - min) / span) * plotH;
  const step = rows.length > 1 ? plotW / (rows.length - 1) : 0;
  const xFor = (i) => (rows.length > 1 ? padL + step * i : padL + plotW / 2);
  const labelEvery = Math.ceil(rows.length / 10);

  let svg =
    `<svg class="chart-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" role="img">` +
    `<defs><linearGradient id="rmasArea" x1="0" y1="0" x2="0" y2="1">` +
    `<stop offset="0%" stop-color="${color}" stop-opacity="0.32"/>` +
    `<stop offset="70%" stop-color="${color}" stop-opacity="0.06"/>` +
    `<stop offset="100%" stop-color="${color}" stop-opacity="0"/>` +
    '</linearGradient></defs>';

  for (let g = 0; g < 4; g++) {
    const y = padT + (plotH / 4) * g;
    const val = max - (span / 4) * g;
    svg += `<line class="chart-grid-line" x1="${padL}" y1="${y}" x2="${W - padR}" y2="${y}"/>`;
    svg += `<text class="chart-axis-text" x="${padL - 10}" y="${y + 4}" text-anchor="end">${val.toFixed(axDec)}</text>`;
  }
  const zeroY = yFor(0);
  svg += `<line class="chart-baseline" x1="${padL}" y1="${zeroY.toFixed(1)}" x2="${W - padR}" y2="${zeroY.toFixed(1)}"/>`;
  svg += `<text class="chart-axis-text" x="${padL - 10}" y="${(zeroY + 4).toFixed(1)}" text-anchor="end">${(0).toFixed(axDec)}</text>`;

  const pts = rows.map((r, i) => `${xFor(i).toFixed(1)},${yFor(r.value).toFixed(1)}`);

  if (rows.length > 1) {
    svg += `<polygon fill="url(#rmasArea)" points="${xFor(0).toFixed(1)},${zeroY.toFixed(1)} ${pts.join(' ')} ${xFor(rows.length - 1).toFixed(1)},${zeroY.toFixed(1)}"/>`;
    svg += `<polyline points="${pts.join(' ')}" fill="none" stroke="${color}" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>`;
  }

  rows.forEach((r, i) => {
    const cx = xFor(i), cy = yFor(r.value), last = i === rows.length - 1;
    svg += `<circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="${last ? 6 : 4.5}" fill="${last ? color : '#ffffff'}" stroke="${last ? '#ffffff' : color}" stroke-width="${last ? 3 : 2.5}"><title>${esc(r.label)} — ${fmt3(r.value)} kg</title></circle>`;
    svg += `<text class="chart-point-text" x="${cx.toFixed(1)}" y="${(cy - 11).toFixed(1)}" text-anchor="middle">${fmt0(r.value)}</text>`;
    if (i % labelEvery === 0) {
      svg += `<text class="chart-tick-text" x="${cx.toFixed(1)}" y="${padT + plotH + 22}" text-anchor="middle">${esc(r.short)}</text>`;
    }
  });

  const lastRow = rows[rows.length - 1];
  const lx = Math.min(xFor(rows.length - 1), W - padR - 58);
  const ly = Math.max(yFor(lastRow.value) - 42, 4);
  svg +=
    `<g transform="translate(${(lx - 52).toFixed(1)},${ly.toFixed(1)})">` +
    '<rect width="110" height="24" rx="5" fill="#0f172a"/>' +
    '<polygon points="51,24 59,24 55,29" fill="#0f172a"/>' +
    `<text class="chart-callout-text" x="55" y="16" text-anchor="middle">${fmt0(lastRow.value)} kg</text></g>`;

  svg += '</svg>';
  el.innerHTML = svg;
}

/** Horizontal sector comparison: navy Required rail above an amber Balance rail. rows: [{sector, required, balance}] */
export function sectorBarChart(el, rows) {
  if (!rows.length) {
    emptyChart(el, 'No sector activity in the selected range.');
    return;
  }

  const top = rows.slice(0, 10);
  const W = 560, rowH = 40, padL = 132, padR = 74, padT = 8;
  const H = padT + top.length * rowH + 6;
  const plotW = W - padL - padR;

  let max = 0;
  top.forEach((r) => { max = Math.max(max, r.required, Math.max(0, r.balance)); });
  max = niceMax(max);

  let svg = `<svg class="chart-svg chart-svg--fit" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" role="img">`;

  top.forEach((r, i) => {
    const y = padT + i * rowH;
    const name = r.sector.length > 20 ? `${r.sector.substring(0, 19)}…` : r.sector;
    svg += `<text class="chart-sector-text" x="${padL - 8}" y="${y + 22}" text-anchor="end">${esc(name)}<title>${esc(r.sector)}</title></text>`;

    const wA = max > 0 ? (r.required / max) * plotW : 0;
    const wB = max > 0 ? (Math.max(0, r.balance) / max) * plotW : 0;

    svg += `<rect x="${padL}" y="${y + 6}" width="${plotW}" height="9" rx="3" fill="#f1f5f9"/>`;
    svg += `<rect x="${padL}" y="${y + 6}" width="${Math.max(1, wA).toFixed(1)}" height="9" rx="3" fill="#1e3a5f"><title>${esc(r.sector)} — Required ${fmt3(r.required)} kg</title></rect>`;
    svg += `<text class="chart-rail-text" x="${(padL + Math.max(1, wA) + 5).toFixed(1)}" y="${y + 14}">${fmt0(r.required)}</text>`;

    svg += `<rect x="${padL}" y="${y + 19}" width="${plotW}" height="13" rx="3" fill="rgba(254,243,199,.6)"/>`;
    svg += `<rect x="${padL}" y="${y + 19}" width="${Math.max(1, wB).toFixed(1)}" height="13" rx="3" fill="#f59e0b"><title>${esc(r.sector)} — Balance ${fmt3(r.balance)} kg</title></rect>`;
    svg += `<text class="chart-rail-text" x="${(padL + Math.max(1, wB) + 5).toFixed(1)}" y="${y + 29}">${fmt0(r.balance)}</text>`;

    svg += `<text class="chart-value-text" x="${W - 6}" y="${y + 22}" text-anchor="end">${fmt0(r.required + Math.max(0, r.balance))}</text>`;
  });

  svg += '</svg>';
  el.innerHTML = svg;
}

/** "versus previous cycle" delta line under a Total Acquired card. */
export function renderCycleDelta(node, cycle) {
  if (!node) return;
  const pct = cycle.change_percent;
  if (pct === null || pct === undefined) {
    node.textContent = 'kg acquired in range';
    node.className = 'summary-stat__sub';
    return;
  }
  const up = pct >= 0;
  node.textContent = `${up ? '↗ +' : '↘ '}${Number(pct).toFixed(1)}% vs prev ${cycle.day_count} day(s)`;
  node.className = `summary-stat__sub summary-stat__sub--${up ? 'up' : 'down'}`;
}

const FLOW_COLORS = [
  '#14345c', '#1f4e87', '#3a6fae', '#5c8fc9', '#7fadde',
  '#a8caee', '#c2d9f2', '#8a5a08', '#b4740c', '#d19b3e',
];
const flowColor = (i) => FLOW_COLORS[i % FLOW_COLORS.length];

/** Horizontal bar chart of total acquired per party. series: {sectors:[{sector,total,percent}]} */
export function sectorShareChart(el, series) {
  if (!series || !series.sectors || !series.sectors.length) {
    emptyChart(el, 'No acquired metal recorded in the selected range.');
    return;
  }

  const rows = series.sectors;
  const W = 560, rowH = 30, padL = 118, padR = 132, padT = 8;
  const H = padT + rows.length * rowH + 8;
  const plotW = W - padL - padR;
  const max = niceMax(rows[0].total);

  let svg = `<svg class="chart-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" role="img">`;

  rows.forEach((r, i) => {
    const y = padT + i * rowH;
    const name = r.sector.length > 16 ? `${r.sector.substring(0, 15)}…` : r.sector;
    const w = max > 0 ? (r.total / max) * plotW : 0;

    svg += `<text class="chart-sector-text" x="${padL - 8}" y="${y + 19}" text-anchor="end">${esc(name)}<title>${esc(r.sector)}</title></text>`;
    svg += `<rect x="${padL}" y="${y + 7}" width="${Math.max(1, w).toFixed(1)}" height="14" fill="${flowColor(i)}" rx="3"><title>${esc(r.sector)} — ${fmt3(r.total)} kg — ${fmtPct(r.percent)}</title></rect>`;
    svg += `<text class="chart-value-text" x="${W - 6}" y="${y + 19}" text-anchor="end">${fmt3(r.total)} · ${fmtPct(r.percent)}</text>`;
  });

  svg += '</svg>';
  el.innerHTML = svg;
}

const HEAT_STOPS = [
  { t: 0.0, c: [242, 244, 247] },
  { t: 0.15, c: [234, 241, 251] },
  { t: 0.45, c: [168, 202, 238] },
  { t: 0.75, c: [79, 139, 208] },
  { t: 1.0, c: [20, 52, 92] },
];

function heatColor(t) {
  if (!(t > 0)) return 'rgb(242,244,247)';
  if (t > 1) t = 1;
  for (let i = 1; i < HEAT_STOPS.length; i++) {
    const hi = HEAT_STOPS[i], lo = HEAT_STOPS[i - 1];
    if (t <= hi.t) {
      const f = (t - lo.t) / (hi.t - lo.t);
      const r = Math.round(lo.c[0] + (hi.c[0] - lo.c[0]) * f);
      const g = Math.round(lo.c[1] + (hi.c[1] - lo.c[1]) * f);
      const b = Math.round(lo.c[2] + (hi.c[2] - lo.c[2]) * f);
      return `rgb(${r},${g},${b})`;
    }
  }
  return 'rgb(20,52,92)';
}

const heatTextColor = (t) => (t >= 0.6 ? '#ffffff' : '#14345c');

/**
 * Draws the Date x Party acquired-metal heatmap as inline SVG into
 * `<prefix>Heatmap`, with summary nodes `<prefix>HeatPeak` etc. updated
 * when present (the Metal Flow History card shows those in the page
 * summary strip instead of inside the chart, so each node is optional).
 */
export function renderFlowHeatmap(prefix, hm) {
  const el = (suffix) => document.getElementById(prefix + suffix);
  const host = el('Heatmap');
  const scroll = el('HeatScroll');
  const desc = el('HeatDesc');
  if (!host) return;

  hm = hm || { dates: [], sectors: [], cells: [], maximum_acquired: 0 };

  const put = (suffix, text) => {
    const n = el(suffix);
    if (n) n.textContent = text;
  };

  put('HeatTotal', fmt3(hm.total_acquired || 0));
  put('HeatDates', hm.date_count || 0);
  put('HeatParties', hm.party_count || 0);

  const peak = hm.peak || {};
  put('HeatPeak', fmt3(peak.acquired || 0));
  put('HeatPeakSub', peak.sector ? `${peak.sector} · ${peak.full_date_label}` : '—');

  const top = hm.most_active || {};
  put('HeatTop', top.sector || '—');
  put('HeatTopSub', top.sector ? `${fmt3(top.total)} kg · ${fmtPct(top.percent)}` : '—');

  const chip = el('HeatChip');
  if (chip) chip.textContent = `${hm.date_count || 0} date(s) × ${hm.party_count || 0} part${hm.party_count === 1 ? 'y' : 'ies'}`;
  put('HeatLegendMax', `${fmt3(hm.maximum_acquired || 0)} kg`);

  if (!hm.dates.length || !hm.sectors.length) {
    host.innerHTML =
      '<div class="empty-state"><div class="empty-state__title">No acquired metal in this range</div>' +
      '<div class="empty-state__text">Widen the date range or clear the sector filter, then apply again.</div></div>';
    if (desc) desc.textContent = 'The heatmap is empty because no Metal Flow records matched the filters.';
    return;
  }

  const nCols = hm.dates.length, nRows = hm.sectors.length;
  const padL = 148, padR = 16, padT = 48, padB = 14;
  const rowH = 30, gap = 2;
  const cellW = nCols <= 8 ? 92 : nCols <= 16 ? 74 : nCols <= 30 ? 62 : 56;

  const TEXT_LIMIT = 90;
  const showCellText = cellW >= 56 && nCols <= TEXT_LIMIT;
  const labelEvery = nCols <= 60 ? 1 : 2;

  const W = padL + nCols * cellW + padR;
  const H = padT + nRows * rowH + padB;

  const value = {};
  hm.cells.forEach((c) => { value[`${c.date_key} ${c.sector}`] = c.acquired; });
  const max = hm.maximum_acquired > 0 ? hm.maximum_acquired : 1;

  let svg =
    `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" role="img" ` +
    `shape-rendering="crispEdges" aria-label="Acquired kilograms for each Metal Flow party on each allocation date">`;

  hm.dates.forEach((d, ci) => {
    if (ci % labelEvery !== 0) return;
    const x = padL + ci * cellW + cellW / 2;
    svg += `<text class="heat-col-label" x="${x.toFixed(1)}" y="${padT - 10}" text-anchor="start" transform="rotate(-45 ${x.toFixed(1)} ${padT - 10})">${esc(d.date_label)}</text>`;
  });

  hm.sectors.forEach((sector, ri) => {
    const y = padT + ri * rowH;
    const name = sector.length > 20 ? `${sector.substring(0, 19)}…` : sector;

    svg += `<text class="heat-row-label" x="${padL - 10}" y="${y + rowH / 2 + 4}" text-anchor="end">${esc(name)}<title>${esc(sector)}</title></text>`;

    hm.dates.forEach((d, ci) => {
      let v = value[`${d.date_key} ${sector}`];
      if (v === undefined) v = 0;
      const t = max > 0 ? v / max : 0;
      const x = padL + ci * cellW;

      svg +=
        `<rect x="${x + gap / 2}" y="${y + gap / 2}" width="${cellW - gap}" height="${rowH - gap}" rx="3" ` +
        `fill="${heatColor(t)}" stroke="#ffffff" stroke-width="1"><title>Date: ${esc(d.full_date_label)}\nParty: ${esc(sector)}\nToday’s Acquired: ${fmt3(v)} kg</title></rect>`;

      if (showCellText) {
        svg += `<text class="heat-cell-text" x="${x + cellW / 2}" y="${y + rowH / 2 + 3.5}" text-anchor="middle" fill="${heatTextColor(t)}" pointer-events="none">${fmt3(v)}</text>`;
      }
    });
  });

  svg += '</svg>';
  host.innerHTML = svg;

  if (scroll) scroll.scrollLeft = scroll.scrollWidth;

  if (desc) {
    const parts = hm.sectors.map((sector) => {
      let total = 0;
      hm.dates.forEach((d) => { total += value[`${d.date_key} ${sector}`] || 0; });
      return `${sector} acquired ${fmt3(total)} kg`;
    });
    desc.textContent = `Heatmap of ${hm.date_count} allocation dates by ${hm.party_count} Metal Flow parties. ${parts.join('. ')}. Each cell shows the kilograms acquired by that party on that date, printed inside the cell and repeated in its tooltip.`;
  }

  const note = el('HeatNote');
  if (note) {
    const windowed = hm.window_days && hm.date_count >= hm.window_days;
    const text = hm.truncation_note || (windowed ? `This grid is limited to the last ${hm.window_days} days of the selected range.` : '');
    note.textContent = text;
    note.classList.toggle('hidden', !text);
  }
}
