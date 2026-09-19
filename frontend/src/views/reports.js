/**
 * views/reports.js — Allocation History and Metal Flow History. Ported
 * from Reports.html. Read-only, independent of views/allocation.js.
 */

import * as reportsApi from '../api/reports.js';
import * as authApi from '../api/auth.js';
import { esc, fmt3, fmtPct, shiftIso } from '../lib/format.js';
import { $, hideOverlay, onViewChange, showOverlay, toast } from '../components/shell.js';
import { renderFlowHeatmap, sectorShareChart } from '../components/charts.js';

const R = {
  options: null,
  loadedOnce: { allocationHistory: false, flowHistory: false },
  lastRows: { allocationHistory: [], flowHistory: [] },
  flowSeries: null,
  offset: { allocationHistory: 0, flowHistory: 0 },
  busy: false,
};

function updateFilterCount(countId, dateIds, selectIds) {
  const node = $(countId);
  if (!node) return;
  let n = 0;
  if (dateIds.some((id) => $(id) && $(id).value)) n++;
  selectIds.forEach((id) => {
    const el = $(id);
    if (el && el.value && el.value !== 'all') n++;
  });
  node.textContent = n === 0 ? 'No filters active' : `${n} filter${n === 1 ? '' : 's'} active`;
}

function fillSelect(id, items, allLabel) {
  const el = $(id);
  if (!el) return;
  let html = `<option value="all">${esc(allLabel)}</option>`;
  items.forEach((it) => {
    const label = it.sector || it.label;
    html += `<option value="${esc(label)}">${esc(label)}${it.active === false ? ' (historical)' : ''}</option>`;
  });
  el.innerHTML = html;
}

async function ensureOptions() {
  if (R.options) return;
  showOverlay('Loading filter options…');
  try {
    const o = await reportsApi.getHistoryFilterOptions();
    hideOverlay();
    populateFilters(o);
  } catch (err) {
    hideOverlay();
    toast('error', err.message || 'Filter options could not be loaded.');
    console.error(err);
  }
}

function populateFilters(o) {
  R.options = o;
  fillSelect('ahSector', o.allocation_sectors, 'All sectors');
  fillSelect('mfSector', o.flow_sectors, 'All sectors');

  ['ah', 'mf'].forEach((p) => {
    if ($(`${p}From`)) $(`${p}From`).value = o.suggested_from || '';
    if ($(`${p}To`)) $(`${p}To`).value = o.suggested_to || '';
  });

  if (o.max_date) {
    let from7 = shiftIso(o.max_date, -6);
    if (o.min_date && from7 < o.min_date) from7 = o.min_date;
    ['ah', 'mf'].forEach((p) => {
      if (!$(`${p}From`)) return;
      $(`${p}From`).value = from7;
      $(`${p}To`).value = o.max_date;
    });
  }

  if (o.allocation_record_count) {
    $('tabCountAlloc').textContent = o.allocation_record_count;
    $('tabCountAlloc').classList.remove('hidden');
  }
  if (o.flow_record_count) {
    $('tabCountFlow').textContent = o.flow_record_count;
    $('tabCountFlow').classList.remove('hidden');
  }
}

function applyQuickRange(prefix, days, btn) {
  btn.parentNode.querySelectorAll('.quick-range__btn').forEach((b) => b.classList.remove('is-active'));
  btn.classList.add('is-active');

  const o = R.options || {};
  if (Number(days) === 0) {
    $(`${prefix}From`).value = o.min_date || '';
    $(`${prefix}To`).value = o.max_date || '';
  } else {
    const to = o.max_date || '';
    if (!to) return;
    let from = shiftIso(to, -(Number(days) - 1));
    if (o.min_date && from < o.min_date) from = o.min_date;
    $(`${prefix}From`).value = from;
    $(`${prefix}To`).value = to;
  }
}

