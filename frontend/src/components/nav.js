/**
 * components/nav.js — the view tabs.
 *
 * Ported from legacy Index.html's .view-nav / .nav-tab markup so the styles in
 * StylesReports.html apply unchanged. Tabs whose views are not built yet are
 * rendered disabled rather than omitted, so the shape of the app is visible.
 */

export const VIEWS = [
  { id: 'daily', label: 'Daily Allocation', ready: true },
  { id: 'allocationHistory', label: 'Allocation History', ready: true },
  { id: 'flowHistory', label: 'Metal Flow History', ready: true },
  { id: 'dashboard', label: 'Analysis Dashboard', ready: true },
  { id: 'audit', label: 'Audit Log', ready: true, adminOnly: true },
];

/** Which tabs show a record-count pill, and which count feeds each. */
const COUNT_KEY = {
  allocationHistory: 'allocation_history',
  flowHistory: 'flow_history',
  audit: 'audit',
};

export function renderNav(activeId, user, counts = null) {
  const tabs = VIEWS.filter((v) => !v.adminOnly || user.role === 'admin')
    .map(
      (v) => `
      <button type="button" class="nav-tab${v.id === activeId ? ' is-active' : ''}"
              data-view="${v.id}" role="tab"
              aria-selected="${v.id === activeId}"
              ${v.ready ? '' : 'disabled title="Not built yet"'}>
        ${v.label}${countPill(v.id, counts)}
      </button>`
    )
    .join('');

  return `<nav class="view-nav" role="tablist" aria-label="Application views">
      <div class="view-nav__inner">${tabs}</div>
    </nav>`;
}

function countPill(viewId, counts) {
  const key = COUNT_KEY[viewId];
  if (!key || !counts || counts[key] === undefined) return '';
  return `<span class="nav-tab__count">${counts[key]}</span>`;
}

export function bindNav(container, onSelect) {
  container.querySelectorAll('.nav-tab').forEach((tab) => {
    tab.addEventListener('click', () => {
      if (tab.disabled) return;
      onSelect(tab.dataset.view);
    });
  });
}
