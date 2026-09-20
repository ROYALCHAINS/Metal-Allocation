/**
 * SchemaService.gs
 * Royal Metal Allocation System — Phase 5A
 *
 * Locates columns by their HEADER TEXT instead of fixed positions.
 *
 * Why: the sheet layout changes as the business changes. A Party column was
 * inserted into Metal Generator and the sector count grew from 19 to 21, which
 * silently broke fixed-range reading. Reading by header label means inserting,
 * moving or reordering a column no longer breaks the app.
 *
 * Every detected layout is cached per execution. Nothing here writes.
 */

var SCHEMA_CACHE_ = {};

/** Normalizes a header label for comparison: lowercase, no punctuation or spaces. */
function normalizeHeader_(text) {
  return String(text === null || text === undefined ? '' : text)
    .replace(/[\u2010-\u2015\u2212]/g, '-')
    .replace(/[^a-z0-9]+/gi, '')
    .toLowerCase();
}

/** True when a cell's header matches any of the accepted labels for a field. */
function headerMatches_(cellValue, labels) {
  var key = normalizeHeader_(cellValue);
  if (!key) return false;
  for (var i = 0; i < labels.length; i++) {
    if (key === normalizeHeader_(labels[i])) return true;
  }
  return false;
}

/** Finds the column index (1-based) of the first header matching the labels. */
function findHeaderColumn_(headerRowValues, labels, startColumn) {
  var from = startColumn || 1;
  for (var c = from; c <= headerRowValues.length; c++) {
    if (headerMatches_(headerRowValues[c - 1], labels)) return c;
  }
  return 0;
}

/* ------------------------------------------------------------------ */
/* Metal Generator layout                                              */
/* ------------------------------------------------------------------ */

/**
 * Detects the Metal Generator layout.
 *
 * Returns:
 * {
 *   headerRow, firstRow, lastRow,
 *   allocation: {priority, party, sector, purity},   // 1-based column numbers, 0 = absent
 *   flow: {sector, party, headerRow, firstRow, lastRow}
 * }
 */
function getGeneratorLayout_() {
  if (SCHEMA_CACHE_.generator) return SCHEMA_CACHE_.generator;

  var sh = getSheetOrThrow_(CONFIG.SHEETS.GENERATOR);
  var lastRow = sh.getLastRow();
  var lastCol = sh.getLastColumn();
  if (lastRow < 2 || lastCol < 2) {
    throw appError_('GENERATOR_EMPTY',
      'The ' + CONFIG.SHEETS.GENERATOR + ' sheet appears to be empty.');
  }

  var scanRows = Math.min(lastRow, CONFIG.GENERATOR.HEADER_SCAN_ROWS);
  var scanCols = Math.min(lastCol, CONFIG.GENERATOR.HEADER_SCAN_COLUMNS);
  var grid = sh.getRange(1, 1, scanRows, scanCols).getValues();

  var L = CONFIG.GENERATOR.LABELS;
  var layout = null;

  // The allocation header row is the one containing a Sector label.
  for (var r = 0; r < grid.length && !layout; r++) {
    var row = grid[r];
    var sectorCol = findHeaderColumn_(row, L.sector, 1);
    if (!sectorCol) continue;

    layout = {
      headerRow: r + 1,
      allocation: {
        priority: findHeaderColumn_(row, L.priority, 1),
        party: findHeaderColumn_(row, L.party, 1),
        sector: sectorCol,
        purity: findHeaderColumn_(row, L.purity, 1)
      },
      // A second Sector label further right marks the Metal Flow block.
      flow: {
        headerRow: r + 1,
        sector: findHeaderColumn_(row, L.sector, sectorCol + 1),
        party: 0
      },
      detectedHeaders: row.map(function (v) { return String(v || '').trim(); })
    };
  }

  if (!layout) {
    throw appError_('GENERATOR_HEADER_NOT_FOUND',
      'No "Sector" header was found in the first ' + scanRows + ' rows of ' +
      CONFIG.SHEETS.GENERATOR + '. Add a header row, or set the column overrides in CONFIG.GENERATOR.OVERRIDE.');
  }

  // The flow Party column, if present, sits just right of the flow Sector column.
  if (layout.flow.sector) {
    var headerRowValues = grid[layout.flow.headerRow - 1];
    var flowParty = findHeaderColumn_(headerRowValues, L.party, layout.flow.sector + 1);
    layout.flow.party = flowParty || 0;
  }

  applyGeneratorOverrides_(layout);

  if (!layout.allocation.sector) {
    throw appError_('GENERATOR_SECTOR_COLUMN_MISSING',
      'The Sector column could not be located in ' + CONFIG.SHEETS.GENERATOR + '.');
  }

  // Sector rows run from just below the header until the first blank sector.
  var bounds = findBlockBounds_(sh, layout.headerRow + 1, layout.allocation.sector);
  layout.firstRow = bounds.firstRow;
  layout.lastRow = bounds.lastRow;

  if (layout.flow.sector) {
    var flowBounds = findBlockBounds_(sh, layout.flow.headerRow + 1, layout.flow.sector);
    layout.flow.firstRow = flowBounds.firstRow;
    layout.flow.lastRow = flowBounds.lastRow;
  } else {
    layout.flow.firstRow = 0;
    layout.flow.lastRow = 0;
  }

  SCHEMA_CACHE_.generator = layout;
  return layout;
}

