/**
 * VersionCheck.gs
 * Royal Metal Allocation System
 *
 * Reports which script files are on the current build and which are stale.
 * READ ONLY. Run checkInstalledFiles() from the editor and read the log.
 *
 * How it works: every updated file defines a small build-marker function. If a
 * file was not pasted, or was pasted only partly, its marker is missing and the
 * file is reported as STALE. This turns a confusing runtime error into a
 * straightforward list of what still needs replacing.
 */

var REQUIRED_BUILD = '5C';

function checkInstalledFiles() {
  var expected = [
    { file: 'Config.gs', marker: 'buildTag_Config_', note: 'party mapping, display names, 21 sectors' },
    { file: 'SchemaService.gs', marker: 'buildTag_SchemaService_', note: 'header-driven column detection' },
    { file: 'DataService.gs', marker: 'buildTag_DataService_', note: 'party-aware sheet access' },
    { file: 'ValidationService.gs', marker: 'buildTag_ValidationService_', note: 'party in the save payload' },
    { file: 'StagingService.gs', marker: 'buildTag_StagingService_', note: 'operator scope and submissions' },
    { file: 'Code.gs', marker: 'buildTag_Code_', note: 'scoped Daily Allocation, operator save block' },
    { file: 'ReportService.gs', marker: 'buildTag_ReportService_', note: 'scoped history and dashboard' },
    { file: 'AuditService.gs', marker: 'buildTag_AuditService_', note: 'identity fix and display names' },
    { file: 'AuditReportService.gs', marker: 'buildTag_AuditReportService_', note: 'audit viewer' }
  ];

  var report = { requiredBuild: REQUIRED_BUILD, current: [], stale: [], missingFile: [] };

  expected.forEach(function (e) {
    var fn = null;
    try { fn = eval(e.marker); } catch (err) { fn = null; }

    if (typeof fn !== 'function') {
      report.missingFile.push(e.file + '  ->  not installed or pasted incompletely (' + e.note + ')');
      return;
    }
    var tag = String(fn());
    if (tag === REQUIRED_BUILD) report.current.push(e.file + '  ->  ' + tag);
    else report.stale.push(e.file + '  ->  build ' + tag + ', expected ' + REQUIRED_BUILD);
  });

  // Configuration sanity, which a correct paste alone does not guarantee.
  report.configuration = [];
  try {
    report.configuration.push('APP_VERSION: ' + CONFIG.APP_VERSION);
    report.configuration.push('OPERATOR_PARTIES entries: ' +
      Object.keys(CONFIG.OPERATOR_PARTIES || {}).length);
    report.configuration.push('ADMIN_EMAILS entries: ' + (CONFIG.ADMIN_EMAILS || []).length);
    report.configuration.push('Expected allocation sectors: ' + CONFIG.EXPECTED.ALLOCATION_ROWS);
    report.configuration.push('GENERATOR detection block present: ' + (!!CONFIG.GENERATOR));
    report.configuration.push('Staging sheet configured: ' + (CONFIG.SHEETS.STAGING || 'MISSING'));
  } catch (err) {
    report.configuration.push('CONFIG could not be read: ' + err);
  }

  report.verdict = (!report.stale.length && !report.missingFile.length)
    ? 'All server files are on build ' + REQUIRED_BUILD +
      '. If the browser still behaves oddly, replace Scripts.html and deploy a NEW VERSION.'
    : 'Replace the files listed under missingFile and stale, then deploy a new version.';

  console.log(CONFIG.LOG_PREFIX + ' INSTALLED FILES\n' + JSON.stringify(report, null, 2));
  return report;
}

/**
 * Confirms what the server would send for a given user, without opening the app
 * as that person. Administrators only, since it reveals another user's scope.
 *
 * @param {string} email  the account to simulate, e.g. 'pc2.rcpl@gmail.com'
 */
function previewScopeFor(email) {
  try {
    if (!isAdministrator_(getActiveUserEmail_())) {
      return { error: 'Only an administrator can preview another user\u2019s scope.' };
    }
    invalidateDataCache_();
    var scope = getUserScope_(email);
    var scoped = scopedSectorNames_(scope);

    var out = {
      email: email,
      displayName: scope.displayName,
      role: scope.role,
      isAdmin: scope.isAdmin,
      parties: scope.parties.map(function (p) { return p.party; }),
      allocationSectorsVisible: scoped.allocation.length,
      allocationSectorNames: scoped.allocation.map(function (d) { return d.sector; }),
      flowSectorsVisible: scoped.flow.length,
      flowSectorNames: scoped.flow.map(function (d) { return d.sector; }),
      canEditAlloted: scope.isAdmin,
      canSaveDate: scope.isAdmin
    };
    console.log(CONFIG.LOG_PREFIX + ' SCOPE PREVIEW\n' + JSON.stringify(out, null, 2));
    return out;
  } catch (err) {
    console.error(CONFIG.LOG_PREFIX + ' previewScopeFor: ' + err);
    return { error: String(err) };
  }
}
