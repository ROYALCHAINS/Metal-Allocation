/**
 * StagingService.gs
 * Royal Metal Allocation System — Phase 5B
 *
 * Two-stage workflow.
 *
 *   Stage 1  Operators submit Today's Required and Today's Acquired for the
 *            sectors belonging to their party. This writes ONLY to the
 *            "Metal Requirement Staging" sheet. Nothing reaches the masters.
 *
 *   Stage 2  An administrator pulls the staged values into the Daily Allocation
 *            screen, adjusts them, enters allocations, and performs the single
 *            atomic save that already exists. That save is unchanged: still
 *            full-allocation, still immutable, still audited.
 *
 * A submission is ONE SHOT. Once an operator submits for a date, that party is
 * locked for that date until an administrator saves it.
 */

/**
 * Additional audit actions used by the staging workflow.
 *
 * These are resolved lazily rather than assigned at file load. Apps Script
 * evaluates files in editor order, not alphabetically, so touching another
 * file's variable at load time makes the whole project sensitive to how the
 * files happen to be ordered.
 */
function stagingAuditAction_(name) {
  var actions = {
    SUBMIT_REQUIREMENT: 'SUBMIT_REQUIREMENT',
    BLOCKED_RESUBMISSION: 'BLOCKED_RESUBMISSION',
    FAILED_SUBMISSION: 'FAILED_SUBMISSION'
  };
  return actions[name] || name;
}

var STAGING_STATUS = {
  SUBMITTED: 'SUBMITTED',    // waiting for the administrator
  CONSUMED: 'CONSUMED'       // the administrator has saved this date
};

var RECORD_TYPE = {
  ALLOCATION: 'ALLOCATION',
  FLOW: 'FLOW'
};

/* Column positions within CONFIG.HEADERS.STAGING. */
var STAGING_COL = {
  SUBMISSION_ID: 1, DATE: 2, PARTY: 3, EMAIL: 4, SUBMITTED_AT: 5,
  RECORD_TYPE: 6, SECTOR: 7, VALUE: 8, STATUS: 9
};

/* ------------------------------------------------------------------ */
/* Sheet access                                                        */
/* ------------------------------------------------------------------ */

/** Creates the staging sheet with headers only if it does not already exist. */
function ensureStagingSheet_() {
  var ss = getSpreadsheet_();
  var sh = ss.getSheetByName(CONFIG.SHEETS.STAGING);
  var created = false;
  if (!sh) {
    sh = ss.insertSheet(CONFIG.SHEETS.STAGING);
    sh.getRange(1, 1, 1, CONFIG.HEADERS.STAGING.length).setValues([CONFIG.HEADERS.STAGING]);
    sh.getRange(1, 1, 1, CONFIG.HEADERS.STAGING.length).setFontWeight('bold');
    sh.setFrozenRows(1);
    created = true;
  }
  DS_CACHE_['sheet::' + CONFIG.SHEETS.STAGING] = sh;
  return { sheet: sh, created: created };
}

/** Bulk read of the staging sheet. Returns [] when it does not exist yet. */
function readStagingRows_() {
  var sh = getSheetIfExists_(CONFIG.SHEETS.STAGING);
  if (!sh) return [];

  var lastRow = sh.getLastRow();
  if (lastRow < 2) return [];

  var width = CONFIG.HEADERS.STAGING.length;
  var values = sh.getRange(2, 1, lastRow - 1, width).getValues();
  var rows = [];

  for (var i = 0; i < values.length; i++) {
    var v = values[i];
    var id = String(v[STAGING_COL.SUBMISSION_ID - 1] || '').trim();
    if (!id) continue;

    var party = String(v[STAGING_COL.PARTY - 1] || '').trim();
    var sector = String(v[STAGING_COL.SECTOR - 1] || '').trim();
    var submittedAt = v[STAGING_COL.SUBMITTED_AT - 1];

    rows.push({
      rowNumber: i + 2,
      submissionId: id,
      dateKey: toDateKey_(v[STAGING_COL.DATE - 1]),
      party: party,
      partyKey: normalizePartyKey_(party),
      operatorEmail: String(v[STAGING_COL.EMAIL - 1] || '').trim(),
      submittedAt: submittedAt,
      submittedAtDisplay: (Object.prototype.toString.call(submittedAt) === '[object Date]')
        ? Utilities.formatDate(submittedAt, getAppTimeZone_(), 'dd-MMM-yyyy HH:mm:ss') : '',
      recordType: String(v[STAGING_COL.RECORD_TYPE - 1] || '').trim(),
      sector: sector,
      sectorKey: normalizeSectorKey_(sector),
      value: toNumber_(v[STAGING_COL.VALUE - 1]),
      status: String(v[STAGING_COL.STATUS - 1] || '').trim()
    });
  }
  return rows;
}

/* ------------------------------------------------------------------ */
/* User scope                                                          */
/* ------------------------------------------------------------------ */

/**
 * Resolves which parties the signed-in user may act on.
 * Administrators are unrestricted. Operators are limited to the parties listed
 * in CONFIG.OPERATOR_PARTIES. A user in neither list has no scope at all.
 */
