/**
 * AuditReportService.gs
 * Royal Metal Allocation System — Phase 3
 *
 * Administrator-only, READ ONLY access to the Metal Allocation Audit Log.
 * Writing is still done exclusively by AuditService.gs (Phase 1). Nothing here writes.
 *
 * Authorization is verified on the SERVER in every public function.
 * Hiding the tab in the browser is convenience, never protection.
 */

var AUDIT_REPORT_CONFIG = {
  MAX_ROWS_RETURNED: 500,      // audit rows sent to the browser in one response
  DEFAULT_RANGE_DAYS: 90,      // default allocation-date look-back
  MAX_REASON_PREVIEW: 140      // characters of reason shown in the list view
};

/* ------------------------------------------------------------------ */
/* Authorization                                                       */
/* ------------------------------------------------------------------ */

/**
 * Throws unless the signed-in user is a configured administrator.
 * The audit log contains user emails and full data snapshots, so it is
 * never exposed to regular users.
 */
function assertAuditAccess_() {
  var email = getActiveUserEmail_();
  if (!isAdministrator_(email)) {
    throw appError_('NOT_AUTHORIZED',
      'The audit log is restricted to authorized administrators.');
  }
  return email;
}

/**
 * DIAGNOSTIC — run this manually from the Apps Script editor when the
 * Audit Log tab does not appear. It reports exactly why the server does or
 * does not treat you as an administrator. Read the result in the execution log.
 * This function is safe: it reads nothing from the sheets and writes nothing.
 */
function diagnoseAdminAccess() {
  var report = {};

  try { report.activeUser = Session.getActiveUser().getEmail() || '(empty)'; }
  catch (e) { report.activeUser = '(blocked: ' + e + ')'; }

  try { report.effectiveUser = Session.getEffectiveUser().getEmail() || '(empty)'; }
  catch (e) { report.effectiveUser = '(blocked: ' + e + ')'; }

  report.resolvedEmail = getActiveUserEmail_();
  report.scriptRunsAs = getEffectiveUserEmail_();
  report.configuredAdmins = (CONFIG.ADMIN_EMAILS || []).slice();
  report.forcedNonAdmins = (CONFIG.NON_ADMIN_EMAILS || []).slice();
  report.deniedByList = emailInList_(report.resolvedEmail, CONFIG.NON_ADMIN_EMAILS);
  report.isAdministrator = isAdministrator_(report.resolvedEmail);

  report.diagnosis = [];

  if (report.deniedByList) {
    report.diagnosis.push(
      'This email is in CONFIG.NON_ADMIN_EMAILS, so admin rights are denied ' +
      'regardless of the admin list. Remove it from that list to restore access.');
  }
  if (report.resolvedEmail === 'unknown') {
    report.diagnosis.push(
      'The signed-in email could not be resolved, so this session has no admin rights. ' +
      'Redeploy with Execute as: "User accessing the web app", or set Access to ' +
      '"Anyone within your organisation" so Google reveals the caller identity.');
  }
  var placeholderOnly = report.configuredAdmins.every(function (a) {
    return String(a || '').indexOf('@yourcompany.com') >= 0;
  });
  if (placeholderOnly) {
    report.diagnosis.push(
      'CONFIG.ADMIN_EMAILS still contains only the placeholder address. ' +
      'Replace it with your real Google account email in Config.gs.');
  }
  if (!report.isAdministrator && report.resolvedEmail !== 'unknown' && !placeholderOnly) {
    report.diagnosis.push(
      'Your email "' + report.resolvedEmail + '" is not in CONFIG.ADMIN_EMAILS. ' +
      'Add it exactly as shown (spelling and domain must match).');
  }
  if (report.isAdministrator) {
    report.diagnosis.push(
      'Administrator access is correctly configured. If the Audit Log tab is still ' +
      'missing in the browser, the deployment is serving an older version: go to ' +
      'Deploy > Manage deployments > Edit > Version: New version > Deploy.');
  }

  console.log(CONFIG.LOG_PREFIX + ' ADMIN DIAGNOSTIC\n' + JSON.stringify(report, null, 2));
  return report;
}

/* ------------------------------------------------------------------ */
/* Snapshot decoding                                                   */
/* ------------------------------------------------------------------ */

