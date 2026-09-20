/**
 * api/allocations.js — the Daily Allocation endpoints.
 * Views never call fetch directly (CLAUDE.md section 3).
 */

async function parseError(response) {
  const body = await response.json().catch(() => ({}));
  // The API returns {detail: {code, message}} for domain errors.
  if (body && body.detail && body.detail.message) return body.detail.message;
  if (body && typeof body.detail === 'string') return body.detail;
  return `Request failed (${response.status})`;
}

/** The screen model for a date: sectors, carry-forward and totals. */
export async function getAllocationForDate(isoDate) {
  const response = await fetch(`/allocations/${isoDate}`);
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

/**
 * Commit a date. Administrators only.
 * `requestId` guards against double-clicks — a repeat is refused by the server.
 */
export async function saveAllocation(isoDate, { allocations, metalFlow, requestId }) {
  const response = await fetch(`/allocations/${isoDate}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      allocations,
      metal_flow: metalFlow,
      request_id: requestId,
    }),
  });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

/** Client-side request id, ported from Scripts.html's uuid(). */
export function newRequestId() {
  return `REQ-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}
