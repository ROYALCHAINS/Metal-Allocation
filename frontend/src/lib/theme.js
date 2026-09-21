/**
 * lib/theme.js — light/dark, and the one place the choice is stored.
 *
 * WHERE THE STATE LIVES. On document.documentElement, as `data-theme`.
 * Not on anything inside #app: dashboard.js's paint() replaces
 * container.innerHTML wholesale, and it fires on mount, on every nav tab
 * click, AND once more when getNavCounts() resolves. Anything held in
 * there is wiped without a user doing a thing.
 *
 * WHY localStorage rather than memory. logout() calls
 * window.location.reload(), so an in-memory preference would be lost on
 * sign-out. This is the app's first piece of client-persisted state,
 * hence the namespaced key.
 *
 * WHY A DELEGATED LISTENER. Same reason as above — a listener bound
 * directly to #themeToggle dies on the next repaint, and that repaint is
 * guaranteed, not hypothetical. Delegating once from the document means
 * neither dashboard.js nor login.js needs to know the toggle exists.
 */

const THEME_KEY = 'rmas.theme';
const THEME_EVENT = 'rmas:themechange';

/** The current theme. The head script guarantees the attribute is set. */
export function getTheme() {
  return document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
}

function stored() {
  try {
    const value = localStorage.getItem(THEME_KEY);
    return value === 'dark' || value === 'light' ? value : null;
  } catch {
    // Safari in private mode throws on access, not just on write.
    return null;
  }
}

function systemTheme() {
  return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches
    ? 'dark'
    : 'light';
}

/** Repaint the live toggle, since a delegated click triggers no re-render. */
function syncToggle(theme) {
  const dark = theme === 'dark';
  document.querySelectorAll('#themeToggle').forEach((button) => {
    button.setAttribute('aria-pressed', String(dark));
    button.title = dark ? 'Switch to light theme' : 'Switch to dark theme';
    const glyph = button.querySelector('.theme-toggle__glyph');
    if (glyph) glyph.textContent = dark ? '☀' : '☾';
  });
}

export function setTheme(theme, { persist = true } = {}) {
  const next = theme === 'dark' ? 'dark' : 'light';
  document.documentElement.setAttribute('data-theme', next);
  if (persist) {
    try {
      localStorage.setItem(THEME_KEY, next);
    } catch {
      /* Private mode. The theme still applies for this page's lifetime. */
    }
  }
  syncToggle(next);
  // Charts bake colours into SVG attributes at draw time, so anything
  // interpolated in JS has to redraw. Anything expressed as var() does not.
  window.dispatchEvent(new CustomEvent(THEME_EVENT, { detail: { theme: next } }));
}

export function initTheme() {
  // The inline script in index.html has already set the attribute before
  // first paint. This only re-asserts it for the no-script-ran case.
  if (!document.documentElement.getAttribute('data-theme')) {
    setTheme(stored() || systemTheme(), { persist: false });
  }

  // Follow the OS while the tab is open, but only while the user has not
  // made a choice of their own — an explicit choice wins from then on.
  if (window.matchMedia) {
    window
      .matchMedia('(prefers-color-scheme: dark)')
      .addEventListener('change', (event) => {
        if (!stored()) setTheme(event.matches ? 'dark' : 'light', { persist: false });
      });
  }

  document.addEventListener('click', (event) => {
    if (!event.target.closest('#themeToggle')) return;
    setTheme(getTheme() === 'dark' ? 'light' : 'dark');
  });
}

export { THEME_EVENT };
