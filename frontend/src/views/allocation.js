/**
 * views/allocation.js — Daily Allocation screen. Ported from Scripts.html.
 * Every rule here is re-validated on the server (services/allocation_service.py,
 * services/staging_service.py); this module is presentation + client-side
 * convenience checks only.
 */

import * as allocationsApi from '../api/allocations.js';
import * as stagingApi from '../api/staging.js';
import { esc, fmt3, fmt1, num, todayIso } from '../lib/format.js';
import {
  $, closeModal, hideOverlay, openModal, setBanner, setBarStatus, setHeaderStatus, showOverlay, toast,
} from '../components/shell.js';

const EPS = 0.0005;

const STATE = {
  busy: false,
  readOnly: true,
  canRevise: false,
  isAdmin: false,
  email: '',
  displayName: '',
  role: 'ADMIN',
  isOperator: false,
  canEditRequired: true,
  canEditAcquired: true,
  canEditAlloted: true,
  showGlobalTotals: true,
  dateKey: '',
  model: null,
  baseline: null,
};

function uuid() {
  return `REQ-${Date.now().toString(36)}-${Math.random().toString(36).substring(2, 10)}-${Math.random().toString(36).substring(2, 6)}`;
}

/* --------------------------- rendering -------------------------- */

function renderAllocationRows(rows) {
  const lockRequired = !STATE.canEditRequired;
  const lockAlloted = !STATE.canEditAlloted;

  if (!rows.length) {
    $('allocBody').innerHTML =
      '<tr><td colspan="6" class="empty-cell">No allocation sectors are mapped to your party. ' +
      'Ask the administrator to check the Party column in Metal Generator.</td></tr>';
    $('allocRowCount').textContent = '0 sectors';
    return;
  }
  const html = rows.map((r, i) => `
    <tr class="alloc-row" data-index="${i}" data-sector="${esc(r.sector)}">
      <td class="cell-sector" data-label="Sector">
        <span class="sector-name">${esc(r.sector)}</span>
        <button type="button" class="row-toggle" data-toggle="${i}" aria-label="Toggle details">&minus;</button>
      </td>
      <td class="cell-purity m-detail" data-label="Purity">${esc(r.purity || 'Any')}</td>
      <td class="num m-detail" data-label="Previous Requirement">
        <span class="readonly-value" id="prevReq-${i}">${fmt3(r.previous_requirement)}</span>
      </td>
      <td class="num m-detail" data-label="Today’s Required">
        <input type="number" inputmode="decimal" step="0.001" min="0" class="cell-input js-required" id="req-${i}"
          data-index="${i}" value="${r.today_required ? fmt3(r.today_required) : ''}" placeholder="0.000"
          aria-label="Today’s Required Weight for ${esc(r.sector)}" ${lockRequired ? 'disabled' : ''}>
        <div class="inline-error hidden" id="reqErr-${i}"></div>
      </td>
      <td class="num" data-label="Alloted">
        <input type="number" inputmode="decimal" step="0.001" min="0" class="cell-input js-alloted" id="alt-${i}"
          data-index="${i}" value="${r.alloted ? fmt3(r.alloted) : ''}" placeholder="0.000"
          aria-label="Alloted for ${esc(r.sector)}" ${lockAlloted ? 'disabled' : ''}>
        <div class="inline-error hidden" id="altErr-${i}"></div>
      </td>
      <td class="num" data-label="Balance"><span class="balance-value" id="bal-${i}">${fmt3(r.balance)}</span></td>
    </tr>`).join('');
  $('allocBody').innerHTML = html;
  $('allocRowCount').textContent = `${rows.length} sectors`;
}