function getUserScope_(email) {
  var who = String(email || getActiveUserEmail_()).trim();
  var isAdmin = isAdministrator_(who);
  var allParties = readPartyDefinitions_();

  if (isAdmin) {
    return {
      email: who,
      displayName: getDisplayName_(who),
      isAdmin: true,
      role: 'ADMIN',
      partyKeys: allParties.map(function (p) { return p.partyKey; }),
      parties: allParties,
      flowSectorKeys: null,
      unrestricted: true
    };
  }

  var map = CONFIG.OPERATOR_PARTIES || {};
  var lower = who.toLowerCase();
  var assigned = null;
  var keys = Object.keys(map);
  for (var i = 0; i < keys.length; i++) {
    if (String(keys[i]).trim().toLowerCase() === lower) { assigned = map[keys[i]]; break; }
  }

  var wanted = (assigned || []).map(normalizePartyKey_).filter(String);
  var parties = allParties.filter(function (p) { return wanted.indexOf(p.partyKey) >= 0; });

  // Metal Flow is keyed by party name, so an operator can be mapped straight to
  // their flow sector(s). null means "fall back to the Party column".
  var flowMap = CONFIG.OPERATOR_FLOW_SECTORS || {};
  var flowAssigned = null;
  var flowKeys = Object.keys(flowMap);
  for (var f = 0; f < flowKeys.length; f++) {
    if (String(flowKeys[f]).trim().toLowerCase() === lower) { flowAssigned = flowMap[flowKeys[f]]; break; }
  }
  var flowSectorKeys = flowAssigned
    ? (flowAssigned || []).map(normalizeSectorKey_).filter(String)
    : null;

  return {
    email: who,
    displayName: getDisplayName_(who),
    isAdmin: false,
    role: 'OPERATOR',
    partyKeys: parties.map(function (p) { return p.partyKey; }),
    parties: parties,
    flowSectorKeys: flowSectorKeys,
    unrestricted: false
  };
}

/**
 * True when a METAL FLOW sector is inside the user's scope.
 * An explicit OPERATOR_FLOW_SECTORS list wins; otherwise the sector's party is used.
 */
function scopeAllowsFlow_(scope, sectorKey, partyKey) {
  if (scope.unrestricted) return true;
  if (scope.flowSectorKeys) return scope.flowSectorKeys.indexOf(sectorKey) >= 0;
  return scopeAllows_(scope, partyKey);
}

/** Keeps only the Metal Flow rows the user may see. */
function filterFlowRowsByScope_(rows, scope, map) {
  if (scope.unrestricted) return rows;
  return rows.filter(function (r) {
    return scopeAllowsFlow_(scope, r.sectorKey, rowPartyKey_(r, map));
  });
}

/** True when a party key is inside the user's scope. */
function scopeAllows_(scope, partyKey) {
  if (scope.unrestricted) return true;
  if (!partyKey) return false;
  return scope.partyKeys.indexOf(partyKey) >= 0;
}

/** Public: the signed-in user's role and party scope, with their scoped sectors. */
function getCurrentUserScope() {
  try {
    invalidateDataCache_();
    var scope = getUserScope_(getActiveUserEmail_());
    var defs = getSectorDefinitions_();

    var allocationSectors = defs.allocationSectors.filter(function (d) {
      return scopeAllows_(scope, d.partyKey);
    });
    var flowSectors = defs.flowSectors.filter(function (d) {
      return scopeAllowsFlow_(scope, d.sectorKey, d.partyKey);
    });

    return response_(true, 'OK', 'Scope resolved.', {
      email: scope.email,
      displayName: scope.displayName,
      role: scope.role,
      isAdmin: scope.isAdmin,
      parties: scope.parties,
      hasScope: scope.isAdmin || scope.parties.length > 0,
      allocationSectors: allocationSectors.map(function (d) {
        return { priority: d.priority, party: d.party, sector: d.sector, purity: d.purity };
      }),
      flowSectors: flowSectors.map(function (d) {
        return { sector: d.sector, party: d.party };
      })
    });
  } catch (err) {
    return handleServerError_('getCurrentUserScope', err);
  }
}

/* ------------------------------------------------------------------ */
/* Operator: load the submission screen                                */
/* ------------------------------------------------------------------ */

/**
 * The operator's view of a date: their sectors only, with any existing
 * submission and whether the date is locked to them.
 */
