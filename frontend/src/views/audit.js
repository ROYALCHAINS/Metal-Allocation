/**
 * views/audit.js — the Audit Log.
 *
 * Built to PROMPT_audit_log.md. Administrator-only, read-only, backed by an
 * append-only log. No update path, no delete path.
 *
 * TWO LAYERS OF GATING, AND ONLY ONE OF THEM IS PROTECTION. The card below is
 * a convenience so a non-admin sees an explanation instead of an error; the
 * real control is that every /audit endpoint re-checks admin status on the
 * server. If that check is ever relaxed, hiding this view changes nothing.
 * A 403 mid-session re-applies the gate, so a revoked administrator loses the
 * view without reloading.
 *
 * Failures and blocked attempts are first-class entries here, not errors to
 * suppress — the log answers "what was attempted", not merely "what happened".
 */

import { AuthError, getAuditEntry, getAuditFilterOptions, getAuditLog } from '../api/audit.js';
import { escapeHtml } from '../components/appHeader.js';
import { fmt3 } from '../lib/format.js';

const DASH = '—';

/** Action type to its badge modifier. Unknown actions get the neutral one. */
const BADGE_CLASS = {
  SAVE: 'save',
  REVISE: 'revise',
  BLOCKED_DUPLICATE: 'blocked',
  FAILED_SAVE: 'failed',
  FAILED_REVISION: 'failed',
  UNAUTHORIZED_REVISION: 'unauth',
  SUBMIT_REQUIREMENT: 'save',
  BLOCKED_RESUBMISSION: 'blocked',
  FAILED_SUBMISSION: 'failed',
};

function actionBadge(action) {
  const modifier = BADGE_CLASS[action] || 'other';
  return `<span class="audit-badge audit-badge--${modifier}">${escapeHtml(
    String(action).replace(/_/g, ' ')
  )}</span>`;
}

/** SUCCESS and BLOCKED are named; everything else reads as a failure. */
function statusDot(status) {
  const modifier =
    status === 'SUCCESS' ? 'success' : status === 'BLOCKED' ? 'blocked' : 'failed';
  return `<span class="status-dot status-dot--${modifier}">${escapeHtml(status)}</span>`;
}

function revChip(revisionNumber) {
  return revisionNumber > 0
    ? `<span class="rev-chip">#${revisionNumber}</span>`
    : '<span class="rev-chip rev-chip--original">Original</span>';
}

/** A missing weight is an em-dash, never 0.000 — absence and zero differ. */
const weight = (value) => (value === null || value === undefined ? DASH : fmt3(value));

/** [change-flag key, column heading, payload field] for the four diff pairs. */
const ALLOCATION_FIELDS = [
  ['previous_requirement', 'Prev. Req.', 'previous_requirement_kg'],
  ['today_required', 'Required', 'today_required_kg'],
  ['alloted', 'Alloted', 'alloted_kg'],
  ['balance', 'Balance', 'balance_kg'],
];

