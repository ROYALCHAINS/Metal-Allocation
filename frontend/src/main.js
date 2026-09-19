/**
 * main.js — application entry point.
 *
 * Legacy had no equivalent: Code.gs's doGet() rendered the page already
 * signed in, since Apps Script authenticates the user implicitly via the
 * Google Workspace session. This is a real static web app served
 * separately from the API, so it must sign in explicitly before any view
 * can call the backend — see api/auth.js.
 */

import { renderSignInButton, whenSignedIn } from './api/auth.js';
import { bindModalChrome, bindTabClicks, hideOverlay, showOverlay } from './components/shell.js';
import * as allocationView from './views/allocation.js';
import * as reportsView from './views/reports.js';
import * as dashboardView from './views/dashboard.js';
import * as auditView from './views/audit.js';

async function start() {
  bindModalChrome();
  bindTabClicks();

  showOverlay('Sign in to continue…');
  const signInContainer = document.createElement('div');
  signInContainer.id = 'googleSignIn';
  signInContainer.style.cssText = 'position:fixed;inset:0;z-index:200;display:flex;align-items:center;justify-content:center;background:rgba(11,22,35,.85);';
  document.body.appendChild(signInContainer);
  renderSignInButton(signInContainer);

  await whenSignedIn();
  signInContainer.remove();
  hideOverlay();

  allocationView.init();
  reportsView.bind();
  dashboardView.bind();
  auditView.bind();
}

document.addEventListener('DOMContentLoaded', start);