function getOperatorRequirementForDate(selectedDate) {
  try {
    var dateKey = toDateKey_(selectedDate);
    if (!isValidDateKey_(dateKey)) {
      return response_(false, 'INVALID_DATE', 'Select a valid allocation date.', null);
    }

    invalidateDataCache_();
    var scope = getUserScope_(getActiveUserEmail_());
    if (!scope.isAdmin && !scope.parties.length) {
      return response_(false, 'NO_PARTY_ASSIGNED',
        'No party is assigned to your account. Contact the administrator.', null);
    }

    var defs = getSectorDefinitions_();
    var prevKey = previousSourceDateKey_(dateKey);
    var masterIndex = indexByDateAndSector_(readMasterRows_(true));
    var flowIndex = indexByDateAndSector_(readFlowMasterRows_(true));

    var savedAlloc = masterIndex[dateKey] || null;
    var savedFlow = flowIndex[dateKey] || null;
    var prevAlloc = masterIndex[prevKey] || {};
    var prevFlow = flowIndex[prevKey] || {};
    var isFinalised = !!savedAlloc;

    var staging = readStagingRows_().filter(function (r) {
      return r.dateKey === dateKey && scopeAllows_(scope, r.partyKey);
    });
    var stagedByKey = {};
    staging.forEach(function (r) { stagedByKey[r.recordType + '::' + r.sectorKey] = r; });

    var submitted = staging.filter(function (r) { return r.status === STAGING_STATUS.SUBMITTED; });
    var consumed = staging.filter(function (r) { return r.status === STAGING_STATUS.CONSUMED; });
    var isSubmitted = submitted.length > 0;
    var submissionMeta = (submitted[0] || consumed[0]) || null;

    var allocations = defs.allocationSectors
      .filter(function (d) { return scopeAllows_(scope, d.partyKey); })
      .map(function (d) {
        var saved = isFinalised ? savedAlloc[d.sectorKey] : null;
        var carried = prevAlloc[d.sectorKey];
        var staged = stagedByKey[RECORD_TYPE.ALLOCATION + '::' + d.sectorKey];
        var previousRequirement = saved
          ? saved.previousRequirement
          : (carried ? round3_(carried.balance) : 0);
        return {
          priority: d.priority,
          party: d.party,
          sector: d.sector,
          sectorKey: d.sectorKey,
          purity: d.purity,
          previousRequirement: previousRequirement,
          // Finalised figures win; otherwise show what was submitted.
          todayRequired: saved ? saved.todayRequired : (staged ? staged.value : 0),
          alloted: saved ? saved.alloted : 0,          // read-only for operators
          balance: saved ? saved.balance : round3_(previousRequirement),
          isFinalised: isFinalised
        };
      });

    var metalFlow = defs.flowSectors
      .filter(function (d) { return scopeAllowsFlow_(scope, d.sectorKey, d.partyKey); })
      .map(function (d) {
        var saved = savedFlow ? savedFlow[d.sectorKey] : null;
        var carried = prevFlow[d.sectorKey];
        var staged = stagedByKey[RECORD_TYPE.FLOW + '::' + d.sectorKey];
        return {
          sector: d.sector,
          sectorKey: d.sectorKey,
          party: d.party,
          previousAcquired: carried ? round3_(carried.acquired) : 0,
          todayAcquired: saved ? saved.acquired : (staged ? staged.value : 0),
          isFinalised: isFinalised
        };
      });

    var totalRequired = 0, totalAcquired = 0;
    allocations.forEach(function (a) { totalRequired += a.todayRequired; });
    metalFlow.forEach(function (f) { totalAcquired += f.todayAcquired; });

    var code, message;
    if (isFinalised) {
      code = 'FINALISED';
      message = 'The administrator has finalised this date. These are the final figures.';
    } else if (isSubmitted) {
      code = 'ALREADY_SUBMITTED';
      message = 'Your requirement was submitted on ' +
        (submissionMeta ? submissionMeta.submittedAtDisplay : '') +
        ' and is awaiting the administrator. It cannot be changed.';
    } else {
      code = 'OPEN';
      message = 'Enter your requirement and acquired metal, then submit.';
    }

    return response_(true, code, message, {
      selectedDate: dateKey,
      selectedDateDisplay: formatDisplayDate_(dateKey),
      previousSourceDate: prevKey,
      previousSourceDateDisplay: formatDisplayDate_(prevKey),
      role: scope.role,
      parties: scope.parties,
      allocations: allocations,
      metalFlow: metalFlow,
      isSubmitted: isSubmitted,
      isFinalised: isFinalised,
      readOnly: isSubmitted || isFinalised,
      submittedAt: submissionMeta ? submissionMeta.submittedAtDisplay : '',
      submittedBy: submissionMeta ? submissionMeta.operatorEmail : '',
      submissionId: submissionMeta ? submissionMeta.submissionId : '',
      totals: {
        totalRequired: round3_(totalRequired),
        totalAcquired: round3_(totalAcquired)
      }
    });
  } catch (err) {
    return handleServerError_('getOperatorRequirementForDate', err);
  }
}

/* ------------------------------------------------------------------ */
/* Operator: submit                                                    */
/* ------------------------------------------------------------------ */

/**
 * Submits one party's requirement for a date. ONE SHOT: once submitted the
 * party is locked for that date until an administrator saves it.
 */
