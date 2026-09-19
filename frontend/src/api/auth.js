/**
 * api/auth.js — Google Identity Services sign-in + the /auth/me lookup.
 * Legacy: getCurrentUserAccess() (Code.gs). Sign-in itself has no legacy
 * equivalent — Apps Script authenticated the user implicitly via the
 * Google Workspace session; this is a real web app, so it authenticates
 * explicitly with Google Identity Services and sends the resulting ID
 * token as a Bearer header on every request (see rmas/routers/deps.py).
 */

import { get, setAuthToken } from './client.js';

const GOOGLE_CLIENT_ID = window.RMAS_GOOGLE_CLIENT_ID || '';

let resolveSignIn = null;
const signedIn = new Promise((resolve) => {
  resolveSignIn = resolve;
});

function handleCredentialResponse(response) {
  setAuthToken(response.credential);
  resolveSignIn(response.credential);
}

/** Renders the Google Sign-In button into the given container element. */
export function renderSignInButton(container) {
  if (!window.google || !window.google.accounts || !window.google.accounts.id) {
    throw new Error('Google Identity Services did not load. Check the network connection.');
  }
  window.google.accounts.id.initialize({
    client_id: GOOGLE_CLIENT_ID,
    callback: handleCredentialResponse,
  });
  window.google.accounts.id.renderButton(container, { theme: 'outline', size: 'large' });
  window.google.accounts.id.prompt();
}

/** Resolves once the user has signed in and the token is set. */
export function whenSignedIn() {
  return signedIn;
}

export function getCurrentUserAccess() {
  return get('/auth/me');
}
