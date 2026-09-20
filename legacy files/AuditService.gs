/**
 * AuditService.gs
 * Royal Metal Allocation System — Phase 1
 *
 * Writes to the separate "Metal Allocation Audit Log" sheet.
 * Metal Master and Metal Flow Master schemas are never extended with audit columns.
 */

var AUDIT_ACTIONS = {
  SAVE: 'SAVE',
  REVISE: 'REVISE',
  BLOCKED_DUPLICATE: 'BLOCKED_DUPLICATE',
  FAILED_SAVE: 'FAILED_SAVE',
  FAILED_REVISION: 'FAILED_REVISION',
  UNAUTHORIZED_REVISION: 'UNAUTHORIZED_REVISION'
};

var AUDIT_STATUS = {
  SUCCESS: 'SUCCESS',
  BLOCKED: 'BLOCKED',
  FAILED: 'FAILED'
};

/** Generates a unique audit identifier, e.g. AUD-20260818-104233-4821. */
function generateAuditId_() {
  var stamp = Utilities.formatDate(new Date(), getAppTimeZone_(), 'yyyyMMdd-HHmmss');
  var salt = String(Math.floor(1000 + Math.random() * 9000));
  return 'AUD-' + stamp + '-' + salt;
}

/** Generates a server-side request identifier when the client did not supply one. */
function generateRequestId_() {
  return 'REQ-' + Utilities.getUuid();
}

/**
 * Email of the person actually using the app, or 'unknown'.
 *
 * SECURITY: this must never fall back to Session.getEffectiveUser(). Under an
 * "Execute as: Me" deployment the effective user is the script owner, so that
 * fallback would hand every visitor the owner's identity and therefore the
 * owner's administrator rights. When the real user cannot be resolved we return
 * 'unknown', which is treated as a regular user with no admin access.
 */
function getActiveUserEmail_() {
  var email = '';
  try { email = Session.getActiveUser().getEmail() || ''; } catch (e) { email = ''; }
  return String(email).trim() || 'unknown';
}

/** Email of the account the script runs as. Diagnostics only, never authorization. */
function getEffectiveUserEmail_() {
  try { return Session.getEffectiveUser().getEmail() || 'unknown'; }
  catch (e) { return 'unknown'; }
}

/**
 * Short display name for the header.
 * Falls back to the local part of the email, capitalised, when the address is
 * not in CONFIG.USER_DISPLAY_NAMES. Never returns an empty string.
 */
function getDisplayName_(email) {
  var who = String(email || '').trim();
  if (!who || who === 'unknown') return 'Unknown user';

  var map = CONFIG.USER_DISPLAY_NAMES || {};
  var lower = who.toLowerCase();
  var keys = Object.keys(map);
  for (var i = 0; i < keys.length; i++) {
    if (String(keys[i]).trim().toLowerCase() === lower) {
      var name = String(map[keys[i]] || '').trim();
      if (name) return name;
    }
  }

  var local = lower.split('@')[0].replace(/[._-]+/g, ' ').trim();
  if (!local) return who;
  return local.split(' ').map(function (part) {
    return part ? part.charAt(0).toUpperCase() + part.slice(1) : part;
  }).join(' ');
}

/** True when the email appears in a configured list, compared case-insensitively. */
function emailInList_(email, list) {
  var who = String(email || '').trim().toLowerCase();
  if (!who || who === 'unknown') return false;
  var arr = list || [];
  for (var i = 0; i < arr.length; i++) {
    if (String(arr[i] || '').trim().toLowerCase() === who) return true;
  }
  return false;
}

/**
 * True when the signed-in user is an administrator. Server-side truth.
 *
 * Resolution order:
 *   1. Unresolved identity  -> NOT admin.
 *   2. Listed in NON_ADMIN_EMAILS -> NOT admin. An explicit denial always wins,
 *      even if the same address also appears in ADMIN_EMAILS.
 *   3. Listed in ADMIN_EMAILS -> admin.
 *   4. Everyone else -> NOT admin.
 */