function submitOperatorRequirements(payload) {
  var lock = null;
  var requestId = (payload && payload.requestId)
    ? String(payload.requestId).substring(0, 80) : generateRequestId_();
  var cache = CacheService.getScriptCache();
  var cacheKey = 'sub::' + requestId;
  var email = getActiveUserEmail_();

  try {
    if (cache.get(cacheKey)) {
      return response_(false, 'DUPLICATE_REQUEST',
        'This submission was already sent. Reload the date to confirm.', null);
    }

    var dateKey = toDateKey_(payload && payload.selectedDate);
    if (!isValidDateKey_(dateKey)) {
      return response_(false, 'INVALID_DATE', 'Select a valid allocation date.', null);
    }

    invalidateDataCache_();
    var scope = getUserScope_(email);
    if (!scope.parties.length && !scope.isAdmin) {
      return response_(false, 'NO_PARTY_ASSIGNED',
        'No party is assigned to your account. Contact the administrator.', null);
    }
    if (scope.isAdmin) {
      return response_(false, 'ADMIN_CANNOT_SUBMIT',
        'Administrators finalise dates directly on the Daily Allocation screen rather than submitting requirements.', null);
    }

    var defs = getSectorDefinitions_();

    // Index what was sent, then rebuild strictly from the sheet definitions so a
    // client can never introduce a sector or a party it does not own.
    var sentAlloc = {}, sentFlow = {};
    ((payload && payload.allocations) || []).forEach(function (r) {
      var k = normalizeSectorKey_(r && r.sector);
      if (k) sentAlloc[k] = r;
    });
    ((payload && payload.metalFlow) || []).forEach(function (r) {
      var k = normalizeSectorKey_(r && r.sector);
      if (k) sentFlow[k] = r;
    });

    var myAlloc = defs.allocationSectors.filter(function (d) { return scopeAllows_(scope, d.partyKey); });
    var myFlow = defs.flowSectors.filter(function (d) { return scopeAllowsFlow_(scope, d.sectorKey, d.partyKey); });

    if (!myAlloc.length && !myFlow.length) {
      return response_(false, 'NO_SECTORS',
        'No sectors are mapped to your party. Contact the administrator.', null);
    }

    var allocations = myAlloc.map(function (d) {
      var sent = sentAlloc[d.sectorKey];
      return {
        party: d.party, partyKey: d.partyKey, sector: d.sector, sectorKey: d.sectorKey,
        todayRequired: assertValidWeight_(sent ? sent.todayRequired : 0,
          "Today's Required (" + d.sector + ')')
      };
    });

    var metalFlow = myFlow.map(function (d) {
      var sent = sentFlow[d.sectorKey];
      return {
        party: d.party, partyKey: d.partyKey, sector: d.sector, sectorKey: d.sectorKey,
        todayAcquired: assertValidWeight_(sent ? sent.todayAcquired : 0,
          "Today's Acquired (" + d.sector + ')')
      };
    });

    // Reject anything sent for a sector outside the operator's party.
    var ownedAlloc = {}, ownedFlow = {};
    myAlloc.forEach(function (d) { ownedAlloc[d.sectorKey] = true; });
    myFlow.forEach(function (d) { ownedFlow[d.sectorKey] = true; });
    var trespass = Object.keys(sentAlloc).filter(function (k) { return !ownedAlloc[k]; })
      .concat(Object.keys(sentFlow).filter(function (k) { return !ownedFlow[k]; }));
    if (trespass.length) {
      return response_(false, 'SECTOR_NOT_IN_SCOPE',
        'The submission included sectors that do not belong to your party.', null);
    }

    var totals = assertSubmissionRules_(allocations, metalFlow);

    lock = LockService.getScriptLock();
    if (!lock.tryLock(CONFIG.LOCK_TIMEOUT_MS)) {
      return response_(false, 'LOCK_TIMEOUT',
        'Another submission is in progress. Wait a few seconds and try again.', null);
    }
    cache.put(cacheKey, '1', CONFIG.REQUEST_ID_TTL_SECONDS);

    // Re-check the locks AFTER acquiring the script lock.
    if (dateExistsInMaster_(dateKey, true)) {
      return response_(false, 'DATE_ALREADY_FINALISED',
        'The administrator has already finalised this date. It can no longer receive submissions.', null);
    }

    var myKeys = scope.partyKeys;
    var existing = readStagingRows_().filter(function (r) {
      return r.dateKey === dateKey && myKeys.indexOf(r.partyKey) >= 0;
    });
    if (existing.length) {
      writeAuditEntry_({
        dateKey: dateKey, actionType: stagingAuditAction_('BLOCKED_RESUBMISSION'),
        revisionNumber: 0, userEmail: email,
        reason: 'Resubmission blocked. A submission already exists for this date and party.',
        requestId: requestId, status: AUDIT_STATUS.BLOCKED
      });
      return response_(false, 'ALREADY_SUBMITTED',
        'You have already submitted for this date. A submission cannot be changed once sent. ' +
        'Contact the administrator if a correction is needed.', null);
    }

    // A sector can carry no Party of its own (Metal Flow is mapped by
    // OPERATOR_FLOW_SECTORS rather than by a Party column). Writing a blank
    // Party would make the submission unattributable, so fall back to the
    // operator's assigned party.
    var fallbackParty = (scope.parties[0] && scope.parties[0].party) || '';

    var submissionId = 'SUB-' +
      Utilities.formatDate(new Date(), getAppTimeZone_(), 'yyyyMMdd-HHmmss') + '-' +
      String(Math.floor(1000 + Math.random() * 9000));
    var now = new Date();
    var storageDate = dateKeyToStorageDate_(dateKey);

    var rows = [];
    allocations.forEach(function (a) {
      rows.push([submissionId, storageDate, a.party || fallbackParty, email, now,
        RECORD_TYPE.ALLOCATION, a.sector, round3_(a.todayRequired), STAGING_STATUS.SUBMITTED]);
    });
    metalFlow.forEach(function (f) {
      rows.push([submissionId, storageDate, f.party || fallbackParty, email, now,
        RECORD_TYPE.FLOW, f.sector, round3_(f.todayAcquired), STAGING_STATUS.SUBMITTED]);
    });

    var sh = ensureStagingSheet_().sheet;
    sh.getRange(sh.getLastRow() + 1, 1, rows.length, CONFIG.HEADERS.STAGING.length).setValues(rows);
    SpreadsheetApp.flush();

    writeAuditEntry_({
      dateKey: dateKey,
      actionType: stagingAuditAction_('SUBMIT_REQUIREMENT'),
      revisionNumber: 0,
      userEmail: email,
      reason: 'Operator requirement submitted for ' +
        scope.parties.map(function (p) { return p.party; }).join(', ') +
        '. Required ' + fmt3_(totals.totalRequired) + ' kg, acquired ' + fmt3_(totals.totalAcquired) + ' kg.',
      afterAllocation: JSON.stringify(allocations.map(function (a) {
        return { s: a.sector, tr: round3_(a.todayRequired) };
      })),
      afterFlow: JSON.stringify(metalFlow.map(function (f) {
        return { s: f.sector, ac: round3_(f.todayAcquired) };
      })),
      requestId: requestId,
      status: AUDIT_STATUS.SUCCESS
    });

    return response_(true, 'SUBMITTED',
      'Requirement submitted for ' + formatDisplayDate_(dateKey) +
      '. It is now locked and awaiting the administrator.',
      {
        submissionId: submissionId,
        selectedDate: dateKey,
        allocationRecords: allocations.length,
        flowRecords: metalFlow.length,
        totals: totals
      });

  } catch (err) {
    try {
      cache.remove(cacheKey);
      writeAuditEntry_({
        dateKey: toDateKey_(payload && payload.selectedDate),
        actionType: stagingAuditAction_('FAILED_SUBMISSION'),
        revisionNumber: 0, userEmail: email,
        reason: (err && (err.userMessage || err.message)) || 'Unknown failure',
        requestId: requestId, status: AUDIT_STATUS.FAILED
      });
    } catch (ignore) { /* never mask the original error */ }
    return handleServerError_('submitOperatorRequirements', err);
  } finally {
    if (lock) { try { lock.releaseLock(); } catch (ignore) { /* nothing to do */ } }
  }
}