function renderFlowRows(rows) {
  const lockAcquired = !STATE.canEditAcquired;

  if (!rows.length) {
    $('flowBody').innerHTML =
      '<tr><td colspan="3" class="empty-cell">No Metal Flow sectors are mapped to your party, so there is nothing to enter here. ' +
      'Ask the administrator to set the Party for the Metal Flow sectors.</td></tr>';
    $('flowRowCount').textContent = '0 sectors';
    return;
  }
  const html = rows.map((r, i) => `
    <tr class="flow-row" data-index="${i}" data-sector="${esc(r.sector)}">
      <td class="cell-sector" data-label="Sector"><span class="sector-name">${esc(r.sector)}</span></td>
      <td class="num" data-label="Previous Acquired">
        <span class="readonly-value readonly-value--blue">${fmt3(r.previous_acquired)}</span>
      </td>
      <td class="num" data-label="Today’s Acquired">
        <input type="number" inputmode="decimal" step="0.001" min="0" class="cell-input cell-input--acquired js-acquired"
          id="acq-${i}" data-index="${i}" value="${r.today_acquired ? fmt3(r.today_acquired) : ''}" placeholder="0.000"
          aria-label="Today’s Acquired for ${esc(r.sector)}" ${lockAcquired ? 'disabled' : ''}>
        <div class="inline-error hidden" id="acqErr-${i}"></div>
      </td>
    </tr>`).join('');
  $('flowBody').innerHTML = html;
  $('flowRowCount').textContent = `${rows.length} sectors`;
}

/* -------------------------- calculation ------------------------- */

function readScreen() {
  const allocations = STATE.model.allocations.map((r, i) => {
    const reqEl = $(`req-${i}`);
    const altEl = $(`alt-${i}`);
    const today_required = num(reqEl ? reqEl.value : r.today_required);
    const alloted = num(altEl ? altEl.value : r.alloted);
    return {
      priority: r.priority,
      sector: r.sector,
      purity: r.purity,
      previous_requirement: r.previous_requirement,
      today_required,
      alloted,
      balance: Math.round((r.previous_requirement + today_required - alloted + Number.EPSILON) * 1000) / 1000,
    };
  });

  const metal_flow = STATE.model.metal_flow.map((r, i) => {
    const el = $(`acq-${i}`);
    return {
      sector: r.sector,
      previous_acquired: r.previous_acquired,
      today_acquired: num(el ? el.value : r.today_acquired),
    };
  });

  return { allocations, metal_flow };
}

function computeTotals(screen) {
  const t = {
    total_previous_requirement: 0, total_today_required: 0, total_alloted: 0,
    total_balance: 0, total_acquired: 0, total_previous_acquired: 0,
  };
  screen.allocations.forEach((r) => {
    t.total_previous_requirement += r.previous_requirement;
    t.total_today_required += r.today_required;
    t.total_alloted += r.alloted;
    t.total_balance += r.balance;
  });
  screen.metal_flow.forEach((r) => {
    t.total_acquired += r.today_acquired;
    t.total_previous_acquired += r.previous_acquired;
  });
  Object.keys(t).forEach((k) => { t[k] = Math.round((t[k] + Number.EPSILON) * 1000) / 1000; });
  t.remaining_to_allocate = Math.round((Math.max(0, t.total_acquired - t.total_alloted) + Number.EPSILON) * 1000) / 1000;
  t.over_allocated_by = Math.round((Math.max(0, t.total_alloted - t.total_acquired) + Number.EPSILON) * 1000) / 1000;
  return t;
}

function flagInput(input, errorEl, message) {
  if (!input || !errorEl) return;
  if (message) {
    input.classList.add('is-invalid');
    errorEl.textContent = message;
    errorEl.classList.remove('hidden');
  } else {
    input.classList.remove('is-invalid');
    errorEl.classList.add('hidden');
  }
}

