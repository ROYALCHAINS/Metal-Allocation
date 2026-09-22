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

/**
 * Series colours, as CSS custom properties rather than literals.
 *
 * SVG presentation attributes are parsed as CSS declarations, so `fill`,
 * `stop-color` and inline `style` all resolve var() live — which means these
 * re-theme with no redraw at all. It also reaches the inline legend swatches,
 * which no stylesheet rule could have overridden without !important.
 *
 * The light values in theme.css are the literals that used to live here,
 * unchanged, so light output is pixel-identical.
 */
const DASH_COLOURS = {
  acquired: 'var(--chart-acquired)',
  alloted: 'var(--chart-alloted)',
  balance: 'var(--chart-balance)',
  required: 'var(--chart-required)',
  pending: 'var(--chart-pending)',
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

  // The fade is a variable too: .72 is tuned to fade into a WHITE card, and
  // on a dark one the bar bases would look cut off rather than softened.
  const defs = `<defs>
      <linearGradient id="rmasBarA" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="${DASH_COLOURS.acquired}" stop-opacity="1"/>
        <stop offset="100%" stop-color="${DASH_COLOURS.acquired}" stop-opacity="var(--chart-bar-fade)"/>
      </linearGradient>
      <linearGradient id="rmasBarB" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="${DASH_COLOURS.alloted}" stop-opacity="1"/>
        <stop offset="100%" stop-color="${DASH_COLOURS.alloted}" stop-opacity="var(--chart-bar-fade)"/>
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

  // Area fill under the line, fading toward the baseline. The gradient id has
  // to be unique per chart: three line charts can share one page, and a
  // duplicate id would make every one of them use the first chart's colour.
  const fillId = `rmasArea${(lineChart.seq = (lineChart.seq || 0) + 1)}`;
  const baselineY = padT + plotH;
  const area =
    `<defs><linearGradient id="${fillId}" x1="0" y1="0" x2="0" y2="1">` +
    `<stop offset="0%" stop-color="${colour}" stop-opacity=".28"/>` +
    `<stop offset="100%" stop-color="${colour}" stop-opacity="0"/>` +
    `</linearGradient></defs>` +
    `<path d="M${points[0].x},${baselineY} ` +
    `${points.map((p) => `L${p.x},${p.y}`).join(' ')} ` +
    `L${points[points.length - 1].x},${baselineY} Z" fill="url(#${fillId})" />`;

  let marks = `${area}<path d="${points
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

/**
 * The heatmap ramp positions. The COLOURS are not here — they live in
 * theme.css as --heat-0 … --heat-4, which is also where reports.css's
 * .heat-legend__scale gradient reads them from.
 *
 * That single-sourcing is the point. The legend used to be a hardcoded
 * four-stop gradient duplicating these values in a second language, so the
 * two could silently drift apart; now the legend cannot disagree with the
 * cells it describes.
 *
 * --heat-0 stays off the ramp deliberately: "nothing was acquired" must be
 * distinguishable at a glance from "a little was acquired". On light it is a
 * flat grey; on dark it is the card surface itself, so an empty cell recedes
 * and the first real step lifts off it.
 */
const HEAT_POSITIONS = [0.0, 0.15, 0.45, 0.75, 1.0];

/* Cycling palette for the share bars, where colour only separates adjacent
   rows. Two sets, because half the light palette is too dark to see on a
   dark card — and being index-cycled, WHICH rows vanished would depend on
   the row count. The rule for editing either: every entry must clear roughly
   4.5:1 against the card surface it sits on. */
const FLOW_COLORS = [
  '#14345c', '#1f4e87', '#3a6fae', '#5c8fc9', '#7fadde',
  '#a8caee', '#c2d9f2', '#8a5a08', '#b4740c', '#d19b3e',
];

const FLOW_COLORS_DARK = [
  '#7fadde', '#a8caee', '#5c8fc9', '#cfe0f5', '#3a6fae',
  '#e3edf9', '#93b8e4', '#d19b3e', '#e0b968', '#b4740c',
];

/**
 * Resolved ramp colours, cached.
 *
 * A heatmap is ~30 columns wide by however many parties, so calling
 * getComputedStyle per cell is not an option. The cache is invalidated by
 * the theme-change event rather than by a timer.
 */
let heatCache = null;

function heatStops() {
  if (heatCache) return heatCache;
  const styles = getComputedStyle(document.documentElement);
  heatCache = HEAT_POSITIONS.map((t, i) => ({
    t,
    c: parseColor(styles.getPropertyValue(`--heat-${i}`).trim()),
  }));
  return heatCache;
}

/** Accepts the two forms the tokens can take: #rrggbb or rgb(r,g,b). */
function parseColor(text) {
  if (text.startsWith('#')) {
    const hex = text.length === 4
      ? text.slice(1).split('').map((c) => c + c).join('')
      : text.slice(1);
    return [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16));
  }
  const parts = text.match(/\d+/g);
  return parts ? parts.slice(0, 3).map(Number) : [0, 0, 0];
}

/** Drop the cached ramp so the next draw re-reads the tokens. */
export function invalidateThemeCache() {
  heatCache = null;
}

function isDark() {
  return document.documentElement.getAttribute('data-theme') === 'dark';
}

/**
 * Interpolate the ramp. Ports heatColor().
 *
 * The ramp runs light-to-dark on a light page and dark-to-light on a dark
 * one — the invariant being that more metal always reads as more salience
 * against the ground, never less.
 */
export function heatColor(t) {
  const stops = heatStops();
  if (!(t > 0)) {
    const zero = stops[0].c;
    return `rgb(${zero[0]},${zero[1]},${zero[2]})`;
  }
  const clamped = Math.min(1, t);
  for (let i = 1; i < stops.length; i += 1) {
    const a = stops[i - 1];
    const b = stops[i];
    if (clamped <= b.t) {
      const span = b.t - a.t || 1;
      const k = (clamped - a.t) / span;
      const mix = a.c.map((channel, j) => Math.round(channel + (b.c[j] - channel) * k));
      return `rgb(${mix[0]},${mix[1]},${mix[2]})`;
    }
  }
  const last = stops[stops.length - 1].c;
  return `rgb(${last[0]},${last[1]},${last[2]})`;
}

/** Bar colour by row index, cycling. Ports flowColor(). */
export function flowColor(index) {
  const palette = isDark() ? FLOW_COLORS_DARK : FLOW_COLORS;
  return palette[index % palette.length];
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

/**
 * How many days of history any date-axis plot will draw.
 *
 * A long filter range is useful for the KPI cards — "total acquired over two
 * months" is a real question — but it is not useful for a bar chart, where
 * sixty bars in a card this wide stop being readable. Capping the PLOT and
 * leaving the cards alone keeps both answers honest, so the totals still cover
 * everything the filter selected while the chart shows the recent shape.
 *
 * Matches the Metal Flow heatmap's server-side window, so every date axis in
 * the application shows the same span.
 */
export const MAX_PLOT_DAYS = 31;

/**
 * The most recent `days` CALENDAR days of a date-ordered series.
 *
 * A calendar window, not the last N points: "the latest 31 days" should mean
 * the same stretch of time whether or not the business saved on every one of
 * them. On a six-day working week this yields about 26 bars, and a gap in the
 * ledger narrows the chart rather than silently reaching further back.
 *
 * The window ends at the NEWEST DATE IN THE DATA, never at today — a range
 * whose records stop a month ago still draws a full chart instead of an empty
 * one. That is the same rule the flow heatmap uses server-side.
 *
 * ISO dates compare correctly as strings, so no parsing is needed for the
 * filter itself; only the cutoff is computed as a date.
 */
export function limitToRecentDays(rows, days = MAX_PLOT_DAYS) {
  if (rows.length <= 1) return rows;

  const newest = rows.reduce(
    (max, row) => (row.allocation_date > max ? row.allocation_date : max),
    rows[0].allocation_date
  );

  const cutoffDate = new Date(`${newest}T00:00:00Z`);
  cutoffDate.setUTCDate(cutoffDate.getUTCDate() - (days - 1));
  const cutoff = cutoffDate.toISOString().slice(0, 10);

  return rows.filter((row) => row.allocation_date >= cutoff);
}
