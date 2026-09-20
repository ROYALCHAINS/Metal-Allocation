/**
 * Config.gs
 * Royal Metal Allocation System — Phase 1
 *
 * SINGLE SOURCE OF CONFIGURATION.
 * Every sheet name, range, row count, rule toggle and administrator email lives here.
 * Do not hard-code these values anywhere else in the project.
 */

var CONFIG = {

  APP_NAME: 'Royal Metal Allocation System',
  APP_VERSION: '5H',

  /**
   * Leave blank ('') to bind to the container spreadsheet (recommended: create the
   * Apps Script project from Extensions > Apps Script inside the workbook).
   * If you deploy as a standalone script, paste the workbook ID here.
   */
  SPREADSHEET_ID: '',

  /* ================================================================
     USER ACCESS CONFIGURATION  <-- the two lists you edit are here
     Both are checked on the SERVER on every request. The browser is
     never trusted. Emails are compared case-insensitively after trimming.
     ================================================================ */

  /**
   * ADMINISTRATORS.
   * Only these Google account emails may open the Audit Log tab and use the
   * Edit Saved Date revision workflow. One quoted email per line, comma separated.
   */
  ADMIN_EMAILS: [
    'shubham.g@royalchains.com'
  ],

  /**
   * FORCED NON-ADMINISTRATORS (deny list).
   * Anyone listed here is always treated as a regular operator, even if the
   * same address also appears in ADMIN_EMAILS above. An explicit denial always
   * wins, so this is the immediate way to strip someone's admin rights.
   *
   * You do NOT need to list ordinary users here. Anyone not in ADMIN_EMAILS is
   * already a regular operator by default. Use this list only when you want to
   * guarantee a specific person can never hold admin rights.
   */
  NON_ADMIN_EMAILS: [
    'pc2.rcpl@gmail.com',
    'godnooblm10@gmail.com'
  ],

  /**
   * DISPLAY NAMES.
   * Maps a Google account email to the short name shown in the app header.
   * Anyone not listed falls back to the part of their email before the '@',
   * so this list is optional and only needs the people you want named exactly.
   * Keys are matched case-insensitively.
   */
  USER_DISPLAY_NAMES: {
    'shubham.g@royalchains.com': 'Shubham',
    'pc2.rcpl@gmail.com': 'Snehal',
    'godnooblm10@gmail.com': 'Operator1'
  },

  /**
   * OPERATOR -> PARTY MAPPING.
   * An operator sees only the sectors belonging to the parties listed here,
   * in every view. Administrators are not listed and always see every party.
   * Party names are matched against the Party column in Metal Generator,
   * case-insensitively and ignoring spacing.
   */
  OPERATOR_PARTIES: {
    'pc2.rcpl@gmail.com': ['Aalishaan'],
    'godnooblm10@gmail.com': ['RC']
  },

  /**
   * How the Metal Generator layout is discovered.
   * Columns are located by their HEADER TEXT, so inserting or moving a column
   * no longer breaks the app. Add alternative spellings to LABELS if your
   * headers differ. Use OVERRIDE only when auto-detection cannot work.
   */
  GENERATOR: {
    HEADER_SCAN_ROWS: 12,
    HEADER_SCAN_COLUMNS: 20,
    MAX_SECTOR_ROWS: 200,
    LABELS: {
      priority: ['Priority'],
      party: ['Party', 'Party Name'],
      sector: ['Sector', 'Sector Name'],
      purity: ['Purity']
    },
    OVERRIDE: {
      // allocation: { headerRow: 5, priority: 'A', party: 'B', sector: 'C', purity: 'D' },
      // flow: { headerRow: 5, sector: 'J', party: 'K' }
    }
  },

  /** Header labels used to locate columns in Metal Master. */
  MASTER_LABELS: {
    date: ['Date'],
    priority: ['Priority'],
    party: ['Party', 'Party Name'],
    sector: ['Sector', 'Sector Name'],
    purity: ['Purity'],
    previousRequirement: ['Previous Requirement', 'Prev Requirement'],
    todayRequired: ["Today's Required Weight", 'Today Required Weight', "Today's Required"],
    alloted: ['Alloted', 'Allotted'],
    balance: ['Balance']
  },

  /**
   * OPERATOR -> METAL FLOW SECTOR MAPPING.
   *
   * The Metal Flow table is keyed by party name rather than by order type, so an
   * operator is mapped straight to the Metal Flow sector(s) they own. Names are
   * matched against Metal Generator's Metal Flow list, case-insensitively and
   * ignoring spacing and dash style.
   *
   * When an email is absent from this map, that operator's Metal Flow access
   * falls back to the Party column beside the Metal Flow list in Metal Generator.
   * Administrators always see every Metal Flow sector.
   */
  OPERATOR_FLOW_SECTORS: {
    'pc2.rcpl@gmail.com': ['Aalishaan'],
    'godnooblm10@gmail.com': ['Royal Chain']
  },

  /**
   * Optional Metal Flow sector -> party fallback, used only when the Metal Flow
   * list has no Party column AND an operator is not listed in
   * OPERATOR_FLOW_SECTORS above. Usually left empty.
   */
  FLOW_SECTOR_PARTIES: {},

  /** Header labels used to locate columns in Metal Flow Master. */
  FLOW_LABELS: {
    date: ['Date'],
    party: ['Party', 'Party Name'],
    sector: ['Sector', 'Sector Name'],
    acquired: ['Acquired', "Today's Acquired"]
  },

  SHEETS: {
    GENERATOR: 'Metal Generator',
    MASTER: 'Metal Master',
    FLOW_MASTER: 'Metal Flow Master',
    AUDIT: 'Metal Allocation Audit Log',
    STAGING: 'Metal Requirement Staging',
    // Referenced only so setup can confirm they exist. Never written to.
    PROTECTED_REFERENCE: ['Example', 'Metal Allocation Working']
  },

  RANGES: {
    // 19 allocation sectors: Priority | Sector | Purity
    ALLOCATION_SECTORS: 'A7:C25',
    // 8 metal flow sectors: Sector
    FLOW_SECTORS: 'I7:I14'
  },

  EXPECTED: {
    // Expected counts. With STRICT false a mismatch is logged as a warning and
    // whatever the sheet actually contains is used, so adding a sector does not
    // stop the app. Set STRICT true to hard-fail on any mismatch.
    ALLOCATION_ROWS: 21,
    FLOW_ROWS: 8,
    STRICT: false
  },

  COLUMNS: {
    MASTER_COUNT: 8,
    FLOW_COUNT: 3,
    AUDIT_COUNT: 13
  },

  HEADERS: {
    // Used only when creating a header row on an EMPTY sheet. Existing sheets
    // are read by header label, so column order here does not have to match.
    MASTER: [
      'Date', 'Priority', 'Party', 'Sector', 'Purity',
      'Previous Requirement', "Today's Required Weight", 'Alloted', 'Balance'
    ],
    FLOW: ['Date', 'Party', 'Sector', 'Acquired'],
    STAGING: [
      'Submission_ID', 'Allocation_Date', 'Party', 'Operator_Email',
      'Submitted_At', 'Record_Type', 'Sector', 'Value', 'Status'
    ],
    AUDIT: [
      'Audit_ID', 'Allocation_Date', 'Action_Type', 'Revision_Number', 'User_Email',
      'Action_Timestamp', 'Revision_Reason', 'Previous_Allocation_Data',
      'Updated_Allocation_Data', 'Previous_Metal_Flow_Data', 'Updated_Metal_Flow_Data',
      'Request_ID', 'Action_Status'
    ]
  },

  /**
   * CONFIRMED BUSINESS RULES (final decisions).
   * These are toggles so the business owner can change policy without editing logic.
   */
  RULES: {
    ALLOW_ZERO_PREVIOUS_REQUIREMENT: true,   // Decision 1

    /**
     * Carry-forward fallback.
     * true  = when nothing was saved on the rule date (Monday -> Saturday,
     *         otherwise yesterday), carry forward from the most recent saved
     *         date instead, so skipped days never reset balances to 0.000.
     * false = strict original behaviour: the rule date only, else 0.000.
     */
    CARRY_FORWARD_FROM_LATEST_SAVED: true,
    ALLOW_ZERO_CLOSING_BALANCE: true,        // Decision 2
    REQUIRE_POSITIVE_ACQUIRED: true,         // there must be metal on the date

    /**
     * Alloted vs Acquired constraints. All three are now OFF: an administrator
     * saves whenever they choose, and the allocation need not match the metal
     * acquired. Set any of them true to reinstate the old behaviour.
     */
    REQUIRE_POSITIVE_ALLOTED: false,         // was Decision 9
    REQUIRE_FULL_ALLOCATION: false,          // was Decision 3 (Remaining = 0.000)
    BLOCK_OVER_ALLOCATION: false,            // allow Alloted to exceed Acquired

    /**
     * Operator submission cross-check. OFF.
     * An operator's Today's Required is no longer capped by their Today's
     * Acquired. Requirement is demand and Acquired is supply, so demand
     * legitimately exceeds supply and the shortfall carries forward as Balance.
     * Set true only if requirement should be capped at metal in hand.
     */
    OPERATOR_REQUIRED_WITHIN_ACQUIRED: false,
    ALLOW_ADMIN_REVISION: true,              // Decision 4
    REQUIRE_REVISION_REASON: true,           // Decision 5
    MIN_REVISION_REASON_LENGTH: 10,
    SAVED_DATE_IMMUTABLE_FOR_USERS: true
  },

  DECIMALS: 3,
  EPSILON: 0.0005,               // half of the 3rd decimal place
  MAX_WEIGHT_KG: 100000,         // sanity ceiling on any single numeric input

  TIMEZONE_FALLBACK: 'Asia/Kolkata',

  LOCK_TIMEOUT_MS: 30000,
  REQUEST_ID_TTL_SECONDS: 900,   // double-click / retry protection window

  /** Dates are stored at 12:00 local time to eliminate DST / UTC rollover drift. */
  STORAGE_HOUR: 12,

  LOG_PREFIX: '[RMAS]'
};

