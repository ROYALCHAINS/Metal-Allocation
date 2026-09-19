/**
 * api/staging.js — replaces StagingService.gs's operator-facing
 * google.script.run call sites used by views/allocation.js.
 */

import { get, post } from './client.js';

export function getOperatorRequirementForDate(selectedDate) {
  return get(`/staging/${encodeURIComponent(selectedDate)}`);
}

export function submitOperatorRequirements(payload) {
  return post('/staging/submit', payload);
}

export function getStagedRequirementsForDate(selectedDate) {
  return get(`/staging/${encodeURIComponent(selectedDate)}/admin-view`);
}