/**
 * Validation applied to an operator submission.
 * Deliberately much lighter than the administrator's save: the full-allocation
 * rule belongs to the final save, not to a requirement submission.
 */
function assertSubmissionRules_(allocations, metalFlow) {
  var totalRequired = 0, totalAcquired = 0;
  allocations.forEach(function (a) { totalRequired += a.todayRequired; });
  metalFlow.forEach(function (f) { totalAcquired += f.todayAcquired; });
  totalRequired = round3_(totalRequired);
  totalAcquired = round3_(totalAcquired);

  if (!(totalAcquired > 0)) {
    throw appError_('NO_ACQUIRED_METAL',
      "Enter Today's Acquired metal before submitting.");
  }
  if (!(totalRequired > 0)) {
    throw appError_('NO_REQUIREMENT',
      "Enter Today's Required weight for at least one sector before submitting.");
  }

  if (CONFIG.RULES.OPERATOR_REQUIRED_WITHIN_ACQUIRED &&
      (totalRequired - totalAcquired) > CONFIG.EPSILON) {
    throw appError_('REQUIRED_EXCEEDS_ACQUIRED',
      "Today's Required (" + fmt3_(totalRequired) + ' kg) cannot exceed Today\u2019s Acquired (' +
      fmt3_(totalAcquired) + ' kg). Reduce the requirement by ' +
      fmt3_(totalRequired - totalAcquired) + ' kg.');
  }

  return { totalRequired: totalRequired, totalAcquired: totalAcquired };
}

/* ------------------------------------------------------------------ */
/* Administrator: consume staged submissions                           */
/* ------------------------------------------------------------------ */

/**
 * Everything operators have submitted for a date, for the administrator to pull
 * into the Daily Allocation screen. Administrators only.
 */
function getStagedRequirementsForDate(selectedDate) {
  try {
    var email = getActiveUserEmail_();
    if (!isAdministrator_(email)) {
      return response_(false, 'NOT_AUTHORIZED',
        'Only an administrator can view submitted requirements.', null);
    }

    var dateKey = toDateKey_(selectedDate);
    if (!isValidDateKey_(dateKey)) {
      return response_(false, 'INVALID_DATE', 'Select a valid allocation date.', null);
    }

    invalidateDataCache_();
    var rows = readStagingRows_().filter(function (r) { return r.dateKey === dateKey; });
    var defs = getSectorDefinitions_();

    var allocationBySector = {}, flowBySector = {};
    rows.forEach(function (r) {
      if (r.recordType === RECORD_TYPE.ALLOCATION) allocationBySector[r.sectorKey] = r.value;
      else if (r.recordType === RECORD_TYPE.FLOW) flowBySector[r.sectorKey] = r.value;
    });

    // One entry per submission, keyed by the submitting operator.
    var byOperator = {};
    rows.forEach(function (r) {
      var key = String(r.operatorEmail || '').toLowerCase() + '::' + r.submissionId;
      if (!byOperator[key]) {
        byOperator[key] = {
          party: '', operatorEmail: r.operatorEmail,
          operatorName: getDisplayName_(r.operatorEmail),
          submittedAt: r.submittedAtDisplay, submissionId: r.submissionId,
          status: r.status, totalRequired: 0, totalAcquired: 0
        };
      }
      if (!byOperator[key].party && r.party) byOperator[key].party = r.party;
      if (r.recordType === RECORD_TYPE.ALLOCATION) byOperator[key].totalRequired += r.value;
      else byOperator[key].totalAcquired += r.value;
    });

    var submissions = Object.keys(byOperator).map(function (k) {
      var s = byOperator[k];
      if (!s.party) s.party = s.operatorName;
      s.totalRequired = round3_(s.totalRequired);
      s.totalAcquired = round3_(s.totalAcquired);
      return s;
    });

    // Which parties have not submitted yet.
    var submittedKeys = submissions.map(function (s) { return normalizePartyKey_(s.party); });
    var pendingParties = defs.parties.filter(function (p) {
      return submittedKeys.indexOf(p.partyKey) < 0;
    }).map(function (p) { return p.party; });

    var totalRequired = 0, totalAcquired = 0;
    submissions.forEach(function (s) {
      totalRequired += s.totalRequired;
      totalAcquired += s.totalAcquired;
    });

    return response_(true, submissions.length ? 'OK' : 'NO_SUBMISSIONS',
      submissions.length
        ? (submissions.length + ' party submission(s) found for ' + formatDisplayDate_(dateKey) + '.')
        : 'No operator submissions have been received for ' + formatDisplayDate_(dateKey) + '.',
      {
        selectedDate: dateKey,
        selectedDateDisplay: formatDisplayDate_(dateKey),
        submissions: submissions,
        pendingParties: pendingParties,
        // Keyed by sector name so the client can fill the matching rows.
        allocationValues: defs.allocationSectors.map(function (d) {
          return {
            sector: d.sector, party: d.party,
            todayRequired: allocationBySector[d.sectorKey] || 0,
            hasSubmission: allocationBySector.hasOwnProperty(d.sectorKey)
          };
        }),
        flowValues: defs.flowSectors.map(function (d) {
          return {
            sector: d.sector, party: d.party,
            todayAcquired: flowBySector[d.sectorKey] || 0,
            hasSubmission: flowBySector.hasOwnProperty(d.sectorKey)
          };
        }),
        totals: {
          totalRequired: round3_(totalRequired),
          totalAcquired: round3_(totalAcquired)
        }
      });
  } catch (err) {
    return handleServerError_('getStagedRequirementsForDate', err);
  }
}

