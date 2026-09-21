/**
 * components/charts.js — hand-written SVG charts, no library.
 *
 * CLAUDE.md section 7: legacy's Reports.html contains a hand-written SVG chart
 * engine whose output classes are styled in StylesReports.html — the two are a
 * matched pair, and "replacing it with a charting library would change the
 * appearance and is out of scope". So these emit the same class names the
 * ported reports.css already styles: .chart-axis-text, .chart-bar-text,
 * .chart-point-text, .chart-value-text, .chart-grid-line, .chart-baseline.
 *
 * Values arrive as kilogram strings and are converted to integer grams for
 * scaling, so chart geometry never depends on float kilogram arithmetic.
 */

import { formatGrams, formatPlotKg, toGrams } from '../lib/format.js';

/* --------------------------- ANALYSIS DASHBOARD ---------------------------
   Geometry below is legacy's, taken from PROMPT_analysis_dashboard.md, not
   invented: fixed viewBox widths with generous left padding for the axis, and
   a top pad that leaves room for the chip row above the plot. */

const DASH_COLOURS = {
  acquired: '#10b981',
  alloted: '#1e3a5f',
  balance: '#d97706',
  required: '#1e3a5f',
  pending: '#f59e0b',
};

/** Round an axis maximum up to something readable. Ports legacy's niceMax(). */
export function niceMax(value) {
  if (value <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  const normalised = value / magnitude;
  const step = normalised <= 1 ? 1 : normalised <= 2 ? 2 : normalised <= 5 ? 5 : 10;
  return step * magnitude;
}

function escapeText(value) {
  return String(value).replace(/[<>&]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;' }[c]));
}

/**
 * Whole kilograms, thousands-separated.
 *
 * PLOTS ONLY. Every figure drawn inside a chart is rounded to the kilogram: at
 * chart scale the third decimal is a sub-pixel distinction that only crowds the
 * axis. The exact 3-decimal value is still on each element's <title> tooltip,
 * and the KPI cards and tables are unchanged — this is a display choice for the
 * plots, never a loss of precision in the data.
 */
function wholeKg(grams) {
  return Math.round(grams / 1000).toLocaleString('en-US');
}

/**
 * Totals strip drawn ABOVE the plot, so the headline figures are readable
 * without adding up the bars.
 *
 * `items` is [{label, value (grams), colour?}]; a `text` item passes a
 * pre-formatted string through for figures that are not a plain sum.
 */
function totalsStrip(items) {
  const cells = items
    .map(
      ({ label, value, colour, text }) => `
      <span class="chart-totals__item">
        ${colour ? `<span class="legend-swatch" style="background:${colour}"></span>` : ''}
        <span class="chart-totals__label">${escapeText(label)}</span>
        <span class="chart-totals__value">${
          text === undefined ? `${wholeKg(value)} kg` : escapeText(text)
        }</span>
      </span>`
    )
    .join('');
  return `<div class="chart-totals">${cells}</div>`;
}

const sumBy = (rows, pick) => rows.reduce((total, row) => total + pick(row), 0);

function svgOpen(width, height, extra = '') {
  return `<svg class="chart-svg" viewBox="0 0 ${width} ${height}" width="100%" height="${height}"
      preserveAspectRatio="xMidYMid meet" role="img"${extra}>`;
}

/** Horizontal grid lines with their value labels, plus the baseline. */
function grid(x0, x1, yFor, minG, maxG, ticks = 4) {
  let out = '';
  for (let i = 0; i <= ticks; i += 1) {
    const value = minG + ((maxG - minG) * i) / ticks;
    const y = yFor(value);
    out += `<line class="chart-grid-line" x1="${x0}" y1="${y}" x2="${x1}" y2="${y}" />`;
    out += `<text class="chart-axis-text" x="${x0 - 10}" y="${y + 4}"
        text-anchor="end">${wholeKg(value)}</text>`;
  }
  out += `<line class="chart-baseline" x1="${x0}" y1="${yFor(Math.max(0, minG))}" x2="${x1}" y2="${yFor(
    Math.max(0, minG)
  )}" />`;
  return out;
}

/**
 * Acquired vs Alloted by date — Chart A. `rows` is
 * [{label, short, a, b}] in integer grams.
 */
export function groupedBarChart(rows, names) {
  if (!rows.length) return emptyChart();

  const W = 1000;
  const H = 300;
  const padL = 60;
  const padR = 20;
  const padT = 52;
  const padB = 50;
  const plotW = W - padL - padR;
  const plotH = H - padT - padB;

  const maxG = niceMax(Math.max(1, ...rows.flatMap((r) => [r.a, r.b])));
  const yFor = (g) => padT + plotH - (g / maxG) * plotH;
  const slot = plotW / rows.length;
  const barW = Math.min(13, Math.max(4, slot / 2.8));
  // Past ten dates the labels would collide, so only every nth is drawn.
  const labelEvery = Math.ceil(rows.length / 10);

  let bars = '';
  rows.forEach((row, i) => {
    const centre = padL + slot * i + slot / 2;
    [
      [row.a, 'url(#rmasBarA)', names[0]],
      [row.b, 'url(#rmasBarB)', names[1]],
    ].forEach(([value, fill, name], j) => {
      const h = Math.max(0, (Math.max(0, value) / maxG) * plotH);
      // Named rather than inlined so the label below can be expressed as "the
      // centre of the rect I just drew". Legacy's own x expressions do NOT
      // transfer: it laid the pair out differently (x = cx - barW - 1, width
      // barW), so copying them puts every label off its bar — by 37% of the
      // bar width once barW bottoms out at 4 on a long range.
      const x = centre - barW + j * barW;
      const w = barW - 1;
      const y = padT + plotH - h;
      bars += `<rect fill="${fill}" x="${x}" y="${y}"
          width="${w}" height="${h}" rx="1.5"><title>${escapeText(row.label)} — ${escapeText(
            name
          )}: ${formatGrams(value)} kg</title></rect>`;

      // Value above each bar, rotated upright. Rotated, a label needs only the
      // bar's own width, which is what keeps every bar labelled even at 30+
      // dates — legacy's answer to crowding, and why labelEvery (which thins
      // the horizontal date ticks below) deliberately does not apply here.
      //
      // Guarded on h, not value: a zero bar is an ABSENT bar, and two "0"s a
      // pixel apart would collide on the baseline over the date tick. A tiny
      // but real bar still gets its figure.
      //
      // formatPlotKg returns only [-0-9.], so no escapeText is needed — unlike
      // every other text emit in this file.
      if (h > 0) {
        // One const each: the anchor appears three times and must not disagree.
        // Fixed to 0.1 because slot is non-terminating for most row counts.
        const lx = (x + w / 2).toFixed(1);
        const ly = (y - 5).toFixed(1);
        bars += `<text class="chart-bar-text" x="${lx}" y="${ly}"
          text-anchor="start" transform="rotate(-90 ${lx} ${ly})">${formatPlotKg(value)}</text>`;
      }
    });
    if (i % labelEvery === 0) {
      bars += `<text class="chart-axis-text" x="${centre}" y="${H - padB + 18}"
          text-anchor="middle">${escapeText(row.short)}</text>`;
    }
  });

  const defs = `<defs>
      <linearGradient id="rmasBarA" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="${DASH_COLOURS.acquired}" stop-opacity="1"/>
        <stop offset="100%" stop-color="${DASH_COLOURS.acquired}" stop-opacity=".72"/>
      </linearGradient>
      <linearGradient id="rmasBarB" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="${DASH_COLOURS.alloted}" stop-opacity="1"/>
        <stop offset="100%" stop-color="${DASH_COLOURS.alloted}" stop-opacity=".72"/>
      </linearGradient>
    </defs>`;

  // Both series summed across every plotted date. Supply and demand are
  // independent quantities, so each total stands on its own.
  const totals = totalsStrip([
    { label: `Total ${names[0]}`, value: sumBy(rows, (r) => r.a), colour: DASH_COLOURS.acquired },
    { label: `Total ${names[1]}`, value: sumBy(rows, (r) => r.b), colour: DASH_COLOURS.alloted },
  ]);

  return `${totals}${svgOpen(W, H)}${defs}${grid(padL, W - padR, yFor, 0, maxG)}${bars}</svg>
    <div class="chart-legend">
      <span class="legend-key"><span class="legend-swatch" style="background:${
        DASH_COLOURS.acquired
      }"></span>${escapeText(names[0])}</span>
      <span class="legend-key"><span class="legend-swatch" style="background:${
        DASH_COLOURS.alloted
      }"></span>${escapeText(names[1])}</span>
    </div>`;
}

/**
 * Single-series line — Charts B and C. `rows` is [{label, short, value}] in
 * integer grams. The axis drops below zero only when the data does.
 */
export function lineChart(rows, { colour = DASH_COLOURS.balance, totals = null } = {}) {
  if (!rows.length) return emptyChart();

  const W = 1000;
  const H = 260;
  const padL = 60;
  const padR = 20;
  const padT = 42;
  const padB = 50;
  const plotW = W - padL - padR;
  const plotH = H - padT - padB;

  const values = rows.map((r) => r.value);
  const maxG = niceMax(Math.max(1, ...values));
  // A balance can legitimately go negative (over-allocation is permitted), and
  // clamping the axis at zero would draw those points on the baseline.
  const minG = Math.min(...values) < 0 ? -niceMax(Math.abs(Math.min(...values))) : 0;
  const yFor = (g) => padT + plotH - ((g - minG) / (maxG - minG)) * plotH;
  const step = rows.length > 1 ? plotW / (rows.length - 1) : 0;
  const labelEvery = Math.ceil(rows.length / 10);

  const points = rows.map((row, i) => ({
    x: padL + (rows.length === 1 ? plotW / 2 : step * i),
    y: yFor(row.value),
    row,
  }));

  let marks = `<path d="${points
    .map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x},${p.y}`)
    .join(' ')}" fill="none" stroke="${colour}" stroke-width="2"
    stroke-linejoin="round" stroke-linecap="round" />`;

  points.forEach((p, i) => {
    marks += `<circle fill="${colour}" cx="${p.x}" cy="${p.y}" r="3.5"><title>${escapeText(
      p.row.label
    )}: ${formatGrams(p.row.value)} kg</title></circle>`;
    // Value above every node, so the trend reads without hovering. Emitted
    // AFTER the circle: SVG paints in document order, and the 2px stroke would
    // otherwise sit on top of the digits.
    //
    // Unguarded, unlike the bars above, and deliberately so: a zero here is a
    // real reading — the balance cleared that day — not an absent mark.
    marks += `<text class="chart-point-text" x="${p.x.toFixed(1)}" y="${(p.y - 11).toFixed(1)}"
      text-anchor="middle">${formatPlotKg(p.row.value)}</text>`;
    if (i % labelEvery === 0) {
      marks += `<text class="chart-axis-text" x="${p.x}" y="${H - padB + 18}"
          text-anchor="middle">${escapeText(p.row.short)}</text>`;
    }
  });

  const strip = totals ? totalsStrip(totals) : '';
  return `${strip}${svgOpen(W, H)}${grid(padL, W - padR, yFor, minG, maxG)}${marks}</svg>`;
}

/**
 * Requirement vs Balance by sector — Chart D. Two bars per row, `rows` is
 * [{label, required, balance}] in integer grams.
 */
export function sectorBarChart(rows) {
  if (!rows.length) return emptyChart();

  const W = 560;
  const rowH = 40;
  const padL = 132;
  const padR = 74;
  const padT = 8;
  const height = rows.length * rowH + padT * 2;
  const plotW = W - padL - padR;
  const maxG = niceMax(
    Math.max(1, ...rows.flatMap((r) => [r.required, Math.max(0, r.balance)]))
  );

  let bars = '';
  rows.forEach((row, i) => {
    const y = padT + i * rowH;
    // Sector names run long; the full name stays available on hover.
    const label = row.label.length > 20 ? `${row.label.slice(0, 19)}…` : row.label;
    bars += `<text class="chart-sector-text" x="${padL - 10}" y="${y + rowH / 2 + 4}"
        text-anchor="end">${escapeText(label)}<title>${escapeText(row.label)}</title></text>`;

    [
      [row.required, DASH_COLOURS.required, 'Required', 0],
      [Math.max(0, row.balance), DASH_COLOURS.pending, 'Balance', 1],
    ].forEach(([value, fill, name, j]) => {
      const w = (value / maxG) * plotW;
      bars += `<rect fill="${fill}" rx="2" x="${padL}" y="${y + 6 + j * 14}" width="${w}"
          height="11"><title>${escapeText(row.label)} — ${name}: ${formatGrams(
            value
          )} kg</title></rect>`;
    });

    bars += `<text class="chart-value-text" x="${W - padR + 8}" y="${
      y + rowH / 2 + 4
    }">${wholeKg(row.required)}</text>`;
  });

  // Across the sectors actually plotted, which is the top slice rather than
  // every sector — the strip says so, so the figure is not mistaken for the
  // range total on the KPI cards.
  const totals = totalsStrip([
    {
      label: `Required (top ${rows.length})`,
      value: sumBy(rows, (r) => r.required),
      colour: DASH_COLOURS.required,
    },
    {
      label: `Balance (top ${rows.length})`,
      value: sumBy(rows, (r) => Math.max(0, r.balance)),
      colour: DASH_COLOURS.pending,
    },
  ]);

  return `${totals}${svgOpen(W, height)}${bars}</svg>
    <div class="chart-legend">
      <span class="legend-key"><span class="legend-swatch" style="background:${
        DASH_COLOURS.required
      }"></span>Required</span>
      <span class="legend-key"><span class="legend-swatch" style="background:${
        DASH_COLOURS.pending
      }"></span>Balance</span>
    </div>`;
}

