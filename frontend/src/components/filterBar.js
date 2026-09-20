/**
 * components/filterBar.js — the "Filter & Query Controls" card.
 *
 * One implementation shared by Allocation History, Metal Flow History and the
 * Analysis Dashboard, so the card cannot drift apart between pages. Each page
 * chooses which controls appear.
 *
 * FILTERS APPLY ON CHANGE. There is no Apply button: picking a date, a quick
 * range, a sector or a status reloads immediately. A button that must be
 * pressed before a visible selection takes effect is a state the screen can
 * show but the data does not match.
 *
 * MARKUP IS THE STYLESHEET'S. reports.css defines a twelve-column grid
 * (.filter-bar__grid) with named groups — .filter-group--dates, .filter-arrow,
 * .filter-field--range, .filter-group--selects, .filter-actions — and those are
 * the names to use here. An earlier version reached for .control-bar__field
 * instead, which is real but belongs to tokens.css's flex .control-bar (the one
 * on the Daily Allocation screen). Dropped into this grid it carries a bare
 * min-width and no column span, which is why the controls ran together with no
 * spacing between them.
 */

import { escapeHtml } from './appHeader.js';

function isoDaysAgo(days) {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
}

const todayIso = () => new Date().toISOString().slice(0, 10);

export { isoDaysAgo, todayIso };

/**
 * @param {object} opts
 * @param {string} opts.prefix    element-id prefix, e.g. 'ah' or 'mf' or 'db'
 * @param {boolean} [opts.status] include the Balance Status select
 * @param {string} [opts.sectorLabel] label over the sector select — Metal Flow
 *   names it "Metal Flow Sector" because its sector set is a different one
 */
export function renderFilterBar({ prefix, status = false, sectorLabel = 'Sector' }) {
  const statusField = status
    ? `
        <div class="filter-field">
          <label class="field-label" for="${prefix}Status">Balance Status</label>
          <select id="${prefix}Status" class="select">
            <option value="all">All records</option>
            <option value="pending">Pending (balance &gt; 0)</option>
            <option value="cleared">Cleared (balance &le; 0)</option>
            <option value="allocated">Allocated (alloted &gt; 0)</option>
            <option value="unallocated">Unallocated (alloted = 0)</option>
          </select>
        </div>`
    : '';

  return `
    <div class="card filter-bar">
      <div class="filter-bar__head">
        <div class="filter-bar__title">
          <span class="filter-bar__icon" aria-hidden="true">&#9660;</span>
          <span class="filter-bar__heading">Filter &amp; Query Controls</span>
        </div>
        <div class="filter-bar__applied">
          Applied: <strong id="${prefix}FilterCount">No filters active</strong>
        </div>
      </div>

      <div class="filter-bar__grid">
        <div class="filter-group filter-group--dates">
          <div class="filter-field">
            <label class="field-label" for="${prefix}From">From Date</label>
            <input type="date" id="${prefix}From" class="input input--date">
          </div>
          <span class="filter-arrow" aria-hidden="true">&rarr;</span>
          <div class="filter-field">
            <label class="field-label" for="${prefix}To">To Date</label>
            <input type="date" id="${prefix}To" class="input input--date">
          </div>
        </div>

        <div class="filter-field filter-field--range">
          <span class="field-label">Quick Range</span>
          <div class="quick-range" id="${prefix}QuickRange">
            <button type="button" class="quick-range__btn is-active" data-days="7">7 d</button>
            <button type="button" class="quick-range__btn" data-days="30">30 d</button>
          </div>
        </div>

        <div class="filter-group filter-group--selects${
          status ? ' filter-group--selects-3' : ''
        }">
          <div class="filter-field">
            <label class="field-label" for="${prefix}Sector">${escapeHtml(sectorLabel)}</label>
            <select id="${prefix}Sector" class="select"><option value="">All sectors</option></select>
          </div>
          ${statusField}
        </div>

        <div class="filter-actions">
          <button type="button" class="btn btn--ghost" id="${prefix}Reset">Reset</button>
        </div>
      </div>
    </div>`;
}

/**
 * Wire the shared controls. Returns helpers the page uses for its own state.
 * `onChange` fires whenever any control changes — there is nothing to press.
 */
export function bindFilterBar(container, prefix, onChange) {
  const $ = (id) => container.querySelector(`#${prefix}${id}`);
  let quickDays = 7;

  function setQuickRange(days) {
    quickDays = days;
    $('From').value = isoDaysAgo(days);
    $('To').value = todayIso();
    container.querySelectorAll(`#${prefix}QuickRange .quick-range__btn`).forEach((b) => {
      b.classList.toggle('is-active', Number(b.dataset.days) === days);
    });
  }

  function updateFilterCount() {
    let n = 0;
    if ($('Sector') && $('Sector').value) n += 1;
    if ($('Status') && $('Status').value !== 'all') n += 1;
    // The date range only counts once it differs from the active quick range,
    // so the default 7 d does not read as "1 filter active".
    if ($('From').value !== isoDaysAgo(quickDays) || $('To').value !== todayIso()) n += 1;
    $('FilterCount').textContent =
      n === 0 ? 'No filters active' : `${n} filter${n > 1 ? 's' : ''} active`;
  }

  /** Every control routes through here, so the count can never drift. */
  function apply() {
    updateFilterCount();
    onChange();
  }

  container.querySelectorAll(`#${prefix}QuickRange .quick-range__btn`).forEach((b) =>
    b.addEventListener('click', () => {
      setQuickRange(Number(b.dataset.days));
      apply();
    })
  );

  $('Reset').addEventListener('click', () => {
    if ($('Sector')) $('Sector').value = '';
    if ($('Status')) $('Status').value = 'all';
    setQuickRange(7);
    apply();
  });

  // 'change', not 'input': a date field fires 'input' on every keystroke, so
  // typing 2026 would fire a request for the year 0002 on the way.
  [$('From'), $('To'), $('Sector'), $('Status')].forEach((el) => {
    if (el) el.addEventListener('change', apply);
  });

  setQuickRange(7);
  return { setQuickRange, updateFilterCount, $ };
}