function recalc() {
  if (!STATE.model) return undefined;

  const screen = readScreen();
  const t = computeTotals(screen);

  screen.allocations.forEach((r, i) => {
    const balEl = $(`bal-${i}`);
    if (balEl) {
      balEl.textContent = fmt3(r.balance);
      balEl.className = `balance-value ${Math.abs(r.balance) < EPS ? 'balance-value--zero' : 'balance-value--positive'}`;
    }
    flagInput($(`req-${i}`), $(`reqErr-${i}`), r.today_required < 0 ? 'Negative values are not allowed.' : '');
    flagInput($(`alt-${i}`), $(`altErr-${i}`), r.alloted < 0 ? 'Negative values are not allowed.' : '');
  });
  screen.metal_flow.forEach((r, i) => {
    flagInput($(`acq-${i}`), $(`acqErr-${i}`), r.today_acquired < 0 ? 'Negative values are not allowed.' : '');
  });

  $('kpiPrevRequirement').textContent = fmt3(t.total_previous_requirement);
  $('kpiTodayRequired').textContent = fmt3(t.total_today_required);
  $('kpiAcquired').textContent = fmt3(t.total_acquired);
  $('kpiAlloted').textContent = fmt3(t.total_alloted);
  $('kpiClosingBalance').textContent = fmt3(t.total_balance);

  const demand = t.total_previous_requirement + t.total_today_required;
  $('kpiAcquiredSub').textContent = demand > 0 ? `${fmt1((t.total_acquired / demand) * 100)}% of today’s demand` : 'kg received today';
  $('kpiAllotedFulfil').textContent = demand > 0 ? `${fmt1((t.total_alloted / demand) * 100)}%` : '—';
  $('kpiClosingSub').textContent = demand > 0 ? `${fmt1((t.total_balance / demand) * 100)}% of demand outstanding` : 'kg carried forward';

  $('totPrevRequirement').textContent = fmt3(t.total_previous_requirement);
  $('totTodayRequired').textContent = fmt3(t.total_today_required);
  $('totAlloted').textContent = fmt3(t.total_alloted);
  $('totBalance').textContent = fmt3(t.total_balance);
  $('totPrevAcquired').textContent = fmt3(t.total_previous_acquired);
  $('totAcquired').textContent = fmt3(t.total_acquired);

  $('flowSummaryAcquired').textContent = `${fmt3(t.total_acquired)} kg`;
  $('flowSummaryAlloted').textContent = `${fmt3(t.total_alloted)} kg`;
  $('flowSummaryRemaining').textContent = `${fmt3(t.remaining_to_allocate)} kg`;

  updateRemainingState(t);
  updateSaveState(t);
  return t;
}

function updateRemainingState(t) {
  const card = $('kpiRemainingCard');
  const note = $('kpiRemainingNote');
  const barWrap = $('barRemainingWrap');
  const summaryRow = $('flowSummaryRemainingRow');

  $('kpiRemaining').textContent = fmt3(t.remaining_to_allocate);
  $('barRemaining').textContent = `${fmt3(t.remaining_to_allocate)} kg`;

  let kind = 'primary';
  if (t.over_allocated_by > 0) kind = 'error';
  else if (t.total_acquired > 0 && t.remaining_to_allocate === 0) kind = 'done';
  else if (t.total_acquired > 0 && t.remaining_to_allocate <= Math.round(t.total_acquired * 0.1 * 1000) / 1000) kind = 'warn';

  card.className = `kpi kpi--${kind}`;
  barWrap.className = `action-bar__remaining${kind === 'error' ? ' is-error' : kind === 'done' ? ' is-done' : kind === 'warn' ? ' is-warn' : ''}`;
  summaryRow.className = `flow-summary__row flow-summary__row--strong${kind === 'error' ? ' flow-summary__row--error' : kind === 'warn' ? ' flow-summary__row--warn' : ''}`;

  if (kind === 'error') note.textContent = `kg over-allocated by ${fmt3(t.over_allocated_by)}`;
  else if (kind === 'done') note.textContent = 'kg — fully allocated';
  else if (kind === 'warn') note.textContent = 'kg nearly exhausted';
  else note.textContent = 'kg available';
}

