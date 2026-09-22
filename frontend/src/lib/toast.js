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
 */

const STACK_ID = 'toastStack';
const DEFAULT_MS = 7000;
/** Beyond this, older toasts are dropped rather than filling the viewport. */
const MAX_VISIBLE = 4;

function stack() {
  let node = document.getElementById(STACK_ID);
  if (!node) {
    node = document.createElement('div');
    node.id = STACK_ID;
    node.className = 'toast-stack';
    node.setAttribute('role', 'status');
    node.setAttribute('aria-live', 'polite');
    // Appended to <body>, not to the view container: a view is re-rendered on
    // every nav click, which would take any toast inside it with it.
    document.body.appendChild(node);
  }
  return node;
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

  while (host.children.length >= MAX_VISIBLE) {
    host.removeChild(host.firstChild);
  }

  const toast = document.createElement('div');
  toast.className = `toast toast--${kind}`;
  toast.textContent = message;
  toast.title = 'Dismiss';
  toast.addEventListener('click', () => dismiss(toast));
  host.appendChild(toast);

  if (durationMs > 0) {
    setTimeout(() => dismiss(toast), durationMs);
  }
  return toast;
}

function dismiss(toast) {
  if (toast.parentNode) toast.parentNode.removeChild(toast);
}

/** Map a server event kind onto a toast colour. */
export function toastKindFor(eventKind) {
  if (eventKind === 'submission') return 'info';
  if (eventKind === 'save') return 'success';
  if (eventKind === 'revision') return 'warn';
  return 'info';
}
