/**
 * main.js — app entry point. Decides login vs. dashboard from session state;
 * no client-side router yet since there is only one authenticated view.
 */

import { getCurrentUser } from './api/auth.js';
import { renderLogin } from './views/login.js';
import { renderDashboard } from './views/dashboard.js';

const app = document.getElementById('app');

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
