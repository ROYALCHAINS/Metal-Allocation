/**
 * DataService.gs
 * Royal Metal Allocation System — Phase 5A
 *
 * All Google Sheets access. Bulk reads, bulk writes, no row-by-row operations.
 *
 * Columns are resolved by HEADER LABEL through SchemaService.gs rather than by
 * fixed position, so inserting a Party column or adding sectors no longer
 * breaks reading or writing.
 *
 * The Example and Metal Allocation Working sheets are never opened for writing.
 */

var DS_CACHE_ = {};

/* ------------------------------------------------------------------ */
/* Spreadsheet access                                                  */
/* ------------------------------------------------------------------ */

function getSpreadsheet_() {
  if (DS_CACHE_.ss) return DS_CACHE_.ss;
  if (CONFIG.SPREADSHEET_ID) {
    DS_CACHE_.ss = SpreadsheetApp.openById(CONFIG.SPREADSHEET_ID);
  } else {
    DS_CACHE_.ss = SpreadsheetApp.getActiveSpreadsheet();
  }
  if (!DS_CACHE_.ss) {
    throw appError_('NO_SPREADSHEET',
      'The workbook could not be opened. Set CONFIG.SPREADSHEET_ID in Config.gs.');
  }
  return DS_CACHE_.ss;
}

function getSheetOrThrow_(name) {
  if (DS_CACHE_['sheet::' + name]) return DS_CACHE_['sheet::' + name];
  var sh = getSpreadsheet_().getSheetByName(name);
  if (!sh) {
    throw appError_('SHEET_MISSING',
      'The sheet "' + name + '" was not found in the workbook. Run setupMetalAllocationApp() or restore the sheet.',
      'missing sheet: ' + name);
  }
  DS_CACHE_['sheet::' + name] = sh;
  return sh;
}

function getSheetIfExists_(name) {
  return getSpreadsheet_().getSheetByName(name);
}

/** Party matching key. Same normalization rules as sector keys. */
function normalizePartyKey_(name) {
  return normalizeSectorKey_(name);
}

/* ------------------------------------------------------------------ */
/* Sector definitions (read from Metal Generator — never invented)      */
/* ------------------------------------------------------------------ */

/**
 * Allocation sectors, in sheet order, with their Party.
 * Party is optional: when the column is absent every sector gets an empty
 * party and party scoping simply has no effect.
 */
function readAllocationSectorDefinitions_() {
  if (DS_CACHE_.allocDefs) return DS_CACHE_.allocDefs;

  var layout = getGeneratorLayout_();
  var sh = getSheetOrThrow_(CONFIG.SHEETS.GENERATOR);

  if (!layout.firstRow) {
    throw appError_('NO_ALLOCATION_SECTORS',
      'No allocation sectors were found under the Sector header in ' +
      CONFIG.SHEETS.GENERATOR + '. Check that the sector list starts directly below the header row.');
  }

  var height = layout.lastRow - layout.firstRow + 1;
  var width = Math.max(
    layout.allocation.priority, layout.allocation.party,
    layout.allocation.sector, layout.allocation.purity);
  var values = sh.getRange(layout.firstRow, 1, height, width).getValues();

  function cell(row, column) {
    if (!column) return '';
    var v = row[column - 1];
    return String(v === null || v === undefined ? '' : v).trim();
  }

  var defs = [];
  var seen = {};

  for (var i = 0; i < values.length; i++) {
    var sector = cell(values[i], layout.allocation.sector);
    if (!sector) continue;

    var key = normalizeSectorKey_(sector);
    if (seen[key]) {
      throw appError_('DUPLICATE_SECTOR',
        'The allocation sector "' + sector + '" appears more than once in ' + CONFIG.SHEETS.GENERATOR + '.');
    }
    seen[key] = true;

    var party = cell(values[i], layout.allocation.party);
    defs.push({
      rowIndex: i,
      sheetRow: layout.firstRow + i,
      priority: cell(values[i], layout.allocation.priority),
      sector: sector,
      sectorKey: key,
      party: party,
      partyKey: normalizePartyKey_(party),
      purity: cell(values[i], layout.allocation.purity) || 'Any'
    });
  }

  assertSectorCount_(defs.length, CONFIG.EXPECTED.ALLOCATION_ROWS, 'allocation');

  DS_CACHE_.allocDefs = defs;
  return defs;
}

