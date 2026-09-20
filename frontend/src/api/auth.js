/**
 * api/auth.js — the only module that calls fetch() for auth. Views never
 * call fetch directly (CLAUDE.md section 3, JavaScript style).
 */

export async function getCurrentUser() {
  const response = await fetch('/auth/me');
  if (response.status === 401) return null;
  if (!response.ok) {
    throw new Error(`Unexpected response checking session: ${response.status}`);
  }
  return response.json();
}

export async function login(email, password) {
  const response = await fetch('/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || 'Invalid email or password.');
  }
  return response.json();
}

export async function logout() {
  const response = await fetch('/auth/logout', { method: 'POST' });
  if (!response.ok) {
    throw new Error(`Logout failed: ${response.status}`);
  }
}