/**
 * Marks a date's staged rows CONSUMED after the administrator's save succeeds.
 * Never throws: a bookkeeping failure must not reverse a completed save.
 */
function markStagingConsumed_(dateKey) {
  try {
    var sh = getSheetIfExists_(CONFIG.SHEETS.STAGING);
    if (!sh) return 0;

    var rows = readStagingRows_().filter(function (r) {
      return r.dateKey === dateKey && r.status === STAGING_STATUS.SUBMITTED;
    });
    if (!rows.length) return 0;

    rows.forEach(function (r) {
      sh.getRange(r.rowNumber, STAGING_COL.STATUS).setValue(STAGING_STATUS.CONSUMED);
    });
    SpreadsheetApp.flush();
    return rows.length;
  } catch (err) {
    console.error(CONFIG.LOG_PREFIX + ' markStagingConsumed_ failed for ' + dateKey + ': ' + err);
    return 0;
  }
}

/* ------------------------------------------------------------------ */
/* Phase 5C — scope filtering for every read path                      */
/* ------------------------------------------------------------------ */

/**
 * sectorKey -> partyKey, built from the live Metal Generator definitions.
 * Historical master rows saved before the Party column existed have a blank
 * Party, so their party is resolved through this map instead.
 */
function buildSectorPartyMaps_() {
  if (DS_CACHE_.sectorPartyMaps) return DS_CACHE_.sectorPartyMaps;

  var maps = { allocation: {}, flow: {} };
  try {
    readAllocationSectorDefinitions_().forEach(function (d) { maps.allocation[d.sectorKey] = d.partyKey; });
  } catch (e) { /* definitions unavailable */ }
  try {
    readFlowSectorDefinitions_().forEach(function (d) { maps.flow[d.sectorKey] = d.partyKey; });
  } catch (e2) { /* definitions unavailable */ }

  DS_CACHE_.sectorPartyMaps = maps;
  return maps;
}

/** Resolves a stored row's party: its own value first, else the sector map. */
function rowPartyKey_(row, map) {
  if (row.partyKey) return row.partyKey;
  return map[row.sectorKey] || '';
}

/** Keeps only the rows whose party is inside the user's scope. */
function filterRowsByScope_(rows, scope, map) {
  if (scope.unrestricted) return rows;
  return rows.filter(function (r) { return scopeAllows_(scope, rowPartyKey_(r, map)); });
}

/** The sector names an operator may see, for scoping filter dropdowns. */
function scopedSectorNames_(scope) {
  var defs = getSectorDefinitions_();
  return {
    allocation: defs.allocationSectors.filter(function (d) { return scopeAllows_(scope, d.partyKey); }),
    flow: defs.flowSectors.filter(function (d) { return scopeAllowsFlow_(scope, d.sectorKey, d.partyKey); })
  };
}

/**
 * Trims a Daily Allocation model to the user's party and applies the operator
 * restrictions: Alloted and Balance become read-only, and the cross-party
 * totals are removed because they describe metal that is not theirs.
 */
function applyScopeToAllocationModel_(model, scope) {
  model.role = scope.role;
  model.parties = scope.parties;
  model.isOperator = !scope.isAdmin;

  if (scope.unrestricted) {
    model.canEditRequired = !model.isSaved;
    model.canEditAlloted = !model.isSaved;
    model.canEditAcquired = !model.isSaved;
    model.showGlobalTotals = true;
    return model;
  }

  model.allocations = model.allocations.filter(function (a) { return scopeAllows_(scope, a.partyKey); });
  model.metalFlow = model.metalFlow.filter(function (f) { return scopeAllowsFlow_(scope, f.sectorKey, f.partyKey); });

  // Operators enter requirement and acquired metal but never allocate.
  // All three flags are set explicitly so the client never has to infer them.
  model.canEditRequired = !model.isSaved;
  model.canEditAcquired = !model.isSaved;
  model.canEditAlloted = false;
  model.showGlobalTotals = false;

  var scopedRequired = 0, scopedPrevious = 0, scopedAlloted = 0, scopedBalance = 0;
  model.allocations.forEach(function (a) {
    scopedPrevious += a.previousRequirement;
    scopedRequired += a.todayRequired;
    scopedAlloted += a.alloted;
    scopedBalance += a.balance;
  });
  var scopedAcquired = 0, scopedPrevAcquired = 0;
  model.metalFlow.forEach(function (f) {
    scopedAcquired += f.todayAcquired;
    scopedPrevAcquired += f.previousAcquired;
  });

  // Replace the workbook-wide totals with this party's own figures.
  model.totals = {
    totalPreviousRequirement: round3_(scopedPrevious),
    totalTodayRequired: round3_(scopedRequired),
    totalAlloted: round3_(scopedAlloted),
    totalBalance: round3_(scopedBalance),
    totalAcquired: round3_(scopedAcquired),
    remainingToAllocate: 0        // not an operator concept
  };
  model.totalPreviousAcquired = round3_(scopedPrevAcquired);

  return model;
}


/** Build marker. Used by checkInstalledFiles() to detect a stale paste. */
function buildTag_StagingService_() { return '5C'; }

/* ------------------------------------------------------------------ */
/* Diagnostic                                                          */
/* ------------------------------------------------------------------ */

/**
 * DIAGNOSTIC — run manually from the Apps Script editor with a date string,
 * e.g. debugScreenFlags('2026-09-05'). Reports exactly what the server would
 * send the browser for that date, so a greyed field can be traced to either
 * the server flags or a stale deployment.
 *
 * Read only. Writes nothing.
 */