/** Metal Flow sectors, in sheet order, with their Party when the column exists. */
function readFlowSectorDefinitions_() {
  if (DS_CACHE_.flowDefs) return DS_CACHE_.flowDefs;

  var layout = getGeneratorLayout_();
  if (!layout.flow.sector || !layout.flow.firstRow) {
    throw appError_('NO_FLOW_SECTORS',
      'The Metal Flow sector list could not be located in ' + CONFIG.SHEETS.GENERATOR +
      '. It is identified by a second "Sector" header to the right of the allocation table.');
  }

  var sh = getSheetOrThrow_(CONFIG.SHEETS.GENERATOR);
  var height = layout.flow.lastRow - layout.flow.firstRow + 1;
  var width = Math.max(layout.flow.sector, layout.flow.party);
  var values = sh.getRange(layout.flow.firstRow, 1, height, width).getValues();

  function cell(row, column) {
    if (!column) return '';
    var v = row[column - 1];
    return String(v === null || v === undefined ? '' : v).trim();
  }

  var defs = [];
  var seen = {};

  for (var i = 0; i < values.length; i++) {
    var sector = cell(values[i], layout.flow.sector);
    if (!sector) continue;

    var key = normalizeSectorKey_(sector);
    if (seen[key]) {
      throw appError_('DUPLICATE_FLOW_SECTOR',
        'The Metal Flow sector "' + sector + '" appears more than once in ' + CONFIG.SHEETS.GENERATOR + '.');
    }
    seen[key] = true;

    // Sheet value first; fall back to the configured map when the Metal Flow
    // list has no Party column.
    var party = cell(values[i], layout.flow.party) || lookupFlowParty_(sector);
    defs.push({
      rowIndex: i,
      sheetRow: layout.flow.firstRow + i,
      sector: sector,
      sectorKey: key,
      party: party,
      partyKey: normalizePartyKey_(party)
    });
  }

  assertSectorCount_(defs.length, CONFIG.EXPECTED.FLOW_ROWS, 'Metal Flow');

  DS_CACHE_.flowDefs = defs;
  return defs;
}

/** Party for a Metal Flow sector from CONFIG.FLOW_SECTOR_PARTIES. '' when unmapped. */
function lookupFlowParty_(sector) {
  var map = CONFIG.FLOW_SECTOR_PARTIES || {};
  var wanted = normalizeSectorKey_(sector);
  var keys = Object.keys(map);
  for (var i = 0; i < keys.length; i++) {
    if (normalizeSectorKey_(keys[i]) === wanted) return String(map[keys[i]] || '').trim();
  }
  return '';
}

/**
 * Compares the detected sector count against the expected count.
 * With CONFIG.EXPECTED.STRICT false this only logs a warning, so adding a
 * sector to the sheet does not stop the app.
 */
function assertSectorCount_(found, expected, label) {
  if (!found) {
    throw appError_('NO_SECTORS_FOUND',
      'No ' + label + ' sectors were found in ' + CONFIG.SHEETS.GENERATOR + '.');
  }
  if (found === expected) return;

  var message = 'Expected ' + expected + ' ' + label + ' sectors but found ' + found +
    ' in ' + CONFIG.SHEETS.GENERATOR + '.';

  if (CONFIG.EXPECTED.STRICT) {
    throw appError_('SECTOR_COUNT_MISMATCH',
      message + ' Correct the sheet, or update CONFIG.EXPECTED.');
  }
  console.warn(CONFIG.LOG_PREFIX + ' ' + message +
    ' Continuing with the sheet contents. Update CONFIG.EXPECTED to silence this warning.');
}

