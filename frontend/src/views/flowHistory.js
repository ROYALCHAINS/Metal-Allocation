/**
 * views/flowHistory.js — Metal Flow History.
 *
 * Metal Flow tracks SUPPLY — metal acquired — as against Allocation History,
 * which tracks demand. The two sets are different and are never merged: Metal
 * Flow is keyed by PARTY — the party metal arrives for — while the allocation
 * side is keyed by order type. One party supplies many allocation sectors, so
 * the column is labelled Party on every screen.
 *
 * Deliberately chart-only: no data table and no pager (page spec, rule 9).
 * Everything drawn comes from the server's analysis of EVERY matched record,
 * so the charts can never reflect just one page of rows.
 *
 * The Acquired Status filter and the Search box were removed from this page in
 * legacy and must not be reintroduced (rule 8) — the backend still accepts both
 * parameters, but nothing here surfaces them.
 *
 * Read-only. It never writes.
 */

import { getFlowAnalysis } from '../api/reports.js';
import { getSectors } from '../api/sectors.js';
import { escapeHtml } from '../components/appHeader.js';
import {
  emptyChart,
  flowShareChart,
  heatColor,
  invalidateThemeCache,
} from '../components/charts.js';
import { bindFilterBar, renderFilterBar } from '../components/filterBar.js';
import { fmt3, toGrams } from '../lib/format.js';

// Heatmap geometry. The row label gutter is fixed so every row lines up
// regardless of name length. Sized to the enlarged type in app.css — the cell
// must hold "00.000" at 11.5px monospace without touching its edges, so the
// two must be changed together.
const CELL_W = 64;
const CELL_H = 32;
// Gutter between columns. The rect is inset by this on each side, so a wider
// gutter reads as space BETWEEN dates rather than as a thinner cell.
const CELL_GAP = 4;
const LABEL_W = 156;
const HEAD_H = 26;

/**
 * Cell text flips once the fill is strong enough to swallow ink.
 *
 * The 0.55 threshold is unchanged from the light-only version and does not
 * need a dark counterpart: the ramp itself inverts between themes, so the
 * ink meaning inverts along with it. Both branches are tokens now — this
 * used to mix a literal with a var(), which would have themed inconsistently.
 */
const cellInk = (t) => (t > 0.55 ? 'var(--heat-ink-hi)' : 'var(--heat-ink-lo)');