/**
 * Walks down a column from a start row and returns the contiguous block of
 * non-blank cells. A single blank row ends the block, so unrelated content
 * further down the sheet is never absorbed.
 */
function findBlockBounds_(sheet, startRow, column) {
  var sheetLastRow = sheet.getLastRow();
  if (startRow > sheetLastRow) return { firstRow: 0, lastRow: 0, count: 0 };

  var height = Math.min(sheetLastRow - startRow + 1, CONFIG.GENERATOR.MAX_SECTOR_ROWS);
  var values = sheet.getRange(startRow, column, height, 1).getValues();

  var firstRow = 0, lastRow = 0;
  for (var i = 0; i < values.length; i++) {
    var filled = String(values[i][0] === null || values[i][0] === undefined ? '' : values[i][0]).trim() !== '';
    if (filled) {
      if (!firstRow) firstRow = startRow + i;
      lastRow = startRow + i;
    } else if (firstRow) {
      break;                          // blank row ends the block
    }
  }
  return { firstRow: firstRow, lastRow: lastRow, count: firstRow ? (lastRow - firstRow + 1) : 0 };
}

/** Applies any manual overrides from CONFIG.GENERATOR.OVERRIDE. */
function applyGeneratorOverrides_(layout) {
  var o = CONFIG.GENERATOR.OVERRIDE || {};

  function col(letter) {
    var s = String(letter || '').trim().toUpperCase();
    if (!s) return 0;
    var n = 0;
    for (var i = 0; i < s.length; i++) {
      var code = s.charCodeAt(i) - 64;
      if (code < 1 || code > 26) return 0;
      n = n * 26 + code;
    }
    return n;
  }

  if (o.allocation) {
    ['priority', 'party', 'sector', 'purity'].forEach(function (f) {
      var c = col(o.allocation[f]);
      if (c) layout.allocation[f] = c;
    });
    if (o.allocation.headerRow) layout.headerRow = Number(o.allocation.headerRow);
  }
  if (o.flow) {
    var fs = col(o.flow.sector);
    if (fs) layout.flow.sector = fs;
    var fp = col(o.flow.party);
    if (fp) layout.flow.party = fp;
    if (o.flow.headerRow) layout.flow.headerRow = Number(o.flow.headerRow);
  }
}

/* ------------------------------------------------------------------ */
/* Master sheet layouts                                                */
/* ------------------------------------------------------------------ */

/**
 * Detects a master sheet's columns from its header row.
 * Party is optional: when the column is absent the value is simply not written,
 * so an older workbook keeps working.
 *
 * @param {string} sheetName
 * @param {Object} labelMap  field -> array of accepted header labels
 * @param {Array}  required  field names that must be present
 */
