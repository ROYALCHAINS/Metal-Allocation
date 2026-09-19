/**
 * api/audit.js — replaces AuditReportService.gs's google.script.run call
 * sites used by views/audit.js.
 */

import { get, post } from './client.js';

export function getAuditFilterOptions() {
  return get('/audit/filter-options');
}

export function getAuditLog(filters) {
  return post('/audit/log', filters);
}

export function getAuditEntryDetail(auditId) {
  return get(`/audit/entries/${encodeURIComponent(auditId)}`);
}

export function getDateRevisionSummary(allocationDate) {
  return get(`/audit/revisions/${encodeURIComponent(allocationDate)}`);
}