/** Distinct parties defined across both sector lists, in first-seen order. */
function readPartyDefinitions_() {
  if (DS_CACHE_.parties) return DS_CACHE_.parties;

  var seen = {}, parties = [];

  function collect(list) {
    list.forEach(function (d) {
      if (!d.partyKey || seen[d.partyKey]) return;
      seen[d.partyKey] = true;
      parties.push({ party: d.party, partyKey: d.partyKey });
    });
  }

  collect(readAllocationSectorDefinitions_());
  try { collect(readFlowSectorDefinitions_()); } catch (e) { /* flow list optional here */ }

  DS_CACHE_.parties = parties;
  return parties;
}

function getSectorDefinitions_() {
  return {
    allocationSectors: readAllocationSectorDefinitions_(),
    flowSectors: readFlowSectorDefinitions_(),
    parties: readPartyDefinitions_()
  };
}

/* ------------------------------------------------------------------ */
/* Master reads (one bulk read per sheet per request)                  */
/* ------------------------------------------------------------------ */

/** Reads a cell from a row array using a 1-based column number. */
function valueAt_(row, column) {
  if (!column) return '';
  var v = row[column - 1];
  return (v === null || v === undefined) ? '' : v;
}

/** Reads Metal Master into memory, resolving columns by header. */
function readMasterRows_(forceReload) {
  if (DS_CACHE_.masterRows && !forceReload) return DS_CACHE_.masterRows;

  var layout = getAllocationMasterLayout_();
  var c = layout.columns;
  var sh = getSheetOrThrow_(CONFIG.SHEETS.MASTER);
  var lastRow = sh.getLastRow();
  var rows = [];

  if (lastRow >= 2) {
    var values = sh.getRange(2, 1, lastRow - 1, layout.columnCount).getValues();
    for (var i = 0; i < values.length; i++) {
      var v = values[i];
      var dateKey = toDateKey_(valueAt_(v, c.date));
      var sector = String(valueAt_(v, c.sector)).trim();
      if (!dateKey || !sector) continue;

      var party = String(valueAt_(v, c.party)).trim();
      rows.push({
        rowNumber: i + 2,
        dateKey: dateKey,
        priority: String(valueAt_(v, c.priority)).trim(),
        party: party,
        partyKey: normalizePartyKey_(party),
        sector: sector,
        sectorKey: normalizeSectorKey_(sector),
        purity: String(valueAt_(v, c.purity)).trim(),
        previousRequirement: toNumber_(valueAt_(v, c.previousRequirement)),
        todayRequired: toNumber_(valueAt_(v, c.todayRequired)),
        alloted: toNumber_(valueAt_(v, c.alloted)),
        balance: toNumber_(valueAt_(v, c.balance))
      });
    }
  }

  DS_CACHE_.masterRows = rows;
  return rows;
}

/** Reads Metal Flow Master into memory, resolving columns by header. */
function readFlowMasterRows_(forceReload) {
  if (DS_CACHE_.flowRows && !forceReload) return DS_CACHE_.flowRows;

  var layout = getFlowMasterLayout_();
  var c = layout.columns;
  var sh = getSheetOrThrow_(CONFIG.SHEETS.FLOW_MASTER);
  var lastRow = sh.getLastRow();
  var rows = [];

  if (lastRow >= 2) {
    var values = sh.getRange(2, 1, lastRow - 1, layout.columnCount).getValues();
    for (var i = 0; i < values.length; i++) {
      var v = values[i];
      var dateKey = toDateKey_(valueAt_(v, c.date));
      var sector = String(valueAt_(v, c.sector)).trim();
      if (!dateKey || !sector) continue;

      var party = String(valueAt_(v, c.party)).trim();
      rows.push({
        rowNumber: i + 2,
        dateKey: dateKey,
        party: party,
        partyKey: normalizePartyKey_(party),
        sector: sector,
        sectorKey: normalizeSectorKey_(sector),
        acquired: toNumber_(valueAt_(v, c.acquired))
      });
    }
  }

  DS_CACHE_.flowRows = rows;
  return rows;
}

/**
 * Most recent date key in an index that falls strictly before the given date.
 * Returns '' when there is none. Keys are yyyy-MM-dd so string order is date order.
 */
function latestDateKeyBefore_(index, dateKey) {
  var best = '';
  var keys = Object.keys(index);
  for (var i = 0; i < keys.length; i++) {
    if (keys[i] < dateKey && keys[i] > best) best = keys[i];
  }
  return best;
}