/** Returned to the client for display only. Never returns ADMIN_EMAILS. */
function getPublicConfig_() {
  return {
    appName: CONFIG.APP_NAME,
    appVersion: CONFIG.APP_VERSION,
    decimals: CONFIG.DECIMALS,
    expected: CONFIG.EXPECTED,
    rules: {
      requireFullAllocation: CONFIG.RULES.REQUIRE_FULL_ALLOCATION,
      requirePositiveAcquired: CONFIG.RULES.REQUIRE_POSITIVE_ACQUIRED,
      minRevisionReasonLength: CONFIG.RULES.MIN_REVISION_REASON_LENGTH
    }
  };
}

/** Build marker. Used by checkInstalledFiles() to detect a stale paste. */
function buildTag_Config_() { return '5C'; }

/**
 * SELF-CHECK — run this from the editor after pasting any file.
 * It proves which content actually landed in which file, which is the failure
 * this project has hit repeatedly. Read the result in the execution log.
 */
function checkInstalledFiles() {
  var report = { ok: true, problems: [], checks: [] };

  function probe(label, fn, expected) {
    var found;
    try { found = fn(); } catch (e) { found = '(missing: ' + e + ')'; }
    var pass = (found === expected);
    report.checks.push((pass ? 'ok   ' : 'FAIL ') + label + ' -> ' + found);
    if (!pass) { report.ok = false; report.problems.push(label + ' is missing or stale.'); }
  }

  probe('Config.gs',        function () { return buildTag_Config_(); },        '5H');
  probe('CONFIG object',    function () { return typeof CONFIG; },            'object');
  probe('OPERATOR_FLOW_SECTORS', function () {
    return CONFIG.OPERATOR_FLOW_SECTORS ? 'present' : 'MISSING'; }, 'present');
  probe('SchemaService.gs', function () { return typeof getGeneratorLayout_; }, 'function');
  probe('DataService.gs',   function () { return typeof readAllocationSectorDefinitions_; }, 'function');
  probe('StagingService.gs',function () { return typeof applyStagingToModel_; }, 'function');
  probe('ReportService.gs', function () { return typeof getAllocationHistory; }, 'function');
  probe('AuditService.gs',  function () { return typeof writeAuditEntry_; },   'function');
  probe('Code.gs',          function () { return typeof saveDailyAllocation; }, 'function');

  if (report.ok) {
    report.verdict = 'All script files are present and current.';
  } else {
    report.verdict = 'One or more files are missing or hold the wrong content. ' +
      'Check that each file name matches the content pasted into it.';
  }

  console.log(CONFIG.LOG_PREFIX + ' INSTALLED FILES\n' + JSON.stringify(report, null, 2));
  return report;
}

/** Build marker. Used by checkInstalledFiles() to detect a stale paste. */
function buildTag_Config_() { return '5H'; }