function updateSaveState(t) {
  const saveBtn = $('btnSave');
  const resetBtn = $('btnReset');

  if (STATE.isOperator) {
    const lockedForOperator = !!(STATE.model && STATE.model.is_saved);
    resetBtn.disabled = lockedForOperator;
    if (lockedForOperator) {
      saveBtn.disabled = true;
      setBarStatus('This date has been finalised by the administrator.');
      return;
    }
    let opReason = '';
    if (!(t.total_acquired > 0)) opReason = 'Enter Today’s Acquired metal before submitting.';
    else if (!(t.total_today_required > 0)) opReason = 'Enter Today’s Required weight before submitting.';

    saveBtn.disabled = STATE.busy || !!opReason;

    let opNote;
    if (opReason) opNote = opReason;
    else if (t.total_today_required - t.total_acquired > EPS) {
      opNote = `Ready to submit. Requirement exceeds acquired metal by ${fmt3(t.total_today_required - t.total_acquired)} kg, which carries forward as balance.`;
    } else {
      opNote = `Ready to submit ${fmt3(t.total_today_required)} kg of requirement.`;
    }
    setBarStatus(opNote);
    return;
  }

  if (STATE.readOnly) {
    saveBtn.disabled = true;
    resetBtn.disabled = true;
    saveBtn.textContent = 'Save Current Data';
    setBarStatus('Data Already Saved. This date is locked and cannot be saved again.');
    return;
  }
  resetBtn.disabled = false;

  let reason = '';
  if (!(t.total_acquired > 0)) reason = 'Enter Today’s Acquired metal in the Metal Flow panel before saving.';

  saveBtn.disabled = STATE.busy || !!reason;

  let note;
  if (reason) note = reason;
  else if (t.over_allocated_by > 0) note = `Ready to save. Alloted exceeds Acquired by ${fmt3(t.over_allocated_by)} kg.`;
  else if (t.remaining_to_allocate > 0) note = `Ready to save. ${fmt3(t.remaining_to_allocate)} kg still unallocated.`;
  else note = `Ready to save. ${fmt3(t.total_alloted)} kg fully allocated.`;
  setBarStatus(note);
}

function applyRoleChrome() {
  const operator = STATE.isOperator;

  const remainingCard = $('kpiRemainingCard');
  if (remainingCard) remainingCard.classList.toggle('hidden', operator && !STATE.showGlobalTotals);
  const remainingRow = $('flowSummaryRemainingRow');
  if (remainingRow) remainingRow.classList.toggle('hidden', operator);
  const barWrap = $('barRemainingWrap');
  if (barWrap) barWrap.classList.toggle('hidden', operator);

  const saveBtn = $('btnSave');
  if (saveBtn && saveBtn.dataset.mode !== 'revise') {
    saveBtn.textContent = operator ? 'Submit Requirement' : 'Save Current Data';
  }
  const reviseBtn = $('btnAdminRevise');
  if (reviseBtn && operator) reviseBtn.classList.add('hidden');
}

/* --------------------------- data loading ----------------------- */

async function bootstrap() {
  showOverlay('Starting the application…');
  try {
    const data = await allocationsApi.getAppBootstrapData();
    hideOverlay();
    STATE.isAdmin = !!(data.access && data.access.is_admin);
    STATE.role = (data.access && data.access.role) || (STATE.isAdmin ? 'ADMIN' : 'OPERATOR');
    STATE.isOperator = !STATE.isAdmin;
    applyRoleChrome();
    STATE.email = (data.access && data.access.email) || '';
    STATE.displayName = (data.access && data.access.display_name) || STATE.email;
    $('hdrUser').textContent = STATE.displayName;
    $('hdrUser').title = STATE.email;
    const initial = data.today || todayIso();
    $('allocationDate').value = initial;
    await loadDate(initial);
  } catch (err) {
    hideOverlay();
    setHeaderStatus('error', 'Error');
    setBanner('error', err.message || 'The application could not reach the server. Reload the page and try again.');
    console.error(err);
  }
}

async function loadDate(dateValue) {
  if (!dateValue) {
    setBanner('warn', 'Select an allocation date.');
    return;
  }
  showOverlay('Loading previous day data…');
  setHeaderStatus('neutral', 'Loading');
  $('btnSave').disabled = true;

  try {
    const model = await allocationsApi.getAllocationForDate(dateValue);
    hideOverlay();
    applyModel(model, model.code, model.message);
  } catch (err) {
    hideOverlay();
    setHeaderStatus('error', 'Error');
    setBanner('error', err.message || 'The date could not be loaded. Check the connection and try again.');
    console.error(err);
  }
}