export function emptyChart(message = 'No saved data in this range yet.') {
  return `<div class="access-gate__text">${escapeText(message)}</div>`;
}

/* ------------------------- METAL FLOW HISTORY -------------------------
   The flow page uses its own palette: one sequential blue ramp for the
   heatmap, so shade always reads as quantity and never as a category, and a
   separate cycling palette for the share bars, where colour only separates
   adjacent rows. Both are lifted from legacy's Reports.html. */

const HEAT_STOPS = [
  { t: 0.0, c: [242, 244, 247] },
  { t: 0.15, c: [234, 241, 251] },
  { t: 0.45, c: [168, 202, 238] },
  { t: 0.75, c: [79, 139, 208] },
  { t: 1.0, c: [20, 52, 92] },
];

const FLOW_COLORS = [
  '#14345c', '#1f4e87', '#3a6fae', '#5c8fc9', '#7fadde',
  '#a8caee', '#c2d9f2', '#8a5a08', '#b4740c', '#d19b3e',
];

/**
 * Interpolate the blue ramp. Ports heatColor().
 *
 * Zero is deliberately the flat grey rather than the ramp's lightest stop:
 * "nothing was acquired" must be distinguishable at a glance from "a little
 * was acquired", which an almost-white blue would not be.
 */
export function heatColor(t) {
  if (!(t > 0)) return 'rgb(242,244,247)';
  const clamped = Math.min(1, t);
  for (let i = 1; i < HEAT_STOPS.length; i += 1) {
    const a = HEAT_STOPS[i - 1];
    const b = HEAT_STOPS[i];
    if (clamped <= b.t) {
      const span = b.t - a.t || 1;
      const k = (clamped - a.t) / span;
      const mix = a.c.map((channel, j) => Math.round(channel + (b.c[j] - channel) * k));
      return `rgb(${mix[0]},${mix[1]},${mix[2]})`;
    }
  }
  const last = HEAT_STOPS[HEAT_STOPS.length - 1].c;
  return `rgb(${last[0]},${last[1]},${last[2]})`;
}

