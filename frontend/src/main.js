/**
 * main.js — app entry point. Decides login vs. dashboard from session state;
 * no client-side router yet since there is only one authenticated view.
 */

import { getCurrentUser } from './api/auth.js';
import { initTheme } from './lib/theme.js';
import { renderLogin } from './views/login.js';
import { renderDashboard } from './views/dashboard.js';

const app = document.getElementById('app');

// The attribute is already set by the inline script in index.html, before
// the first paint. This registers the delegated toggle listener and the
// OS-preference watcher.
initTheme();

function showDashboard(user) {
  renderDashboard(app, user);
}

function showLogin() {
  renderLogin(app, showDashboard);
}

async function bootstrap() {
  let user = null;
  try {
    user = await getCurrentUser();
  } catch (err) {
    console.error('Failed to check session', err);
  }

  if (user) {
    showDashboard(user);
  } else {
    showLogin();
  }
}

bootstrap();
