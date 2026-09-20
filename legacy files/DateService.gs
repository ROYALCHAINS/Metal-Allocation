/**
 * DateService.gs
 * Royal Metal Allocation System — Phase 1
 *
 * All date normalization, key generation and the previous-source-date business rule.
 * Every date key in this system is a 'yyyy-MM-dd' string produced in the SPREADSHEET
 * timezone (Asia/Kolkata only as a fallback).
 */

var DATE_CACHE_ = {};

/** Spreadsheet timezone, with configured fallback. */
function getAppTimeZone_() {
  if (DATE_CACHE_.tz) return DATE_CACHE_.tz;
  var tz = null;
  try {
    tz = getSpreadsheet_().getSpreadsheetTimeZone();
  } catch (e) {
    tz = null;
  }
  if (!tz) {
    try { tz = Session.getScriptTimeZone(); } catch (e2) { tz = null; }
  }
  DATE_CACHE_.tz = tz || CONFIG.TIMEZONE_FALLBACK;
  return DATE_CACHE_.tz;
}

/**
 * Normalizes any supported value into a 'yyyy-MM-dd' key.
 * Accepts: Date object, 'yyyy-MM-dd', 'dd/MM/yyyy', 'dd-MM-yyyy', 'dd-MMM-yyyy'.
 * Returns '' when the value cannot be interpreted.
 */
function toDateKey_(value) {
  if (value === null || value === undefined || value === '') return '';

  if (Object.prototype.toString.call(value) === '[object Date]') {
    if (isNaN(value.getTime())) return '';
    return Utilities.formatDate(value, getAppTimeZone_(), 'yyyy-MM-dd');
  }

  if (typeof value === 'number' && isFinite(value)) {
    // Spreadsheet serial number (days since 1899-12-30).
    var serialDate = new Date(Math.round((value - 25569) * 86400 * 1000));
    if (isNaN(serialDate.getTime())) return '';
    return Utilities.formatDate(serialDate, 'UTC', 'yyyy-MM-dd');
  }

  var s = String(value).trim();
  if (!s) return '';

  var m = s.match(/^(\d{4})-(\d{1,2})-(\d{1,2})/);
  if (m) return pad4_(m[1]) + '-' + pad2_(m[2]) + '-' + pad2_(m[3]);

  m = s.match(/^(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4})$/);
  if (m) return pad4_(m[3]) + '-' + pad2_(m[2]) + '-' + pad2_(m[1]);

  m = s.match(/^(\d{1,2})[\-\s]([A-Za-z]{3,})[\-\s](\d{4})$/);
  if (m) {
    var mi = monthIndexFromName_(m[2]);
    if (mi > 0) return pad4_(m[3]) + '-' + pad2_(String(mi)) + '-' + pad2_(m[1]);
  }

  var parsed = new Date(s);
  if (!isNaN(parsed.getTime())) {
    return Utilities.formatDate(parsed, getAppTimeZone_(), 'yyyy-MM-dd');
  }
  return '';
}

function monthIndexFromName_(name) {
  var names = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'];
  var key = String(name).toLowerCase().substring(0, 3);
  for (var i = 0; i < names.length; i++) if (names[i] === key) return i + 1;
  return 0;
}

function pad2_(v) { v = String(v); return v.length < 2 ? '0' + v : v; }
function pad4_(v) { v = String(v); while (v.length < 4) v = '0' + v; return v; }

/** True when the key is a structurally valid calendar date. */
function isValidDateKey_(key) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(String(key || ''))) return false;
  var p = String(key).split('-');
  var y = Number(p[0]), m = Number(p[1]), d = Number(p[2]);
  if (m < 1 || m > 12 || d < 1 || d > 31) return false;
  var probe = new Date(y, m - 1, d, CONFIG.STORAGE_HOUR, 0, 0, 0);
  return probe.getFullYear() === y && probe.getMonth() === (m - 1) && probe.getDate() === d;
}

/** 'yyyy-MM-dd' -> Date at the configured storage hour (local script time). */
function dateKeyToStorageDate_(key) {
  var p = String(key).split('-');
  return new Date(Number(p[0]), Number(p[1]) - 1, Number(p[2]), CONFIG.STORAGE_HOUR, 0, 0, 0);
}

/** 0 = Sunday ... 6 = Saturday */
function dayOfWeekFromKey_(key) {
  return dateKeyToStorageDate_(key).getDay();
}

/** Adds (or subtracts) whole days to a date key and returns a new key. */
function shiftDateKey_(key, days) {
  var d = dateKeyToStorageDate_(key);
  d.setDate(d.getDate() + days);
  return pad4_(String(d.getFullYear())) + '-' + pad2_(String(d.getMonth() + 1)) + '-' + pad2_(String(d.getDate()));
}

/**
 * PREVIOUS SOURCE DATE RULE
 *   Monday        -> selected date - 2 days (Saturday)
 *   Any other day -> selected date - 1 day
 */
function previousSourceDateKey_(selectedKey) {
  return shiftDateKey_(selectedKey, dayOfWeekFromKey_(selectedKey) === 1 ? -2 : -1);
}

/** Human display, e.g. 'Mon, 17-Aug-2026'. */
function formatDisplayDate_(key) {
  if (!isValidDateKey_(key)) return '';
  return Utilities.formatDate(dateKeyToStorageDate_(key), getAppTimeZone_(), 'EEE, dd-MMM-yyyy');
}

/** Today's key in the spreadsheet timezone. */
function todayKey_() {
  return Utilities.formatDate(new Date(), getAppTimeZone_(), 'yyyy-MM-dd');
}

/**
 * PUBLIC server function (also callable from the client).
 * Returns the previous source date for a selected date.
 */
function calculatePreviousSourceDate(selectedDate) {
  try {
    var key = toDateKey_(selectedDate);
    if (!isValidDateKey_(key)) {
      return response_(false, 'INVALID_DATE', 'Select a valid allocation date.', null);
    }
    var prev = previousSourceDateKey_(key);
    return response_(true, 'OK', 'Previous source date calculated.', {
      selectedDate: key,
      selectedDateDisplay: formatDisplayDate_(key),
      previousSourceDate: prev,
      previousSourceDateDisplay: formatDisplayDate_(prev),
      timeZone: getAppTimeZone_()
    });
  } catch (err) {
    return handleServerError_('calculatePreviousSourceDate', err);
  }
}