function applyModel(model, code, message) {
  STATE.model = model;
  STATE.dateKey = model.selected_date;
  STATE.readOnly = !!model.read_only;
  STATE.canRevise = !!model.can_revise;
  STATE.isOperator = !!model.is_operator;
  STATE.canEditRequired = model.can_edit_required !== false && !model.is_saved;
  STATE.canEditAcquired = model.can_edit_acquired !== false && !model.is_saved;
  STATE.canEditAlloted = model.can_edit_alloted !== false && !model.is_saved;
  STATE.showGlobalTotals = model.show_global_totals !== false;
  applyRoleChrome();
  STATE.baseline = JSON.parse(JSON.stringify({ allocations: model.allocations, metal_flow: model.metal_flow }));

  $('hdrSelectedDate').textContent = model.selected_date_display;
  $('hdrPrevDate').textContent = model.previous_source_date_display;
  $('prevSourceDateBox').textContent = model.previous_source_date_display;

  renderAllocationRows(model.allocations);
  renderFlowRows(model.metal_flow);

  if (model.is_saved) {
    setHeaderStatus('locked', 'Saved / Read-only');
    $('dateStatusBox').textContent = `Data Already Saved (${model.saved_record_count} allocation records)`;
    setBanner('locked', 'Data Already Saved. This date is locked and cannot be saved again. Select a new date.');
  } else {
    setHeaderStatus('editable', 'Editable');
    $('dateStatusBox').textContent = 'Not saved yet — open for entry';
    if (code === 'NO_PREVIOUS_DATA') {
      setBanner('info', message || 'No previous source date records were found. Previous values are shown as 0.000.');
    } else {
      setBanner('info', `Previous values loaded from ${model.previous_source_date_display}.`);
    }
  }

  $('btnAdminRevise').classList.toggle('hidden', !STATE.canRevise);
  recalc();
  announceSubmissions(model);
}

function announceSubmissions(model) {
  const list = model.staging_submissions || [];

  if (STATE.isOperator) {
    if (model.is_submitted) {
      setBanner('locked', `Requirement submitted${model.submitted_at ? ` on ${model.submitted_at}` : ''}. It is locked and awaiting the administrator.`);
    }
    return;
  }

  if (!list.length || model.is_saved) return;

  const partyRows = list.map((s) => (
    `<li style="margin-bottom:6px;"><strong>${esc(s.party)}</strong>${s.submitted_at ? ` <span style="color:#5b6577;font-size:12px;">submitted ${esc(s.submitted_at)}</span>` : ''}</li>`
  )).join('');

  openModal({
    title: `Requirements Received (${list.length})`,
    confirmLabel: 'Continue',
    bodyHtml:
      `The following part${list.length === 1 ? 'y has' : 'ies have'} submitted a requirement for ` +
      `<strong>${esc(model.selected_date_display)}</strong>:` +
      `<ul style="margin:12px 0 0 18px;padding:0;">${partyRows}</ul>` +
      '<div style="margin-top:14px;">Their figures are already loaded into the Today’s Required and ' +
      'Today’s Acquired fields. Adjust them if needed, enter the allocation, then save.</div>',
    onConfirm: closeModal,
  });
}

/* ------------------------------ saving -------------------------- */

function buildPayload(extra) {
  const screen = readScreen();
  const payload = {
    request_id: uuid(),
    selected_date: STATE.dateKey,
    allocations: screen.allocations.map((r) => ({
      sector: r.sector, priority: r.priority, purity: r.purity,
      previous_requirement: r.previous_requirement, today_required: r.today_required, alloted: r.alloted,
    })),
    metal_flow: screen.metal_flow.map((r) => ({ sector: r.sector, today_acquired: r.today_acquired })),
  };
  if (extra) Object.keys(extra).forEach((k) => { payload[k] = extra[k]; });
  return payload;
}

function requestSubmission() {
  if (STATE.busy) return;
  const t = recalc();
  if ($('btnSave').disabled) {
    toast('warn', $('barStatus').textContent);
    return;
  }
  openModal({
    title: 'Submit Requirement',
    confirmLabel: 'Submit Requirement',
    bodyHtml:
      `Submit your requirement for <strong>${esc(STATE.model.selected_date_display)}</strong>?<br><br>` +
      `Total Today’s Required: <strong>${fmt3(t.total_today_required)} kg</strong><br>` +
      `Total Today’s Acquired: <strong>${fmt3(t.total_acquired)} kg</strong><br><br>` +
      '<strong>A submission cannot be changed once sent.</strong> It will be locked until the administrator finalises the date.',
    onConfirm: () => { closeModal(); doSubmit(); },
  });
}