export function renderAuditView(container, user) {
  // The server is the authority; this only decides what to draw first.
  let isAdmin = user.role === 'admin';
  let options = null;

  container.innerHTML = `
    <div class="card access-gate hidden" id="auditGate">
      <div class="access-gate__icon" aria-hidden="true">!</div>
      <div class="access-gate__title">Administrator access required</div>
      <div class="access-gate__text">
        The audit log contains user identities and full data snapshots, so it is
        restricted to authorized administrators. Contact your administrator if you
        need access to this record.
      </div>
    </div>

    <div id="auditContent">
      <div class="card filter-bar">
        <div class="filter-bar__head">
          <div class="filter-bar__title">
            <span class="filter-bar__icon" aria-hidden="true">&#9660;</span>
            <span class="filter-bar__heading">Filter &amp; Query Controls</span>
          </div>
          <div class="filter-bar__applied">
            Applied: <strong id="auFilterCount">No filters active</strong>
          </div>
        </div>
        <div class="filter-bar__grid filter-bar__grid--audit">
          <div class="filter-group filter-group--dates">
            <div class="filter-field">
              <label class="field-label" for="auFrom">Allocation Date From</label>
              <input type="date" id="auFrom" class="input input--date">
            </div>
            <span class="filter-arrow" aria-hidden="true">&rarr;</span>
            <div class="filter-field">
              <label class="field-label" for="auTo">Allocation Date To</label>
              <input type="date" id="auTo" class="input input--date">
            </div>
          </div>
          <div class="filter-group filter-group--selects filter-group--selects-3">
            <div class="filter-field">
              <label class="field-label" for="auAction">Action Type</label>
              <select id="auAction" class="select"><option value="">All actions</option></select>
            </div>
            <div class="filter-field">
              <label class="field-label" for="auStatus">Status</label>
              <select id="auStatus" class="select"><option value="">All statuses</option></select>
            </div>
            <div class="filter-field">
              <label class="field-label" for="auUser">User</label>
              <select id="auUser" class="select"><option value="">All users</option></select>
            </div>
          </div>
          <div class="filter-actions">
            <button type="button" class="btn btn--ghost" id="auReset">Reset</button>
          </div>
        </div>
      </div>

      <div class="summary-strip" id="auKpis"></div>

      <div class="card panel">
        <div class="panel__head">
          <h2 class="panel__title">Audit Log</h2>
          <div class="panel__tools"><span class="chip" id="auRowChip">0 entries</span></div>
        </div>
        <div class="table-scroll">
          <table class="history-table">
            <thead>
              <tr>
                <th>Timestamp</th>
                <th>Allocation Date</th>
                <th>Action</th>
                <th>Rev.</th>
                <th>User</th>
                <th>Reason</th>
                <th>Status</th>
                <th>Audit ID</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody id="auBody"></tbody>
          </table>
        </div>
        <div class="truncation-note hidden" id="auTruncated"></div>
        <div class="empty-state hidden" id="auEmpty">
          <div class="empty-state__title">No audit entries found</div>
          <div class="empty-state__text">Adjust the date range or filters and apply again.</div>
        </div>
      </div>
    </div>

    <div class="modal hidden" id="auditModal" role="dialog" aria-modal="true"
         aria-labelledby="auditModalTitle">
      <div class="modal__box modal__box--wide">
        <h3 class="modal__title" id="auditModalTitle">Audit Entry</h3>
        <div class="modal__body" id="auditModalBody"></div>
        <div class="modal__actions">
          <button type="button" class="btn btn--ghost" id="auditModalClose">Close</button>
        </div>
      </div>
    </div>
  `;

  const $ = (id) => container.querySelector(`#${id}`);

  /** Server said no. Trust that over whatever the session claimed. */
  function revokeAccess() {
    isAdmin = false;
    applyAccess();
  }

  function applyAccess() {
    $('auditGate').classList.toggle('hidden', isAdmin);
    $('auditContent').classList.toggle('hidden', !isAdmin);
    if (!isAdmin) closeModal();
  }

  // ------------------------------------------------------------ KPI cards

  function kpi(label, value, sub, modifier) {
    return `
      <div class="summary-stat summary-stat--${modifier}">
        <span class="summary-stat__label">${label}</span>
        <span class="summary-stat__value">${value}</span>
        <span class="summary-stat__sub">${sub}</span>
      </div>`;
  }

  /** Counts, not weights — plain integers, no decimals. */
  function renderKpis(counts) {
    $('auKpis').innerHTML = [
      kpi('Entries', counts.total, 'matching the filters', 'navy'),
      kpi('Successful', counts.success, 'saves and revisions', 'green'),
      kpi('Blocked', counts.blocked, 'duplicates and refusals', 'amber'),
      kpi('Failed', counts.failed, 'errors and rollbacks', 'rose'),
      // Overlaps the three above — a REVISE is also a SUCCESS. Never summed in.
      kpi('Revisions', counts.revisions, 'administrator edits', 'indigo'),
    ].join('');
  }

  // ---------------------------------------------------------------- table

  function renderRows(rows) {
    const hasRows = rows.length > 0;
    $('auEmpty').classList.toggle('hidden', hasRows);
    $('auBody').innerHTML = rows
      .map(
        (r) => `
        <tr>
          <td class="date-cell">${escapeHtml(r.timestamp_display || DASH)}</td>
          <td>${escapeHtml(r.allocation_date_display || DASH)}</td>
          <td>${actionBadge(r.action_type)}</td>
          <td>${revChip(r.revision_number)}</td>
          <td>${escapeHtml(r.user_email)}</td>
          <td class="reason-text">${escapeHtml(r.reason_preview || DASH)}</td>
          <td>${statusDot(r.action_status)}</td>
          <td><span class="audit-id">${escapeHtml(r.audit_id)}</span></td>
          <td>${
            r.has_snapshots
              ? `<button type="button" class="btn--link js-audit-detail"
                   data-audit-id="${escapeHtml(r.audit_id)}">View changes</button>`
              : '<button type="button" class="btn--link" disabled>No snapshot</button>'
          }</td>
        </tr>`
      )
      .join('');
  }

  // --------------------------------------------------------- detail modal

  function metaItem(label, value) {
    return `
      <div class="detail-meta__item">
        <div class="detail-meta__label">${label}</div>
        <div class="detail-meta__value">${value}</div>
      </div>`;
  }

  function rowClass(entry) {
    if (entry.only_after) return ' class="row-added"';
    if (entry.only_before) return ' class="row-removed"';
    return '';
  }

  function sectorCell(entry) {
    const tag = entry.only_after
      ? ' <span class="audit-badge audit-badge--save">added</span>'
      : entry.only_before
        ? ' <span class="audit-badge audit-badge--failed">removed</span>'
        : '';
    return `<td class="sector-col">${escapeHtml(entry.sector_name)}${tag}</td>`;
  }

  /**
   * Nine columns: the sector, then a before/after pair per field. The
   * data-label attributes are what the narrow-width card layout in audit.css
   * prints as each cell's heading.
   */
  function allocationDiffTable(diff, beforeTotals, afterTotals) {
    const head = ALLOCATION_FIELDS.map(
      ([, label]) =>
        `<th class="num group-before">${label} (before)</th>
         <th class="num group-after">${label} (after)</th>`
    ).join('');

    const body = diff
      .map((entry) => {
        const cells = ALLOCATION_FIELDS.map(([name, label, kgField]) => {
          const changed = entry.changed[name] ? ' is-changed' : '';
          const before = entry.before ? entry.before[kgField] : null;
          const after = entry.after ? entry.after[kgField] : null;
          return `
            <td class="num cell-before${changed}" data-label="${label} (before)">${weight(
              before
            )}</td>
            <td class="num cell-after${changed}" data-label="${label} (after)">${weight(
              after
            )}</td>`;
        }).join('');
        return `<tr${rowClass(entry)}>${sectorCell(entry)}${cells}</tr>`;
      })
      .join('');

    // Labelled "B → A rows" so a change in the number of sectors is visible.
    const foot = ALLOCATION_FIELDS.map(
      ([, label, kgField]) => `
        <td class="num" data-label="${label} (before)">${weight(beforeTotals[kgField])}</td>
        <td class="num" data-label="${label} (after)">${weight(afterTotals[kgField])}</td>`
    ).join('');

    return `
      <div class="diff-wrap">
        <table class="diff-table">
          <thead><tr><th>Sector</th>${head}</tr></thead>
          <tbody>${body}</tbody>
          <tfoot>
            <tr>
              <td class="sector-col">Totals (${beforeTotals.row_count} &rarr; ${
                afterTotals.row_count
              } rows)</td>
              ${foot}
            </tr>
          </tfoot>
        </table>
      </div>
      <div class="diff-legend">
        <span><span class="legend-swatch" style="background:#fdf0d8;border:1px solid #f2ddb0"></span> Changed value</span>
        <span><span class="legend-swatch" style="background:#e3f5ec"></span> Sector added</span>
        <span><span class="legend-swatch" style="background:#fbe4e4"></span> Sector removed</span>
      </div>`;
  }

  function flowDiffTable(diff, beforeTotals, afterTotals) {
    const body = diff
      .map((entry) => {
        const changed = entry.changed.acquired ? ' is-changed' : '';
        return `
          <tr${rowClass(entry)}>
            ${sectorCell(entry)}
            <td class="num cell-before${changed}" data-label="Acquired (before)">${weight(
              entry.before ? entry.before.acquired_kg : null
            )}</td>
            <td class="num cell-after${changed}" data-label="Acquired (after)">${weight(
              entry.after ? entry.after.acquired_kg : null
            )}</td>
          </tr>`;
      })
      .join('');

    return `
      <div class="diff-wrap">
        <table class="diff-table">
          <thead>
            <tr>
              <th>Sector</th>
              <th class="num group-before">Acquired (before)</th>
              <th class="num group-after">Acquired (after)</th>
            </tr>
          </thead>
          <tbody>${body}</tbody>
          <tfoot>
            <tr>
              <td class="sector-col">Totals (${beforeTotals.row_count} &rarr; ${
                afterTotals.row_count
              } rows)</td>
              <td class="num" data-label="Acquired (before)">${weight(
                beforeTotals.acquired_kg
              )}</td>
              <td class="num" data-label="Acquired (after)">${weight(
                afterTotals.acquired_kg
              )}</td>
            </tr>
          </tfoot>
        </table>
      </div>`;
  }

  function snapshotNote(d) {
    if (!d.has_before && d.has_after) {
      return `<div class="snapshot-note">This is an original save, so there is no earlier
        state to compare against. The &ldquo;before&rdquo; columns are empty by design.</div>`;
    }
    if (!d.has_before && !d.has_after) {
      return `<div class="snapshot-note">This entry records a blocked or failed action, so
        no data snapshot was captured. Nothing in either master table was changed.</div>`;
    }
    return '';
  }

  function section(title, note, table) {
    return `
      <div class="detail-section">
        <div class="detail-section__head">
          <h4 class="detail-section__title">${title}</h4>
          <span class="detail-section__note">${note}</span>
        </div>
        ${table}
      </div>`;
  }

  function renderDetail(d) {
    $('auditModalTitle').textContent = `Audit Entry — ${d.allocation_date_display || DASH}`;

    const meta = [
      metaItem('Action', actionBadge(d.action_type)),
      metaItem('Status', statusDot(d.action_status)),
      metaItem(
        'Revision',
        d.revision_number > 0 ? `#${d.revision_number}` : 'Original save'
      ),
      metaItem('User', escapeHtml(d.user_email)),
      metaItem('Timestamp', escapeHtml(d.timestamp_display || DASH)),
      metaItem('Audit ID', `<span class="audit-id">${escapeHtml(d.audit_id)}</span>`),
      metaItem('Request ID', `<span class="audit-id">${escapeHtml(d.request_id || DASH)}</span>`),
      metaItem('Sectors changed', `${d.changed_sectors} allocation · ${d.changed_flow_sectors} flow`),
    ].join('');

    // The FULL reason here, not the list's 140-character preview.
    const reason = d.reason
      ? `<div class="detail-reason">
           <span class="detail-reason__label">Revision reason</span>${escapeHtml(d.reason)}
         </div>`
      : '';

    const allocation = d.allocation_diff.length
      ? section(
          'Allocation Data',
          `${d.changed_sectors} sector(s) changed`,
          allocationDiffTable(
            d.allocation_diff,
            d.before_allocation_totals,
            d.after_allocation_totals
          )
        )
      : '';

    const flow = d.flow_diff.length
      ? section(
          'Metal Flow Data',
          `${d.changed_flow_sectors} sector(s) changed`,
          flowDiffTable(d.flow_diff, d.before_flow_totals, d.after_flow_totals)
        )
      : '';

    $('auditModalBody').innerHTML =
      `<div class="detail-meta">${meta}</div>${reason}${snapshotNote(d)}${allocation}${flow}`;
  }

  function closeModal() {
    $('auditModal').classList.add('hidden');
  }

  async function openDetail(auditId) {
    $('auditModalTitle').textContent = 'Audit Entry';
    $('auditModalBody').innerHTML =
      '<div class="access-gate__text">Loading the snapshot comparison…</div>';
    $('auditModal').classList.remove('hidden');
    try {
      renderDetail(await getAuditEntry(auditId));
    } catch (err) {
      if (err instanceof AuthError) {
        revokeAccess();
        return;
      }
      $('auditModalBody').innerHTML =
        `<div class="banner banner--error"><span>${escapeHtml(err.message)}</span></div>`;
    }
  }

  // --------------------------------------------------------------- loading

  function updateFilterCount() {
    const active = ['Action', 'Status', 'User'].filter((id) => $(`au${id}`).value).length;
    const dated =
      options &&
      ($('auFrom').value !== options.suggested_from || $('auTo').value !== options.suggested_to);
    const n = active + (dated ? 1 : 0);
    $('auFilterCount').textContent =
      n === 0 ? 'No filters active' : `${n} filter${n > 1 ? 's' : ''} active`;
  }

  async function load() {
    if (!isAdmin) return;
    $('auRowChip').textContent = 'Loading…';
    try {
      const data = await getAuditLog({
        date_from: $('auFrom').value,
        date_to: $('auTo').value,
        action_type: $('auAction').value,
        status: $('auStatus').value,
        user: $('auUser').value,
      });

      renderKpis(data.summary.counts);
      renderRows(data.rows);
      updateFilterCount();

      $('auRowChip').textContent = `${data.summary.returned_count} entr${
        data.summary.returned_count === 1 ? 'y' : 'ies'
      }`;

      // A note, not a pager — this page deliberately has no pagination.
      $('auTruncated').classList.toggle('hidden', !data.summary.truncated);
      if (data.summary.truncated) {
        $('auTruncated').textContent =
          `Showing the most recent ${data.summary.returned_count} of ` +
          `${data.summary.record_count} matching entries. Narrow the date range or ` +
          'filters to see older entries.';
      }
    } catch (err) {
      if (err instanceof AuthError) {
        revokeAccess();
        return;
      }
      $('auRowChip').textContent = 'Error';
      $('auBody').innerHTML =
        `<tr><td colspan="9" class="empty-cell">${escapeHtml(err.message)}</td></tr>`;
    }
  }

  function fillSelect(id, values) {
    const select = $(id);
    values.forEach((value) => {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = value.replace(/_/g, ' ');
      select.appendChild(option);
    });
  }

  function seedDates() {
    $('auFrom').value = options.suggested_from;
    $('auTo').value = options.suggested_to;
  }

  async function loadOptions() {
    try {
      options = await getAuditFilterOptions();
      fillSelect('auAction', options.actions);
      fillSelect('auStatus', options.statuses);
      fillSelect('auUser', options.users);
      seedDates();
    } catch (err) {
      if (err instanceof AuthError) revokeAccess();
      // Otherwise the log still loads; only the selects stay empty.
    }
  }

  // ---------------------------------------------------------------- events

  // Filters apply on change — there is no Apply button on any module.
  ['auFrom', 'auTo', 'auAction', 'auStatus', 'auUser'].forEach((id) =>
    $(id).addEventListener('change', load)
  );

  $('auReset').addEventListener('click', () => {
    ['auAction', 'auStatus', 'auUser'].forEach((id) => {
      $(id).value = '';
    });
    if (options) seedDates();
    load();
  });

  // Delegated: one listener survives every re-render of the table body.
  $('auBody').addEventListener('click', (event) => {
    const button = event.target.closest('.js-audit-detail');
    if (button) openDetail(button.dataset.auditId);
  });

  $('auditModalClose').addEventListener('click', closeModal);
  $('auditModal').addEventListener('click', (event) => {
    if (event.target === $('auditModal')) closeModal();
  });
  // Escape has to be caught on the document — focus may be anywhere. The
  // listener removes itself once this view has been swapped out, so revisiting
  // the tab does not stack one listener per visit.
  function onEscape(event) {
    if (!$('auditModal').isConnected) {
      document.removeEventListener('keydown', onEscape);
      return;
    }
    if (event.key === 'Escape') closeModal();
  }
  document.addEventListener('keydown', onEscape);

  applyAccess();
  if (isAdmin) {
    loadOptions().then(load);
  }
}