function debugScreenFlags(selectedDate, asEmail) {
  var out = {};
  try {
    // Administrators may compute another user's flags without signing in as them.
    // This only calculates what the server WOULD send; it grants nothing.
    var caller = getActiveUserEmail_();
    var subject = String(asEmail || '').trim();
    if (subject && !isAdministrator_(caller)) {
      out.error = 'Only an administrator may inspect another user\u2019s flags.';
      return out;
    }
    out.inspecting = subject || caller;
    var dateKey = toDateKey_(selectedDate || todayKey_());
    out.requestedDate = dateKey;
    out.dateIsValid = isValidDateKey_(dateKey);
    if (!out.dateIsValid) {
      out.verdict = 'The date could not be parsed. Pass it as yyyy-MM-dd.';
      console.log(CONFIG.LOG_PREFIX + ' SCREEN FLAGS\n' + JSON.stringify(out, null, 2));
      return out;
    }

    var email = subject || caller;
    var scope = getUserScope_(email);
    out.signedInAs = caller;
    out.flagsComputedFor = email;
    out.role = scope.role;
    out.parties = scope.parties.map(function (p) { return p.party; });
    out.flowSectorMapping = scope.flowSectorKeys
      ? scope.flowSectorKeys.join(', ')
      : '(none configured - falling back to the Party column)';

    invalidateDataCache_();
    var model = buildAllocationModel_(dateKey);
    applyScopeToAllocationModel_(model, scope);

    out.isSaved = model.isSaved;
    out.allocationRowsReturned = model.allocations.length;
    out.flowRowsReturned = model.metalFlow.length;
    out.canEditRequired = model.canEditRequired;
    out.canEditAcquired = model.canEditAcquired;
    out.canEditAlloted = model.canEditAlloted;
    out.showGlobalTotals = model.showGlobalTotals;
    out.isOperator = model.isOperator;

    out.verdict = [];
    if (model.isSaved) {
      out.verdict.push('This date is ALREADY SAVED, so every field is correctly locked. Choose an unsaved date.');
    }
    if (model.canEditAcquired === undefined) {
      out.verdict.push('canEditAcquired is undefined: StagingService.gs is not the current version.');
    } else if (model.canEditAcquired === true) {
      out.verdict.push('The server says Today\u2019s Acquired IS editable for ' + email +
        '. If the field still looks grey in that user\u2019s browser, the deployment is serving ' +
        'an older Scripts.html. Check the browser console for "[RMAS] client build: RMAS-Scripts-5C.2", ' +
        'then Deploy > Manage deployments > Edit > Version: New version > Deploy.');
    }
    if (!scope.isAdmin && !scope.parties.length) {
      out.verdict.push('This account has no party assigned, so it can see nothing.');
    }
    if (model.flowRowsReturned === 0 || model.metalFlow.length === 0) {
      out.verdict.push('No Metal Flow sectors matched this user. Add their Metal Flow sector ' +
        'name(s) to CONFIG.OPERATOR_FLOW_SECTORS, spelled as in Metal Generator.');
    }

    console.log(CONFIG.LOG_PREFIX + ' SCREEN FLAGS\n' + JSON.stringify(out, null, 2));
    return out;
  } catch (err) {
    out.error = (err && (err.userMessage || err.message)) || String(err);
    console.error(CONFIG.LOG_PREFIX + ' debugScreenFlags: ' + err);
    return out;
  }
}

/* ------------------------------------------------------------------ */
/* Phase 5D — staged values on the Daily Allocation screen             */
/* ------------------------------------------------------------------ */

/**
 * Overlays operator submissions onto a Daily Allocation model.
 *
 * For an OPERATOR: their submitted figures are shown back to them and every
 * input is locked, because a submission is one-shot.
 *
 * For an ADMIN: submitted figures are pulled in as the starting point and stay
 * editable, so the administrator can adjust before allocating and saving.
 *
 * Call after applyScopeToAllocationModel_.
 */