/** Builds { dateKey: { sectorKey: row } } — matching is by normalized date + sector only. */
function indexByDateAndSector_(rows) {
  var index = {};
  for (var i = 0; i < rows.length; i++) {
    var r = rows[i];
    if (!index[r.dateKey]) index[r.dateKey] = {};
    index[r.dateKey][r.sectorKey] = r;
  }
  return index;
}

/** Clears the per-execution read cache. Call after any write. */
function invalidateDataCache_() {
  delete DS_CACHE_.masterRows;
  delete DS_CACHE_.flowRows;
  delete DS_CACHE_.allocDefs;
  delete DS_CACHE_.flowDefs;
  delete DS_CACHE_.parties;
}

/** True when the date already has at least one Metal Master record. */
function dateExistsInMaster_(dateKey, forceReload) {
  var rows = readMasterRows_(forceReload);
  for (var i = 0; i < rows.length; i++) {
    if (rows[i].dateKey === dateKey) return true;
  }
  return false;
}

/* ------------------------------------------------------------------ */
/* Screen data assembly                                                */
/* ------------------------------------------------------------------ */

/**
 * Builds the complete Daily Allocation screen model for a date.
 * Saved dates load their stored values; unsaved dates load previous-source-date
 * carry-forward values with empty inputs.
 */
function buildAllocationModel_(dateKey) {
  var defs = getSectorDefinitions_();
  var ruleKey = previousSourceDateKey_(dateKey);

  var masterIndex = indexByDateAndSector_(readMasterRows_(false));
  var flowIndex = indexByDateAndSector_(readFlowMasterRows_(false));

  var savedAlloc = masterIndex[dateKey] || null;
  var savedFlow = flowIndex[dateKey] || null;
  var isSaved = !!savedAlloc;

  // The rule date is Monday -> Saturday, otherwise the previous calendar day.
  // When nothing was saved on that exact date, fall back to the most recent
  // saved date before the selected one, so a gap of skipped days never wipes
  // out the carried-forward balance.
  var allocSourceKey = masterIndex[ruleKey] ? ruleKey
    : (CONFIG.RULES.CARRY_FORWARD_FROM_LATEST_SAVED ? latestDateKeyBefore_(masterIndex, dateKey) : '');
  var flowSourceKey = flowIndex[ruleKey] ? ruleKey
    : (CONFIG.RULES.CARRY_FORWARD_FROM_LATEST_SAVED ? latestDateKeyBefore_(flowIndex, dateKey) : '');

  var prevAlloc = (allocSourceKey && masterIndex[allocSourceKey]) || {};
  var prevFlow = (flowSourceKey && flowIndex[flowSourceKey]) || {};
  var hasPreviousData = !!(allocSourceKey || flowSourceKey);
  var usedFallback = !!((allocSourceKey && allocSourceKey !== ruleKey) ||
                        (flowSourceKey && flowSourceKey !== ruleKey));

  var allocations = defs.allocationSectors.map(function (def) {
    var saved = isSaved ? savedAlloc[def.sectorKey] : null;
    var carried = prevAlloc[def.sectorKey];
    var previousRequirement = saved
      ? saved.previousRequirement
      : (carried ? round3_(carried.balance) : 0);
    return {
      priority: def.priority,
      party: def.party,
      partyKey: def.partyKey,
      sector: def.sector,
      sectorKey: def.sectorKey,
      purity: def.purity,
      previousRequirement: previousRequirement,
      todayRequired: saved ? saved.todayRequired : 0,
      alloted: saved ? saved.alloted : 0,
      balance: saved ? saved.balance : round3_(previousRequirement)
    };
  });

  var metalFlow = defs.flowSectors.map(function (def) {
    var saved = savedFlow ? savedFlow[def.sectorKey] : null;
    var carried = prevFlow[def.sectorKey];
    return {
      sector: def.sector,
      sectorKey: def.sectorKey,
      party: def.party,
      partyKey: def.partyKey,
      previousAcquired: carried ? round3_(carried.acquired) : 0,
      todayAcquired: saved ? saved.acquired : 0
    };
  });

  var totals = computeTotals_(
    allocations.map(function (a) {
      return {
        previousRequirement: a.previousRequirement, todayRequired: a.todayRequired,
        alloted: a.alloted, balance: a.balance
      };
    }),
    metalFlow.map(function (f) { return { todayAcquired: f.todayAcquired }; })
  );

  var totalPreviousAcquired = 0;
  metalFlow.forEach(function (f) { totalPreviousAcquired += f.previousAcquired; });

  // What the screen shows as "Previous Source Date" is the date the values
  // actually came from, not the theoretical rule date.
  var shownSourceKey = allocSourceKey || flowSourceKey || ruleKey;

  return {
    selectedDate: dateKey,
    selectedDateDisplay: formatDisplayDate_(dateKey),
    previousSourceDate: shownSourceKey,
    previousSourceDateDisplay: formatDisplayDate_(shownSourceKey),
    ruleSourceDate: ruleKey,
    ruleSourceDateDisplay: formatDisplayDate_(ruleKey),
    allocationSourceDate: allocSourceKey,
    flowSourceDate: flowSourceKey,
    usedFallbackSource: usedFallback,
    hasPreviousData: hasPreviousData,
    isSaved: isSaved,
    savedRecordCount: isSaved ? Object.keys(savedAlloc).length : 0,
    savedFlowRecordCount: savedFlow ? Object.keys(savedFlow).length : 0,
    allocations: allocations,
    metalFlow: metalFlow,
    parties: defs.parties,
    totals: totals,
    totalPreviousAcquired: round3_(totalPreviousAcquired),
    timeZone: getAppTimeZone_()
  };
}