function renderPager(prefix, page, onGo) {
  const info = $(`${prefix}PageInfo`);
  const prev = $(`${prefix}Prev`);
  const next = $(`${prefix}Next`);
  if (!info || !page) return;

  if (!page.total_records) {
    info.textContent = 'No records';
    prev.disabled = true;
    next.disabled = true;
    return;
  }

  info.textContent = `Showing ${page.first_record}–${page.last_record} of ${page.total_records}  ·  Page ${page.current_page} of ${page.total_pages}`;
  prev.disabled = !page.has_previous;
  next.disabled = !page.has_next;

  prev.onclick = () => { if (page.has_previous) onGo(page.offset - page.page_size); };
  next.onclick = () => { if (page.has_next) onGo(page.offset + page.page_size); };
}

/* ---------------------- Allocation History ---------------------- */

function allocationFilters() {
  updateFilterCount('ahFilterCount', ['ahFrom', 'ahTo'], ['ahSector', 'ahStatus']);
  const sector = $('ahSector').value;
  return {
    from_date: $('ahFrom').value || null,
    to_date: $('ahTo').value || null,
    sectors: sector === 'all' ? null : [sector],
    status: $('ahStatus').value,
    offset: R.offset.allocationHistory,
  };
}

export async function loadAllocationHistory() {
  if (R.busy) return;
  R.busy = true;
  showOverlay('Loading allocation history…');
  try {
    const data = await reportsApi.getAllocationHistory(allocationFilters());
    R.busy = false;
    hideOverlay();
    R.loadedOnce.allocationHistory = true;
    R.lastRows.allocationHistory = data.rows;
    renderAllocationHistory(data);
  } catch (err) {
    R.busy = false;
    hideOverlay();
    toast('error', err.message || 'The history could not be loaded. Check the connection and retry.');
    console.error(err);
  }
}

function renderAllocationHistory(data) {
  const s = data.summary;
  $('ahStatRecords').textContent = s.record_count;
  $('ahStatDates').textContent = `${s.date_count} dates · ${s.sector_count} sectors`;
  $('ahStatPrev').textContent = fmt3(s.total_previous_requirement);
  $('ahStatRequired').textContent = fmt3(s.total_today_required);
  $('ahStatAlloted').textContent = fmt3(s.total_alloted);
  $('ahStatFulfil').textContent = fmtPct(s.fulfilment_rate || 0);
  const ahPeak = s.peak_balance || {};
  $('ahStatPeak').textContent = `Trajectory peak: ${fmt3(ahPeak.value || 0)} kg${ahPeak.date_display ? ` on ${ahPeak.date_display}` : ''}`;
  $('ahStatBalance').textContent = fmt3(s.total_balance);
  $('ahRowChip').textContent = `${s.record_count} rows`;
  renderPager('ah', data.page, (offset) => { R.offset.allocationHistory = offset; loadAllocationHistory(); });

  const html = data.rows.map((r) => {
    const pending = r.balance > 0;
    return `<tr>
      <td class="date-cell" data-label="Date">${esc(r.date_display)}</td>
      <td data-label="Sector">${esc(r.sector)}</td>
      <td data-label="Purity">${esc(r.purity)}</td>
      <td class="num" data-label="Prev. Requirement">${fmt3(r.previous_requirement)}</td>
      <td class="num" data-label="Today’s Required">${fmt3(r.today_required)}</td>
      <td class="num" data-label="Alloted">${fmt3(r.alloted)}</td>
      <td class="num" data-label="Balance">${fmt3(r.balance)}</td>
      <td data-label="Status"><span class="${pending ? 'pill-pending' : 'pill-cleared'}">${pending ? 'Pending' : 'Cleared'}</span></td>
    </tr>`;
  }).join('');

  $('ahBody').innerHTML = html;
  $('ahEmpty').classList.toggle('hidden', data.rows.length > 0);
  $('ahTable').classList.toggle('hidden', data.rows.length === 0);

  const trunc = $('ahTruncated');
  if (s.truncated) {
    trunc.textContent = `Showing the first ${s.returned_count} of ${s.record_count} matching records. Narrow the date range or filters to see the rest.`;
    trunc.classList.remove('hidden');
  } else {
    trunc.classList.add('hidden');
  }
}

/* ---------------------- Metal Flow History ---------------------- */

