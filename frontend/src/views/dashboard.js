/**
 * views/dashboard.js — the authenticated app shell.
 *
 * Owns the header, the view tabs and the view container, then hands the active
 * view its slot.
 *
 * It also owns the notification poll, and owns it HERE rather than in a view
 * because the shell outlives every view: a poll living in a view would restart
 * on each nav click, and its toasts would be torn out of the DOM with the view
 * that created them.
 */

import { renderAppHeader } from '../components/appHeader.js';
import { bindNav, renderNav } from '../components/nav.js';
import { logout } from '../api/auth.js';
import { renderAllocationView } from './allocation.js';
import { renderAnalysisView } from './analysis.js';
import { renderAuditView } from './audit.js';
import { renderAllocationHistoryView } from './allocationHistory.js';
import { renderFlowHistoryView } from './flowHistory.js';
import { getEvents, getNavCounts } from '../api/reports.js';
import { showToastBatch, toastKindFor } from '../lib/toast.js';

export function renderDashboard(container, user) {
  let activeView = 'daily';
  let counts = null;

  function paint() {
    container.innerHTML = `
      ${renderAppHeader({ user })}
      ${renderNav(activeView, user, counts)}
      <main class="page" id="viewSlot"></main>
    `;

    bindNav(container, (viewId) => {
      activeView = viewId;
      paint();
    });

    const signOut = container.querySelector('#signOutBtn');
    if (signOut) {
      signOut.addEventListener('click', async () => {
        await logout();
        window.location.reload();
      });
    }

    const slot = container.querySelector('#viewSlot');
    switch (activeView) {
      case 'daily':
        renderAllocationView(slot, user);
        break;
      case 'allocationHistory':
        renderAllocationHistoryView(slot);
        break;
      case 'flowHistory':
        renderFlowHistoryView(slot);
        break;
      case 'dashboard':
        renderAnalysisView(slot);
        break;
      case 'audit':
        renderAuditView(slot, user);
        break;
      default:
        slot.innerHTML = '';
    }
  }

  paint();

  // Counts arrive after the first paint so the tabs are never blocked on them.
  getNavCounts()
    .then((data) => {
      counts = data;
      paint();
    })
    .catch(() => {
      /* Pills are decorative; a failure must not break navigation. */
    });

  // The refresh callback is passed in rather than reached for: startEventPolling
  // lives outside renderDashboard and has no access to `counts` or `paint`.
  startEventPolling(user, () => {
    getNavCounts()
      .then((data) => {
        counts = data;
        paint();
      })
      .catch(() => {});
  });
}

/**
 * How often to ask the server whether anything happened elsewhere.
 *
 * 5 seconds, so a notification lands while the other person is still at their
 * desk rather than a third of a minute later. The cost is one indexed query
 * per signed-in client per tick — the roster is a handful of people, and the
 * query is a bounded range scan on the audit log's primary key, so the extra
 * traffic is not worth trading for a slower notice.
 *
 * Revisit this before any large deployment: the cost scales with the number of
 * signed-in clients, not with activity, so a hundred idle tabs would poll a
 * hundred times every five seconds for nothing.
 */
const POLL_MS = 5000;

/**
 * Toast anything that happens on somebody else's screen: an operator's
 * submission reaches the administrator, and the administrator finalising or
 * revising a date reaches the operators.
 *
 * POLLED, not pushed — see routers/events.py for why there is no WebSocket.
 *
 * THE FIRST CALL SENDS NO CURSOR and is expected to return nothing. That is
 * how a page load takes its position in the log without replaying the entire
 * history as pop-ups; only events after that baseline are ever shown.
 */
function startEventPolling(user, onEventsReceived) {
  // Per ACCOUNT, not per browser: two people using one machine must not
  // inherit each other's position in the log.
  const storageKey = `rmas.lastEvent.${user.email}`;

  /**
   * The cursor persists across sign-out, which is the whole point.
   *
   * Reading it back on sign-in is what makes an event that happened while the
   * user was away still reach them. A per-page-load baseline could not: it
   * started at "now" every time, so anything that happened in between was
   * skipped permanently.
   *
   * localStorage can be absent or throw (private windows, blocked site data),
   * so every access is guarded and a failure simply falls back to the old
   * baseline behaviour rather than breaking the shell.
   */
  function readCursor() {
    try {
      const raw = window.localStorage.getItem(storageKey);
      const value = Number.parseInt(raw, 10);
      return Number.isInteger(value) && value >= 0 ? value : null;
    } catch {
      return null;
    }
  }

  function writeCursor(value) {
    try {
      window.localStorage.setItem(storageKey, String(value));
    } catch {
      /* Not fatal: notifications degrade to this session only. */
    }
  }

  // null on a first-ever sign-in on this browser, which still takes a baseline
  // — there is no "while you were away" before the first visit, and replaying
  // the whole log as pop-ups is what the baseline exists to prevent.
  let cursor = readCursor();
  let caughtUp = cursor === null;
  let stopped = false;

  async function tick() {
    if (stopped) return;
    try {
      const data = await getEvents(cursor);

      if (cursor !== null && data.events.length) {
        const items = data.events.map((event) => ({
          message: event.message,
          kind: toastKindFor(event.kind),
        }));
        // Only the first delivery after a gap is "while you were away"; once
        // caught up, later arrivals are simply new.
        showToastBatch(items, {
          summaryHint: caughtUp ? '' : 'while you were away',
        });
        // The nav pills count records the events just changed, so refresh them
        // rather than leaving a stale number beside a fresh notification.
        onEventsReceived();
      }

      caughtUp = true;
      cursor = data.cursor;
      writeCursor(cursor);
    } catch {
      // A failed poll is not worth telling anyone about: the session may have
      // ended, the server may be restarting, and the authoritative screens are
      // all still reachable. Keep the cursor and try again next tick.
    }
  }

  tick();
  const timer = setInterval(tick, POLL_MS);

  // Stop when the shell is gone (sign-out replaces the page), so a detached
  // poll cannot keep running against a dead session.
  window.addEventListener('beforeunload', () => {
    stopped = true;
    clearInterval(timer);
  });
}