/* ------------------------------------------------------------------ */
/* Row preparation (written by resolved column position)               */
/* ------------------------------------------------------------------ */

/** Creates a blank row array of the sheet's width. */
function blankRow_(width) {
  var row = [];
  for (var i = 0; i < width; i++) row.push('');
  return row;
}

/** Places a value at a 1-based column, ignoring columns that do not exist. */
function putAt_(row, column, value) {
  if (column) row[column - 1] = value;
}

function buildMasterRowValues_(dateKey, allocations) {
  var layout = getAllocationMasterLayout_();
  var c = layout.columns;
  var storageDate = dateKeyToStorageDate_(dateKey);

  return allocations.map(function (a) {
    var row = blankRow_(layout.columnCount);
    putAt_(row, c.date, storageDate);
    putAt_(row, c.priority, a.priority);
    putAt_(row, c.party, a.party || '');
    putAt_(row, c.sector, a.sector);
    putAt_(row, c.purity, a.purity);
    putAt_(row, c.previousRequirement, round3_(a.previousRequirement));
    putAt_(row, c.todayRequired, round3_(a.todayRequired));
    putAt_(row, c.alloted, round3_(a.alloted));
    putAt_(row, c.balance, round3_(a.balance));
    return row;
  });
}

function buildFlowRowValues_(dateKey, metalFlow) {
  var layout = getFlowMasterLayout_();
  var c = layout.columns;
  var storageDate = dateKeyToStorageDate_(dateKey);

  return metalFlow.map(function (f) {
    var row = blankRow_(layout.columnCount);
    putAt_(row, c.date, storageDate);
    putAt_(row, c.party, f.party || '');
    putAt_(row, c.sector, f.sector);
    putAt_(row, c.acquired, round3_(f.todayAcquired));
    return row;
  });
}

/* ------------------------------------------------------------------ */
/* Transaction-safe writes                                             */
/* ------------------------------------------------------------------ */

/**
 * Appends both master datasets. If the second write fails, the first is removed,
 * so a date can never be half saved.
 */
