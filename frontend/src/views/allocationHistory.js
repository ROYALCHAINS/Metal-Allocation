/**
 * views/allocationHistory.js — the Allocation History page.
 *
 * Built to PROMPT_allocation_history.md and the supplied screenshot, reusing
 * the existing class names from the ported StylesReports.html (.filter-bar,
 * .summary-strip/.summary-stat, .history-table, .pager, .pill-pending/
 * .pill-cleared, .empty-state, .truncation-note) rather than rebuilding them.
 *
 * Read-only. It never writes.
 *
 * Deliberately NOT present: the Purity filter and the Search box. Legacy's
 * allocationFilters() hard-codes them to 'all' and '' with the comments "the
 * Purity filter was removed" / "the Search field was removed". The backend
 * still accepts the parameters; they stay unexposed.
 *
 * `priority` is carried on each row and drives sort order only — it is
 * deliberately not a column.
 */

import { getAllocationHistory } from '../api/reports.js';
import { getSectors } from '../api/sectors.js';
import { escapeHtml } from '../components/appHeader.js';
import { bindFilterBar, isoDaysAgo, renderFilterBar, todayIso } from '../components/filterBar.js';
import { fmt3 } from '../lib/format.js';

const PAGE_SIZE = 100;

const STATUS_OPTIONS = [
  ['all', 'All records'],
  ['pending', 'Pending (balance > 0)'],
  ['cleared', 'Cleared (balance ≤ 0)'],
  ['allocated', 'Allocated (alloted > 0)'],
  ['unallocated', 'Unallocated (alloted = 0)'],
];

