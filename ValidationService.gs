/**
 * ValidationService.gs
 * Royal Metal Allocation System — Phase 1
 *
 * Shared helpers + ALL server-authoritative validation.
 * The browser validates for convenience only. Nothing is written unless it passes here.
 */

/* ------------------------------------------------------------------ */
/* Shared helpers                                                      */
/* ------------------------------------------------------------------ */

/** Standard structured response envelope used by every public server function. */
function response_(ok, code, message, data) {
  return { ok: !!ok, code: code || (ok ? 'OK' : 'ERROR'), message: message || '', data: data || null };
}

/** Creates an Error carrying a stable machine code and a safe user message. */
function appError_(code, userMessage, detail) {
  var e = new Error(userMessage || code);
  e.appCode = code;
  e.userMessage = userMessage || 'The operation could not be completed.';
  e.detail = detail || '';
  return e;
}

/**
 * Logs the real error server side and returns a safe envelope to the browser.
 * Raw stack traces are never sent to end users.
 */
function handleServerError_(fnName, err) {
  var code = (err && err.appCode) ? err.appCode : 'UNEXPECTED_ERROR';
  var userMessage = (err && err.userMessage)
    ? err.userMessage
    : 'Something went wrong on the server. Please retry, and contact the administrator if it continues.';
  try {
    console.error(CONFIG.LOG_PREFIX + ' ' + fnName + ' | code=' + code +
      ' | message=' + (err && err.message) +
      ' | detail=' + (err && err.detail ? err.detail : '') +
      ' | stack=' + (err && err.stack ? err.stack : 'n/a'));
  } catch (ignore) { /* logging must never break the response */ }
  return response_(false, code, userMessage, null);
}

/** Rounds to the configured decimal precision (3). Non-numeric -> 0. */
function round3_(n) {
  var v = Number(n);
  if (!isFinite(v)) return 0;
  var f = Math.pow(10, CONFIG.DECIMALS);
  return Math.round((v + Number.EPSILON) * f) / f;
}

/** Parses any cell/input value into a safe non-negative rounded number. */
function toNumber_(value) {
  if (value === null || value === undefined || value === '') return 0;
  if (typeof value === 'number') return isFinite(value) ? round3_(value) : 0;
  var s = String(value).replace(/,/g, '').trim();
  if (!s) return 0;
  var n = Number(s);
  return isFinite(n) ? round3_(n) : 0;
}

/** Formats a number as a 3-decimal kilogram string. */
function fmt3_(n) { return round3_(n).toFixed(CONFIG.DECIMALS); }

/**
 * Sector matching key. Never match on row position.
 * Trims, collapses internal whitespace, normalizes dash variants, lowercases.
 */
function normalizeSectorKey_(name) {
  return String(name === null || name === undefined ? '' : name)
    .replace(/[\u2010-\u2015\u2212]/g, '-')   // en/em dash and minus -> hyphen
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase();
}

/** Two numbers are equal at 3-decimal business precision. */
function nearlyEqual_(a, b) {
  return Math.abs(round3_(a) - round3_(b)) < CONFIG.EPSILON;
}

/* ------------------------------------------------------------------ */
/* Input validation                                                    */
/* ------------------------------------------------------------------ */

/**
 * Validates a DERIVED weight that is allowed to be negative.
 *
 * Previous Requirement and Balance are carried forward from the prior day's
 * Balance. Since an allocation may exceed the requirement, that balance can be
 * negative, and the negative legitimately carries into the next day. Only the
 * magnitude is sanity-checked.
 */
function assertSignedWeight_(value, label) {
  var raw = (value === null || value === undefined || value === '')
    ? 0 : Number(String(value).replace(/,/g, '').trim());
  if (!isFinite(raw)) {
    throw appError_('INVALID_NUMBER', label + ' must be a valid number.');
  }
  if (Math.abs(raw) > CONFIG.MAX_WEIGHT_KG) {
    throw appError_('VALUE_TOO_LARGE', label + ' exceeds the maximum permitted weight.');
  }
  return round3_(raw);
}

