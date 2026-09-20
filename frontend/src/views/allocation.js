/**
 * views/allocation.js — the Daily Allocation screen.
 *
 * Markup and class names are ported from legacy Index.html's #view-daily and
 * Scripts.html's renderAllocationRows()/recalc(): the same control bar, the six
 * KPI cards in the same order, the same table columns, and the same
 * .alloc-table/.flow-table/.kpi/.totals-row classes so the ported CSS applies
 * unchanged (CLAUDE.md section 7, UI fidelity).
 *
 * ONE ROLE-CONDITIONAL VIEW, not two (resolved 2026-09-20): operators get the
 * Today's Required / Today's Acquired inputs, administrators additionally get
 * Alloted and the Save button — mirroring legacy's applyRoleChrome().
 *
 * All arithmetic is done in INTEGER GRAMS via lib/format.js, never in
 * kilograms with JS floats.
 */

import { getAllocationForDate, newRequestId, saveAllocation } from '../api/allocations.js';
import { escapeHtml } from '../components/appHeader.js';
import { balanceClass, fmt3, formatGrams, toGrams } from '../lib/format.js';

const KPI_ORDER = [
  'Previous Requirement',
  "Today's Required",
  "Today's Acquired",
  'Actual Alloted',
  'Remaining to Allocate',
  'Closing Balance',
];

function todayIso() {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const day = String(now.getDate()).padStart(2, '0');
  return `${now.getFullYear()}-${month}-${day}`;
}

