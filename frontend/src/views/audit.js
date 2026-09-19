/**
 * views/audit.js — administrator-only audit log viewer and snapshot
 * comparison. Ported from Audit.html. Read-only, independent of the other
 * view modules.
 */

import * as auditApi from '../api/audit.js';
import * as authApi from '../api/auth.js';
import { esc, fmt3, shiftIso } from '../lib/format.js';
import { $, hideOverlay, showOverlay, toast } from '../components/shell.js';

const A = { isAdmin: false, accessChecked: false, options: null, loadedOnce: false, busy: false, rows: [] };

function fmtOrDash(n) {
  return n === null || n === undefined ? '—' : fmt3(n);
}

function actionBadge(action) {
  const map = {
    SAVE: 'save', REVISE: 'revise', BLOCKED_DUPLICATE: 'blocked',
    FAILED_SAVE: 'failed', FAILED_REVISION: 'failed', UNAUTHORIZED_REVISION: 'unauth',
  };
  const cls = map[action] || 'other';
  const label = String(action || '—').replace(/_/g, ' ');
  return `<span class="audit-badge audit-badge--${cls}">${esc(label)}</span>`;
}

function statusDot(status) {
  const cls = status === 'SUCCESS' ? 'success' : status === 'BLOCKED' ? 'blocked' : 'failed';
  return `<span class="status-dot status-dot--${cls}">${esc(status || '—')}</span>`;
}

async function checkAccess() {
  if (A.accessChecked) return;
  try {
    const access = await authApi.getCurrentUserAccess();
    A.accessChecked = true;
    A.isAdmin = !!access.is_admin;
  } catch (err) {
    A.accessChecked = true;
    A.isAdmin = false;
    console.error(err);
  }
  applyAccess();
}

function applyAccess() {
  $('tabAudit').classList.toggle('hidden', !A.isAdmin);
  $('auditGate').classList.toggle('hidden', A.isAdmin);
  $('auditContent').classList.toggle('hidden', !A.isAdmin);

  const pill = $('hdrRole');
  if (!pill) return;
  if (A.isAdmin) {
    pill.className = 'role-pill role-pill--admin';
    pill.textContent = 'Admin';
  } else {
    pill.className = 'role-pill role-pill--user';
    pill.textContent = 'User';
  }
}

async function ensureOptions() {
  if (A.options) return;
  showOverlay('Loading audit filters…');
  try {
    const o = await auditApi.getAuditFilterOptions();
    hideOverlay();
    A.options = o;
    populateFilters();
  } catch (err) {
    hideOverlay();
    if (err.code === 'NOT_AUTHORIZED') {
      A.isAdmin = false;
      applyAccess();
      return;
    }
    toast('error', err.message || 'Audit filters could not be loaded. Check the connection and retry.');
    console.error(err);
  }
}

function fillSelect(id, values, allLabel) {
  const el = $(id);
  if (!el) return;
  let html = `<option value="all">${esc(allLabel)}</option>`;
  values.forEach((v) => {
    const label = String(v).replace(/_/g, ' ');
    html += `<option value="${esc(v)}">${esc(label)}</option>`;
  });
  el.innerHTML = html;
}

function populateFilters() {
  const o = A.options;
  fillSelect('auAction', o.actions, 'All actions');
  fillSelect('auStatus', o.statuses, 'All statuses');
  fillSelect('auUser', o.users, 'All users');
  $('auFrom').value = o.suggested_from || '';
  $('auTo').value = o.suggested_to || '';
  if (o.entry_count) {
    $('tabCountAudit').textContent = o.entry_count;
    $('tabCountAudit').classList.remove('hidden');
  }
}

function applyQuickRange(days, btn) {
  btn.parentNode.querySelectorAll('.quick-range__btn').forEach((b) => b.classList.remove('is-active'));
  btn.classList.add('is-active');
  const o = A.options || {};
  if (Number(days) === 0) {
    $('auFrom').value = o.min_date || '';
    $('auTo').value = o.max_date || '';
  } else {
    const to = o.max_date || '';
    if (!to) return;
    let from = shiftIso(to, -(Number(days) - 1));
    if (o.min_date && from < o.min_date) from = o.min_date;
    $('auFrom').value = from;
    $('auTo').value = to;
  }
}