/** Validates one numeric weight INPUT. Inputs may not be negative. */
function assertValidWeight_(value, label) {
  var raw = (value === null || value === undefined || value === '') ? 0 : Number(String(value).replace(/,/g, '').trim());
  if (!isFinite(raw)) {
    throw appError_('INVALID_NUMBER', label + ' must be a valid number.');
  }
  if (raw < 0) {
    throw appError_('NEGATIVE_VALUE', label + ' cannot be negative.');
  }
  if (raw > CONFIG.MAX_WEIGHT_KG) {
    throw appError_('VALUE_TOO_LARGE', label + ' exceeds the maximum permitted weight.');
  }
  return round3_(raw);
}

/**
 * Validates and normalizes the incoming save/revise payload against the live
 * sector definitions. Returns a fully normalized structure the writer can trust.
 *
 * @param {Object} payload   { selectedDate, allocations[], metalFlow[], requestId, revisionReason }
 * @param {Object} defs      { allocationSectors[], flowSectors[] }
 * @return {Object} normalized { dateKey, allocations[], metalFlow[], totals{} }
 */
function validateAndNormalizePayload_(payload, defs) {
  if (!payload || typeof payload !== 'object') {
    throw appError_('EMPTY_PAYLOAD', 'No allocation data was received. Reload the screen and try again.');
  }

  var dateKey = toDateKey_(payload.selectedDate);
  if (!isValidDateKey_(dateKey)) {
    throw appError_('INVALID_DATE', 'Select a valid allocation date before saving.');
  }

  var allocIn = payload.allocations;
  var flowIn = payload.metalFlow;
  if (!allocIn || !allocIn.length || !flowIn || !flowIn.length) {
    throw appError_('INCOMPLETE_PAYLOAD', 'The allocation data is incomplete. Reload the screen and try again.');
  }
  if (allocIn.length !== defs.allocationSectors.length) {
    throw appError_('ALLOCATION_ROW_COUNT',
      'Expected ' + defs.allocationSectors.length + ' allocation rows but received ' + allocIn.length + '.');
  }
  if (flowIn.length !== defs.flowSectors.length) {
    throw appError_('FLOW_ROW_COUNT',
      'Expected ' + defs.flowSectors.length + ' Metal Flow rows but received ' + flowIn.length + '.');
  }

  // Index submitted rows by normalized sector so row order can never corrupt a save.
  var allocByKey = {};
  allocIn.forEach(function (r) {
    var k = normalizeSectorKey_(r && r.sector);
    if (k) allocByKey[k] = r;
  });
  var flowByKey = {};
  flowIn.forEach(function (r) {
    var k = normalizeSectorKey_(r && r.sector);
    if (k) flowByKey[k] = r;
  });

  var allocations = defs.allocationSectors.map(function (def) {
    var submitted = allocByKey[def.sectorKey];
    if (!submitted) {
      throw appError_('SECTOR_MISSING', 'Allocation data for "' + def.sector + '" was not received.');
    }
    // Carried forward from yesterday's Balance, so it may be negative.
    var previousRequirement = assertSignedWeight_(submitted.previousRequirement, 'Previous Requirement (' + def.sector + ')');
    var todayRequired = assertValidWeight_(submitted.todayRequired, "Today's Required Weight (" + def.sector + ')');
    var alloted = assertValidWeight_(submitted.alloted, 'Alloted (' + def.sector + ')');
    return {
      priority: def.priority,
      party: def.party,                 // authoritative party from Metal Generator
      partyKey: def.partyKey,
      sector: def.sector,               // authoritative name from Metal Generator
      sectorKey: def.sectorKey,
      purity: def.purity,               // authoritative purity from Metal Generator
      previousRequirement: previousRequirement,
      todayRequired: todayRequired,
      alloted: alloted,
      balance: round3_(previousRequirement + todayRequired - alloted)
    };
  });

  var metalFlow = defs.flowSectors.map(function (def) {
    var submitted = flowByKey[def.sectorKey];
    if (!submitted) {
      throw appError_('FLOW_SECTOR_MISSING', 'Metal Flow data for "' + def.sector + '" was not received.');
    }
    return {
      sector: def.sector,
      sectorKey: def.sectorKey,
      party: def.party,
      partyKey: def.partyKey,
      todayAcquired: assertValidWeight_(submitted.todayAcquired, "Today's Acquired (" + def.sector + ')')
    };
  });

  var totals = computeTotals_(allocations, metalFlow);

  return { dateKey: dateKey, allocations: allocations, metalFlow: metalFlow, totals: totals };
}

