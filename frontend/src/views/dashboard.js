/**
 * views/dashboard.js — Analysis Dashboard. Ported from Reports.html.
 * Read-only, independent of views/allocation.js.
 */

import * as reportsApi from '../api/reports.js';
import * as authApi from '../api/auth.js';
import { esc, fmt3, fmtPct, shiftIso, shortDate } from '../lib/format.js';
import { $, hideOverlay, onViewChange, showOverlay, toast } from '../components/shell.js';
import { groupedBarChart, lineChart, renderCycleDelta, sectorBarChart } from '../components/charts.js';

const D = { options: null, loadedOnce: false, busy: false, isAdmin: null };

async function ensureOptions() {
  if (D.options) return;
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
  D.options = o;
  const el = $('dbSector');
  if (el) {
    let html = '<option value="all">All sectors</option>';
    o.allocation_sectors.forEach((it) => {
      html += `<option value="${esc(it.sector)}">${esc(it.sector)}${it.active === false ? ' (historical)' : ''}</option>`;
    });
    el.innerHTML = html;
  }
  if ($('dbFrom')) $('dbFrom').value = o.suggested_from || '';
  if ($('dbTo')) $('dbTo').value = o.suggested_to || '';
  if (o.max_date) {
    let from7 = shiftIso(o.max_date, -6);
    if (o.min_date && from7 < o.min_date) from7 = o.min_date;
    if ($('dbFrom')) {
      $('dbFrom').value = from7;
      $('dbTo').value = o.max_date;
    }
  }
}

function updateFilterCount() {
  const node = $('dbFilterCount');
  if (!node) return;
  let n = 0;
  if ($('dbFrom').value || $('dbTo').value) n++;
  if ($('dbSector').value && $('dbSector').value !== 'all') n++;
  node.textContent = n === 0 ? 'No filters active' : `${n} filter${n === 1 ? '' : 's'} active`;
}

function dashboardFilters() {
  updateFilterCount();
  const sector = $('dbSector').value;
  return { from_date: $('dbFrom').value || null, to_date: $('dbTo').value || null, sectors: sector === 'all' ? null : [sector] };
}

export async function loadDashboard() {
  if (D.busy) return;
  D.busy = true;
  showOverlay('Preparing the analysis…');
  try {
    const data = await reportsApi.getDashboardSummary(dashboardFilters());
    D.busy = false;
    hideOverlay();
    D.loadedOnce = true;
    renderDashboard(data);
  } catch (err) {
    D.busy = false;
    hideOverlay();
    toast('error', err.message || 'The dashboard could not be loaded. Check the connection and retry.');
    console.error(err);
  }
}

