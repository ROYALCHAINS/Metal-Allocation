/**
 * views/login.js — the only page in the app before a session exists.
 *
 * Username/password only (CLAUDE.md section 6, rule 11) — no signup, no
 * "forgot password" self-service, no OAuth. An account must already exist
 * (created via create_user.py) for this form to succeed. Reuses the real
 * .access-gate/.input/.field-label/.modal__field/.inline-error component
 * classes from the ported visual contract rather than inventing new ones.
 */

import { renderAppHeader } from '../components/appHeader.js';
import { login } from '../api/auth.js';

export function renderLogin(container, onSuccess) {
  container.innerHTML = `
    ${renderAppHeader()}
    <main class="center-page">
      <div class="card access-gate">
        <div class="access-gate__icon" aria-hidden="true">&#128274;</div>
        <div class="access-gate__title">Sign in to continue</div>
        <div class="access-gate__text">
          Enter the email and password an administrator has set up for you.
        </div>
        <form id="loginForm" class="access-gate__action access-gate__form">
          <div class="modal__field">
            <label class="field-label" for="loginEmail">Email</label>
            <input class="input" type="email" id="loginEmail" required autocomplete="username">
          </div>
          <div class="modal__field">
            <label class="field-label" for="loginPassword">Password</label>
            <input class="input" type="password" id="loginPassword" required autocomplete="current-password">
          </div>
          <p class="inline-error hidden" id="loginError"></p>
          <div class="modal__field">
            <button type="submit" class="btn btn--primary" id="loginSubmit">Sign in</button>
          </div>
        </form>
      </div>
    </main>
  `;

  const form = container.querySelector('#loginForm');
  const errorEl = container.querySelector('#loginError');
  const submitBtn = container.querySelector('#loginSubmit');

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    errorEl.classList.add('hidden');
    submitBtn.disabled = true;

    const email = container.querySelector('#loginEmail').value.trim();
    const password = container.querySelector('#loginPassword').value;

    try {
      const user = await login(email, password);
      onSuccess(user);
    } catch (err) {
      errorEl.textContent = err.message || 'Sign in failed.';
      errorEl.classList.remove('hidden');
    } finally {
      submitBtn.disabled = false;
    }
  });
}