/** Decodes an allocation snapshot into readable rows. Returns [] when empty/unparseable. */
function decodeAllocationSnapshot_(text) {
  var raw = String(text || '').trim();
  if (!raw) return [];
  try {
    var parsed = JSON.parse(raw);
    if (!parsed || !parsed.length) return [];
    return parsed.map(function (r) {
      return {
        priority: String(r.p === undefined ? '' : r.p),
        sector: String(r.s === undefined ? '' : r.s),
        sectorKey: normalizeSectorKey_(r.s),
        purity: String(r.pu === undefined ? '' : r.pu),
        previousRequirement: round3_(r.pr),
        todayRequired: round3_(r.tr),
        alloted: round3_(r.al),
        balance: round3_(r.bl)
      };
    });
  } catch (e) {
    console.error(CONFIG.LOG_PREFIX + ' allocation snapshot could not be parsed: ' + e);
    return [];
  }
}

/** Decodes a metal flow snapshot into readable rows. */
function decodeFlowSnapshot_(text) {
  var raw = String(text || '').trim();
  if (!raw) return [];
  try {
    var parsed = JSON.parse(raw);
    if (!parsed || !parsed.length) return [];
    return parsed.map(function (r) {
      return {
        sector: String(r.s === undefined ? '' : r.s),
        sectorKey: normalizeSectorKey_(r.s),
        acquired: round3_(r.ac)
      };
    });
  } catch (e) {
    console.error(CONFIG.LOG_PREFIX + ' flow snapshot could not be parsed: ' + e);
    return [];
  }
}

/** Sums the numeric columns of a decoded allocation snapshot. */
function snapshotAllocationTotals_(rows) {
  var t = { previousRequirement: 0, todayRequired: 0, alloted: 0, balance: 0, count: rows.length };
  rows.forEach(function (r) {
    t.previousRequirement += r.previousRequirement;
    t.todayRequired += r.todayRequired;
    t.alloted += r.alloted;
    t.balance += r.balance;
  });
  ['previousRequirement', 'todayRequired', 'alloted', 'balance'].forEach(function (k) {
    t[k] = round3_(t[k]);
  });
  return t;
}

/** Sums a decoded flow snapshot. */
function snapshotFlowTotals_(rows) {
  var total = 0;
  rows.forEach(function (r) { total += r.acquired; });
  return { acquired: round3_(total), count: rows.length };
}

/**
 * Builds a sector-keyed before/after comparison for allocation snapshots.
 * Sectors present in only one snapshot are still returned, with the missing
 * side null, so an added or removed sector is visible rather than silently dropped.
 */
function diffAllocationSnapshots_(beforeRows, afterRows) {
  var beforeMap = {}, afterMap = {}, order = [], seen = {};

  beforeRows.forEach(function (r) {
    beforeMap[r.sectorKey] = r;
    if (!seen[r.sectorKey]) { seen[r.sectorKey] = true; order.push({ key: r.sectorKey, sector: r.sector, priority: r.priority }); }
  });
  afterRows.forEach(function (r) {
    afterMap[r.sectorKey] = r;
    if (!seen[r.sectorKey]) { seen[r.sectorKey] = true; order.push({ key: r.sectorKey, sector: r.sector, priority: r.priority }); }
  });

  var fields = ['previousRequirement', 'todayRequired', 'alloted', 'balance'];

  return order.map(function (o) {
    var b = beforeMap[o.key] || null;
    var a = afterMap[o.key] || null;
    var changed = {};
    var anyChange = false;

    fields.forEach(function (f) {
      var bv = b ? b[f] : null;
      var av = a ? a[f] : null;
      var isChanged = (b && a) ? !nearlyEqual_(bv, av) : true;
      changed[f] = isChanged;
      if (isChanged) anyChange = true;
    });

    return {
      sector: o.sector,
      priority: o.priority,
      before: b,
      after: a,
      changed: changed,
      anyChange: anyChange,
      onlyBefore: !!(b && !a),
      onlyAfter: !!(a && !b)
    };
  });
}

/** Before/after comparison for metal flow snapshots. */
function diffFlowSnapshots_(beforeRows, afterRows) {
  var beforeMap = {}, afterMap = {}, order = [], seen = {};

  beforeRows.forEach(function (r) {
    beforeMap[r.sectorKey] = r;
    if (!seen[r.sectorKey]) { seen[r.sectorKey] = true; order.push({ key: r.sectorKey, sector: r.sector }); }
  });
  afterRows.forEach(function (r) {
    afterMap[r.sectorKey] = r;
    if (!seen[r.sectorKey]) { seen[r.sectorKey] = true; order.push({ key: r.sectorKey, sector: r.sector }); }
  });

  return order.map(function (o) {
    var b = beforeMap[o.key] || null;
    var a = afterMap[o.key] || null;
    var changed = (b && a) ? !nearlyEqual_(b.acquired, a.acquired) : true;
    return {
      sector: o.sector,
      before: b ? b.acquired : null,
      after: a ? a.acquired : null,
      changed: changed,
      onlyBefore: !!(b && !a),
      onlyAfter: !!(a && !b)
    };
  });
}