async function doSubmit() {
  STATE.busy = true;
  $('btnSave').disabled = true;
  showOverlay('Submitting your requirement…');

  try {
    const res = await stagingApi.submitOperatorRequirements(buildPayload());
    STATE.busy = false;
    hideOverlay();
    toast('success', `Requirement submitted for ${res.selected_date}.`);
    setBanner('success', 'Requirement submitted. It is now locked and awaiting the administrator.');
    await loadDate(STATE.dateKey);
  } catch (err) {
    STATE.busy = false;
    hideOverlay();
    const msg = err.message || 'The requirement could not be submitted.';
    toast('error', msg);
    setBanner('error', msg);
    recalc();
  }
}

function requestSave() {
  if (STATE.busy || STATE.readOnly) return;
  const t = recalc();
  if ($('btnSave').disabled) {
    toast('warn', $('barStatus').textContent);
    return;
  }
  openModal({
    title: 'Confirm Save',
    confirmLabel: 'Save Current Data',
    bodyHtml:
      `Save the allocation for <strong>${esc(STATE.model.selected_date_display)}</strong>?<br><br>` +
      `Total Today’s Acquired: <strong>${fmt3(t.total_acquired)} kg</strong><br>` +
      `Actual Total Alloted: <strong>${fmt3(t.total_alloted)} kg</strong><br>` +
      `Unallocated: <strong>${fmt3(t.remaining_to_allocate)} kg</strong><br>` +
      `Closing Balance: <strong>${fmt3(t.total_balance)} kg</strong><br><br>` +
      'A saved date becomes permanently locked for regular users.',
    onConfirm: () => { closeModal(); doSave(); },
  });
}

async function doSave() {
  STATE.busy = true;
  $('btnSave').disabled = true;
  showOverlay('Saving allocation and Metal Flow data…');

  try {
    const res = await allocationsApi.saveDailyAllocation(buildPayload());
    STATE.busy = false;
    hideOverlay();
    toast('success', `Data saved successfully. ${res.master_records} allocation records and ${res.flow_records} Metal Flow records were created.`);
    setBanner('success', 'Data saved successfully.');
    await loadDate(STATE.dateKey);
  } catch (err) {
    STATE.busy = false;
    hideOverlay();
    const msg = err.message || 'The data could not be saved.';
    toast('error', msg);
    setBanner('error', msg);
    if (err.code === 'DATE_ALREADY_SAVED') await loadDate(STATE.dateKey);
    else recalc();
  }
}

/* --------------------- administrator revision ------------------- */

function requestRevision() {
  if (!STATE.canRevise) {
    toast('warn', 'Only an authorized administrator can revise a saved date.');
    return;
  }
  STATE.readOnly = false;
  STATE.canEditRequired = true;
  STATE.canEditAcquired = true;
  STATE.canEditAlloted = true;
  renderAllocationRows(STATE.model.allocations);
  renderFlowRows(STATE.model.metal_flow);
  setHeaderStatus('warn', 'Revision mode');
  setBanner('warn', 'Revision mode. Edit the values, then use Submit Revision. All changes are audited.');
  $('btnSave').textContent = 'Submit Revision';
  $('btnSave').dataset.mode = 'revise';
  $('btnAdminRevise').classList.add('hidden');
  recalc();
  $('btnSave').disabled = false;
  updateSaveState(recalc());
}

function requestRevisionSubmit() {
  const t = recalc();
  openModal({
    title: 'Submit Revision',
    confirmLabel: 'Submit Revision',
    requireReason: true,
    bodyHtml:
      `Revise the saved allocation for <strong>${esc(STATE.model.selected_date_display)}</strong>.<br><br>` +
      'The existing records in Metal Master and Metal Flow Master will be replaced. ' +
      'A before-and-after snapshot is written to the audit log.<br><br>' +
      `Actual Total Alloted: <strong>${fmt3(t.total_alloted)} kg</strong> &middot; Total Acquired: <strong>${fmt3(t.total_acquired)} kg</strong>`,
    onConfirm: () => {
      const reason = String($('modalReason').value || '').trim();
      if (reason.length < 10) {
        $('modalReasonError').textContent = 'The revision reason must be at least 10 characters.';
        $('modalReasonError').classList.remove('hidden');
        return;
      }
      closeModal();
      doRevise(reason);
    },
  });
}