/** Bar colour by row index, cycling. Ports flowColor(). */
export function flowColor(index) {
  return FLOW_COLORS[index % FLOW_COLORS.length];
}

/**
 * "Total Acquired by Sector" — horizontal bars. Ports sectorShareChart().
 *
 * Geometry is legacy's, not this file's shared PAD: the wide right gutter
 * exists to hold the "weight · share" label outside the plot, so a bar at
 * full width still has somewhere to put its number.
 */
export function flowShareChart(rows, grandTotalG) {
  if (!rows.length) return emptyChart('No acquired metal recorded in the selected range.');

  const W = 560;
  const rowH = 30;
  const padL = 118;
  const padR = 132;
  const padT = 8;
  const height = rows.length * rowH + padT * 2;
  const plotWidth = W - padL - padR;
  const maxG = niceMax(Math.max(1, rows[0].value));

  let bars = '';
  rows.forEach((row, i) => {
    const y = padT + i * rowH;
    const w = (Math.max(0, row.value) / maxG) * plotWidth;
    // Long party names would otherwise run under the bars.
    const label = row.label.length > 16 ? `${row.label.slice(0, 15)}…` : row.label;
    const share = grandTotalG > 0 ? (row.value / grandTotalG) * 100 : 0;

    bars += `<text class="chart-sector-text" x="${padL - 10}" y="${y + rowH / 2 + 4}" text-anchor="end">${escapeText(label)}<title>${escapeText(row.label)}</title></text>`;
    bars += `<rect fill="${flowColor(i)}" rx="3" x="${padL}" y="${y + (rowH - 14) / 2}" width="${w}" height="14"><title>${escapeText(row.label)}: ${formatGrams(row.value)} kg</title></rect>`;
    bars += `<text class="chart-value-text" x="${padL + w + 8}" y="${y + rowH / 2 + 4}">${formatGrams(row.value)} &middot; ${share.toFixed(1)}%</text>`;
  });

  return `${svgOpen(W, height)}${bars}</svg>`;
}

/** Convert an API kilogram string to grams for charting. */
export function kgToGrams(value) {
  return toGrams(value) || 0;
}
