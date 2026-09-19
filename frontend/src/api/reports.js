/**
 * api/reports.js — replaces ReportService.gs's google.script.run call
 * sites used by views/reports.js and views/dashboard.js.
 */

import { get, post } from './client.js';

export function getHistoryFilterOptions() {
  return get('/reports/filter-options');
}

export function getAllocationHistory(filters) {
  return post('/reports/allocation-history', filters);
}

export function getMetalFlowHistory(filters) {
  return post('/reports/flow-history', filters);
}

export function getDashboardSummary(filters) {
  return post('/reports/dashboard', filters);
}