function updateAuditFilterCount() {
  const node = $('auFilterCount');
  if (!node) return;
  let n = 0;
  if ($('auFrom').value || $('auTo').value) n++;
  ['auAction', 'auStatus', 'auUser'].forEach((id) => {
    if ($(id).value && $(id).value !== 'all') n++;
  });
  node.textContent = n === 0 ? 'No filters active' : `${n} filter${n === 1 ? '' : 's'} active`;
}

function auditFilters() {
  updateAuditFilterCount();
  return {
    from_date: $('auFrom').value || null,
    to_date: $('auTo').value || null,
    action_type: $('auAction').value,
    status: $('auStatus').value,
    user: $('auUser').value,
  };
}

async function loadAuditLog() {
  if (A.busy || !A.isAdmin) return;
  A.busy = true;
  showOverlay('Loading the audit log…');
  try {
    const data = await auditApi.getAuditLog(auditFilters());
    A.busy = false;
    hideOverlay();
    A.loadedOnce = true;
    A.rows = data.rows;
    renderAuditLog(data);
  } catch (err) {
    A.busy = false;
    hideOverlay();
    if (err.code === 'NOT_AUTHORIZED') {
      A.isAdmin = false;
      applyAccess();
      return;
    }
    toast('error', err.message || 'The audit log could not be loaded. Check the connection and retry.');
    console.error(err);
  }
}