function applyStagingToModel_(model, scope, dateKey) {
  model.stagingSubmissions = [];
  model.isSubmitted = false;
  model.stagedValueCount = 0;

  // Once a date is saved the staging rows are CONSUMED and the masters are
  // authoritative, so there is nothing to overlay.
  if (model.isSaved) return model;

  var rows;
  try {
    rows = readStagingRows_().filter(function (r) {
      return r.dateKey === dateKey && r.status === STAGING_STATUS.SUBMITTED;
    });
  } catch (e) {
    console.error(CONFIG.LOG_PREFIX + ' staging overlay skipped: ' + e);
    return model;
  }
  if (!rows.length) return model;

  var partyMaps = buildSectorPartyMaps_();

  // An operator only ever sees their own submission.
  var visible = scope.unrestricted ? rows : rows.filter(function (r) {
    if (r.recordType === RECORD_TYPE.FLOW) {
      return scopeAllowsFlow_(scope, r.sectorKey, rowPartyKey_(r, partyMaps.flow));
    }
    return scopeAllows_(scope, rowPartyKey_(r, partyMaps.allocation));
  });
  if (!visible.length) return model;

  var allocByKey = {}, flowByKey = {};
  visible.forEach(function (r) {
    if (r.recordType === RECORD_TYPE.ALLOCATION) allocByKey[r.sectorKey] = r.value;
    else if (r.recordType === RECORD_TYPE.FLOW) flowByKey[r.sectorKey] = r.value;
  });

  var applied = 0;
  model.allocations.forEach(function (a) {
    if (!allocByKey.hasOwnProperty(a.sectorKey)) return;
    a.todayRequired = round3_(allocByKey[a.sectorKey]);
    a.balance = round3_(a.previousRequirement + a.todayRequired - a.alloted);
    a.fromSubmission = true;
    applied++;
  });
  model.metalFlow.forEach(function (f) {
    if (!flowByKey.hasOwnProperty(f.sectorKey)) return;
    f.todayAcquired = round3_(flowByKey[f.sectorKey]);
    f.fromSubmission = true;
    applied++;
  });
  model.stagedValueCount = applied;

  // Per-party summary, used for the administrator's notification.
  // Group by the SUBMITTING OPERATOR, not by the Party text. One submission is
  // one operator is one party, so a row whose Party happens to be blank can
  // never split a single submission into two entries.
  var byOperator = {};
  visible.forEach(function (r) {
    var key = String(r.operatorEmail || '').toLowerCase() + '::' + r.submissionId;
    if (!byOperator[key]) {
      byOperator[key] = {
        party: '',
        operatorEmail: r.operatorEmail,
        operatorName: getDisplayName_(r.operatorEmail),
        submittedAt: r.submittedAtDisplay,
        submissionId: r.submissionId,
        totalRequired: 0,
        totalAcquired: 0
      };
    }
    // Take the party name from whichever row carries one.
    if (!byOperator[key].party && r.party) byOperator[key].party = r.party;
    if (r.recordType === RECORD_TYPE.ALLOCATION) byOperator[key].totalRequired += r.value;
    else byOperator[key].totalAcquired += r.value;
  });

  model.stagingSubmissions = Object.keys(byOperator).map(function (k) {
    var s = byOperator[k];
    if (!s.party) s.party = s.operatorName;   // never show an unnamed entry
    s.totalRequired = round3_(s.totalRequired);
    s.totalAcquired = round3_(s.totalAcquired);
    return s;
  });

  recomputeScopedTotals_(model);

  // A submission is one-shot, so an operator viewing their own is read-only.
  if (!scope.unrestricted) {
    model.isSubmitted = true;
    model.readOnly = true;
    model.canEditRequired = false;
    model.canEditAcquired = false;
    model.canEditAlloted = false;
    var first = model.stagingSubmissions[0];
    model.submittedAt = first ? first.submittedAt : '';
    model.submittedBy = first ? first.operatorName : '';
  }

  return model;
}

/** Recomputes the model totals after values have been overlaid. */
function recomputeScopedTotals_(model) {
  var prev = 0, req = 0, alloted = 0, balance = 0, acquired = 0, prevAcquired = 0;
  model.allocations.forEach(function (a) {
    prev += a.previousRequirement;
    req += a.todayRequired;
    alloted += a.alloted;
    balance += a.balance;
  });
  model.metalFlow.forEach(function (f) {
    acquired += f.todayAcquired;
    prevAcquired += f.previousAcquired;
  });

  model.totals = {
    totalPreviousRequirement: round3_(prev),
    totalTodayRequired: round3_(req),
    totalAlloted: round3_(alloted),
    totalBalance: round3_(balance),
    totalAcquired: round3_(acquired),
    remainingToAllocate: model.showGlobalTotals === false
      ? 0 : round3_(Math.max(0, acquired - alloted))
  };
  model.totalPreviousAcquired = round3_(prevAcquired);
  return model;
}

/**
 * DIAGNOSTIC — dumps every staging row for a date, and reports whether each one
 * matches a live sector definition. Run from the editor, e.g.
 * debugStagingForDate('2026-09-05'). Read only.
 */
function debugStagingForDate(selectedDate) {
  var out = {};
  try {
    var dateKey = toDateKey_(selectedDate || todayKey_());
    out.date = dateKey;

    invalidateDataCache_();
    var defs = getSectorDefinitions_();
    var allocKeys = {}, flowKeys = {};
    defs.allocationSectors.forEach(function (d) { allocKeys[d.sectorKey] = d.sector; });
    defs.flowSectors.forEach(function (d) { flowKeys[d.sectorKey] = d.sector; });

    var rows = readStagingRows_().filter(function (r) { return r.dateKey === dateKey; });
    out.rowCount = rows.length;
    out.problems = [];

    out.rows = rows.map(function (r) {
      var known = (r.recordType === RECORD_TYPE.FLOW)
        ? flowKeys.hasOwnProperty(r.sectorKey)
        : allocKeys.hasOwnProperty(r.sectorKey);
      if (!known) {
        out.problems.push('Sector "' + r.sector + '" (' + r.recordType +
          ') does not match any current sector definition, so its value cannot be loaded.');
      }
      if (!r.party) {
        out.problems.push('Row for "' + r.sector + '" has a BLANK Party. ' +
          'It was written before the party fallback existed.');
      }
      return [r.status, r.recordType, 'party=' + (r.party || '(blank)'),
        r.sector, r.value, r.operatorEmail, r.submittedAtDisplay,
        known ? 'matches a sector' : 'NO MATCHING SECTOR'].join(' | ');
    });

    var submitted = rows.filter(function (r) { return r.status === STAGING_STATUS.SUBMITTED; });
    out.submittedRows = submitted.length;
    out.consumedRows = rows.length - submitted.length;
    if (!submitted.length && rows.length) {
      out.problems.push('Every row is CONSUMED, so nothing will load. The date was already saved.');
    }
    if (!out.problems.length) out.problems.push('None found.');

    console.log(CONFIG.LOG_PREFIX + ' STAGING ROWS\n' + JSON.stringify(out, null, 2));
    return out;
  } catch (err) {
    out.error = String(err);
    console.error(CONFIG.LOG_PREFIX + ' debugStagingForDate: ' + err);
    return out;
  }
}