async function doRevise(reason) {
  STATE.busy = true;
  $('btnSave').disabled = true;
  showOverlay('Submitting the administrator revision…');

  try {
    const res = await allocationsApi.reviseDailyAllocation(buildPayload({ revision_reason: reason }));
    STATE.busy = false;
    hideOverlay();
    toast('success', `Revision ${res.revision_number} saved successfully.`);
    setBanner('success', 'Revision saved successfully.');
  } catch (err) {
    STATE.busy = false;
    hideOverlay();
    toast('error', err.message || 'The revision could not be completed.');
    setBanner('error', err.message || 'The revision could not be completed.');
  } finally {
    $('btnSave').textContent = 'Save Current Data';
    delete $('btnSave').dataset.mode;
    await loadDate(STATE.dateKey);
  }
}

/* ------------------------------ reset --------------------------- */

function resetUnsaved() {
  if (!STATE.baseline || STATE.busy) return;
  openModal({
    title: 'Reset Unsaved Changes',
    confirmLabel: 'Reset',
    bodyHtml: 'Discard all values entered on this screen and restore the loaded starting values? Saved data is not affected.',
    onConfirm: () => {
      closeModal();
      STATE.model.allocations = JSON.parse(JSON.stringify(STATE.baseline.allocations));
      STATE.model.metal_flow = JSON.parse(JSON.stringify(STATE.baseline.metal_flow));
      renderAllocationRows(STATE.model.allocations);
      renderFlowRows(STATE.model.metal_flow);
      recalc();
      toast('info', 'Unsaved changes were reset.');
    },
  });
}

/* ----------------------------- events --------------------------- */

function bindEvents() {
  $('allocationDate').addEventListener('change', function onDateChange() {
    $('btnSave').textContent = 'Save Current Data';
    delete $('btnSave').dataset.mode;
    loadDate(this.value);
  });

  $('btnReloadDate').addEventListener('click', () => {
    $('btnSave').textContent = 'Save Current Data';
    delete $('btnSave').dataset.mode;
    loadDate($('allocationDate').value);
  });

  $('btnSave').addEventListener('click', function onSaveClick() {
    if (this.dataset.mode === 'revise') requestRevisionSubmit();
    else if (STATE.isOperator) requestSubmission();
    else requestSave();
  });

  $('btnReset').addEventListener('click', resetUnsaved);
  $('btnAdminRevise').addEventListener('click', requestRevision);

  document.addEventListener('input', (e) => {
    if (e.target && e.target.classList && e.target.classList.contains('cell-input')) recalc();
  });
  document.addEventListener('change', (e) => {
    if (e.target && e.target.classList && e.target.classList.contains('cell-input')) {
      let v = num(e.target.value);
      if (v < 0) v = 0;
      e.target.value = e.target.value === '' ? '' : fmt3(v);
      recalc();
    }
  });

  document.addEventListener('click', (e) => {
    const btn = e.target.closest ? e.target.closest('.row-toggle') : null;
    if (!btn) return;
    const row = btn.closest('tr');
    if (!row) return;
    row.classList.toggle('is-collapsed');
    btn.innerHTML = row.classList.contains('is-collapsed') ? '&plus;' : '&minus;';
  });

  $('btnToggleCards').addEventListener('click', function onToggleAll() {
    const rows = document.querySelectorAll('#allocBody tr.alloc-row');
    const collapseAll = this.textContent.indexOf('Collapse') === 0;
    rows.forEach((row) => {
      row.classList.toggle('is-collapsed', collapseAll);
      const tgl = row.querySelector('.row-toggle');
      if (tgl) tgl.innerHTML = collapseAll ? '&plus;' : '&minus;';
    });
    this.textContent = collapseAll ? 'Expand all' : 'Collapse all';
  });

  window.addEventListener('beforeunload', (e) => {
    if (STATE.readOnly || !STATE.model) return;
    const t = computeTotals(readScreen());
    if (t.total_alloted > 0 || t.total_acquired > 0 || t.total_today_required > 0) {
      e.preventDefault();
      e.returnValue = '';
    }
  });
}

export function init() {
  bindEvents();
  bootstrap();
}