/* ------------------------------------------------------------------ */
/* Audit sheet reading                                                 */
/* ------------------------------------------------------------------ */

/**
 * Bulk read of the audit sheet. Returns [] when the sheet has not been created yet.
 * Snapshot columns are kept as raw text here and decoded only on demand.
 */
function readAuditRows_() {
  var sh = getSheetIfExists_(CONFIG.SHEETS.AUDIT);
  if (!sh) return [];

  var lastRow = sh.getLastRow();
  if (lastRow < 2) return [];

  var values = sh.getRange(2, 1, lastRow - 1, CONFIG.COLUMNS.AUDIT_COUNT).getValues();
  var rows = [];

  for (var i = 0; i < values.length; i++) {
    var v = values[i];
    var auditId = String(v[0] === null || v[0] === undefined ? '' : v[0]).trim();
    if (!auditId) continue;

    var timestamp = v[5];
    var isDate = Object.prototype.toString.call(timestamp) === '[object Date]';

    rows.push({
      rowNumber: i + 2,
      auditId: auditId,
      allocationDateKey: toDateKey_(v[1]),
      actionType: String(v[2] === null || v[2] === undefined ? '' : v[2]).trim(),
      revisionNumber: Number(v[3]) || 0,
      userEmail: String(v[4] === null || v[4] === undefined ? '' : v[4]).trim(),
      timestamp: isDate ? timestamp : null,
      timestampSort: isDate ? timestamp.getTime() : 0,
      reason: String(v[6] === null || v[6] === undefined ? '' : v[6]),
      beforeAllocationRaw: String(v[7] === null || v[7] === undefined ? '' : v[7]),
      afterAllocationRaw: String(v[8] === null || v[8] === undefined ? '' : v[8]),
      beforeFlowRaw: String(v[9] === null || v[9] === undefined ? '' : v[9]),
      afterFlowRaw: String(v[10] === null || v[10] === undefined ? '' : v[10]),
      requestId: String(v[11] === null || v[11] === undefined ? '' : v[11]).trim(),
      status: String(v[12] === null || v[12] === undefined ? '' : v[12]).trim()
    });
  }
  return rows;
}

/** Formats an audit timestamp for display. */
function formatAuditTimestamp_(date) {
  if (!date) return '';
  return Utilities.formatDate(date, getAppTimeZone_(), 'dd-MMM-yyyy HH:mm:ss');
}

/** Shortens a reason for the list view without breaking mid-escape. */
function previewReason_(text) {
  var s = String(text || '').replace(/\s+/g, ' ').trim();
  if (s.length <= AUDIT_REPORT_CONFIG.MAX_REASON_PREVIEW) return s;
  return s.substring(0, AUDIT_REPORT_CONFIG.MAX_REASON_PREVIEW - 1) + '\u2026';
}

/* ------------------------------------------------------------------ */
/* Public: filter options                                              */
/* ------------------------------------------------------------------ */

/** Distinct action types, statuses, users and the available date span. */
function getAuditFilterOptions() {
  try {
    assertAuditAccess_();
    var rows = readAuditRows_();

    var actionSeen = {}, actions = [];
    var statusSeen = {}, statuses = [];
    var userSeen = {}, users = [];
    var dateSeen = {}, dateKeys = [];

    rows.forEach(function (r) {
      if (r.actionType && !actionSeen[r.actionType]) { actionSeen[r.actionType] = true; actions.push(r.actionType); }
      if (r.status && !statusSeen[r.status]) { statusSeen[r.status] = true; statuses.push(r.status); }
      if (r.userEmail && !userSeen[r.userEmail]) { userSeen[r.userEmail] = true; users.push(r.userEmail); }
      if (r.allocationDateKey && !dateSeen[r.allocationDateKey]) {
        dateSeen[r.allocationDateKey] = true;
        dateKeys.push(r.allocationDateKey);
      }
    });

    actions.sort();
    statuses.sort();
    users.sort();
    dateKeys.sort();

    var latest = dateKeys.length ? dateKeys[dateKeys.length - 1] : todayKey_();
    var suggestedFrom = shiftDateKey_(latest, -(AUDIT_REPORT_CONFIG.DEFAULT_RANGE_DAYS - 1));
    if (dateKeys.length && suggestedFrom < dateKeys[0]) suggestedFrom = dateKeys[0];

    return response_(true, 'OK', 'Audit filter options loaded.', {
      actions: actions,
      statuses: statuses,
      users: users,
      entryCount: rows.length,
      minDate: dateKeys.length ? dateKeys[0] : '',
      maxDate: dateKeys.length ? latest : '',
      suggestedFrom: suggestedFrom,
      suggestedTo: latest,
      sheetExists: !!getSheetIfExists_(CONFIG.SHEETS.AUDIT)
    });
  } catch (err) {
    return handleServerError_('getAuditFilterOptions', err);
  }
}