export function renderAllocationHistoryView(container) {
  let offset = 0;

  container.innerHTML = `
    ${renderFilterBar({
      prefix: 'ah',
      status: true,
    })}

    <div class="summary-strip tile-grid">
      <div class="summary-stat tile summary-stat--navy">
        <span class="summary-stat__label">Records</span>
        <span class="summary-stat__value" id="ahStatRecords">0</span>
        <span class="summary-stat__sub" id="ahStatDates">0 dates &middot; 0 sectors</span>
      </div>
      <div class="summary-stat tile summary-stat--green">
        <span class="summary-stat__label">Previous Requirement</span>
        <span class="summary-stat__value" id="ahStatPrev">0.000</span>
        <span class="stat-unit">kg</span>
      </div>
      <div class="summary-stat tile summary-stat--navy">
        <span class="summary-stat__label">Today&rsquo;s Required</span>
        <span class="summary-stat__value" id="ahStatRequired">0.000</span>
        <span class="stat-unit">kg</span>
      </div>
      <div class="summary-stat tile summary-stat--green">
        <div class="stat-head">
          <span class="summary-stat__label">Total Alloted</span>
          <span class="stat-dot stat-dot--navy" aria-hidden="true"></span>
        </div>
        <span class="summary-stat__value" id="ahStatAlloted">0.000</span>
        <span class="summary-stat__sub" id="ahStatFulfil">0.0% fulfilment rate</span>
      </div>
      <div class="summary-stat tile summary-stat--closing summary-stat--amber">
        <div class="stat-head">
          <span class="summary-stat__label">Total Balance</span>
          <span class="stat-badge">Latest</span>
        </div>
        <span class="summary-stat__value" id="ahStatBalance">0.000</span>
        <span class="summary-stat__sub" id="ahStatPeak">Trajectory peak: &mdash;</span>
      </div>
    </div>

    <div class="card panel">
      <div class="panel__head">
        <h2 class="panel__title">Allocation History</h2>
        <div class="panel__tools"><span class="chip" id="ahRowChip">0 rows</span></div>
      </div>

      <div class="truncation-note hidden" id="ahTruncated">
        Only the first rows are shown. Narrow the date range to see the rest.
      </div>

      <div class="table-scroll" id="ahTableWrap">
        <table class="data-table history-table">
          <thead>
            <tr>
              <th>Date</th>
              <th>Sector</th>
              <th>Purity</th>
              <th class="num">Prev. Requirement</th>
              <th class="num">Today&rsquo;s Required</th>
              <th class="num">Alloted</th>
              <th class="num">Balance</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody id="ahBody"></tbody>
        </table>
      </div>

      <div class="empty-state hidden" id="ahEmpty">
        <div class="empty-state__title">No records found</div>
        <div class="empty-state__text">Adjust the date range or filters and apply again.</div>
      </div>

      <div class="pager">
        <button type="button" class="pager__btn" id="ahPrev" disabled>Previous</button>
        <span class="pager__info" id="ahPageInfo">&mdash;</span>
        <button type="button" class="pager__btn" id="ahNext" disabled>Next</button>
      </div>
    </div>
  `;

  const $ = (id) => container.querySelector(`#${id}`);
  const bar = bindFilterBar(container, 'ah', () => {
    offset = 0;
    load();
  });

  function renderRows(rows) {
    const hasRows = rows.length > 0;
    $('ahTableWrap').classList.toggle('hidden', !hasRows);
    $('ahEmpty').classList.toggle('hidden', hasRows);
    if (!hasRows) {
      $('ahBody').innerHTML = '';
      return;
    }

    $('ahBody').innerHTML = rows
      .map((r) => {
        // Status is derived on the client, never stored.
        const pending = Number(r.balance_kg) > 0;
        const pill = pending
          ? '<span class="pill-pending">Pending</span>'
          : '<span class="pill-cleared">Cleared</span>';
        return `
        <tr>
          <td class="date-cell" data-label="Date">${escapeHtml(r.date_display)}</td>
          <td data-label="Sector">${escapeHtml(r.sector_name)}</td>
          <td data-label="Purity">${escapeHtml(r.purity)}</td>
          <td class="num" data-label="Prev. Requirement">${fmt3(r.previous_requirement_kg)}</td>
          <td class="num" data-label="Today's Required">${fmt3(r.today_required_kg)}</td>
          <td class="num" data-label="Alloted">${fmt3(r.alloted_kg)}</td>
          <td class="num" data-label="Balance">${fmt3(r.balance_kg)}</td>
          <td data-label="Status">${pill}</td>
        </tr>`;
      })
      .join('');
  }

  function renderSummary(summary) {
    $('ahStatRecords').textContent = summary.record_count;
    $('ahStatDates').textContent =
      `${summary.date_count} date${summary.date_count === 1 ? '' : 's'} · ` +
      `${summary.sector_count} sector${summary.sector_count === 1 ? '' : 's'}`;
    $('ahStatPrev').textContent = fmt3(summary.total_previous_requirement_kg);
    $('ahStatRequired').textContent = fmt3(summary.total_today_required_kg);
    $('ahStatAlloted').textContent = fmt3(summary.total_alloted_kg);
    $('ahStatFulfil').textContent = `${summary.fulfilment_rate}% fulfilment rate`;
    $('ahStatBalance').textContent = fmt3(summary.total_balance_kg);
    $('ahStatPeak').textContent = summary.peak_balance.date_display
      ? `Trajectory peak: ${fmt3(summary.peak_balance.value_kg)} kg on ${summary.peak_balance.date_display}`
      : 'Trajectory peak: —';
    $('ahTruncated').classList.toggle('hidden', !summary.truncated);
  }

  function renderPager(page) {
    $('ahPageInfo').textContent = page.total_records
      ? `${page.first_record}–${page.last_record} of ${page.total_records} · page ${page.current_page} of ${page.total_pages}`
      : 'No records';
    $('ahPrev').disabled = !page.has_previous;
    $('ahNext').disabled = !page.has_next;
  }

  async function load() {
    $('ahRowChip').textContent = 'Loading…';
    try {
      const data = await getAllocationHistory({
        date_from: $('ahFrom').value,
        date_to: $('ahTo').value,
        sector_id: $('ahSector').value,
        status: $('ahStatus').value,
        limit: PAGE_SIZE,
        offset,
      });
      $('ahRowChip').textContent = `${data.summary.record_count} rows`;
      renderSummary(data.summary);
      renderRows(data.rows);
      renderPager(data.page);
      bar.updateFilterCount();
    } catch (err) {
      $('ahRowChip').textContent = 'Error';
      $('ahTableWrap').classList.add('hidden');
      $('ahEmpty').classList.remove('hidden');
      $('ahEmpty').innerHTML =
        `<div class="empty-state__title">Could not load history</div>
         <div class="empty-state__text">${escapeHtml(err.message)}</div>`;
    }
  }

  /** Fill the Sector dropdown from the scope-filtered reference data. */
  async function loadSectors() {
    try {
      const data = await getSectors();
      const select = $('ahSector');
      data.allocation_sectors.forEach((s) => {
        const option = document.createElement('option');
        option.value = s.sector_id;
        option.textContent = s.sector_name;
        select.appendChild(option);
      });
    } catch {
      // A failed dropdown must not stop the table loading; "All sectors" still works.
    }
  }

  loadSectors();
  load();
}
