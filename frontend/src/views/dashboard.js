/**
 * views/dashboard.js — the authenticated app shell.
 *
 * Owns the header, the view tabs and the view container, then hands the active
 * view its slot. The Analysis Dashboard itself is not built yet: it is purely an
 * aggregation over metal_master/metal_flow_master via ReportService.gs, which
 * has not been ported — so its tab is disabled rather than showing an empty
 * chart (CLAUDE.md section 6, rule 23: don't invent behaviour).
 */

import { renderAppHeader } from '../components/appHeader.js';
import { bindNav, renderNav } from '../components/nav.js';
import { logout } from '../api/auth.js';
import { renderAllocationView } from './allocation.js';
import { renderAnalysisView } from './analysis.js';
import { renderAuditView } from './audit.js';
import { renderAllocationHistoryView } from './allocationHistory.js';
import { renderFlowHistoryView } from './flowHistory.js';
import { getNavCounts } from '../api/reports.js';

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
}