/* ------------------------------------------------------------------ */
/* Public: audit list                                                  */
/* ------------------------------------------------------------------ */

/**
 * Filtered audit entries, newest first.
 * @param {Object} filters {fromDate,toDate,actionType,status,user,search,limit}
 */
function getAuditLog(filters) {
  try {
    assertAuditAccess_();

    var f = filters || {};
    var from = toDateKey_(f.fromDate);
    var to = toDateKey_(f.toDate);
    if (from && !isValidDateKey_(from)) from = '';
    if (to && !isValidDateKey_(to)) to = '';
    if (from && to && from > to) { var swap = from; from = to; to = swap; }

    var actionType = String(f.actionType || 'all').trim();
    var status = String(f.status || 'all').trim();
    var user = String(f.user || 'all').trim().toLowerCase();
    var search = String(f.search || '').trim().toLowerCase();

    var limit = Number(f.limit);
    if (!isFinite(limit) || limit <= 0 || limit > AUDIT_REPORT_CONFIG.MAX_ROWS_RETURNED) {
      limit = AUDIT_REPORT_CONFIG.MAX_ROWS_RETURNED;
    }

    var rows = readAuditRows_();

    var matched = rows.filter(function (r) {
      // An entry with no allocation date (a hard failure before the date was
      // resolved) must not be hidden by a date window.
      if (r.allocationDateKey) {
        if (from && r.allocationDateKey < from) return false;
        if (to && r.allocationDateKey > to) return false;
      }
      if (actionType !== 'all' && r.actionType !== actionType) return false;
      if (status !== 'all' && r.status !== status) return false;
      if (user !== 'all' && r.userEmail.toLowerCase() !== user) return false;
      if (search) {
        var hay = (r.auditId + ' ' + r.userEmail + ' ' + r.reason + ' ' +
          r.requestId + ' ' + r.actionType).toLowerCase();
        if (hay.indexOf(search) < 0) return false;
      }
      return true;
    });

    matched.sort(function (a, b) {
      if (b.timestampSort !== a.timestampSort) return b.timestampSort - a.timestampSort;
      return b.rowNumber - a.rowNumber;
    });

    var counts = { total: matched.length, success: 0, blocked: 0, failed: 0, revisions: 0 };
    matched.forEach(function (r) {
      if (r.status === 'SUCCESS') counts.success++;
      else if (r.status === 'BLOCKED') counts.blocked++;
      else if (r.status === 'FAILED') counts.failed++;
      if (r.actionType === 'REVISE') counts.revisions++;
    });

    var truncated = matched.length > limit;
    var page = truncated ? matched.slice(0, limit) : matched;

    return response_(true, 'OK', matched.length + ' audit entries matched.', {
      rows: page.map(function (r) {
        return {
          auditId: r.auditId,
          allocationDateKey: r.allocationDateKey,
          allocationDateDisplay: r.allocationDateKey ? formatDisplayDate_(r.allocationDateKey) : '\u2014',
          actionType: r.actionType,
          revisionNumber: r.revisionNumber,
          userEmail: r.userEmail,
          timestampDisplay: formatAuditTimestamp_(r.timestamp),
          reasonPreview: previewReason_(r.reason),
          requestId: r.requestId,
          status: r.status,
          hasSnapshots: !!(r.beforeAllocationRaw || r.afterAllocationRaw ||
                           r.beforeFlowRaw || r.afterFlowRaw)
        };
      }),
      summary: {
        recordCount: matched.length,
        returnedCount: page.length,
        truncated: truncated,
        counts: counts
      }
    });
  } catch (err) {
    return handleServerError_('getAuditLog', err);
  }
}

/* ------------------------------------------------------------------ */
/* Public: single entry detail with decoded snapshots                  */
/* ------------------------------------------------------------------ */

