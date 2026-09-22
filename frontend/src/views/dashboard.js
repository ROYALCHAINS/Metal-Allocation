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
import { showToast, toastKindFor } from '../lib/toast.js';

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
  startEventPolling(() => {
    getNavCounts()
      .then((data) => {
        counts = data;
        paint();
      })
      .catch(() => {});
  });
}

/** How often to ask the server whether anything happened elsewhere. */
const POLL_MS = 20000;

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
function startEventPolling(onEventsReceived) {
  let cursor = null;
  let stopped = false;

  async function tick() {
    if (stopped) return;
    try {
      const data = await getEvents(cursor);
      // Only toast once a baseline exists; the first response establishes it.
      if (cursor !== null) {
        data.events.forEach((event) => {
          showToast(event.message, toastKindFor(event.kind));
        });
        // The nav pills count records the events just changed, so refresh them
        // rather than leaving a stale number beside a fresh notification.
        if (data.events.length) onEventsReceived();
      }
      cursor = data.cursor;
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
