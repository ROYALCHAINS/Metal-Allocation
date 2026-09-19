/**
 * api/allocations.js — replaces the Code.gs google.script.run call sites
 * used by views/allocation.js.
 */

import { get, post } from './client.js';

export function getAppBootstrapData() {
  return get('/allocations/bootstrap');
}

export function checkDateAlreadySaved(selectedDate) {
  return get(`/allocations/check-saved?selected_date=${encodeURIComponent(selectedDate)}`);
}

export function getAllocationForDate(selectedDate) {
  return get(`/allocations/${encodeURIComponent(selectedDate)}`);
}

export function saveDailyAllocation(payload) {
  return post('/allocations/save', payload);
}

export function reviseDailyAllocation(payload) {
  return post('/allocations/revise', payload);
}
