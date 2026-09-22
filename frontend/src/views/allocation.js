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

import {
  getAllocationForDate,
  newRequestId,
  previewRevision,
  reviseAllocation,
  saveAllocation,
  submitRequirements,
} from '../api/allocations.js';
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
  // Revision mode. renderRows() computes its locks from the model, which has
  // no mutable state to flip, so this is the flag it consults. Cleared by
  // load(), so changing date or hitting Refresh always leaves revision mode —
  // the same guard legacy needs.
  let reviseMode = false;

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

    <div class="kpi-grid tile-grid" aria-label="Daily totals" id="kpiGrid">
      ${KPI_ORDER.map(
        (label, i) => `
        <div class="kpi tile${i === 4 ? ' kpi--primary' : ''}${i === 5 ? ' kpi--closing' : ''}">
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

    <!-- Confirmation and revision reason. Every class here is already in the
         ported stylesheet; the ids are namespaced so they cannot collide with
         the Audit Log's own modal. -->
    <div class="modal hidden" id="reviseModal" role="dialog" aria-modal="true"
         aria-labelledby="reviseModalTitle">
      <div class="modal__box">
        <h3 class="modal__title" id="reviseModalTitle">Submit Revision</h3>
        <div class="modal__body" id="reviseModalBody"></div>
        <div class="modal__field">
          <label class="field-label" for="reviseReason">Revision Reason (mandatory)</label>
          <textarea id="reviseReason" class="input input--textarea" rows="3"
                    placeholder="Explain why this saved date is being revised"></textarea>
          <div class="inline-error hidden" id="reviseReasonError"></div>
        </div>
        <div class="modal__actions">
          <button type="button" class="btn btn--ghost" id="reviseModalCancel">Cancel</button>
          <button type="button" class="btn btn--primary" id="reviseModalConfirm">
            Submit Revision
          </button>
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
        <button type="button" class="btn btn--gold hidden" id="btnAdminRevise">
          Edit Saved Date
        </button>
        <button type="button" class="btn btn--primary" id="btnSave" ${isAdmin ? '' : 'hidden'}>
          Save Current Data
        </button>
        <button type="button" class="btn btn--primary" id="btnSubmit" ${isAdmin ? 'hidden' : ''}>
          Submit Requirement
        </button>
      </div>
    </div>
  `;

  const $ = (id) => container.querySelector(`#${id}`);

  // Legacy's icon map, from Scripts.html's setBanner(). Without it a warning
  // and an informational notice both render an "i".
  const BANNER_ICONS = { error: '!', warn: '!', success: '✓', locked: '■', info: 'i' };

  function bannerHtml(kind, innerHtml) {
    return `<div class="banner banner--${kind}"><span class="banner__icon">${
      BANNER_ICONS[kind] || 'i'
    }</span><span>${innerHtml}</span></div>`;
  }

  /** One transient notice, replacing whatever was there. Save/submit/error use this. */
  function banner(kind, text) {
    $('allocBanner').innerHTML = text ? bannerHtml(kind, escapeHtml(text)) : '';
  }

  /**
   * Several notices at once, stacked in order. A load can raise three at the
   * same time — this date was revised, operator submissions were loaded, AND
   * the figures were carried from an older date — and they explain different
   * columns, so none should hide the others. Legacy showed only one because it
   * had a single banner element.
   */
  function renderNotices(notices) {
    $('allocBanner').innerHTML = notices
      .map((notice) => bannerHtml(notice.kind, notice.html))
      .join('');
  }

  /**
   * The administrator's announcement that operator figures are on the screen.
   * Null for operators (who submitted is the admin's business) and for a saved
   * date, where staging is no longer a proposal — legacy suppresses it too.
   */
  function submissionNotice() {
    if (!isAdmin || model.is_saved) return null;

    const submissions = model.submissions || [];
    if (!submissions.length) {
      return {
        kind: 'info',
        html: escapeHtml(
          `No operator submissions have been received for ${model.selected_date_display}.`
        ),
      };
    }

    // The count is submissions, NOT staged_value_count — that one counts fields
    // overlaid, so a single submission across three sectors would read as three.
    const lines = submissions
      .map(
        (s) =>
          `<div class="submission-line" title="${escapeHtml(s.operator_email)}">${escapeHtml(s.party_name)} &mdash; ${escapeHtml(
            s.operator_name
          )} &mdash; ${escapeHtml(s.submitted_at_display)}</div>`
      )
      .join('');

    return {
      kind: 'info',
      html:
        `<strong>${submissions.length} operator submission(s) loaded into this date.` +
        ` Adjust the figures, allocate, then save.</strong>${lines}`,
    };
  }

  /**
   * Enter revision mode: unlock the fields and relabel Save.
   *
   * Nothing is written until Submit Revision is confirmed with a reason. The
   * button's visibility comes from the server's can_revise, never from the
   * browser's own idea of who the user is.
   */
  function enterReviseMode() {
    reviseMode = true;
    renderRows();
    // No banner here, deliberately (removed on request). The status box below
    // already says the screen is in revision mode, and the primary button
    // relabels itself to "Submit Revision" — the state is legible without a
    // notice that has to be read and dismissed on every edit.
    $('dateStatusBox').textContent = 'Revision mode — editing a saved date.';
    $('btnAdminRevise').classList.add('hidden');
    $('btnSave').textContent = 'Submit Revision';
    $('btnSave').disabled = false;
  }

  function closeReviseModal() {
    $('reviseModal').classList.add('hidden');
  }

  /**
   * Ask for a reason, and show what the revision will rewrite.
   *
   * The dialog opens immediately and fills in the cascade line when the
   * preview resolves — a slow or failed preview must never stop an
   * administrator from revising.
   */
  function openReviseModal() {
    const payload = collect();
    $('reviseReason').value = '';
    $('reviseReasonError').classList.add('hidden');
    $('reviseModalBody').innerHTML = `
      Revise the saved allocation for <strong>${escapeHtml(
        model.selected_date_display
      )}</strong>.<br><br>
      The stored records for this date will be replaced and a before-and-after
      snapshot is written to the audit log.<br><br>
      <span id="reviseCascadeLine">Checking which later dates are affected&hellip;</span>`;
    $('reviseModal').classList.remove('hidden');

    previewRevision(selectedDate, {
      allocations: payload.allocations,
      metalFlow: payload.metalFlow,
      // The server still checks the real reason on submit; this only has to
      // clear the length rule so the preview is not refused before it runs.
      reason: 'Cascade preview request.',
    })
      .then((preview) => {
        const line = $('reviseCascadeLine');
        if (line) line.innerHTML = `<strong>${escapeHtml(preview.message)}</strong>`;
      })
      .catch(() => {
        const line = $('reviseCascadeLine');
        if (line) {
          line.textContent =
            'The number of affected later dates could not be checked. The revision can still be submitted.';
        }
      });
  }

  async function submitRevision(reason) {
    const button = $('btnSave');
    button.disabled = true;
    button.textContent = 'Submitting revision…';
    try {
      const payload = collect();
      const result = await reviseAllocation(selectedDate, {
        allocations: payload.allocations,
        metalFlow: payload.metalFlow,
        reason,
        requestId: newRequestId(),
      });
      const cascaded = result.cascaded_dates.length;
      banner(
        'success',
        `Revision ${result.revision_number} saved for ${model.selected_date_display}.` +
          (cascaded
            ? ` ${cascaded} later date${cascaded === 1 ? ' was' : 's were'} recalculated.`
            : '') +
          ` Audit ${result.audit_id}.`
      );
      await load(selectedDate);
    } catch (err) {
      banner('error', err.message);
      button.disabled = false;
      button.textContent = 'Submit Revision';
    }
  }

  function renderRows() {
    // In revision mode an administrator edits a saved date, so the saved-date
    // locks lift — including already_submitted, which is moot once the date
    // has been committed.
    const lockAlloted = !isAdmin || (model.is_saved && !reviseMode);
    // A submission cannot be changed once sent, so the operator's own inputs
    // lock the moment their party has submitted. The server decides this —
    // already_submitted is resolved from the staging table, not the browser.
    const lockRequired = (model.is_saved || model.already_submitted) && !reviseMode;

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
        // previous_requirement is NOT sent: the server derives it from the
        // source date's closing balance. It was only ever echoed back from the
        // model, and the server used to persist whatever arrived.
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
    // Any reload leaves revision mode, so a stray Refresh or date change can
    // never leave the fields unlocked against a saved date.
    reviseMode = false;
    $('btnSave').textContent = 'Save Current Data';
    $('dateStatusBox').textContent = 'Loading…';
    banner('', '');
    try {
      model = await getAllocationForDate(isoDate);
      selectedDate = isoDate;
      $('prevSourceDateBox').textContent = model.previous_source_date_display;
      $('dateStatusBox').textContent = model.is_saved
        ? 'Saved — this date is locked. Use a revision to change it.'
        : 'Editable — not yet saved.';
      // The revision-summary notice ("originally saved by ... / last revised
      // by ...") was removed on request. `revision_summary` is still returned
      // by the server and still drives nothing else here; the same history is
      // available in full on the Audit Log.
      const notices = [];
      const submissions = submissionNotice();
      if (submissions) notices.push(submissions);
      if (model.used_fallback_source) {
        notices.push({
          kind: 'warn',
          html: escapeHtml(
            `Nothing was saved on the rule date (${model.rule_source_date_display}); figures were carried from ${model.previous_source_date_display}.`
          ),
        });
      }
      renderNotices(notices);
      // Server-resolved: administrator, already saved, feature enabled.
      $('btnAdminRevise').classList.toggle('hidden', !model.can_revise);
      $('btnSave').disabled = !isAdmin || model.is_saved;
      $('btnSubmit').disabled = !model.can_submit;
      $('btnSubmit').textContent = model.already_submitted
        ? 'Requirement submitted'
        : 'Submit Requirement';
      renderRows();
    } catch (err) {
      $('dateStatusBox').textContent = 'Could not load this date.';
      banner('error', err.message);
    }
  }

  $('allocationDate').addEventListener('change', (e) => load(e.target.value));
  $('btnReloadDate').addEventListener('click', () => load(selectedDate));

  $('btnAdminRevise').addEventListener('click', enterReviseMode);
  $('reviseModalCancel').addEventListener('click', closeReviseModal);
  $('reviseModal').addEventListener('click', (event) => {
    if (event.target === $('reviseModal')) closeReviseModal();
  });

  // Confirm deliberately does NOT close the dialog itself — a reason that is
  // too short shows the inline error and leaves the box open, which is the
  // whole point of having one.
  $('reviseModalConfirm').addEventListener('click', () => {
    const reason = $('reviseReason').value.trim();
    if (reason.length < 10) {
      $('reviseReasonError').textContent =
        'The revision reason must be at least 10 characters.';
      $('reviseReasonError').classList.remove('hidden');
      return;
    }
    closeReviseModal();
    submitRevision(reason);
  });

  // Self-removing, unlike legacy's bare document listener: this view is
  // re-rendered on every nav click, and a listener per visit would stack.
  function onEscape(event) {
    if (!container.isConnected) {
      document.removeEventListener('keydown', onEscape);
      return;
    }
    if (event.key === 'Escape') closeReviseModal();
  }
  document.addEventListener('keydown', onEscape);

  $('btnSave').addEventListener('click', async () => {
    if (reviseMode) {
      openReviseModal();
      return;
    }
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
      button.textContent = 'Save Current Data';
    }
  });

  $('btnSubmit').addEventListener('click', async () => {
    const button = $('btnSubmit');
    button.disabled = true;
    button.textContent = 'Submitting…';
    try {
      const payload = collect();
      // Only the two figures an operator owns. Alloted is the administrator's
      // decision and is never sent from here.
      const result = await submitRequirements(selectedDate, {
        allocations: payload.allocations.map((row) => ({
          sector_id: row.sector_id,
          today_required_kg: row.today_required_kg,
        })),
        metal_flow: payload.metalFlow.map((row) => ({
          flow_sector_id: row.flow_sector_id,
          today_acquired_kg: row.today_acquired_kg,
        })),
        request_id: newRequestId(),
      });
      banner(
        'success',
        `Submitted ${result.allocation_records} sector and ${result.flow_records} Metal Flow ` +
          `figures — ${result.total_required_kg} kg required, ${result.total_acquired_kg} kg ` +
          'acquired. This cannot be changed; contact the administrator if a correction is needed.'
      );
      await load(selectedDate);
    } catch (err) {
      banner('error', err.message);
      button.disabled = false;
      button.textContent = 'Submit Requirement';
    }
  });

  load(selectedDate);
}
