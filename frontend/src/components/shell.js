/**
 * components/shell.js — chrome shared by every view: overlay, toast, modal,
 * banner, header status, and tab switching. Legacy: each of Scripts.html /
 * Reports.html / Audit.html carried its own copy of these (three
 * independent IIFEs sharing no state, per CLAUDE.md 7's "share no state"
 * note about the client modules). Consolidating the chrome helpers is safe
 * because they only ever touch shared DOM elements declared once in
 * index.html — it does not merge the three modules' own state.
 *
 * NOTE ON JSON FIELD NAMING: the legacy client used camelCase field names
 * matching the Apps Script server objects (e.g. model.selectedDate). The
 * new FastAPI backend serializes Pydantic models as snake_case (Python
 * convention), so every view below reads response fields as snake_case
 * (e.g. model.selected_date) rather than camelCase.
 */

export function $(id) {
  return document.getElementById(id);
}

export function showOverlay(text) {
  $('overlayText').textContent = text || 'Loading…';
  $('overlay').classList.remove('hidden');
}

export function hideOverlay() {
  $('overlay').classList.add('hidden');
}

export function toast(type, message) {
  const stack = $('toastStack');
  const el = document.createElement('div');
  el.className = `toast toast--${type || 'info'}`;
  el.textContent = message;
  stack.appendChild(el);
  setTimeout(() => {
    if (el.parentNode) el.parentNode.removeChild(el);
  }, type === 'error' ? 9000 : 5000);
}

export function setBanner(kind, message) {
  const banner = $('banner');
  if (!message) {
    banner.classList.add('hidden');
    return;
  }
  banner.className = `banner banner--${kind}`;
  const icons = { error: '!', warn: '!', success: '✓', locked: '■', info: 'i' };
  $('bannerIcon').textContent = icons[kind] || 'i';
  $('bannerText').textContent = message;
  banner.classList.remove('hidden');
}

export function setHeaderStatus(kind, text) {
  const pill = $('hdrStatus');
  pill.className = `status-pill status-pill--${kind}`;
  pill.textContent = text;
}

export function setBarStatus(text) {
  $('barStatus').textContent = text;
}

let modalHandler = null;

export function openModal(opts) {
  $('modalTitle').textContent = opts.title || 'Confirm';
  $('modalBody').innerHTML = opts.bodyHtml || '';
  $('modalConfirm').textContent = opts.confirmLabel || 'Confirm';
  $('modalReasonError').classList.add('hidden');
  $('modalReason').value = '';
  $('modalReasonWrap').classList.toggle('hidden', !opts.requireReason);
  modalHandler = opts.onConfirm || null;
  $('modal').classList.remove('hidden');
}

export function closeModal() {
  $('modal').classList.add('hidden');
  modalHandler = null;
}

export function bindModalChrome() {
  $('modalCancel').addEventListener('click', closeModal);
  $('modalConfirm').addEventListener('click', () => {
    if (modalHandler) modalHandler();
  });
  $('modal').addEventListener('click', (e) => {
    if (e.target === $('modal')) closeModal();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !$('modal').classList.contains('hidden')) closeModal();
  });
}

const viewChangeListeners = [];

/** Registers a callback fired whenever the active view tab changes. */
export function onViewChange(fn) {
  viewChangeListeners.push(fn);
}

export function switchView(view) {
  const tabs = document.querySelectorAll('.nav-tab');
  tabs.forEach((tab) => {
    const active = tab.getAttribute('data-view') === view;
    tab.classList.toggle('is-active', active);
    tab.setAttribute('aria-selected', active ? 'true' : 'false');
  });

  document.querySelectorAll('.view').forEach((v) => {
    v.classList.toggle('is-active', v.id === `view-${view}`);
  });

  document.body.classList.toggle('view-reports', view !== 'daily');
  window.scrollTo(0, 0);

  viewChangeListeners.forEach((fn) => fn(view));
}

export function bindTabClicks() {
  document.querySelectorAll('.nav-tab').forEach((tab) => {
    tab.addEventListener('click', () => switchView(tab.getAttribute('data-view')));
  });
}