function renderDashboard(data) {
  const k = data.kpis;

  $('dbStatDays').textContent = k.day_count;
  $('dbStatLatest').textContent = k.latest_date_display || 'no data';
  $('dbStatAcquired').textContent = fmt3(k.total_acquired);
  $('dbStatAlloted').textContent = fmt3(k.total_alloted);
  $('dbStatFulfil').textContent = fmtPct(k.fulfilment_rate || 0);

  renderCycleDelta($('dbStatAcquiredDelta'), { change_percent: k.acquired_change_percent, day_count: k.cycle_day_count });

  $('dbStatClosing').textContent = fmt3(k.latest_closing_balance);
  $('dbStatPeak').textContent = `Trajectory peak: ${fmt3(k.peak_closing_balance)} kg${k.peak_closing_date ? ` on ${k.peak_closing_date}` : ''}`;
  $('dbStatUtilisation').textContent = fmtPct(k.utilisation);
  $('dbStatAvg').textContent = fmt3(k.average_daily_acquired);

  $('dbChart1Chip').textContent = `${k.day_count} day(s)`;
  $('dbChart2Chip').textContent = k.latest_date_display ? `Latest ${fmt3(k.latest_closing_balance)} kg` : '—';

  groupedBarChart($('dbChartAcquiredAlloted'), data.by_date.map((d) => ({ label: d.date_display, short: shortDate(d.date_key), a: d.acquired, b: d.alloted })));
  lineChart($('dbChartBalance'), data.by_date.map((d) => ({ label: d.date_display, short: shortDate(d.date_key), value: d.balance })), '#d97706');
  sectorBarChart($('dbChartSector'), data.by_sector);

  const flowCard = $('dbFlowTrendCard');
  if (flowCard) {
    const showFlowTrend = D.isAdmin === false;
    flowCard.classList.toggle('hidden', !showFlowTrend);
    if (showFlowTrend) {
      const flowPoints = data.by_date.map((d) => ({ label: d.date_display, short: shortDate(d.date_key), value: d.acquired }));
      lineChart($('dbChartFlowTrend'), flowPoints, '#10b981');
      const totalAcq = flowPoints.reduce((sum, p) => sum + p.value, 0);
      $('dbFlowTrendChip').textContent = `${fmt3(totalAcq)} kg over ${flowPoints.length} day(s)`;
    }
  }

  const pendingHtml = data.top_pending.map((r, i) => `
    <tr>
      <td data-label="Rank">${i + 1}</td>
      <td class="date-cell" data-label="Sector">${esc(r.sector)}</td>
      <td class="num" data-label="Pending Balance">${fmt3(r.pending)}</td>
      <td data-label="As Of">${esc(r.as_of)}</td>
    </tr>`).join('');
  const footSectors = $('dbFootSectors');
  if (footSectors) {
    footSectors.textContent = `${data.by_sector.length} sector(s) active`;
    $('dbFootAcquired').textContent = `${fmt3(k.total_acquired)} kg`;
    $('dbFootSynced').textContent = `Last synced ${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
  }

  $('dbPendingBody').innerHTML = pendingHtml;
  $('dbPendingEmpty').classList.toggle('hidden', data.top_pending.length > 0);
  $('dbPendingTable').classList.toggle('hidden', data.top_pending.length === 0);
}

function resetFilters() {
  const o = D.options || {};
  let from7 = o.max_date ? shiftIso(o.max_date, -6) : o.suggested_from || '';
  if (o.min_date && from7 && from7 < o.min_date) from7 = o.min_date;
  if ($('dbFrom')) $('dbFrom').value = from7;
  if ($('dbTo')) $('dbTo').value = o.max_date || o.suggested_to || '';
  if ($('dbSector')) $('dbSector').value = 'all';
  const group = $('dbQuickRange');
  if (group) group.querySelectorAll('.quick-range__btn').forEach((b) => b.classList.toggle('is-active', b.getAttribute('data-days') === '7'));
  loadDashboard();
}

function applyQuickRange(days, btn) {
  btn.parentNode.querySelectorAll('.quick-range__btn').forEach((b) => b.classList.remove('is-active'));
  btn.classList.add('is-active');
  const o = D.options || {};
  if (Number(days) === 0) {
    $('dbFrom').value = o.min_date || '';
    $('dbTo').value = o.max_date || '';
  } else {
    const to = o.max_date || '';
    if (!to) return;
    let from = shiftIso(to, -(Number(days) - 1));
    if (o.min_date && from < o.min_date) from = o.min_date;
    $('dbFrom').value = from;
    $('dbTo').value = to;
  }
}

export function bind() {
  $('dbApply').addEventListener('click', loadDashboard);
  $('dbReset').addEventListener('click', resetFilters);
  const printBtn = $('dbPrint');
  if (printBtn) printBtn.addEventListener('click', () => window.print());

  $('dbQuickRange').addEventListener('click', (e) => {
    const btn = e.target.closest ? e.target.closest('.quick-range__btn') : null;
    if (!btn) return;
    applyQuickRange(btn.getAttribute('data-days'), btn);
    loadDashboard();
  });

  onViewChange(async (view) => {
    if (view !== 'dashboard') return;
    await ensureOptions();
    if (!D.loadedOnce) loadDashboard();
  });

  authApi.getCurrentUserAccess().then((access) => { D.isAdmin = access.is_admin; }).catch(() => { D.isAdmin = true; });
}