function flowFilters() {
  updateFilterCount('mfFilterCount', ['mfFrom', 'mfTo'], ['mfSector']);
  const sector = $('mfSector').value;
  return {
    from_date: $('mfFrom').value || null,
    to_date: $('mfTo').value || null,
    sectors: sector === 'all' ? null : [sector],
    status: 'all',
    offset: R.offset.flowHistory,
  };
}

export async function loadFlowHistory() {
  if (R.busy) return;
  R.busy = true;
  showOverlay('Loading Metal Flow history…');
  try {
    const data = await reportsApi.getMetalFlowHistory(flowFilters());
    R.busy = false;
    hideOverlay();
    R.loadedOnce.flowHistory = true;
    R.lastRows.flowHistory = data.rows;
    R.flowSeries = data.series || null;
    renderFlowHistory(data);
  } catch (err) {
    R.busy = false;
    hideOverlay();
    toast('error', err.message || 'The Metal Flow history could not be loaded. Check the connection and retry.');
    console.error(err);
  }
}

function renderCycleDeltaLocal(node, cycle) {
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

function renderFlowHistory(data) {
  const s = data.summary;
  const series = data.series || { dates: [], displays: [], sectors: [], grand_total: 0 };

  $('mfStatRecords').textContent = s.record_count;
  $('mfStatDates').textContent = `${s.date_count} dates`;
  $('mfStatTotal').textContent = fmt3(s.total_acquired);
  renderCycleDeltaLocal($('mfStatTotalSub'), s.cycle || {});
  $('mfStatAvg').textContent = fmt3(s.average_per_day);
  $('mfStatSectors').textContent = s.sector_count;
  const hm0 = data.heatmap || {};
  const pk = hm0.peak || {}, tp = hm0.most_active || {};
  $('mfHeatPeak').textContent = fmt3(pk.acquired || 0);
  $('mfHeatPeakSub').textContent = pk.sector ? `${pk.sector} · ${pk.full_date_label}` : '—';
  $('mfHeatTop').textContent = tp.sector || '—';
  $('mfHeatTopSub').textContent = tp.sector ? `${fmt3(tp.total)} kg · ${fmtPct(tp.percent)}` : '—';
  $('mfRowChip').textContent = `${s.record_count} records`;
  $('mfShareChip').textContent = `${fmt3(series.grand_total)} kg total`;

  renderFlowHeatmap('mf', data.heatmap);
  sectorShareChart($('mfShareChart'), series);
}

/* ---------------------------- CSV export ------------------------ */

function csvCell(v) {
  const s = String(v === null || v === undefined ? '' : v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

function buildCsv(headers, rows) {
  const lines = [headers.map(csvCell).join(',')];
  rows.forEach((r) => lines.push(r.map(csvCell).join(',')));
  return lines.join('\n');
}

function offerCsv(filename, csv) {
  if (!csv) {
    toast('warn', 'There is nothing to export.');
    return;
  }
  $('exportText').value = csv;
  $('exportBody').textContent = 'Copy the CSV below and paste it into a spreadsheet or text file.';
  $('exportModal').classList.remove('hidden');
}

function exportAllocationHistory() {
  const rows = R.lastRows.allocationHistory || [];
  if (!rows.length) {
    toast('warn', 'Load some history before exporting.');
    return;
  }
  const csv = buildCsv(
    ['Date', 'Sector', 'Purity', 'Previous Requirement', "Today's Required Weight", 'Alloted', 'Balance'],
    rows.map((r) => [r.date_display, r.sector, r.purity, fmt3(r.previous_requirement), fmt3(r.today_required), fmt3(r.alloted), fmt3(r.balance)]),
  );
  offerCsv('allocation-history.csv', csv);
}

function exportFlowHistory() {
  const series = R.flowSeries;
  if (!series || !series.dates.length || !series.sectors.length) {
    toast('warn', 'Load some history before exporting.');
    return;
  }
  const names = series.sectors.map((x) => x.sector);
  const body = series.dates.map((dk, i) => [series.displays[i]].concat(series.sectors.map((x) => fmt3(x.values[i]))));
  body.push([]);
  body.push(['Total (kg)'].concat(series.sectors.map((x) => fmt3(x.total))));
  body.push(['Share (%)'].concat(series.sectors.map((x) => fmtPct(x.percent))));
  offerCsv('metal-flow-history.csv', buildCsv(['Date'].concat(names), body));
}

/* ------------------------------ events -------------------------- */

function resetFilters(prefix, then) {
  const o = R.options || {};
  let from7 = o.max_date ? shiftIso(o.max_date, -6) : o.suggested_from || '';
  if (o.min_date && from7 && from7 < o.min_date) from7 = o.min_date;
  if ($(`${prefix}From`)) $(`${prefix}From`).value = from7;
  if ($(`${prefix}To`)) $(`${prefix}To`).value = o.max_date || o.suggested_to || '';
  ['Sector', 'Status'].forEach((f) => {
    const el = $(prefix + f);
    if (el) el.value = 'all';
  });
  const group = $(`${prefix}QuickRange`);
  if (group) {
    group.querySelectorAll('.quick-range__btn').forEach((b) => b.classList.toggle('is-active', b.getAttribute('data-days') === '7'));
  }
  then();
}

export function bind() {
  $('ahApply').addEventListener('click', () => { R.offset.allocationHistory = 0; loadAllocationHistory(); });
  $('ahReset').addEventListener('click', () => { R.offset.allocationHistory = 0; resetFilters('ah', loadAllocationHistory); });

  $('mfApply').addEventListener('click', () => { R.offset.flowHistory = 0; loadFlowHistory(); });
  $('mfReset').addEventListener('click', () => { R.offset.flowHistory = 0; resetFilters('mf', loadFlowHistory); });

  [['ahQuickRange', 'ah', loadAllocationHistory], ['mfQuickRange', 'mf', loadFlowHistory]].forEach(([groupId, prefix, reload]) => {
    $(groupId).addEventListener('click', (e) => {
      const btn = e.target.closest ? e.target.closest('.quick-range__btn') : null;
      if (!btn) return;
      applyQuickRange(prefix, btn.getAttribute('data-days'), btn);
      if (prefix === 'ah') R.offset.allocationHistory = 0;
      if (prefix === 'mf') R.offset.flowHistory = 0;
      reload();
    });
  });

  $('exportClose').addEventListener('click', () => $('exportModal').classList.add('hidden'));
  $('exportModal').addEventListener('click', (e) => { if (e.target === $('exportModal')) $('exportModal').classList.add('hidden'); });
  $('exportCopy').addEventListener('click', () => {
    const ta = $('exportText');
    ta.select();
    ta.setSelectionRange(0, ta.value.length);
    let done = false;
    try { done = document.execCommand('copy'); } catch (e) { done = false; }
    if (!done && navigator.clipboard) {
      navigator.clipboard.writeText(ta.value).then(
        () => toast('success', 'CSV copied to the clipboard.'),
        () => toast('warn', 'Select the text and copy it manually.'),
      );
    } else {
      toast(done ? 'success' : 'warn', done ? 'CSV copied to the clipboard.' : 'Select the text and copy it manually.');
    }
  });

  onViewChange(async (view) => {
    if (view !== 'allocationHistory' && view !== 'flowHistory') return;
    await ensureOptions();
    if (view === 'allocationHistory' && !R.loadedOnce.allocationHistory) loadAllocationHistory();
    else if (view === 'flowHistory' && !R.loadedOnce.flowHistory) loadFlowHistory();
  });

  // Operators own a single Metal Flow sector, so a whole history tab for it
  // is more navigation than it is worth — their acquired trend is shown as
  // a line chart on the dashboard instead (views/dashboard.js), and this
  // tab is hidden. Legacy: Reports.html's applyRoleToTabs().
  authApi.getCurrentUserAccess().then((access) => {
    const tab = document.querySelector('.nav-tab[data-view="flowHistory"]');
    if (tab) tab.classList.toggle('hidden', !access.is_admin);
  }).catch(() => {});
}

export { exportAllocationHistory, exportFlowHistory };