function isAdministrator_(email) {
  var who = String(email || getActiveUserEmail_()).trim().toLowerCase();
  if (!who || who === 'unknown') return false;
  if (emailInList_(who, CONFIG.NON_ADMIN_EMAILS)) return false;
  return emailInList_(who, CONFIG.ADMIN_EMAILS);
}

/** Compact JSON snapshot of allocation rows (stored as text in the audit log). */
function snapshotAllocations_(allocations) {
  if (!allocations || !allocations.length) return '';
  return JSON.stringify(allocations.map(function (a) {
    return {
      p: a.priority,
      s: a.sector,
      pu: a.purity,
      pr: round3_(a.previousRequirement),
      tr: round3_(a.todayRequired),
      al: round3_(a.alloted),
      bl: round3_(a.balance)
    };
  }));
}

/** Compact JSON snapshot of metal flow rows. */
function snapshotMetalFlow_(metalFlow) {
  if (!metalFlow || !metalFlow.length) return '';
  return JSON.stringify(metalFlow.map(function (f) {
    return {
      s: f.sector,
      ac: round3_(f.todayAcquired !== undefined ? f.todayAcquired : f.acquired)
    };
  }));
}

/** Snapshot built directly from stored Metal Master rows. */
function snapshotStoredMaster_(rows) {
  if (!rows || !rows.length) return '';
  return JSON.stringify(rows.map(function (r) {
    return { p: r.priority, s: r.sector, pu: r.purity, pr: r.previousRequirement, tr: r.todayRequired, al: r.alloted, bl: r.balance };
  }));
}

/** Snapshot built directly from stored Metal Flow Master rows. */
function snapshotStoredFlow_(rows) {
  if (!rows || !rows.length) return '';
  return JSON.stringify(rows.map(function (r) { return { s: r.sector, ac: r.acquired }; }));
}

/** Highest revision number already recorded for a date (0 when never revised). */
function getLatestRevisionNumber_(dateKey) {
  var sh = getSheetIfExists_(CONFIG.SHEETS.AUDIT);
  if (!sh) return 0;
  var lastRow = sh.getLastRow();
  if (lastRow < 2) return 0;

  var values = sh.getRange(2, 1, lastRow - 1, CONFIG.COLUMNS.AUDIT_COUNT).getValues();
  var max = 0;
  for (var i = 0; i < values.length; i++) {
    if (toDateKey_(values[i][1]) !== dateKey) continue;
    if (String(values[i][12] || '') !== AUDIT_STATUS.SUCCESS) continue;
    var rev = Number(values[i][3]);
    if (isFinite(rev) && rev > max) max = rev;
  }
  return max;
}

/**
 * Appends one audit row.
 * @param {Object} entry {auditId, dateKey, actionType, revisionNumber, userEmail,
 *                        reason, beforeAllocation, afterAllocation, beforeFlow,
 *                        afterFlow, requestId, status}
 */
function writeAuditEntry_(entry) {
  try {
    var sh = ensureAuditSheet_().sheet;
    var row = [
      entry.auditId || generateAuditId_(),
      entry.dateKey ? dateKeyToStorageDate_(entry.dateKey) : '',
      entry.actionType || '',
      (entry.revisionNumber === null || entry.revisionNumber === undefined) ? 0 : entry.revisionNumber,
      entry.userEmail || getActiveUserEmail_(),
      new Date(),
      entry.reason || '',
      entry.beforeAllocation || '',
      entry.afterAllocation || '',
      entry.beforeFlow || '',
      entry.afterFlow || '',
      entry.requestId || '',
      entry.status || AUDIT_STATUS.SUCCESS
    ];
    sh.getRange(sh.getLastRow() + 1, 1, 1, CONFIG.COLUMNS.AUDIT_COUNT).setValues([row]);
    return row[0];
  } catch (err) {
    // Auditing must never block or reverse a completed business operation.
    console.error(CONFIG.LOG_PREFIX + ' AUDIT WRITE FAILED: ' + err + ' | entry=' + JSON.stringify({
      dateKey: entry && entry.dateKey, action: entry && entry.actionType
    }));
    return '';
  }
}


/** Build marker. Used by checkInstalledFiles() to detect a stale paste. */
function buildTag_AuditService_() { return '5C'; }
