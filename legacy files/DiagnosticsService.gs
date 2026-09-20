/**
 * DiagnosticsService.gs
 * Royal Metal Allocation System — layout inspection
 *
 * READ ONLY. These functions write nothing. Run them from the Apps Script
 * editor and read the output in the execution log, so the configuration can be
 * matched to the real sheet layout instead of being guessed.
 */

/** Converts a 1-based column number to its letter, e.g. 1 -> A, 27 -> AA. */
function columnLetter_(n) {
  var s = '';
  while (n > 0) {
    var m = (n - 1) % 26;
    s = String.fromCharCode(65 + m) + s;
    n = Math.floor((n - m) / 26);
  }
  return s;
}

function cellPreview_(v) {
  if (v === null || v === undefined || v === '') return '';
  if (Object.prototype.toString.call(v) === '[object Date]') {
    return 'DATE(' + Utilities.formatDate(v, getAppTimeZone_(), 'yyyy-MM-dd') + ')';
  }
  var s = String(v).trim();
  return s.length > 40 ? s.substring(0, 39) + '\u2026' : s;
}

/**
 * Dumps the top-left block of Metal Generator so the true position of
 * Priority, Party, Sector, Purity and the Metal Flow list can be identified.
 */
function inspectMetalGeneratorLayout() {
  var out = { sheet: CONFIG.SHEETS.GENERATOR, rows: [] };
  try {
    var sh = getSheetOrThrow_(CONFIG.SHEETS.GENERATOR);
    out.lastRow = sh.getLastRow();
    out.lastColumn = sh.getLastColumn();

    var rowCount = Math.min(sh.getLastRow(), 32);
    var colCount = Math.min(sh.getLastColumn(), 14);
    if (rowCount < 1 || colCount < 1) {
      out.error = 'The sheet appears to be empty.';
      console.log(CONFIG.LOG_PREFIX + ' GENERATOR LAYOUT\n' + JSON.stringify(out, null, 2));
      return out;
    }

    var header = [];
    for (var c = 1; c <= colCount; c++) header.push(columnLetter_(c));
    out.columns = header.join(' | ');

    var values = sh.getRange(1, 1, rowCount, colCount).getValues();
    for (var r = 0; r < values.length; r++) {
      var cells = values[r].map(cellPreview_);
      if (cells.join('').trim() === '') continue;      // skip fully blank rows
      out.rows.push('Row ' + (r + 1) + ': ' + cells.join(' | '));
    }

    out.currentConfig = {
      allocationRange: CONFIG.RANGES.ALLOCATION_SECTORS,
      flowRange: CONFIG.RANGES.FLOW_SECTORS,
      expectedAllocationRows: CONFIG.EXPECTED.ALLOCATION_ROWS,
      expectedFlowRows: CONFIG.EXPECTED.FLOW_ROWS
    };
    out.next = 'Identify which column letter holds Priority, Party, Sector and Purity, ' +
      'and the first and last row of the sector block. Then update CONFIG.';

    console.log(CONFIG.LOG_PREFIX + ' GENERATOR LAYOUT\n' + JSON.stringify(out, null, 2));
    return out;
  } catch (err) {
    out.error = String(err);
    console.error(CONFIG.LOG_PREFIX + ' inspectMetalGeneratorLayout: ' + err);
    return out;
  }
}

/**
 * Reports the header row and a sample data row from both master sheets, so the
 * position of any newly added Party column can be confirmed before the save
 * code is changed.
 */
function inspectMasterLayout() {
  var out = {};

  [CONFIG.SHEETS.MASTER, CONFIG.SHEETS.FLOW_MASTER].forEach(function (name) {
    var info = { sheet: name };
    try {
      var sh = getSheetIfExists_(name);
      if (!sh) { info.error = 'Sheet not found.'; out[name] = info; return; }

      info.lastRow = sh.getLastRow();
      info.lastColumn = sh.getLastColumn();

      var colCount = Math.min(sh.getLastColumn(), 14);
      if (colCount < 1 || sh.getLastRow() < 1) { info.note = 'Sheet is empty.'; out[name] = info; return; }

      var letters = [];
      for (var c = 1; c <= colCount; c++) letters.push(columnLetter_(c));
      info.columns = letters.join(' | ');
      info.headerRow = sh.getRange(1, 1, 1, colCount).getValues()[0].map(cellPreview_).join(' | ');

      if (sh.getLastRow() >= 2) {
        info.firstDataRow = sh.getRange(2, 1, 1, colCount).getValues()[0].map(cellPreview_).join(' | ');
        info.lastDataRow = sh.getRange(sh.getLastRow(), 1, 1, colCount)
          .getValues()[0].map(cellPreview_).join(' | ');
        info.dataRowCount = sh.getLastRow() - 1;
      } else {
        info.note = 'No saved records yet.';
      }

      info.expectedByConfig = (name === CONFIG.SHEETS.MASTER)
        ? CONFIG.HEADERS.MASTER.join(' | ')
        : CONFIG.HEADERS.FLOW.join(' | ');
    } catch (err) {
      info.error = String(err);
    }
    out[name] = info;
  });

  console.log(CONFIG.LOG_PREFIX + ' MASTER LAYOUT\n' + JSON.stringify(out, null, 2));
  return out;
}

/** Runs every layout inspection in one go. */
function inspectAllLayouts() {
  return {
    generator: inspectMetalGeneratorLayout(),
    masters: inspectMasterLayout()
  };
}