function getMasterLayout_(sheetName, labelMap, required) {
  var cacheKey = 'master::' + sheetName;
  if (SCHEMA_CACHE_[cacheKey]) return SCHEMA_CACHE_[cacheKey];

  var sh = getSheetOrThrow_(sheetName);
  var lastCol = Math.max(sh.getLastColumn(), 1);
  var headerValues = sh.getRange(1, 1, 1, lastCol).getValues()[0];

  var columns = {};
  Object.keys(labelMap).forEach(function (field) {
    columns[field] = findHeaderColumn_(headerValues, labelMap[field], 1);
  });

  var missing = (required || []).filter(function (f) { return !columns[f]; });
  if (missing.length) {
    throw appError_('MASTER_HEADER_MISSING',
      'The sheet "' + sheetName + '" is missing required column(s): ' + missing.join(', ') +
      '. Found headers: ' + headerValues.map(function (v) { return String(v || '').trim(); })
        .filter(String).join(', ') + '.');
  }

  var layout = {
    sheetName: sheetName,
    columns: columns,
    columnCount: lastCol,
    headers: headerValues.map(function (v) { return String(v || '').trim(); })
  };

  SCHEMA_CACHE_[cacheKey] = layout;
  return layout;
}

function getAllocationMasterLayout_() {
  return getMasterLayout_(CONFIG.SHEETS.MASTER, CONFIG.MASTER_LABELS,
    ['date', 'sector', 'previousRequirement', 'todayRequired', 'alloted', 'balance']);
}

function getFlowMasterLayout_() {
  return getMasterLayout_(CONFIG.SHEETS.FLOW_MASTER, CONFIG.FLOW_LABELS,
    ['date', 'sector', 'acquired']);
}

/** Clears the detected layouts. Call after any structural sheet change. */
function invalidateSchemaCache_() {
  SCHEMA_CACHE_ = {};
}

/**
 * Human-readable summary of everything that was detected.
 * Run this from the editor after changing the sheet structure.
 */
function describeDetectedSchema() {
  try {
    invalidateSchemaCache_();
    var g = getGeneratorLayout_();

    var report = {
      generator: {
        headerRow: g.headerRow,
        sectorRows: g.firstRow + ' to ' + g.lastRow,
        sectorCount: g.firstRow ? (g.lastRow - g.firstRow + 1) : 0,
        columns: {
          priority: g.allocation.priority ? columnLetterOf_(g.allocation.priority) : '(not found)',
          party: g.allocation.party ? columnLetterOf_(g.allocation.party) : '(not found)',
          sector: columnLetterOf_(g.allocation.sector),
          purity: g.allocation.purity ? columnLetterOf_(g.allocation.purity) : '(not found)'
        },
        flow: {
          sector: g.flow.sector ? columnLetterOf_(g.flow.sector) : '(not found)',
          party: g.flow.party ? columnLetterOf_(g.flow.party) : '(not found)',
          rows: g.flow.firstRow ? (g.flow.firstRow + ' to ' + g.flow.lastRow) : '(none)',
          count: g.flow.firstRow ? (g.flow.lastRow - g.flow.firstRow + 1) : 0
        }
      }
    };

    try {
      var m = getAllocationMasterLayout_();
      report.metalMaster = { headers: m.headers.filter(String), resolved: describeColumns_(m.columns) };
    } catch (e) { report.metalMaster = { error: e.userMessage || String(e) }; }

    try {
      var f = getFlowMasterLayout_();
      report.metalFlowMaster = { headers: f.headers.filter(String), resolved: describeColumns_(f.columns) };
    } catch (e2) { report.metalFlowMaster = { error: e2.userMessage || String(e2) }; }

    console.log(CONFIG.LOG_PREFIX + ' DETECTED SCHEMA\n' + JSON.stringify(report, null, 2));
    return report;
  } catch (err) {
    console.error(CONFIG.LOG_PREFIX + ' describeDetectedSchema: ' + err);
    return { error: (err && err.userMessage) || String(err) };
  }
}

function describeColumns_(columns) {
  var out = {};
  Object.keys(columns).forEach(function (k) {
    out[k] = columns[k] ? columnLetterOf_(columns[k]) : '(not found)';
  });
  return out;
}

/** 1 -> A, 27 -> AA */
function columnLetterOf_(n) {
  var s = '';
  while (n > 0) {
    var m = (n - 1) % 26;
    s = String.fromCharCode(65 + m) + s;
    n = Math.floor((n - m) / 26);
  }
  return s;
}


/** Build marker. Used by checkInstalledFiles() to detect a stale paste. */
function buildTag_SchemaService_() { return '5C'; }
