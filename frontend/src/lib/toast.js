/**
 * lib/toast.js — transient pop-up notifications.
 *
 * The styles already shipped in the ported contract (tokens.css's .toast-stack
 * and .toast--success/--error/--warn/--info) but nothing ever created one, so
 * this is the missing half rather than a new design.
 *
 * ACCESSIBILITY. The stack is an aria-live region, so a screen reader announces
 * a toast without the focus moving — a pop-up that stole focus mid-edit would
 * be worse than no pop-up at all. `polite` rather than `assertive`: none of
 * these are urgent enough to interrupt what is being read.
 *
 * A toast is never the only place information appears. These announce something
 * that happened on somebody else's screen; the authoritative view is always the
 * Daily Allocation screen or the Audit Log. Anything that would be lost if the
 * toast were missed does not belong here.
 *
 * TOASTS DO NOT EXPIRE. They stay until the reader closes one, on request. That
 * inverts the usual trade-off — nothing is missed by looking away, but nothing
 * clears itself either — so every toast carries a close button, the stack
 * scrolls rather than growing past the top of the viewport, and a "Dismiss all"
 * appears once more than one is waiting. No toast is ever removed without a
 * click.
 *
 * STYLING NOTE. .toast-stack and .toast are legacy classes from the ported
 * tokens.css, which must not be overridden outside theme.css (CLAUDE.md
 * section 7). Everything added here is therefore a NEW class applied ALONGSIDE
 * them — .toast-stack--managed, .toast__close, .toast__text — so the ported
 * rules still apply untouched and the additions only add.
 */

const STACK_ID = 'toastStack';
/** 0 = stay until dismissed. A caller may still pass a duration. */
const DEFAULT_MS = 0;

function stack() {
  let node = document.getElementById(STACK_ID);
  if (!node) {
    node = document.createElement('div');
    node.id = STACK_ID;
    // The ported class plus our own: the second adds scrolling and spacing for
    // a stack that no longer empties itself.
    node.className = 'toast-stack toast-stack--managed';
    node.setAttribute('role', 'status');
    node.setAttribute('aria-live', 'polite');
    // Appended to <body>, not to the view container: a view is re-rendered on
    // every nav click, which would take any toast inside it with it.
    document.body.appendChild(node);
  }
  return node;
}

/**
 * Show or hide the "Dismiss all" control.
 *
 * It only earns its place once toasts are actually accumulating, which they can
 * now that none expire — with one on screen the per-toast close button is
 * quicker than reading a second control.
 */
function syncDismissAll(host) {
  const toasts = host.querySelectorAll('.toast');
  let clear = host.querySelector('.toast-stack__clear');

  if (toasts.length < 2) {
    if (clear) clear.remove();
    return;
  }
  if (!clear) {
    clear = document.createElement('button');
    clear.type = 'button';
    clear.className = 'toast-stack__clear';
    clear.addEventListener('click', () => {
      host.querySelectorAll('.toast').forEach((t) => t.remove());
      syncDismissAll(host);
    });
    // First child, so it sits above the stack and does not move as toasts
    // arrive underneath it.
    host.insertBefore(clear, host.firstChild);
  }
  clear.textContent = `Dismiss all (${toasts.length})`;
}

/**
 * Show one toast.
 *
 * @param {string} message plain text — set via textContent, never innerHTML,
 *   because the message names a person and a date that originate in the
 *   database.
 * @param {'success'|'error'|'warn'|'info'} [kind]
 * @param {number} [durationMs] 0 keeps it until dismissed.
 */
export function showToast(message, kind = 'info', durationMs = DEFAULT_MS) {
  const host = stack();

  const toast = document.createElement('div');
  toast.className = `toast toast--${kind}`;

  // The button comes FIRST in the DOM so it can float right and have the text
  // flow around it — which is what lets the ported .toast rule stay untouched
  // rather than being overridden to a flex container.
  const close = document.createElement('button');
  close.type = 'button';
  close.className = 'toast__close';
  close.setAttribute('aria-label', 'Dismiss notification');
  close.title = 'Dismiss';
  close.textContent = '×';
  close.addEventListener('click', () => dismiss(toast));

  const text = document.createElement('span');
  text.className = 'toast__text';
  // textContent, never innerHTML: the message names a person and a date that
  // come from the database.
  text.textContent = message;

  toast.append(close, text);
  host.appendChild(toast);
  syncDismissAll(host);

  // Only when a caller asks for one. The default is 0 — stay until dismissed.
  if (durationMs > 0) {
    setTimeout(() => dismiss(toast), durationMs);
  }
  return toast;
}

function dismiss(toast) {
  const host = toast.parentNode;
  if (!host) return;
  host.removeChild(toast);
  syncDismissAll(host);
}

/** Map a server event kind onto a toast colour. */
export function toastKindFor(eventKind) {
  if (eventKind === 'submission') return 'info';
  if (eventKind === 'save') return 'success';
  if (eventKind === 'revision') return 'warn';
  return 'info';
}