export function renderFlowHistoryView(container) {
  container.innerHTML = `
    ${renderFilterBar({
      prefix: 'mf',
      sectorLabel: 'Party',
    })}

    <div class="summary-strip tile-grid">
      <div class="summary-stat tile summary-stat--navy">
        <span class="summary-stat__label">Records</span>
        <span class="summary-stat__value" id="mfStatRecords">0</span>
        <span class="summary-stat__sub" id="mfStatDates">0 dates</span>
      </div>
      <div class="summary-stat tile summary-stat--green">
        <div class="stat-head">
          <span class="summary-stat__label">Total Acquired</span>
          <span class="stat-dot stat-dot--emerald" aria-hidden="true"></span>
        </div>
        <span class="summary-stat__value" id="mfStatTotal">0.000</span>
        <span class="summary-stat__sub" id="mfStatTotalSub">kg acquired in range</span>
      </div>
      <div class="summary-stat tile summary-stat--indigo">
        <span class="summary-stat__label">Highest Single Day</span>
        <span class="summary-stat__value" id="mfHeatPeak">0.000</span>
        <span class="summary-stat__sub" id="mfHeatPeakSub">&mdash;</span>
      </div>
      <div class="summary-stat tile summary-stat--navy">
        <span class="summary-stat__label">Most Active Party</span>
        <span class="summary-stat__value summary-stat__value--text" id="mfHeatTop">&mdash;</span>
        <span class="summary-stat__sub" id="mfHeatTopSub">&mdash;</span>
      </div>
      <div class="summary-stat tile summary-stat--emerald">
        <span class="summary-stat__label">Average per Day</span>
        <span class="summary-stat__value" id="mfStatAvg">0.000</span>
        <span class="stat-unit">kg</span>
      </div>
      <div class="summary-stat tile summary-stat--rose">
        <span class="summary-stat__label">Parties Covered</span>
        <span class="summary-stat__value" id="mfStatSectors">0</span>
        <span class="summary-stat__sub" id="mfStatSectorsSub">of 0</span>
      </div>
    </div>

    <div class="chart-grid">
      <div class="chart-card chart-card--full">
        <div class="chart-card__head">
          <h3 class="chart-card__title">Daily Acquired Metal by Party</h3>
          <span class="chip" id="mfHeatChip">&mdash;</span>
        </div>
        <p class="chart-card__subtitle">
          Daily acquired kilograms by Metal Flow party, for the last 31 days of the
          selected range. Darker cells indicate higher acquisition.
        </p>
        <div class="chart-card__body">
          <div class="heat-scroll" id="mfHeatScroll" tabindex="0"
               aria-describedby="mfHeatDesc"></div>
          <p class="visually-hidden" id="mfHeatDesc">
            Grid of Metal Flow parties by date. Each cell is the kilograms acquired by
            one party on one date; the exact figure is on every cell.
          </p>
        </div>
        <div class="chart-legend heat-legend" id="mfHeatLegend">
          <span class="heat-legend__caption">Acquired (kg)</span>
          <span class="heat-legend__scale" aria-hidden="true"></span>
          <span class="heat-legend__ticks">
            <span>0 kg</span><span>Low</span><span>Medium</span>
            <span id="mfHeatLegendMax">0.000</span>
          </span>
        </div>
        <div class="heat-note hidden" id="mfHeatNote"></div>
      </div>

      <div class="chart-card">
        <div class="chart-card__head">
          <h3 class="chart-card__title">Total Acquired by Party</h3>
          <span class="chip" id="mfShareChip">0.000 kg total</span>
          <span class="chip" id="mfRowChip">0 records</span>
        </div>
        <div class="chart-card__body" id="mfShareChart"></div>
      </div>
    </div>
  `;

  const $ = (id) => container.querySelector(`#${id}`);
  const bar = bindFilterBar(container, 'mf', () => load());

  /**
   * The Date × Party grid as inline SVG.
   *
   * SVG rather than a table because reports.css styles `.heat-row-label` and
   * `.heat-col-label` with `fill:`, which only applies to SVG text — the
   * stylesheet is the visual contract and it was written for this shape.
   */
  function renderHeatmap(heatmap) {
    const { dates, sectors, cells } = heatmap;
    if (!dates.length || !sectors.length) {
      $('mfHeatScroll').innerHTML = emptyChart(
        'No acquired metal recorded in the selected range.'
      );
      $('mfHeatChip').textContent = '—';
      $('mfHeatNote').classList.add('hidden');
      return;
    }

    const maxG = toGrams(heatmap.max_acquired_kg) || 0;
    // Index once; the grid is read sectors × dates times.
    const byKey = new Map();
    cells.forEach((c) => byKey.set(`${c.date_key}|${c.flow_sector_id}`, c.acquired_kg));

    const width = LABEL_W + dates.length * CELL_W;
    const height = HEAD_H + sectors.length * CELL_H;

    let svg = `<svg class="chart-svg" viewBox="0 0 ${width} ${height}" width="${width}"
        height="${height}" role="img" aria-label="Acquired metal by party and date">`;

    dates.forEach((d, i) => {
      svg += `<text class="heat-col-label" x="${LABEL_W + i * CELL_W + CELL_W / 2}"
          y="${HEAD_H - 7}" text-anchor="middle">${escapeHtml(d.short_label)}<title>${escapeHtml(
            d.full_label
          )}</title></text>`;
    });

    sectors.forEach((s, r) => {
      const y = HEAD_H + r * CELL_H;
      svg += `<text class="heat-row-label" x="${LABEL_W - 10}" y="${y + CELL_H / 2 + 4}"
          text-anchor="end">${escapeHtml(s.sector_name)}<title>${escapeHtml(
            s.sector_name
          )}</title></text>`;

      dates.forEach((d, i) => {
        const kg = byKey.get(`${d.date_key}|${s.flow_sector_id}`) || '0.000';
        const grams = toGrams(kg) || 0;
        const t = maxG > 0 ? grams / maxG : 0;
        const x = LABEL_W + i * CELL_W;
        svg += `<rect x="${x + CELL_GAP / 2}" y="${y + 2}" width="${CELL_W - CELL_GAP}" height="${CELL_H - 4}"
            rx="3" fill="${heatColor(t)}"><title>${escapeHtml(s.sector_name)} — ${escapeHtml(
              d.full_label
            )}: ${fmt3(kg)} kg</title></rect>`;
        if (grams > 0) {
          svg += `<text class="heat-cell-text" x="${x + CELL_W / 2}" y="${y + CELL_H / 2 + 3}"
              text-anchor="middle" fill="${cellInk(t)}">${fmt3(kg)}</text>`;
        }
      });
    });

    $('mfHeatScroll').innerHTML = `${svg}</svg>`;
    $('mfHeatChip').textContent = `${sectors.length} parties × ${dates.length} days`;
    $('mfHeatLegendMax').textContent = fmt3(heatmap.max_acquired_kg);

    // The heatmap carries its own truncation flag, separate from the summary's.
    $('mfHeatNote').classList.toggle('hidden', !heatmap.truncated);
    if (heatmap.truncated) $('mfHeatNote').textContent = heatmap.truncation_note || '';
  }

  /** "↗ +N.N% vs prev N day(s)", or the plain caption when undefined. */
  function cycleSub(cycle) {
    if (cycle.change_percent === null) return 'kg acquired in range';
    const up = cycle.change_percent >= 0;
    return `<span class="summary-stat__sub--${up ? 'up' : 'down'}">${up ? '↗' : '↘'} ${
      up ? '+' : ''
    }${cycle.change_percent}%</span> vs prev ${cycle.day_count} day(s)`;
  }

  async function load() {
    $('mfHeatChip').textContent = 'Loading…';
    try {
      const data = await getFlowAnalysis({
        date_from: bar.$('From').value,
        date_to: bar.$('To').value,
        sector_id: bar.$('Sector').value,
      });
      const s = data.summary;
      const h = data.heatmap;

      $('mfStatRecords').textContent = s.record_count;
      $('mfStatDates').textContent = `${s.date_count} date${s.date_count === 1 ? '' : 's'}`;
      $('mfStatTotal').textContent = fmt3(s.total_acquired_kg);
      $('mfStatTotalSub').innerHTML = cycleSub(s.cycle);

      // The largest single CELL — one party on one date — not the largest day
      // total. The day total is returned as busiest_day_kg and not shown.
      $('mfHeatPeak').textContent = fmt3(h.peak.acquired_kg);
      $('mfHeatPeakSub').textContent = h.peak.sector_name
        ? `${h.peak.sector_name} · ${h.peak.full_date_label}`
        : '—';

      $('mfHeatTop').textContent = h.most_active.sector_name || '—';
      $('mfHeatTopSub').textContent = h.most_active.sector_name
        ? `${fmt3(h.most_active.total_kg)} kg · ${h.most_active.percent.toFixed(1)}%`
        : '—';

      $('mfStatAvg').textContent = fmt3(s.average_per_day_kg);
      $('mfStatSectors').textContent = s.sector_count;
      $('mfStatSectorsSub').textContent = `of ${s.total_sector_count}`;

      renderHeatmap(h);

      const grandTotalG = toGrams(s.total_acquired_kg) || 0;
      $('mfShareChip').textContent = `${fmt3(s.total_acquired_kg)} kg total`;
      $('mfRowChip').textContent = `${s.record_count} record${
        s.record_count === 1 ? '' : 's'
      }`;
      $('mfShareChart').innerHTML = flowShareChart(
        h.sectors.map((x) => ({ label: x.sector_name, value: toGrams(x.total_kg) || 0 })),
        grandTotalG
      );

      bar.updateFilterCount();
    } catch (err) {
      $('mfHeatChip').textContent = 'Error';
      $('mfHeatScroll').innerHTML =
        `<div class="banner banner--error"><span>${escapeHtml(err.message)}</span></div>`;
    }
  }

  /** The select lists only the parties the server's scope allows. */
  async function loadSectors() {
    try {
      const data = await getSectors();
      const select = bar.$('Sector');
      data.flow_sectors.forEach((s) => {
        const option = document.createElement('option');
        option.value = s.flow_sector_id;
        option.textContent = s.sector_name;
        select.appendChild(option);
      });
    } catch {
      // A failed dropdown must not stop the analysis loading.
    }
  }

  // The heatmap bakes resolved colours into SVG attributes at draw time, so
  // unlike the var()-driven charts it has to be redrawn when the theme flips.
  window.addEventListener('rmas:themechange', () => {
    invalidateThemeCache();
    load();
  });

  loadSectors();
  load();
}