/** Computes every aggregate the business rules depend on. */
function computeTotals_(allocations, metalFlow) {
  var totalPrevRequirement = 0, totalTodayRequired = 0, totalAlloted = 0, totalBalance = 0, totalAcquired = 0;

  allocations.forEach(function (r) {
    totalPrevRequirement += r.previousRequirement;
    totalTodayRequired += r.todayRequired;
    totalAlloted += r.alloted;
    totalBalance += r.balance;
  });
  metalFlow.forEach(function (r) { totalAcquired += r.todayAcquired; });

  totalPrevRequirement = round3_(totalPrevRequirement);
  totalTodayRequired = round3_(totalTodayRequired);
  totalAlloted = round3_(totalAlloted);
  totalBalance = round3_(totalBalance);
  totalAcquired = round3_(totalAcquired);

  return {
    totalPreviousRequirement: totalPrevRequirement,
    totalTodayRequired: totalTodayRequired,
    totalAlloted: totalAlloted,
    totalBalance: totalBalance,
    totalAcquired: totalAcquired,
    remainingToAllocate: round3_(Math.max(0, totalAcquired - totalAlloted))
  };
}

/**
 * CONFIRMED SAVE RULES (final business decisions).
 *  - Zero Previous Requirement is allowed.
 *  - Zero Closing Balance is allowed.
 *  - The old "every D:G total must be non-zero" rule is removed.
 *  - Total Today's Acquired must be > 0.
 *  - Actual Total Alloted must be > 0.
 *  - Alloted must equal Acquired at 3 decimals (Remaining to Allocate = 0.000).
 */
function assertSaveRules_(normalized) {
  var t = normalized.totals;

  if (CONFIG.RULES.REQUIRE_POSITIVE_ACQUIRED && !(t.totalAcquired > 0)) {
    throw appError_('NO_ACQUIRED_METAL',
      "Enter Today's Acquired metal in the Metal Flow panel before saving.");
  }

  if (CONFIG.RULES.REQUIRE_POSITIVE_ALLOTED && !(t.totalAlloted > 0)) {
    throw appError_('NO_ALLOCATION',
      'Enter the sector-wise Alloted quantities before saving.');
  }

  if (CONFIG.RULES.BLOCK_OVER_ALLOCATION &&
      (t.totalAlloted - t.totalAcquired) > CONFIG.EPSILON) {
    throw appError_('OVER_ALLOCATED',
      'Allocation exceeds Total Today\u2019s Acquired by ' +
      fmt3_(t.totalAlloted - t.totalAcquired) + ' kg. Reduce the allocation before saving.');
  }

  if (CONFIG.RULES.REQUIRE_FULL_ALLOCATION && !nearlyEqual_(t.totalAlloted, t.totalAcquired)) {
    throw appError_('INCOMPLETE_ALLOCATION',
      'Complete the allocation before saving. ' + fmt3_(t.remainingToAllocate) + ' kg is still remaining.');
  }

  return true;
}

/** Validates an administrator revision reason. */
function assertRevisionReason_(reason) {
  var text = String(reason === null || reason === undefined ? '' : reason).trim();
  if (CONFIG.RULES.REQUIRE_REVISION_REASON) {
    if (!text) {
      throw appError_('REVISION_REASON_REQUIRED', 'A revision reason is mandatory.');
    }
    if (text.length < CONFIG.RULES.MIN_REVISION_REASON_LENGTH) {
      throw appError_('REVISION_REASON_TOO_SHORT',
        'The revision reason must be at least ' + CONFIG.RULES.MIN_REVISION_REASON_LENGTH + ' characters.');
    }
  }
  if (text.length > 1000) text = text.substring(0, 1000);
  return text;
}


/** Build marker. Used by checkInstalledFiles() to detect a stale paste. */
function buildTag_ValidationService_() { return '5C'; }
