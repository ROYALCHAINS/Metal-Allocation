/**
 * format.js — the one shared round3/fmt3/epsilon-compare helper.
 *
 * Legacy carried three near-identical copies of this logic across
 * Scripts.html, Reports.html and Audit.html (each an independent IIFE with
 * no module system to share code through). CLAUDE.md's JS conventions
 * explicitly call for one shared formatting helper instead of scattering
 * toFixed() calls through views, so this consolidates them.
 */

export const DECIMALS = 3;
export const EPSILON = 0.0005;

export function round3(n) {
  const v = Number(n);
  if (!Number.isFinite(v)) return 0;
  return Math.round((v + Number.EPSILON) * 1000) / 1000;
}

export function fmt3(n) {
  return round3(n).toFixed(DECIMALS);
}

export function fmt1(n) {
  const v = Number(n);
  return (Number.isFinite(v) ? v : 0).toFixed(1);
}

export function fmtPct(n) {
  const v = Number(n);
  return (Number.isFinite(v) ? v : 0).toFixed(1) + '%';
}

/** Fixed-decimal string with trailing zeros trimmed (legacy fmtTrim). */
export function fmtTrim(v, decimals) {
  let s = v.toFixed(decimals);
  if (s.indexOf('.') >= 0) s = s.replace(/0+$/, '').replace(/\.$/, '');
  return s;
}

/**
 * On-plot chart value labels (legacy fmt0). Precision follows the
 * magnitude of the figure so a genuinely small series stays readable.
 */
export function fmt0(n) {
  const v = Number(n);
  if (!Number.isFinite(v) || v === 0) return '0';
  const a = Math.abs(v);
  if (a >= 10) return Math.round(v).toString();
  if (a >= 1) return fmtTrim(v, 1);
  const small = fmtTrim(round3(v), 3);
  return small === '0' || small === '-0' ? '0' : small;
}

export function nearlyEqual(a, b) {
  return Math.abs(round3(a) - round3(b)) < EPSILON;
}

export function num(value) {
  if (value === null || value === undefined || value === '') return 0;
  const n = Number(String(value).replace(/,/g, '').trim());
  return Number.isFinite(n) ? round3(n) : 0;
}

export function esc(value) {
  return String(value === null || value === undefined ? '' : value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

export function shiftIso(iso, days) {
  const p = String(iso).split('-');
  const d = new Date(Number(p[0]), Number(p[1]) - 1, Number(p[2]), 12, 0, 0);
  d.setDate(d.getDate() + days);
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${d.getFullYear()}-${m}-${dd}`;
}

export function shortDate(dateKey) {
  const p = String(dateKey).split('-');
  const mo = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  if (p.length !== 3) return String(dateKey);
  return `${p[2]} ${mo[Number(p[1]) - 1] || ''}`;
}

export function todayIso() {
  const d = new Date();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${d.getFullYear()}-${m}-${day}`;
}