/** Full decoded detail for one audit entry, including the before/after comparison. */
function getAuditEntryDetail(auditId) {
  try {
    assertAuditAccess_();

    var wanted = String(auditId || '').trim();
    if (!wanted) {
      return response_(false, 'INVALID_AUDIT_ID', 'No audit entry was specified.', null);
    }

    var rows = readAuditRows_();
    var entry = null;
    for (var i = 0; i < rows.length; i++) {
      if (rows[i].auditId === wanted) { entry = rows[i]; break; }
    }
    if (!entry) {
      return response_(false, 'AUDIT_ENTRY_NOT_FOUND',
        'That audit entry no longer exists in the log.', null);
    }

    var beforeAlloc = decodeAllocationSnapshot_(entry.beforeAllocationRaw);
    var afterAlloc = decodeAllocationSnapshot_(entry.afterAllocationRaw);
    var beforeFlow = decodeFlowSnapshot_(entry.beforeFlowRaw);
    var afterFlow = decodeFlowSnapshot_(entry.afterFlowRaw);

    var allocationDiff = diffAllocationSnapshots_(beforeAlloc, afterAlloc);
    var flowDiff = diffFlowSnapshots_(beforeFlow, afterFlow);

    var changedSectors = allocationDiff.filter(function (d) { return d.anyChange; }).length;
    var changedFlowSectors = flowDiff.filter(function (d) { return d.changed; }).length;

    return response_(true, 'OK', 'Audit entry loaded.', {
      auditId: entry.auditId,
      allocationDateKey: entry.allocationDateKey,
      allocationDateDisplay: entry.allocationDateKey ? formatDisplayDate_(entry.allocationDateKey) : '\u2014',
      actionType: entry.actionType,
      revisionNumber: entry.revisionNumber,
      userEmail: entry.userEmail,
      timestampDisplay: formatAuditTimestamp_(entry.timestamp),
      reason: entry.reason,
      requestId: entry.requestId,
      status: entry.status,
      hasBefore: beforeAlloc.length > 0 || beforeFlow.length > 0,
      hasAfter: afterAlloc.length > 0 || afterFlow.length > 0,
      allocationDiff: allocationDiff,
      flowDiff: flowDiff,
      totals: {
        beforeAllocation: snapshotAllocationTotals_(beforeAlloc),
        afterAllocation: snapshotAllocationTotals_(afterAlloc),
        beforeFlow: snapshotFlowTotals_(beforeFlow),
        afterFlow: snapshotFlowTotals_(afterFlow)
      },
      changedSectors: changedSectors,
      changedFlowSectors: changedFlowSectors
    });
  } catch (err) {
    return handleServerError_('getAuditEntryDetail', err);
  }
}

/* ------------------------------------------------------------------ */
/* Public: revision awareness for the Daily Allocation screen          */
/* ------------------------------------------------------------------ */

/**
 * Lightweight revision summary for one allocation date.
 * Safe for every user: returns counts and timestamps only, never snapshots.
 * Returns a zeroed summary rather than an error when the audit sheet is absent.
 */
function getDateRevisionSummary(selectedDate) {
  try {
    var dateKey = toDateKey_(selectedDate);
    if (!isValidDateKey_(dateKey)) {
      return response_(false, 'INVALID_DATE', 'Select a valid allocation date.', null);
    }

    var rows = readAuditRows_().filter(function (r) {
      return r.allocationDateKey === dateKey && r.status === 'SUCCESS';
    });

    var revisions = rows.filter(function (r) { return r.actionType === 'REVISE'; });
    revisions.sort(function (a, b) { return b.timestampSort - a.timestampSort; });

    var saves = rows.filter(function (r) { return r.actionType === 'SAVE'; });
    saves.sort(function (a, b) { return a.timestampSort - b.timestampSort; });

    var latest = revisions.length ? revisions[0] : null;
    var original = saves.length ? saves[0] : null;

    return response_(true, 'OK',
      revisions.length ? ('This date has been revised ' + revisions.length + ' time(s).')
                       : 'This date has not been revised.',
      {
        allocationDate: dateKey,
        revisionCount: revisions.length,
        latestRevisionNumber: latest ? latest.revisionNumber : 0,
        lastRevisedBy: latest ? latest.userEmail : '',
        lastRevisedAt: latest ? formatAuditTimestamp_(latest.timestamp) : '',
        lastRevisionReason: latest ? latest.reason : '',
        originallySavedBy: original ? original.userEmail : '',
        originallySavedAt: original ? formatAuditTimestamp_(original.timestamp) : ''
      });
  } catch (err) {
    return handleServerError_('getDateRevisionSummary', err);
  }
}


/** Build marker. Used by checkInstalledFiles() to detect a stale paste. */
function buildTag_AuditReportService_() { return '5C'; }
