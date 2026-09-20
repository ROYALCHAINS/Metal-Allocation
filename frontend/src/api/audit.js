/**
 * api/audit.js — the administrator-only audit endpoints.
 * Views never call fetch directly (CLAUDE.md section 3).
 *
 * A 403 from any of these means admin status was revoked since the page
 * loaded. The caller re-applies the access gate rather than showing an error,
 * so a revoked administrator loses the view mid-session.
 */

export class AuthError extends Error {}

async function getJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = body && body.detail;
    const message =
      (detail && detail.message) ||
      (typeof detail === 'string' ? detail : null) ||
      `Request failed (${response.status})`;

    if (response.status === 403 || response.status === 401) throw new AuthError(message);
    throw new Error(message);
  }
  return response.json();
}

function query(params) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== null && value !== undefined && value !== '') search.set(key, value);
  });
  const text = search.toString();
  return text ? `?${text}` : '';
}

/** Fetched once per visit to build the selects and seed the date range. */
export function getAuditFilterOptions() {
  return getJson('/audit/filter-options');
}

export function getAuditLog(filters = {}) {
  return getJson(`/audit${query(filters)}`);
}

/** Snapshots load only when asked for — never in the list payload. */
export function getAuditEntry(auditId) {
  return getJson(`/audit/entry/${encodeURIComponent(auditId)}`);
}
