/**
 * api/reports.js — history, dashboard and audit endpoints.
 * Views never call fetch directly (CLAUDE.md section 3).
 */

async function getJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = body && body.detail;
    throw new Error(
      (detail && detail.message) || (typeof detail === 'string' ? detail : null) ||
        `Request failed (${response.status})`
    );
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

export function getAllocationHistory(filters = {}) {
  return getJson(`/reports/allocation-history${query(filters)}`);
}

export function getFlowHistory(filters = {}) {
  return getJson(`/reports/flow-history${query(filters)}`);
}

export function getFlowAnalysis(filters = {}) {
  return getJson(`/reports/flow-analysis${query(filters)}`);
}

export function getNavCounts() {
  return getJson('/reports/counts');
}

export function getDashboard(filters = {}) {
  return getJson(`/reports/dashboard${query(filters)}`);
}
