/**
 * Code.gs
 * Royal Metal Allocation System — Phase 1
 *
 * Web app entry points and orchestration.
 * Every public function returns the structured envelope {ok, code, message, data}.
 */

/* ------------------------------------------------------------------ */
/* HTML Service entry points                                           */
/* ------------------------------------------------------------------ */

function doGet(e) {
  var template = HtmlService.createTemplateFromFile('Index');
  template.appName = CONFIG.APP_NAME;
  return template.evaluate()
    .setTitle(CONFIG.APP_NAME)
    .addMetaTag('viewport', 'width=device-width, initial-scale=1, viewport-fit=cover')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

/** Used by Index.html to inline Styles.html and Scripts.html. */
function include(filename) {
  return HtmlService.createHtmlOutputFromFile(filename).getContent();
}

/* ------------------------------------------------------------------ */
/* Setup                                                               */
/* ------------------------------------------------------------------ */

/**
 * One-time setup / health check. Run manually from the Apps Script editor.
 * Creates the Audit Log sheet if absent, adds master headers only when row 1 is empty,
 * and verifies the sector definitions. Example and Metal Allocation Working are untouched.
 */
function setupMetalAllocationApp() {
  var report = { checks: [], warnings: [], created: [] };
  try {
    var ss = getSpreadsheet_();
    report.spreadsheet = ss.getName();
    report.timeZone = getAppTimeZone_();

    [CONFIG.SHEETS.GENERATOR, CONFIG.SHEETS.MASTER, CONFIG.SHEETS.FLOW_MASTER].forEach(function (name) {
      var sh = ss.getSheetByName(name);
      report.checks.push(name + ': ' + (sh ? 'found' : 'MISSING'));
      if (!sh) report.warnings.push('Required sheet "' + name + '" is missing.');
    });

    CONFIG.SHEETS.PROTECTED_REFERENCE.forEach(function (name) {
      var sh = ss.getSheetByName(name);
      report.checks.push(name + ' (reference, not modified): ' + (sh ? 'found' : 'not found'));
    });

    var masterSheet = ss.getSheetByName(CONFIG.SHEETS.MASTER);
    if (masterSheet && ensureHeaderRow_(masterSheet, CONFIG.HEADERS.MASTER)) {
      report.created.push('Metal Master header row');
    }
    var flowSheet = ss.getSheetByName(CONFIG.SHEETS.FLOW_MASTER);
    if (flowSheet && ensureHeaderRow_(flowSheet, CONFIG.HEADERS.FLOW)) {
      report.created.push('Metal Flow Master header row');
    }

    var audit = ensureAuditSheet_();
    if (audit.created) report.created.push(CONFIG.SHEETS.AUDIT + ' sheet with headers');
    else report.checks.push(CONFIG.SHEETS.AUDIT + ': found (left unchanged)');

    var staging = ensureStagingSheet_();
    if (staging.created) report.created.push(CONFIG.SHEETS.STAGING + ' sheet with headers');
    else report.checks.push(CONFIG.SHEETS.STAGING + ': found (left unchanged)');

    invalidateSchemaCache_();
    var defs = getSectorDefinitions_();
    report.detectedSchema = describeDetectedSchema();
    report.checks.push('Allocation sectors read: ' + defs.allocationSectors.length);
    report.checks.push('Parties detected: ' + defs.parties.map(function (p) { return p.party; }).join(', '));
    report.checks.push('Metal Flow sectors read: ' + defs.flowSectors.length);
    report.allocationSectors = defs.allocationSectors.map(function (d) { return d.priority + ' | ' + d.sector + ' | ' + d.purity; });
    report.flowSectors = defs.flowSectors.map(function (d) { return d.sector; });

    var admins = (CONFIG.ADMIN_EMAILS || []).filter(function (a) {
      return a && a.indexOf('@yourcompany.com') === -1;
    });
    if (!admins.length) {
      report.warnings.push('CONFIG.ADMIN_EMAILS still contains only the placeholder address. Set a real administrator email.');
    }

    console.log(CONFIG.LOG_PREFIX + ' setup report: ' + JSON.stringify(report));
    return response_(true, 'OK', 'Setup completed. Review the report for warnings.', report);
  } catch (err) {
    return handleServerError_('setupMetalAllocationApp', err);
  }
}

/* ------------------------------------------------------------------ */
/* Access                                                              */
/* ------------------------------------------------------------------ */

/** Server-verified access level for the signed-in user. */
function getCurrentUserAccess() {
  try {
    var email = getActiveUserEmail_();
    return response_(true, 'OK', 'Access resolved.', {
      email: email,
      displayName: getDisplayName_(email),
      isAdmin: isAdministrator_(email)
    });
  } catch (err) {
    return handleServerError_('getCurrentUserAccess', err);
  }
}

/* ------------------------------------------------------------------ */
/* Bootstrap and loading                                               */
/* ------------------------------------------------------------------ */

/** Everything the client needs on first paint. */
function getAppBootstrapData() {
  try {
    var email = getActiveUserEmail_();
    var scope = getUserScope_(email);
    var scoped = scopedSectorNames_(scope);
    return response_(true, 'OK', 'Bootstrap data loaded.', {
      config: getPublicConfig_(),
      access: {
        email: email,
        displayName: scope.displayName,
        isAdmin: scope.isAdmin,
        role: scope.role,
        hasScope: scope.isAdmin || scope.parties.length > 0
      },
      timeZone: getAppTimeZone_(),
      today: todayKey_(),
      parties: scope.parties,
      role: scope.role,
      allocationSectors: scoped.allocation.map(function (d) {
        return { priority: d.priority, party: d.party, sector: d.sector, purity: d.purity };
      }),
      flowSectors: scoped.flow.map(function (d) {
        return { sector: d.sector, party: d.party };
      })
    });
  } catch (err) {
    return handleServerError_('getAppBootstrapData', err);
  }
}

/** Quick duplicate-date probe used by the UI before it enables Save. */
function checkDateAlreadySaved(selectedDate) {
  try {
    var dateKey = toDateKey_(selectedDate);
    if (!isValidDateKey_(dateKey)) {
      return response_(false, 'INVALID_DATE', 'Select a valid allocation date.', null);
    }
    var exists = dateExistsInMaster_(dateKey, true);
    return response_(true, exists ? 'DATE_ALREADY_SAVED' : 'DATE_AVAILABLE',
      exists ? 'Data Already Saved.' : 'This date has not been saved yet.',
      { selectedDate: dateKey, isSaved: exists });
  } catch (err) {
    return handleServerError_('checkDateAlreadySaved', err);
  }
}

/** Full Daily Allocation screen model for a date. */
function getAllocationForDate(selectedDate) {
  try {
    var dateKey = toDateKey_(selectedDate);
    if (!isValidDateKey_(dateKey)) {
      return response_(false, 'INVALID_DATE', 'Select a valid allocation date.', null);
    }

    invalidateDataCache_();
    var model = buildAllocationModel_(dateKey);
    var email = getActiveUserEmail_();
    var scope = getUserScope_(email);
    var isAdmin = scope.isAdmin;

    if (!isAdmin && !scope.parties.length) {
      return response_(false, 'NO_PARTY_ASSIGNED',
        'No party is assigned to your account. Contact the administrator.', null);
    }

    // Trim the model to the caller's party BEFORE it leaves the server.
    applyScopeToAllocationModel_(model, scope);

    // Overlay any operator submissions: read-only for the operator who sent
    // them, editable starting values for the administrator.
    applyStagingToModel_(model, scope, dateKey);

    model.access = {
      email: email, displayName: scope.displayName,
      isAdmin: isAdmin, role: scope.role
    };
    // Operators submit requirements; only administrators save a date.
    model.readOnly = model.isSaved || !isAdmin;
    model.canRevise = model.isSaved && isAdmin && CONFIG.RULES.ALLOW_ADMIN_REVISION;

    var code, message;
    if (model.isSaved) {
      code = 'DATE_ALREADY_SAVED';
      message = 'Data Already Saved. This date is locked and cannot be saved again.';
    } else if (model.isSubmitted) {
      code = 'REQUIREMENT_SUBMITTED';
      message = 'Your requirement was submitted' +
        (model.submittedAt ? ' on ' + model.submittedAt : '') +
        ' and is awaiting the administrator. It cannot be changed.';
    } else if (model.stagingSubmissions && model.stagingSubmissions.length) {
      code = 'SUBMISSIONS_RECEIVED';
      message = model.stagingSubmissions.length +
        ' operator submission(s) loaded into this date. Adjust the figures, allocate, then save.';
    } else if (model.hasPreviousData) {
      code = 'OK';
      message = model.usedFallbackSource
        ? ('No records exist for ' + model.ruleSourceDateDisplay +
           '. Previous values carried forward from ' + model.previousSourceDateDisplay + '.')
        : 'Previous day values loaded.';
    } else {
      code = 'NO_PREVIOUS_DATA';
      message = 'No records found for ' + model.previousSourceDateDisplay +
        '. Previous values are shown as 0.000.';
    }

    return response_(true, code, message, model);
  } catch (err) {
    return handleServerError_('getAllocationForDate', err);
  }
}

/* ------------------------------------------------------------------ */
/* Save                                                                */
/* ------------------------------------------------------------------ */

/**
 * Saves one complete day: 19 Metal Master rows + 8 Metal Flow Master rows.
 * Immutable: an already-saved date is never updated, overwritten or appended to.
 */
function saveDailyAllocation(payload) {
  var lock = null;
  var requestId = (payload && payload.requestId) ? String(payload.requestId).substring(0, 80) : generateRequestId_();
  var cache = CacheService.getScriptCache();
  var cacheKey = 'req::' + requestId;

  try {
    // 0. Double-click / retry protection.
    if (cache.get(cacheKey)) {
      return response_(false, 'DUPLICATE_REQUEST',
        'This save request was already submitted. Reload the date to confirm the result.', null);
    }

    // 0b. Only administrators may finalise a date. Operators submit requirements.
    if (!isAdministrator_(getActiveUserEmail_())) {
      return response_(false, 'NOT_AUTHORIZED',
        'Only an administrator can save a date. Submit your requirement instead.', null);
    }

    // 1. Validate the payload against the live sector definitions.
    var defs = getSectorDefinitions_();
    var normalized = validateAndNormalizePayload_(payload, defs);
    assertSaveRules_(normalized);

    // 2. Acquire the script lock.
    lock = LockService.getScriptLock();
    if (!lock.tryLock(CONFIG.LOCK_TIMEOUT_MS)) {
      return response_(false, 'LOCK_TIMEOUT',
        'Another save is currently running. Wait a few seconds and try again.', null);
    }

    cache.put(cacheKey, '1', CONFIG.REQUEST_ID_TTL_SECONDS);

    // 3+4. Re-read and re-check the duplicate date AFTER acquiring the lock.
    invalidateDataCache_();
    if (dateExistsInMaster_(normalized.dateKey, true)) {
      writeAuditEntry_({
        dateKey: normalized.dateKey,
        actionType: AUDIT_ACTIONS.BLOCKED_DUPLICATE,
        revisionNumber: 0,
        reason: 'Duplicate save attempt blocked.',
        requestId: requestId,
        status: AUDIT_STATUS.BLOCKED
      });
      return response_(false, 'DATE_ALREADY_SAVED',
        'Data Already Saved. This date is locked and cannot be saved again. Select a new date.',
        { selectedDate: normalized.dateKey });
    }

    // 5+6. Prepare both datasets before writing either one.
    var masterValues = buildMasterRowValues_(normalized.dateKey, normalized.allocations);
    var flowValues = buildFlowRowValues_(normalized.dateKey, normalized.metalFlow);

    if (masterValues.length !== CONFIG.EXPECTED.ALLOCATION_ROWS ||
        flowValues.length !== CONFIG.EXPECTED.FLOW_ROWS) {
      throw appError_('ROW_COUNT_MISMATCH',
        'The prepared records did not match the expected counts. Nothing was saved.');
    }

    // 7+8. Write both masters with rollback protection.
    var writeResult = appendBothMasters_(masterValues, flowValues);
    invalidateDataCache_();

    // Release the operator submissions this save consumed. Never fatal.
    var consumedRows = 0;
    try { consumedRows = markStagingConsumed_(normalized.dateKey); } catch (ignore) { consumedRows = 0; }

    // 9. Audit the successful save.
    var auditId = writeAuditEntry_({
      dateKey: normalized.dateKey,
      actionType: AUDIT_ACTIONS.SAVE,
      revisionNumber: 0,
      reason: 'Initial daily allocation save.',
      beforeAllocation: '',
      afterAllocation: snapshotAllocations_(normalized.allocations),
      beforeFlow: '',
      afterFlow: snapshotMetalFlow_(normalized.metalFlow),
      requestId: requestId,
      status: AUDIT_STATUS.SUCCESS
    });

    return response_(true, 'SAVED',
      'Data saved successfully. ' + writeResult.masterCount + ' allocation records and ' +
      writeResult.flowCount + ' Metal Flow records were created.',
      {
        selectedDate: normalized.dateKey,
        selectedDateDisplay: formatDisplayDate_(normalized.dateKey),
        masterRecords: writeResult.masterCount,
        flowRecords: writeResult.flowCount,
        stagingRowsConsumed: consumedRows,
        totals: normalized.totals,
        auditId: auditId,
        requestId: requestId
      });

  } catch (err) {
    try {
      cache.remove(cacheKey);   // allow a corrected retry
      writeAuditEntry_({
        dateKey: toDateKey_(payload && payload.selectedDate),
        actionType: AUDIT_ACTIONS.FAILED_SAVE,
        revisionNumber: 0,
        reason: (err && (err.userMessage || err.message)) || 'Unknown failure',
        requestId: requestId,
        status: AUDIT_STATUS.FAILED
      });
    } catch (ignore) { /* never mask the original error */ }
    return handleServerError_('saveDailyAllocation', err);
  } finally {
    // 11. Always release the lock.
    if (lock) {
      try { lock.releaseLock(); } catch (ignore) { /* nothing to do */ }
    }
  }
}

/* ------------------------------------------------------------------ */
/* Administrator revision                                              */
/* ------------------------------------------------------------------ */

/**
 * Controlled Edit Saved Date workflow. Administrators only, verified server side.
 * Replaces the stored rows for the date in both masters within one locked operation,
 * after capturing a before-snapshot in the audit log.
 */
function reviseDailyAllocation(payload) {
  var lock = null;
  var requestId = (payload && payload.requestId) ? String(payload.requestId).substring(0, 80) : generateRequestId_();
  var email = getActiveUserEmail_();

  try {
    if (!CONFIG.RULES.ALLOW_ADMIN_REVISION) {
      return response_(false, 'REVISION_DISABLED', 'Saved dates are currently immutable. Revision is disabled.', null);
    }

    // Server-side authorization. The UI flag is never trusted.
    if (!isAdministrator_(email)) {
      writeAuditEntry_({
        dateKey: toDateKey_(payload && payload.selectedDate),
        actionType: AUDIT_ACTIONS.UNAUTHORIZED_REVISION,
        revisionNumber: 0,
        userEmail: email,
        reason: 'Revision attempted without administrator authorization.',
        requestId: requestId,
        status: AUDIT_STATUS.BLOCKED
      });
      return response_(false, 'NOT_AUTHORIZED',
        'You are not authorized to revise a saved date. Contact an administrator.', null);
    }

    var reason = assertRevisionReason_(payload && payload.revisionReason);

    var defs = getSectorDefinitions_();
    var normalized = validateAndNormalizePayload_(payload, defs);
    assertSaveRules_(normalized);

    lock = LockService.getScriptLock();
    if (!lock.tryLock(CONFIG.LOCK_TIMEOUT_MS)) {
      return response_(false, 'LOCK_TIMEOUT',
        'Another operation is currently running. Wait a few seconds and try again.', null);
    }

    invalidateDataCache_();
    var masterRows = readMasterRows_(true);
    var flowRows = readFlowMasterRows_(true);

    var existingMaster = masterRows.filter(function (r) { return r.dateKey === normalized.dateKey; });
    var existingFlow = flowRows.filter(function (r) { return r.dateKey === normalized.dateKey; });

    if (!existingMaster.length) {
      return response_(false, 'DATE_NOT_SAVED',
        'This date has not been saved yet, so there is nothing to revise. Use Save Current Data instead.', null);
    }

    var beforeAllocation = snapshotStoredMaster_(existingMaster);
    var beforeFlow = snapshotStoredFlow_(existingFlow);
    var revisionNumber = getLatestRevisionNumber_(normalized.dateKey) + 1;
    var auditId = generateAuditId_();

    var masterSheet = getSheetOrThrow_(CONFIG.SHEETS.MASTER);
    var flowSheet = getSheetOrThrow_(CONFIG.SHEETS.FLOW_MASTER);

    var removedMaster = [];
    var removedFlow = [];

    try {
      removedMaster = deleteRowsForDate_(masterSheet, masterRows, normalized.dateKey, CONFIG.COLUMNS.MASTER_COUNT);
      removedFlow = deleteRowsForDate_(flowSheet, flowRows, normalized.dateKey, CONFIG.COLUMNS.FLOW_COUNT);

      var masterValues = buildMasterRowValues_(normalized.dateKey, normalized.allocations);
      var flowValues = buildFlowRowValues_(normalized.dateKey, normalized.metalFlow);
      appendBothMasters_(masterValues, flowValues);
    } catch (revErr) {
      // Restore the exact rows that were removed.
      try {
        appendRawRows_(masterSheet, removedMaster, CONFIG.COLUMNS.MASTER_COUNT);
        appendRawRows_(flowSheet, removedFlow, CONFIG.COLUMNS.FLOW_COUNT);
      } catch (restoreErr) {
        console.error(CONFIG.LOG_PREFIX + ' REVISION RESTORE FAILED for ' + normalized.dateKey + ': ' + restoreErr);
        writeAuditEntry_({
          auditId: auditId, dateKey: normalized.dateKey, actionType: AUDIT_ACTIONS.FAILED_REVISION,
          revisionNumber: revisionNumber, userEmail: email, reason: reason,
          beforeAllocation: beforeAllocation, beforeFlow: beforeFlow,
          requestId: requestId, status: AUDIT_STATUS.FAILED
        });
        throw appError_('REVISION_RESTORE_FAILED',
          'The revision failed and the original rows could not be restored automatically. ' +
          'Use the audit log snapshot to recover before retrying.', String(restoreErr));
      }
      throw appError_('REVISION_FAILED',
        'The revision could not be completed. The previously saved data was restored.', String(revErr));
    }

    invalidateDataCache_();

    writeAuditEntry_({
      auditId: auditId,
      dateKey: normalized.dateKey,
      actionType: AUDIT_ACTIONS.REVISE,
      revisionNumber: revisionNumber,
      userEmail: email,
      reason: reason,
      beforeAllocation: beforeAllocation,
      afterAllocation: snapshotAllocations_(normalized.allocations),
      beforeFlow: beforeFlow,
      afterFlow: snapshotMetalFlow_(normalized.metalFlow),
      requestId: requestId,
      status: AUDIT_STATUS.SUCCESS
    });

    return response_(true, 'REVISED',
      'Revision ' + revisionNumber + ' saved successfully for ' + formatDisplayDate_(normalized.dateKey) + '.',
      {
        selectedDate: normalized.dateKey,
        revisionNumber: revisionNumber,
        auditId: auditId,
        totals: normalized.totals,
        requestId: requestId
      });

  } catch (err) {
    try {
      writeAuditEntry_({
        dateKey: toDateKey_(payload && payload.selectedDate),
        actionType: AUDIT_ACTIONS.FAILED_REVISION,
        revisionNumber: 0,
        userEmail: email,
        reason: (err && (err.userMessage || err.message)) || 'Unknown failure',
        requestId: requestId,
        status: AUDIT_STATUS.FAILED
      });
    } catch (ignore) { /* never mask the original error */ }
    return handleServerError_('reviseDailyAllocation', err);
  } finally {
    if (lock) {
      try { lock.releaseLock(); } catch (ignore) { /* nothing to do */ }
    }
  }
}


/** Build marker. Used by checkInstalledFiles() to detect a stale paste. */
function buildTag_Code_() { return '5C'; }