export function renderAllocationView(container, user) {
  const isAdmin = user.role === 'admin';
  let model = null;
  let selectedDate = todayIso();

  container.innerHTML = `
    <div class="card control-bar" aria-label="Allocation date selection">
      <div class="control-bar__field">
        <label class="field-label" for="allocationDate">Allocation Date</label>
        <input type="date" id="allocationDate" class="input input--date" value="${selectedDate}">
      </div>
      <div class="control-bar__field">
        <span class="field-label">Previous Source Date</span>
        <div class="readonly-box" id="prevSourceDateBox">&mdash;</div>
      </div>
      <div class="control-bar__field control-bar__field--grow">
        <span class="field-label">Date Status</span>
        <div class="readonly-box" id="dateStatusBox">Loading&hellip;</div>
      </div>
      <div class="control-bar__actions">
        <button type="button" class="btn btn--ghost" id="btnReloadDate">Refresh</button>
      </div>
    </div>

    <div class="kpi-grid" aria-label="Daily totals" id="kpiGrid">
      ${KPI_ORDER.map(
        (label, i) => `
        <div class="kpi${i === 4 ? ' kpi--primary' : ''}${i === 5 ? ' kpi--closing' : ''}">
          <span class="kpi__label">${label}</span>
          <span class="kpi__value" id="kpi${i}">0.000</span>
          <span class="kpi__unit">kg</span>
        </div>`
      ).join('')}
    </div>

    <div id="allocBanner"></div>

    <div class="layout">
      <div class="card panel">
        <div class="panel__head">
          <h2 class="panel__title">Allocation</h2>
          <div class="panel__tools"><span class="chip" id="allocRowCount">0 sectors</span></div>
        </div>
        <div class="table-scroll">
          <table class="data-table alloc-table">
            <thead>
              <tr>
                <th class="col-sector">Sector</th>
                <th class="col-purity">Purity</th>
                <th class="num">Previous Requirement</th>
                <th class="num">Today&rsquo;s Required</th>
                <th class="num">Alloted</th>
                <th class="num">Balance</th>
              </tr>
            </thead>
            <tbody id="allocBody"></tbody>
            <tfoot>
              <tr class="totals-row">
                <td class="totals-row__label" colspan="2">Totals</td>
                <td class="num" id="totPrev">0.000</td>
                <td class="num" id="totReq">0.000</td>
                <td class="num" id="totAlt">0.000</td>
                <td class="num" id="totBal">0.000</td>
              </tr>
            </tfoot>
          </table>
        </div>
      </div>

      <div class="card panel panel--flow">
        <div class="panel__head">
          <h2 class="panel__title">Metal Flow</h2>
          <div class="panel__tools"><span class="chip" id="flowRowCount">0 parties</span></div>
        </div>
        <div class="table-scroll">
          <table class="data-table flow-table">
            <thead>
              <tr>
                <th class="col-sector">Party</th>
                <th class="num">Previous Acquired</th>
                <th class="num">Today&rsquo;s Acquired</th>
              </tr>
            </thead>
            <tbody id="flowBody"></tbody>
            <tfoot>
              <tr class="totals-row">
                <td class="totals-row__label">Totals</td>
                <td class="num" id="totPrevAcq">0.000</td>
                <td class="num" id="totAcq">0.000</td>
              </tr>
            </tfoot>
          </table>
        </div>
      </div>
    </div>

    <div class="page-spacer"></div>
    <div class="action-bar">
      <div class="action-bar__info">
        <div class="action-bar__remaining" id="remainingBox">
          <span class="action-bar__label">Remaining to Allocate</span>
          <span class="action-bar__value" id="remainingValue">0.000 kg</span>
        </div>
      </div>
      <div class="action-bar__buttons">
        <button type="button" class="btn btn--primary" id="btnSave" ${isAdmin ? '' : 'disabled'}>
          ${isAdmin ? 'Save Current Data' : 'Administrator only'}
        </button>
      </div>
    </div>
  `;

  const $ = (id) => container.querySelector(`#${id}`);

  function banner(kind, text) {
    $('allocBanner').innerHTML = text
      ? `<div class="banner banner--${kind}"><span class="banner__icon">i</span><span>${escapeHtml(text)}</span></div>`
      : '';
  }

  function renderRows() {
    const lockAlloted = !isAdmin || model.is_saved;
    const lockRequired = model.is_saved;

    $('allocBody').innerHTML = model.allocations.length
      ? model.allocations
          .map(
            (row, i) => `
        <tr class="alloc-row" data-index="${i}">
          <td class="cell-sector" data-label="Sector">
            <span class="sector-name">${escapeHtml(row.sector_name)}</span>
          </td>
          <td class="cell-purity" data-label="Purity">${escapeHtml(row.purity)}</td>
          <td class="num" data-label="Previous Requirement">
            <span class="readonly-value">${fmt3(row.previous_requirement_kg)}</span>
          </td>
          <td class="num" data-label="Today's Required">
            <input type="text" inputmode="decimal" class="cell-input js-required" data-index="${i}"
                   value="${fmt3(row.today_required_kg)}" ${lockRequired ? 'disabled' : ''}>
          </td>
          <td class="num" data-label="Alloted">
            <input type="text" inputmode="decimal" class="cell-input js-alloted" data-index="${i}"
                   value="${fmt3(row.alloted_kg)}" ${lockAlloted ? 'disabled' : ''}>
          </td>
          <td class="num" data-label="Balance">
            <span class="${balanceClass(toGrams(row.balance_kg))}" id="bal${i}">${fmt3(row.balance_kg)}</span>
          </td>
        </tr>`
          )
          .join('')
      : `<tr><td colspan="6" class="empty-cell">No allocation sectors are mapped to your party.
           Ask the administrator to check the Party column.</td></tr>`;

    $('flowBody').innerHTML = model.metal_flow.length
      ? model.metal_flow
          .map(
            (row, i) => `
          <tr data-index="${i}">
            <td class="cell-sector" data-label="Party">
              <span class="sector-name">${escapeHtml(row.sector_name)}</span>
            </td>
            <td class="num" data-label="Previous Acquired">
              <span class="readonly-value">${fmt3(row.previous_acquired_kg)}</span>
            </td>
            <td class="num" data-label="Today's Acquired">
              <input type="text" inputmode="decimal" class="cell-input cell-input--acquired js-acquired"
                     data-index="${i}" value="${fmt3(row.today_acquired_kg)}" ${lockRequired ? 'disabled' : ''}>
            </td>
          </tr>`
          )
          .join('')
      // The two sector sets are scoped independently through party, so one can
      // be empty while the other is not. Say which, rather than leaving a table
      // showing nothing but a zero totals row (legacy Scripts.html).
      : `<tr><td colspan="3" class="empty-cell">Your party has no Metal Flow row, so
           there is nothing to acquire against here. Ask the administrator to add your
           party to the Metal Flow list.</td></tr>`;

    $('allocRowCount').textContent = `${model.allocations.length} sectors`;
    $('flowRowCount').textContent = `${model.metal_flow.length} part${
      model.metal_flow.length === 1 ? 'y' : 'ies'
    }`;

    container.querySelectorAll('.cell-input').forEach((input) => {
      input.addEventListener('input', recalc);
      // Normalise to 3 decimals once the user leaves the cell: '1' -> '1.000',
      // '2.5' -> '2.500'. Done on blur rather than on every keystroke so it
      // cannot fight the user mid-type (typing '1.' would otherwise snap).
      input.addEventListener('blur', () => {
        const grams = toGrams(input.value);
        if (grams === null) return; // leave invalid text alone for correction
        input.value = formatGrams(grams);
        recalc();
      });
    });
    recalc();
  }

  /** Live recalculation, ported from Scripts.html's recalc(). Grams only. */
  function recalc() {
    let totPrev = 0;
    let totReq = 0;
    let totAlt = 0;
    let totBal = 0;

    model.allocations.forEach((row, i) => {
      const prev = toGrams(row.previous_requirement_kg) || 0;
      const reqInput = container.querySelector(`.js-required[data-index="${i}"]`);
      const altInput = container.querySelector(`.js-alloted[data-index="${i}"]`);
      const req = toGrams(reqInput.value);
      const alt = toGrams(altInput.value);

      reqInput.classList.toggle('is-invalid', req === null);
      altInput.classList.toggle('is-invalid', alt === null);

      const balance = prev + (req || 0) - (alt || 0);
      const cell = $(`bal${i}`);
      cell.textContent = formatGrams(balance);
      cell.className = balanceClass(balance);

      totPrev += prev;
      totReq += req || 0;
      totAlt += alt || 0;
      totBal += balance;
    });

    let totAcq = 0;
    let totPrevAcq = 0;
    model.metal_flow.forEach((row, i) => {
      const input = container.querySelector(`.js-acquired[data-index="${i}"]`);
      const acquired = toGrams(input.value);
      input.classList.toggle('is-invalid', acquired === null);
      totAcq += acquired || 0;
      totPrevAcq += toGrams(row.previous_acquired_kg) || 0;
    });

    $('totPrev').textContent = formatGrams(totPrev);
    $('totReq').textContent = formatGrams(totReq);
    $('totAlt').textContent = formatGrams(totAlt);
    $('totBal').textContent = formatGrams(totBal);
    $('totAcq').textContent = formatGrams(totAcq);
    $('totPrevAcq').textContent = formatGrams(totPrevAcq);

    const remaining = Math.max(0, totAcq - totAlt);
    $('remainingValue').textContent = `${formatGrams(remaining)} kg`;
    const box = $('remainingBox');
    box.classList.toggle('is-done', remaining === 0 && totAcq > 0);
    box.classList.toggle('is-warn', remaining > 0);

    [totPrev, totReq, totAcq, totAlt, remaining, totBal].forEach((value, i) => {
      $(`kpi${i}`).textContent = formatGrams(value);
    });
  }

  function collect() {
    return {
      allocations: model.allocations.map((row, i) => ({
        sector_id: row.sector_id,
        previous_requirement_kg: fmt3(row.previous_requirement_kg),
        today_required_kg: container.querySelector(`.js-required[data-index="${i}"]`).value || '0',
        alloted_kg: container.querySelector(`.js-alloted[data-index="${i}"]`).value || '0',
      })),
      metalFlow: model.metal_flow.map((row, i) => ({
        flow_sector_id: row.flow_sector_id,
        today_acquired_kg: container.querySelector(`.js-acquired[data-index="${i}"]`).value || '0',
      })),
    };
  }

  async function load(isoDate) {
    $('dateStatusBox').textContent = 'Loading…';
    banner('', '');
    try {
      model = await getAllocationForDate(isoDate);
      selectedDate = isoDate;
      $('prevSourceDateBox').textContent = model.previous_source_date_display;
      $('dateStatusBox').textContent = model.is_saved
        ? 'Saved — this date is locked. Use a revision to change it.'
        : 'Editable — not yet saved.';
      if (model.used_fallback_source) {
        banner(
          'warn',
          `Nothing was saved on the rule date (${model.rule_source_date_display}); figures were carried from ${model.previous_source_date_display}.`
        );
      }
      $('btnSave').disabled = !isAdmin || model.is_saved;
      renderRows();
    } catch (err) {
      $('dateStatusBox').textContent = 'Could not load this date.';
      banner('error', err.message);
    }
  }

  $('allocationDate').addEventListener('change', (e) => load(e.target.value));
  $('btnReloadDate').addEventListener('click', () => load(selectedDate));

  $('btnSave').addEventListener('click', async () => {
    const button = $('btnSave');
    button.disabled = true;
    button.textContent = 'Saving…';
    try {
      const payload = collect();
      const result = await saveAllocation(selectedDate, {
        ...payload,
        requestId: newRequestId(),
      });
      banner(
        'success',
        `Saved ${result.allocation_records} allocation and ${result.flow_records} Metal Flow records. Audit ${result.audit_id}.`
      );
      await load(selectedDate);
    } catch (err) {
      banner('error', err.message);
      button.disabled = false;
    } finally {
      button.textContent = isAdmin ? 'Save Current Data' : 'Administrator only';
    }
  });

  load(selectedDate);
}