function appendBothMasters_(masterValues, flowValues) {
  var masterSheet = getSheetOrThrow_(CONFIG.SHEETS.MASTER);
  var flowSheet = getSheetOrThrow_(CONFIG.SHEETS.FLOW_MASTER);

  ensureHeaderRow_(masterSheet, CONFIG.HEADERS.MASTER);
  ensureHeaderRow_(flowSheet, CONFIG.HEADERS.FLOW);

  var masterWidth = masterValues[0].length;
  var flowWidth = flowValues[0].length;

  var masterStart = masterSheet.getLastRow() + 1;
  masterSheet.getRange(masterStart, 1, masterValues.length, masterWidth).setValues(masterValues);
  SpreadsheetApp.flush();

  try {
    var flowStart = flowSheet.getLastRow() + 1;
    flowSheet.getRange(flowStart, 1, flowValues.length, flowWidth).setValues(flowValues);
    SpreadsheetApp.flush();
    return {
      masterStart: masterStart, masterCount: masterValues.length,
      flowStart: flowStart, flowCount: flowValues.length
    };
  } catch (writeErr) {
    // Compensating rollback of the Metal Master rows written moments ago.
    try {
      masterSheet.deleteRows(masterStart, masterValues.length);
      SpreadsheetApp.flush();
    } catch (rollbackErr) {
      console.error(CONFIG.LOG_PREFIX + ' ROLLBACK FAILED. Remove Metal Master rows ' +
        masterStart + '-' + (masterStart + masterValues.length - 1) + ' manually. ' + rollbackErr);
      throw appError_('PARTIAL_SAVE',
        'The save could not be completed and automatic cleanup failed. Contact the administrator before retrying.',
        String(rollbackErr));
    }
    throw appError_('SAVE_WRITE_FAILED',
      'The data could not be written to the Metal Flow Master. No changes were kept.',
      String(writeErr));
  }
}

/** Deletes every row for a date in one sheet (bottom-up). Returns the removed raw values. */
function deleteRowsForDate_(sheet, rows, dateKey, columnCount) {
  var targets = rows.filter(function (r) { return r.dateKey === dateKey; })
    .map(function (r) { return r.rowNumber; })
    .sort(function (a, b) { return b - a; });

  var removed = [];
  targets.forEach(function (rowNumber) {
    removed.push(sheet.getRange(rowNumber, 1, 1, columnCount).getValues()[0]);
    sheet.deleteRow(rowNumber);
  });
  SpreadsheetApp.flush();
  return removed.reverse();
}

/** Appends raw value arrays back to a sheet (used by revision rollback). */
function appendRawRows_(sheet, values, columnCount) {
  if (!values || !values.length) return;
  var start = sheet.getLastRow() + 1;
  sheet.getRange(start, 1, values.length, columnCount).setValues(values);
  SpreadsheetApp.flush();
}

/* ------------------------------------------------------------------ */
/* Setup / structure maintenance                                       */
/* ------------------------------------------------------------------ */

/** Writes the header row only when row 1 is empty. Never overwrites existing data. */
function ensureHeaderRow_(sheet, headers) {
  if (sheet.getLastRow() >= 1) {
    var width = Math.max(sheet.getLastColumn(), headers.length);
    var existing = sheet.getRange(1, 1, 1, width).getValues()[0];
    var hasContent = existing.some(function (v) { return String(v || '').trim() !== ''; });
    if (hasContent) return false;
  }
  sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
  sheet.getRange(1, 1, 1, headers.length).setFontWeight('bold');
  sheet.setFrozenRows(1);
  return true;
}

/** Creates the Audit Log sheet with headers only if it does not already exist. */
function ensureAuditSheet_() {
  var ss = getSpreadsheet_();
  var sh = ss.getSheetByName(CONFIG.SHEETS.AUDIT);
  var created = false;
  if (!sh) {
    sh = ss.insertSheet(CONFIG.SHEETS.AUDIT);
    sh.getRange(1, 1, 1, CONFIG.HEADERS.AUDIT.length).setValues([CONFIG.HEADERS.AUDIT]);
    sh.getRange(1, 1, 1, CONFIG.HEADERS.AUDIT.length).setFontWeight('bold');
    sh.setFrozenRows(1);
    created = true;
  }
  DS_CACHE_['sheet::' + CONFIG.SHEETS.AUDIT] = sh;
  return { sheet: sh, created: created };
}


/** Build marker. Used by checkInstalledFiles() to detect a stale paste. */
function buildTag_DataService_() { return '5C'; }