function renderAuditLog(data) {
  const s = data.summary;
  $('auStatTotal').textContent = s.counts.total;
  $('auStatSuccess').textContent = s.counts.success;
  $('auStatBlocked').textContent = s.counts.blocked;
  $('auStatFailed').textContent = s.counts.failed;
  $('auStatRevisions').textContent = s.counts.revisions;
  $('auRowChip').textContent = `${s.returned_count} entries`;

  const html = data.rows.map((r) => `
    <tr>
      <td class="date-cell" data-label="Timestamp">${esc(r.timestamp_display || '—')}</td>
      <td data-label="Allocation Date">${esc(r.allocation_date_display)}</td>
      <td data-label="Action">${actionBadge(r.action_type)}</td>
      <td data-label="Revision">${r.revision_number > 0 ? `<span class="rev-chip">#${r.revision_number}</span>` : '<span class="rev-chip rev-chip--original">Original</span>'}</td>
      <td data-label="User">${esc(r.user_email || '—')}</td>
      <td data-label="Reason"><span class="reason-text">${esc(r.reason_preview || '—')}</span></td>
      <td data-label="Status">${statusDot(r.status)}</td>
      <td data-label="Audit ID"><span class="audit-id">${esc(r.audit_id)}</span></td>
      <td data-label="Detail"><button type="button" class="btn--link js-audit-detail" data-audit-id="${esc(r.audit_id)}" ${r.has_snapshots ? '' : 'disabled'}>${r.has_snapshots ? 'View changes' : 'No snapshot'}</button></td>
    </tr>`).join('');

  $('auBody').innerHTML = html;
  $('auEmpty').classList.toggle('hidden', data.rows.length > 0);
  $('auTable').classList.toggle('hidden', data.rows.length === 0);

  const trunc = $('auTruncated');
  if (s.truncated) {
    trunc.textContent = `Showing the most recent ${s.returned_count} of ${s.record_count} matching entries. Narrow the date range or filters to see older entries.`;
    trunc.classList.remove('hidden');
  } else {
    trunc.classList.add('hidden');
  }
}

function metaItem(label, value) {
  return `<div class="detail-meta__item"><div class="detail-meta__label">${esc(label)}</div><div class="detail-meta__value">${value}</div></div>`;
}

function fieldLabel(field) {
  const map = { previous_requirement: 'Prev. Req.', today_required: 'Required', alloted: 'Alloted', balance: 'Balance' };
  return map[field] || field;
}

function allocationDiffTable(diff, totals) {
  if (!diff.length) return '';

  const body = diff.map((d) => {
    const rowCls = d.only_after ? ' class="row-added"' : d.only_before ? ' class="row-removed"' : '';
    const cell = (field, side, isBefore) => {
      const value = side ? side[field] : null;
      const cls = `${isBefore ? 'cell-before' : 'cell-after'} num${d.changed[field] ? ' is-changed' : ''}`;
      const label = `${isBefore ? 'Before ' : 'After '}${fieldLabel(field)}`;
      return `<td class="${cls}" data-label="${esc(label)}">${fmtOrDash(value)}</td>`;
    };
    return `<tr${rowCls}>
      <td class="sector-col" data-label="Sector">${esc(d.sector)}${d.only_after ? ' <span class="audit-badge audit-badge--save">added</span>' : ''}${d.only_before ? ' <span class="audit-badge audit-badge--failed">removed</span>' : ''}</td>
      ${cell('previous_requirement', d.before, true)}${cell('previous_requirement', d.after, false)}
      ${cell('today_required', d.before, true)}${cell('today_required', d.after, false)}
      ${cell('alloted', d.before, true)}${cell('alloted', d.after, false)}
      ${cell('balance', d.before, true)}${cell('balance', d.after, false)}
    </tr>`;
  }).join('');

  const b = totals.before_allocation, a = totals.after_allocation;

  return `<div class="diff-wrap"><table class="diff-table">
    <thead><tr>
      <th>Sector</th>
      <th class="num group-before">Prev. Req. (before)</th><th class="num group-after">Prev. Req. (after)</th>
      <th class="num group-before">Required (before)</th><th class="num group-after">Required (after)</th>
      <th class="num group-before">Alloted (before)</th><th class="num group-after">Alloted (after)</th>
      <th class="num group-before">Balance (before)</th><th class="num group-after">Balance (after)</th>
    </tr></thead>
    <tbody>${body}</tbody>
    <tfoot><tr>
      <td data-label="Totals">Totals (${b.count} → ${a.count} rows)</td>
      <td class="num" data-label="Prev. Req. (before)">${fmt3(b.previous_requirement)}</td>
      <td class="num" data-label="Prev. Req. (after)">${fmt3(a.previous_requirement)}</td>
      <td class="num" data-label="Required (before)">${fmt3(b.today_required)}</td>
      <td class="num" data-label="Required (after)">${fmt3(a.today_required)}</td>
      <td class="num" data-label="Alloted (before)">${fmt3(b.alloted)}</td>
      <td class="num" data-label="Alloted (after)">${fmt3(a.alloted)}</td>
      <td class="num" data-label="Balance (before)">${fmt3(b.balance)}</td>
      <td class="num" data-label="Balance (after)">${fmt3(a.balance)}</td>
    </tr></tfoot>
  </table></div>`;
}

function flowDiffTable(diff, totals) {
  if (!diff.length) return '';
  const body = diff.map((d) => {
    const rowCls = d.only_after ? ' class="row-added"' : d.only_before ? ' class="row-removed"' : '';
    const changedCls = d.changed ? ' is-changed' : '';
    return `<tr${rowCls}>
      <td class="sector-col" data-label="Sector">${esc(d.sector)}</td>
      <td class="cell-before num${changedCls}" data-label="Acquired (before)">${fmtOrDash(d.before)}</td>
      <td class="cell-after num${changedCls}" data-label="Acquired (after)">${fmtOrDash(d.after)}</td>
    </tr>`;
  }).join('');

  return `<div class="diff-wrap"><table class="diff-table">
    <thead><tr><th>Sector</th><th class="num group-before">Acquired (before)</th><th class="num group-after">Acquired (after)</th></tr></thead>
    <tbody>${body}</tbody>
    <tfoot><tr>
      <td data-label="Totals">Totals</td>
      <td class="num" data-label="Acquired (before)">${fmt3(totals.before_flow.acquired)}</td>
      <td class="num" data-label="Acquired (after)">${fmt3(totals.after_flow.acquired)}</td>
    </tr></tfoot>
  </table></div>`;
}

function renderDetail(d) {
  $('auditModalTitle').textContent = `Audit Entry — ${d.allocation_date_display}`;

  let html = '<div class="detail-meta">' +
    metaItem('Action', actionBadge(d.action_type)) +
    metaItem('Status', statusDot(d.status)) +
    metaItem('Revision', d.revision_number > 0 ? `#${d.revision_number}` : 'Original save') +
    metaItem('User', esc(d.user_email || '—')) +
    metaItem('Timestamp', esc(d.timestamp_display || '—')) +
    metaItem('Audit ID', `<span class="audit-id">${esc(d.audit_id)}</span>`) +
    metaItem('Request ID', `<span class="audit-id">${esc(d.request_id || '—')}</span>`) +
    metaItem('Sectors changed', `${d.changed_sectors} allocation · ${d.changed_flow_sectors} flow`) +
  '</div>';

  if (d.reason) {
    html += `<div class="detail-reason"><span class="detail-reason__label">Reason</span>${esc(d.reason)}</div>`;
  }

  if (!d.has_before && d.has_after) {
    html += '<div class="snapshot-note">This is an original save, so there is no earlier state to compare against. The "before" columns are empty by design.</div>';
  } else if (!d.has_before && !d.has_after) {
    html += '<div class="snapshot-note">This entry records a blocked or failed action, so no data snapshot was captured. Nothing in either master sheet was changed.</div>';
  }

  if (d.allocation_diff.length) {
    html += `<div class="detail-section">
      <div class="detail-section__head"><h4 class="detail-section__title">Allocation Data</h4><span class="detail-section__note">${d.changed_sectors} sector(s) changed</span></div>
      ${allocationDiffTable(d.allocation_diff, d.totals)}
      <div class="diff-legend">
        <span class="legend-key"><span class="legend-swatch" style="background:#fdf0d8;border:1px solid #f2ddb0"></span>Changed value</span>
        <span class="legend-key"><span class="legend-swatch" style="background:#e3f5ec"></span>Sector added</span>
        <span class="legend-key"><span class="legend-swatch" style="background:#fbe4e4"></span>Sector removed</span>
      </div>
    </div>`;
  }

  if (d.flow_diff.length) {
    html += `<div class="detail-section">
      <div class="detail-section__head"><h4 class="detail-section__title">Metal Flow Data</h4><span class="detail-section__note">${d.changed_flow_sectors} sector(s) changed</span></div>
      ${flowDiffTable(d.flow_diff, d.totals)}
    </div>`;
  }

  $('auditModalBody').innerHTML = html;
}

async function openDetail(auditId) {
  showOverlay('Loading the snapshot comparison…');
  try {
    const detail = await auditApi.getAuditEntryDetail(auditId);
    hideOverlay();
    renderDetail(detail);
    $('auditModal').classList.remove('hidden');
  } catch (err) {
    hideOverlay();
    toast('error', err.message || 'The audit entry could not be loaded.');
    console.error(err);
  }
}

function exportAuditLog() {
  if (!A.rows.length) {
    toast('warn', 'Load some audit entries before exporting.');
    return;
  }
  const csvCell = (v) => {
    const s = String(v === null || v === undefined ? '' : v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const lines = [['Timestamp', 'Allocation Date', 'Action', 'Revision', 'User', 'Reason', 'Status', 'Audit ID', 'Request ID'].map(csvCell).join(',')];
  A.rows.forEach((r) => {
    lines.push([r.timestamp_display, r.allocation_date_display, r.action_type, r.revision_number || '', r.user_email, r.reason_preview, r.status, r.audit_id, r.request_id].map(csvCell).join(','));
  });
  const csv = lines.join('\n');
  $('exportText').value = csv;
  $('exportBody').textContent = 'Copy the CSV below and paste it into a spreadsheet or text file.';
  $('exportModal').classList.remove('hidden');
}

function resetFilters() {
  const o = A.options || {};
  $('auFrom').value = o.suggested_from || '';
  $('auTo').value = o.suggested_to || '';
  $('auAction').value = 'all';
  $('auStatus').value = 'all';
  $('auUser').value = 'all';
  loadAuditLog();
}

export function bind() {
  $('tabAudit').addEventListener('click', async () => {
    await ensureOptions();
    if (!A.loadedOnce) loadAuditLog();
  });

  $('auApply').addEventListener('click', loadAuditLog);
  $('auReset').addEventListener('click', resetFilters);

  $('auBody').addEventListener('click', (e) => {
    const btn = e.target.closest ? e.target.closest('.js-audit-detail') : null;
    if (!btn || btn.disabled) return;
    openDetail(btn.getAttribute('data-audit-id'));
  });

  $('auditModalClose').addEventListener('click', () => $('auditModal').classList.add('hidden'));
  $('auditModal').addEventListener('click', (e) => { if (e.target === $('auditModal')) $('auditModal').classList.add('hidden'); });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !$('auditModal').classList.contains('hidden')) $('auditModal').classList.add('hidden');
  });

  checkAccess();
}

export { exportAuditLog };
