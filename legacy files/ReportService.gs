/**
 * ReportService.gs
 * Royal Metal Allocation System — Phase 2
 *
 * Allocation History, Metal Flow History and Analysis Dashboard.
 * STRICTLY READ ONLY. Nothing in this file writes to any sheet.
 * Phase 1 files are not modified by Phase 2.
 */

/**
 * Phase 2 reporting configuration.
 * Kept here so Phase 1's Config.gs does not have to be re-pasted on a live system.
 * Move these into CONFIG later if you prefer a single object.
 */
/** Fixed window, in calendar days, for the acquired-metal heatmap. */
var HEATMAP_WINDOW_DAYS = 30;

var REPORT_CONFIG = {
  MAX_ROWS_RETURNED: 3000,     // hard ceiling on rows in one response
  PAGE_SIZE: 100,              // default rows per page in the history views
  DEFAULT_RANGE_DAYS: 30,      // default look-back when no date filter is supplied
  TOP_SECTOR_LIMIT: 10,        // "Top sectors by pending balance"
  MAX_TREND_POINTS: 120,       // date points drawn on the dashboard trend charts
  MAX_HEATMAP_DATES: 180       // hard ceiling on heatmap columns
};

/* ------------------------------------------------------------------ */
/* Filter helpers                                                      */
/* ------------------------------------------------------------------ */

/** Builds a lookup of sector -> sheet order so history sorts like the Generator. */
function buildSectorOrderMap_() {
  var map = {};
  try {
    readAllocationSectorDefinitions_().forEach(function (d, i) { map[d.sectorKey] = i; });
  } catch (e) { /* definitions unavailable: fall back to alphabetical ordering */ }
  return map;
}

function buildFlowOrderMap_() {
  var map = {};
  try {
    readFlowSectorDefinitions_().forEach(function (d, i) { map[d.sectorKey] = i; });
  } catch (e) { /* ignore */ }
  return map;
}

/** Normalizes a raw filter object from the browser into safe internal values. */
function normalizeFilters_(filters) {
  var f = filters || {};

  var from = toDateKey_(f.fromDate);
  var to = toDateKey_(f.toDate);
  if (from && !isValidDateKey_(from)) from = '';
  if (to && !isValidDateKey_(to)) to = '';
  if (from && to && from > to) { var swap = from; from = to; to = swap; }

  function toKeyList(value) {
    if (!value) return null;
    var arr = Array.isArray(value) ? value : [value];
    var out = arr.map(function (v) { return normalizeSectorKey_(v); })
      .filter(function (v) { return v && v !== 'all'; });
    return out.length ? out : null;
  }

  var limit = Number(f.limit);
  if (!isFinite(limit) || limit <= 0 || limit > REPORT_CONFIG.MAX_ROWS_RETURNED) {
    limit = REPORT_CONFIG.PAGE_SIZE;
  }
  var offset = Number(f.offset);
  if (!isFinite(offset) || offset < 0) offset = 0;

  return {
    from: from,
    to: to,
    sectors: toKeyList(f.sectors),
    priorities: toKeyList(f.priorities),
    purities: toKeyList(f.purities),
    status: ['pending', 'cleared', 'allocated', 'unallocated'].indexOf(String(f.status || '')) >= 0
      ? String(f.status) : 'all',
    search: String(f.search || '').trim().toLowerCase(),
    limit: Math.floor(limit),
    offset: Math.floor(offset)
  };
}

/** Date-window test using yyyy-MM-dd string comparison. */
function inDateWindow_(dateKey, nf) {
  if (nf.from && dateKey < nf.from) return false;
  if (nf.to && dateKey > nf.to) return false;
  return true;
}

/** Applies every allocation filter to one Metal Master row. */
function matchesAllocationFilters_(row, nf) {
  if (!inDateWindow_(row.dateKey, nf)) return false;
  if (nf.sectors && nf.sectors.indexOf(row.sectorKey) < 0) return false;
  if (nf.priorities && nf.priorities.indexOf(normalizeSectorKey_(row.priority)) < 0) return false;
  if (nf.purities && nf.purities.indexOf(normalizeSectorKey_(row.purity)) < 0) return false;

  if (nf.status === 'pending' && !(row.balance > 0)) return false;
  if (nf.status === 'cleared' && row.balance > 0) return false;
  if (nf.status === 'allocated' && !(row.alloted > 0)) return false;
  if (nf.status === 'unallocated' && row.alloted > 0) return false;

  if (nf.search) {
    var haystack = (row.sector + ' ' + row.priority + ' ' + row.purity).toLowerCase();
    if (haystack.indexOf(nf.search) < 0) return false;
  }
  return true;
}

/** Applies every metal flow filter to one Metal Flow Master row. */
function matchesFlowFilters_(row, nf) {
  if (!inDateWindow_(row.dateKey, nf)) return false;
  if (nf.sectors && nf.sectors.indexOf(row.sectorKey) < 0) return false;
  if (nf.status === 'allocated' && !(row.acquired > 0)) return false;
  if (nf.status === 'unallocated' && row.acquired > 0) return false;
  if (nf.search && row.sector.toLowerCase().indexOf(nf.search) < 0) return false;
  return true;
}

/**
 * Slices a result set into the requested page and describes it.
 * Paging is done on the SERVER so the browser never holds the whole history.
 */
function paginate_(matched, nf) {
  var total = matched.length;
  var pageSize = nf.limit;
  var totalPages = Math.max(1, Math.ceil(total / pageSize));
  var currentPage = Math.min(Math.floor(nf.offset / pageSize) + 1, totalPages);
  var start = (currentPage - 1) * pageSize;
  var rows = matched.slice(start, start + pageSize);

  return {
    rows: rows,
    page: {
      currentPage: currentPage,
      totalPages: totalPages,
      pageSize: pageSize,
      offset: start,
      totalRecords: total,
      firstRecord: total ? start + 1 : 0,
      lastRecord: start + rows.length,
      hasPrevious: currentPage > 1,
      hasNext: currentPage < totalPages
    }
  };
}

/* ------------------------------------------------------------------ */
/* Filter option discovery                                             */
/* ------------------------------------------------------------------ */

/**
 * Everything the history and dashboard filter controls need.
 * Sector lists come from the live Metal Generator definitions, extended with any
 * historical sector still present in the masters but no longer in the Generator.
 */
function getHistoryFilterOptions() {
  try {
    invalidateDataCache_();

    var scope = getUserScope_(getActiveUserEmail_());
    if (!scope.isAdmin && !scope.parties.length) {
      return response_(false, 'NO_PARTY_ASSIGNED',
        'No party is assigned to your account. Contact the administrator.', null);
    }
    var partyMaps = buildSectorPartyMaps_();

    var masterRows = filterRowsByScope_(readMasterRows_(true), scope, partyMaps.allocation);
    var flowRows = filterFlowRowsByScope_(readFlowMasterRows_(true), scope, partyMaps.flow);

    var allocSectors = [];
    var allocSeen = {};
    try {
      readAllocationSectorDefinitions_().forEach(function (d) {
        if (!scopeAllows_(scope, d.partyKey)) return;
        allocSeen[d.sectorKey] = true;
        allocSectors.push({ sector: d.sector, key: d.sectorKey, active: true });
      });
    } catch (e) { /* definitions unreadable: derive from history only */ }

    var flowSectors = [];
    var flowSeen = {};
    try {
      readFlowSectorDefinitions_().forEach(function (d) {
        if (!scopeAllowsFlow_(scope, d.sectorKey, d.partyKey)) return;
        flowSeen[d.sectorKey] = true;
        flowSectors.push({ sector: d.sector, key: d.sectorKey, active: true });
      });
    } catch (e) { /* ignore */ }

    var prioritySeen = {}, priorities = [];
    var puritySeen = {}, purities = [];
    var dateSeen = {}, dateKeys = [];

    masterRows.forEach(function (r) {
      if (!allocSeen[r.sectorKey]) {
        allocSeen[r.sectorKey] = true;
        allocSectors.push({ sector: r.sector, key: r.sectorKey, active: false });
      }
      var pk = normalizeSectorKey_(r.priority);
      if (pk && !prioritySeen[pk]) { prioritySeen[pk] = true; priorities.push({ label: r.priority, key: pk }); }
      var uk = normalizeSectorKey_(r.purity);
      if (uk && !puritySeen[uk]) { puritySeen[uk] = true; purities.push({ label: r.purity, key: uk }); }
      if (!dateSeen[r.dateKey]) { dateSeen[r.dateKey] = true; dateKeys.push(r.dateKey); }
    });

    flowRows.forEach(function (r) {
      if (!flowSeen[r.sectorKey]) {
        flowSeen[r.sectorKey] = true;
        flowSectors.push({ sector: r.sector, key: r.sectorKey, active: false });
      }
      if (!dateSeen[r.dateKey]) { dateSeen[r.dateKey] = true; dateKeys.push(r.dateKey); }
    });

    dateKeys.sort();
    priorities.sort(function (a, b) { return a.key < b.key ? -1 : (a.key > b.key ? 1 : 0); });
    purities.sort(function (a, b) { return a.key < b.key ? -1 : (a.key > b.key ? 1 : 0); });

    var latest = dateKeys.length ? dateKeys[dateKeys.length - 1] : todayKey_();
    var suggestedFrom = shiftDateKey_(latest, -(REPORT_CONFIG.DEFAULT_RANGE_DAYS - 1));
    if (dateKeys.length && suggestedFrom < dateKeys[0]) suggestedFrom = dateKeys[0];

    return response_(true, 'OK', 'Filter options loaded.', {
      allocationSectors: allocSectors,
      flowSectors: flowSectors,
      priorities: priorities,
      purities: purities,
      savedDateCount: dateKeys.length,
      minDate: dateKeys.length ? dateKeys[0] : '',
      maxDate: dateKeys.length ? latest : '',
      suggestedFrom: suggestedFrom,
      suggestedTo: latest,
      allocationRecordCount: masterRows.length,
      flowRecordCount: flowRows.length
    });
  } catch (err) {
    return handleServerError_('getHistoryFilterOptions', err);
  }
}

/* ------------------------------------------------------------------ */
/* Allocation History                                                  */
/* ------------------------------------------------------------------ */

/**
 * Filtered Metal Master history with totals.
 * @param {Object} filters {fromDate,toDate,sectors[],priorities[],purities[],status,search,limit}
 */
function getAllocationHistory(filters) {
  try {
    var nf = normalizeFilters_(filters);
    invalidateDataCache_();

    // Party scope is applied on the SERVER, before any filtering the client asked
    // for, so an operator can never widen it from the browser.
    var scope = getUserScope_(getActiveUserEmail_());
    if (!scope.isAdmin && !scope.parties.length) {
      return response_(false, 'NO_PARTY_ASSIGNED',
        'No party is assigned to your account. Contact the administrator.', null);
    }
    var partyMaps = buildSectorPartyMaps_();

    var rows = filterRowsByScope_(readMasterRows_(true), scope, partyMaps.allocation);
    var orderMap = buildSectorOrderMap_();

    var matched = rows.filter(function (r) { return matchesAllocationFilters_(r, nf); });

    var totals = {
      previousRequirement: 0, todayRequired: 0, alloted: 0, balance: 0
    };
    var dateSeen = {}, sectorSeen = {};
    matched.forEach(function (r) {
      totals.previousRequirement += r.previousRequirement;
      totals.todayRequired += r.todayRequired;
      totals.alloted += r.alloted;
      totals.balance += r.balance;
      dateSeen[r.dateKey] = true;
      sectorSeen[r.sectorKey] = true;
    });
    Object.keys(totals).forEach(function (k) { totals[k] = round3_(totals[k]); });

    matched.sort(function (a, b) {
      if (a.dateKey !== b.dateKey) return a.dateKey < b.dateKey ? 1 : -1;   // newest first
      var oa = orderMap[a.sectorKey], ob = orderMap[b.sectorKey];
      oa = (oa === undefined) ? 999 : oa;
      ob = (ob === undefined) ? 999 : ob;
      if (oa !== ob) return oa - ob;
      return a.sector < b.sector ? -1 : 1;
    });

    var paged = paginate_(matched, nf);
    var page = paged.rows;

    return response_(true, 'OK',
      matched.length + ' allocation records matched.',
      {
        rows: page.map(function (r) {
          return {
            dateKey: r.dateKey,
            dateDisplay: formatDisplayDate_(r.dateKey),
            priority: r.priority,
            sector: r.sector,
            purity: r.purity,
            previousRequirement: r.previousRequirement,
            todayRequired: r.todayRequired,
            alloted: r.alloted,
            balance: r.balance
          };
        }),
        summary: {
          recordCount: matched.length,
          returnedCount: page.length,
          truncated: false,
          dateCount: Object.keys(dateSeen).length,
          sectorCount: Object.keys(sectorSeen).length,
          totals: totals,

          /*
           * Fulfilment rate ties Alloted back to what was actually being
           * asked for. Total demand on a date is the unmet requirement
           * carried forward plus the new indents raised that day:
           *
           *     demand      = previousRequirement + todayRequired
           *     fulfilment  = alloted / demand * 100
           *
           * This is the same relationship the ledger already enforces,
           * since balance = demand - alloted, so the rate is equivalently
           * (1 - balance / demand). A negative previousRequirement means a
           * sector was over-allocated earlier and is carrying credit, so
           * demand can come out at or below zero; the rate is reported as
           * zero in that case rather than as a misleading large number.
           */
          /*
           * Trajectory peak: the highest total closing balance reached on
           * any single date in range, with that date. Computed from the
           * already-matched rows, so no extra spreadsheet read.
           */
          peakBalance: (function () {
            var byDay = {}, best = 0, bestKey = '';
            matched.forEach(function (r) {
              byDay[r.dateKey] = (byDay[r.dateKey] || 0) + r.balance;
            });
            Object.keys(byDay).forEach(function (k) {
              if (!bestKey || byDay[k] > best) { best = byDay[k]; bestKey = k; }
            });
            return { value: round3_(best), dateDisplay: bestKey ? formatDisplayDate_(bestKey) : '' };
          })(),

          totalDemand: round3_(totals.previousRequirement + totals.todayRequired),
          fulfilmentRate: (totals.previousRequirement + totals.todayRequired) > 0
            ? round3_((totals.alloted /
                (totals.previousRequirement + totals.todayRequired)) * 100)
            : 0
        },
        page: paged.page,
        appliedFilters: nf
      });
  } catch (err) {
    return handleServerError_('getAllocationHistory', err);
  }
}

/* ------------------------------------------------------------------ */
/* Metal Flow History                                                  */
/* ------------------------------------------------------------------ */

/** Filtered Metal Flow Master history with totals. */
function getMetalFlowHistory(filters) {
  try {
    var nf = normalizeFilters_(filters);
    invalidateDataCache_();

    var scope = getUserScope_(getActiveUserEmail_());
    if (!scope.isAdmin && !scope.parties.length) {
      return response_(false, 'NO_PARTY_ASSIGNED',
        'No party is assigned to your account. Contact the administrator.', null);
    }
    var partyMaps = buildSectorPartyMaps_();

    var rows = filterFlowRowsByScope_(readFlowMasterRows_(true), scope, partyMaps.flow);
    var orderMap = buildFlowOrderMap_();

    var matched = rows.filter(function (r) { return matchesFlowFilters_(r, nf); });

    var totalAcquired = 0;
    var dateSeen = {}, sectorSeen = {};
    matched.forEach(function (r) {
      totalAcquired += r.acquired;
      dateSeen[r.dateKey] = true;
      sectorSeen[r.sectorKey] = true;
    });
    totalAcquired = round3_(totalAcquired);

    matched.sort(function (a, b) {
      if (a.dateKey !== b.dateKey) return a.dateKey < b.dateKey ? 1 : -1;
      var oa = orderMap[a.sectorKey], ob = orderMap[b.sectorKey];
      oa = (oa === undefined) ? 999 : oa;
      ob = (ob === undefined) ? 999 : ob;
      if (oa !== ob) return oa - ob;
      return a.sector < b.sector ? -1 : 1;
    });

    var paged = paginate_(matched, nf);
    var page = paged.rows;
    var dateCount = Object.keys(dateSeen).length;

    // Charts must reflect every matched record, not just the current page,
    // so the series is built from `matched` before pagination is applied.
    var flowSeries = buildFlowSeries_(matched);

    return response_(true, 'OK',
      matched.length + ' Metal Flow records matched.',
      {
        rows: page.map(function (r) {
          return {
            dateKey: r.dateKey,
            dateDisplay: formatDisplayDate_(r.dateKey),
            sector: r.sector,
            acquired: r.acquired
          };
        }),
        summary: {
          recordCount: matched.length,
          returnedCount: page.length,
          truncated: false,
          dateCount: dateCount,
          sectorCount: Object.keys(sectorSeen).length,
          totalAcquired: totalAcquired,
          averagePerDay: dateCount ? round3_(totalAcquired / dateCount) : 0,

          /*
           * Splits the saved dates in range down the middle and compares the
           * newer half against the older half:
           *
           *     change % = (current - previous) / previous * 100
           *
           * With an odd number of dates the extra date joins the current
           * half, which never inflates the change. Reported as null below
           * four dates, or when the older half acquired nothing, because a
           * change from zero is undefined rather than infinite.
           */
          cycle: (function () {
            var byDay = {}, keys = [];
            matched.forEach(function (r) {
              if (byDay[r.dateKey] === undefined) { byDay[r.dateKey] = 0; keys.push(r.dateKey); }
              byDay[r.dateKey] += r.acquired;
            });
            keys.sort();
            var half = Math.floor(keys.length / 2);
            if (keys.length < 4) return { changePercent: null, dayCount: half };
            var prevSum = 0, currSum = 0;
            keys.forEach(function (k, i) {
              if (i < half) prevSum += byDay[k]; else currSum += byDay[k];
            });
            return {
              previousAcquired: round3_(prevSum),
              currentAcquired: round3_(currSum),
              dayCount: half,
              changePercent: prevSum > 0 ? round3_(((currSum - prevSum) / prevSum) * 100) : null
            };
          })()
        },
        series: flowSeries,
        heatmap: buildFlowHeatmap_(limitFlowToWindow_(matched)),
        page: paged.page,
        appliedFilters: nf
      });
  } catch (err) {
    return handleServerError_('getMetalFlowHistory', err);
  }
}

/* ------------------------------------------------------------------ */
/* Analysis Dashboard                                                  */
/* ------------------------------------------------------------------ */

/**
 * Aggregated operational analytics across both masters.
 * Date and sector filters apply to every series returned.
 */
function getDashboardSummary(filters) {
  try {
    var nf = normalizeFilters_(filters);
    invalidateDataCache_();

    var scope = getUserScope_(getActiveUserEmail_());
    if (!scope.isAdmin && !scope.parties.length) {
      return response_(false, 'NO_PARTY_ASSIGNED',
        'No party is assigned to your account. Contact the administrator.', null);
    }
    var partyMaps = buildSectorPartyMaps_();

    var masterRows = filterRowsByScope_(readMasterRows_(true), scope, partyMaps.allocation);
    var flowRows = filterFlowRowsByScope_(readFlowMasterRows_(true), scope, partyMaps.flow);

    var alloc = masterRows.filter(function (r) {
      if (!inDateWindow_(r.dateKey, nf)) return false;
      if (nf.sectors && nf.sectors.indexOf(r.sectorKey) < 0) return false;
      if (nf.priorities && nf.priorities.indexOf(normalizeSectorKey_(r.priority)) < 0) return false;
      return true;
    });

    // Metal Flow has its own sector list, so allocation-sector filters must not
    // silently blank the acquired series. Sector filtering applies to flow only
    // when the selected key actually exists in the flow master.
    var flowKeysPresent = {};
    flowRows.forEach(function (r) { flowKeysPresent[r.sectorKey] = true; });
    var flowFilterActive = !!(nf.sectors && nf.sectors.some(function (k) { return flowKeysPresent[k]; }));

    var flow = flowRows.filter(function (r) {
      if (!inDateWindow_(r.dateKey, nf)) return false;
      if (flowFilterActive && nf.sectors.indexOf(r.sectorKey) < 0) return false;
      return true;
    });

    /* --- Series 1 & 2: by date --- */
    var byDateMap = {};
    function dateBucket(key) {
      if (!byDateMap[key]) {
        byDateMap[key] = {
          dateKey: key, dateDisplay: formatDisplayDate_(key),
          previousRequirement: 0, required: 0, alloted: 0, balance: 0, acquired: 0
        };
      }
      return byDateMap[key];
    }
    alloc.forEach(function (r) {
      var b = dateBucket(r.dateKey);
      b.previousRequirement += r.previousRequirement;
      b.required += r.todayRequired;
      b.alloted += r.alloted;
      b.balance += r.balance;
    });
    flow.forEach(function (r) { dateBucket(r.dateKey).acquired += r.acquired; });

    var byDate = Object.keys(byDateMap).sort().map(function (k) {
      var b = byDateMap[k];
      b.previousRequirement = round3_(b.previousRequirement);
      b.required = round3_(b.required);
      b.alloted = round3_(b.alloted);
      b.balance = round3_(b.balance);
      b.acquired = round3_(b.acquired);
      b.unallocated = round3_(Math.max(0, b.acquired - b.alloted));
      b.utilisation = b.acquired > 0 ? round3_((b.alloted / b.acquired) * 100) : 0;
      return b;
    });
    if (byDate.length > REPORT_CONFIG.MAX_TREND_POINTS) {
      byDate = byDate.slice(byDate.length - REPORT_CONFIG.MAX_TREND_POINTS);
    }

    /* --- Series 3: by sector --- */
    var bySectorMap = {};
    alloc.forEach(function (r) {
      if (!bySectorMap[r.sectorKey]) {
        bySectorMap[r.sectorKey] = {
          sector: r.sector, priority: r.priority,
          required: 0, alloted: 0, balance: 0, latestBalance: 0, latestDate: ''
        };
      }
      var b = bySectorMap[r.sectorKey];
      b.required += r.todayRequired;
      b.alloted += r.alloted;
      b.balance += r.balance;
      if (!b.latestDate || r.dateKey > b.latestDate) {
        b.latestDate = r.dateKey;
        b.latestBalance = r.balance;
        b.priority = r.priority;
      }
    });
    var bySector = Object.keys(bySectorMap).map(function (k) {
      var b = bySectorMap[k];
      b.required = round3_(b.required);
      b.alloted = round3_(b.alloted);
      b.balance = round3_(b.balance);
      b.latestBalance = round3_(b.latestBalance);
      b.latestDateDisplay = b.latestDate ? formatDisplayDate_(b.latestDate) : '';
      return b;
    }).sort(function (a, b) { return b.required - a.required; });

    /* --- Series 4: by priority --- */
    var byPriorityMap = {};
    var grandAlloted = 0;
    alloc.forEach(function (r) {
      var label = r.priority || 'Unspecified';
      if (!byPriorityMap[label]) byPriorityMap[label] = { priority: label, alloted: 0, required: 0, balance: 0 };
      byPriorityMap[label].alloted += r.alloted;
      byPriorityMap[label].required += r.todayRequired;
      byPriorityMap[label].balance += r.balance;
      grandAlloted += r.alloted;
    });
    grandAlloted = round3_(grandAlloted);
    var byPriority = Object.keys(byPriorityMap).sort().map(function (k) {
      var b = byPriorityMap[k];
      b.alloted = round3_(b.alloted);
      b.required = round3_(b.required);
      b.balance = round3_(b.balance);
      b.share = grandAlloted > 0 ? round3_((b.alloted / grandAlloted) * 100) : 0;
      return b;
    });

    /* --- Series 5: top pending balance (latest saved date per sector) --- */
    var topPending = Object.keys(bySectorMap).map(function (k) {
      return {
        sector: bySectorMap[k].sector,
        priority: bySectorMap[k].priority,
        pending: round3_(bySectorMap[k].latestBalance),
        asOf: bySectorMap[k].latestDate ? formatDisplayDate_(bySectorMap[k].latestDate) : ''
      };
    }).filter(function (r) { return r.pending > 0; })
      .sort(function (a, b) { return b.pending - a.pending; })
      .slice(0, REPORT_CONFIG.TOP_SECTOR_LIMIT);

    /* --- Headline KPIs --- */
    var totalAcquired = 0, totalAlloted = 0, totalRequired = 0;
    byDate.forEach(function (b) {
      totalAcquired += b.acquired;
      totalAlloted += b.alloted;
      totalRequired += b.required;
    });
    var latest = byDate.length ? byDate[byDate.length - 1] : null;
    var totalPendingNow = 0;
    topPending.forEach(function (r) { totalPendingNow += r.pending; });

    var kpis = {
      dayCount: byDate.length,
      totalAcquired: round3_(totalAcquired),
      totalAlloted: round3_(totalAlloted),
      totalRequired: round3_(totalRequired),
      unallocated: round3_(Math.max(0, totalAcquired - totalAlloted)),
      utilisation: totalAcquired > 0 ? round3_((totalAlloted / totalAcquired) * 100) : 0,
      averageDailyAcquired: byDate.length ? round3_(totalAcquired / byDate.length) : 0,
      latestDate: latest ? latest.dateKey : '',
      latestDateDisplay: latest ? latest.dateDisplay : '',
      latestClosingBalance: latest ? latest.balance : 0,
      pendingSectorCount: topPending.length,
      totalPendingLatest: round3_(totalPendingNow)
    };

    /*
     * "Versus previous cycle" compares the newer half of the saved dates in
     * range against the older half, so the figure always reflects the range
     * the user has actually selected and needs no second query. With an odd
     * number of dates the extra date goes to the current half, which is the
     * conservative direction: it never inflates the change.
     *
     *     change % = (current - previous) / previous * 100
     *
     * Reported as null when there are fewer than four dates or when the
     * previous half acquired nothing, because a percentage change from zero
     * is undefined rather than infinite.
     */
    kpis.fulfilmentRate = totalRequired > 0
      ? round3_((totalAlloted / totalRequired) * 100) : 0;

    var half = Math.floor(byDate.length / 2);
    kpis.previousCycleAcquired = 0;
    kpis.currentCycleAcquired = 0;
    kpis.acquiredChangePercent = null;
    kpis.cycleDayCount = half;
    if (byDate.length >= 4) {
      var prevSum = 0, currSum = 0;
      byDate.forEach(function (d, i) {
        if (i < half) prevSum += d.acquired; else currSum += d.acquired;
      });
      kpis.previousCycleAcquired = round3_(prevSum);
      kpis.currentCycleAcquired = round3_(currSum);
      if (prevSum > 0) kpis.acquiredChangePercent = round3_(((currSum - prevSum) / prevSum) * 100);
    }

    /* Highest closing balance reached anywhere in the range. */
    var peak = { balance: 0, dateKey: '', dateDisplay: '' };
    byDate.forEach(function (d) {
      if (!peak.dateKey || d.balance > peak.balance) {
        peak = { balance: d.balance, dateKey: d.dateKey, dateDisplay: d.dateDisplay };
      }
    });
    kpis.peakClosingBalance = round3_(peak.balance);
    kpis.peakClosingDate = peak.dateDisplay;

    return response_(true, 'OK',
      byDate.length ? ('Analysis prepared for ' + byDate.length + ' saved date(s).')
                    : 'No saved records matched the selected filters.',
      {
        kpis: kpis,
        heatmap: buildFlowHeatmap_(flow),
        byDate: byDate,
        bySector: bySector,
        byPriority: byPriority,
        topPending: topPending,
        appliedFilters: nf
      });
  } catch (err) {
    return handleServerError_('getDashboardSummary', err);
  }
}


/** Build marker. Used by checkInstalledFiles() to detect a stale paste. */
function buildTag_ReportService_() { return '5C'; }


/**
 * Pivots matched Metal Flow rows into a date-by-sector matrix for charting.
 *
 * Records are matched on their normalised date key and sector name, never on
 * a row position, so an inserted column or a re-sorted master cannot shift a
 * value onto the wrong sector. Sectors are ordered by total acquired weight
 * descending, which lets the client hand the same colour to the same sector
 * in both the trend chart and the share chart.
 *
 * @param {Array<Object>} rows Matched flow rows, each {dateKey, sector, acquired}.
 * @return {Object} {dates, displays, sectors:[{sector, values, total, percent}], grandTotal}
 */
function buildFlowSeries_(rows) {
  var dateKeys = [], dateSeen = {};
  var sectorTotal = {}, cell = {};
  var grandTotal = 0;

  rows.forEach(function (r) {
    if (!dateSeen[r.dateKey]) { dateSeen[r.dateKey] = true; dateKeys.push(r.dateKey); }
    var key = r.dateKey + '\u0000' + r.sector;
    cell[key] = (cell[key] || 0) + r.acquired;
    sectorTotal[r.sector] = (sectorTotal[r.sector] || 0) + r.acquired;
    grandTotal += r.acquired;
  });

  dateKeys.sort();                       // yyyy-MM-dd keys sort chronologically
  grandTotal = round3_(grandTotal);

  // A sector that acquired nothing across the whole range would draw a flat
  // line along zero and crowd the legend, so it is left out of the charts.
  var names = Object.keys(sectorTotal).filter(function (n) {
    return round3_(sectorTotal[n]) > 0;
  });
  names.sort(function (a, b) {
    if (sectorTotal[b] !== sectorTotal[a]) return sectorTotal[b] - sectorTotal[a];
    return a < b ? -1 : 1;
  });

  var sectors = names.map(function (name) {
    var total = round3_(sectorTotal[name]);
    return {
      sector: name,
      total: total,
      percent: grandTotal > 0 ? round3_((total / grandTotal) * 100) : 0,
      values: dateKeys.map(function (dk) {
        return round3_(cell[dk + '\u0000' + name] || 0);
      })
    };
  });

  return {
    dates: dateKeys,
    displays: dateKeys.map(function (dk) { return formatDisplayDate_(dk); }),
    sectors: sectors,
    grandTotal: grandTotal
  };
}


/**
 * Builds the Date x Party matrix behind the "Daily Acquired Metal by Party"
 * heatmap on the Analysis Dashboard.
 *
 * The caller passes rows that have already been read from Metal Flow Master in
 * one bulk operation, scoped to the user and filtered by the dashboard date
 * range, so nothing here touches the spreadsheet again. Metal Flow Master is
 * only read, never written, and no reporting copy of it is stored anywhere.
 *
 * Cells are keyed on the normalised date key and the normalised sector key, so
 * duplicate Date + Sector rows are summed rather than overwriting each other,
 * and a re-sorted or re-columned master cannot shift a value onto the wrong
 * party. Row positions are never used.
 *
 * Rules applied:
 *   - only dates that actually carry Metal Flow records become columns
 *   - a party with no row on a date that other parties have is shown as 0.000
 *   - a genuine saved 0 is also shown as 0.000, indistinguishable by design
 *   - a party whose total across the whole range is 0 is excluded entirely
 *
 * @param {Array<Object>} flowRows Filtered flow rows {dateKey, sector, sectorKey, acquired}.
 * @return {Object} heatmap payload consumed by renderFlowHeatmap() in Reports.html
 */
function buildFlowHeatmap_(flowRows) {
  var dateSeen = {}, dateKeys = [];
  var sectorName = {}, sectorTotal = {};
  var cellMap = {};
  var recordCount = 0;
  var totalAcquired = 0;

  flowRows.forEach(function (r) {
    var dk = r.dateKey;
    var sk = r.sectorKey;
    if (!dk || !sk) return;

    if (!dateSeen[dk]) { dateSeen[dk] = true; dateKeys.push(dk); }
    if (sectorName[sk] === undefined) { sectorName[sk] = r.sector; sectorTotal[sk] = 0; }

    var key = dk + '\u0000' + sk;
    cellMap[key] = (cellMap[key] || 0) + r.acquired;   // duplicates are summed
    sectorTotal[sk] += r.acquired;
    totalAcquired += r.acquired;
    recordCount++;
  });

  dateKeys.sort();                       // yyyy-MM-dd keys sort chronologically
  var truncated = false;
  if (dateKeys.length > REPORT_CONFIG.MAX_HEATMAP_DATES) {
    dateKeys = dateKeys.slice(dateKeys.length - REPORT_CONFIG.MAX_HEATMAP_DATES);
    truncated = true;
  }
  var keptDates = {};
  dateKeys.forEach(function (dk) { keptDates[dk] = true; });

  // Parties that acquired nothing across the range are dropped, so the grid
  // does not carry rows of solid zeroes.
  var sectorKeys = Object.keys(sectorName).filter(function (sk) {
    return round3_(sectorTotal[sk]) > 0;
  });
  sectorKeys.sort(function (a, b) {
    if (sectorTotal[b] !== sectorTotal[a]) return sectorTotal[b] - sectorTotal[a];
    return sectorName[a] < sectorName[b] ? -1 : 1;
  });

  var dates = dateKeys.map(function (dk) {
    return {
      dateKey: dk,
      dateLabel: shortDateLabel_(dk),
      fullDateLabel: formatDisplayDate_(dk)
    };
  });

  var cells = [];
  var maximumAcquired = 0;
  var peak = { acquired: 0, sector: '', dateLabel: '', fullDateLabel: '' };
  var dayTotal = {};

  dates.forEach(function (d) {
    sectorKeys.forEach(function (sk) {
      var v = round3_(cellMap[d.dateKey + '\u0000' + sk] || 0);
      cells.push({
        dateKey: d.dateKey,
        dateLabel: d.dateLabel,
        fullDateLabel: d.fullDateLabel,
        sector: sectorName[sk],
        acquired: v
      });
      dayTotal[d.dateKey] = round3_((dayTotal[d.dateKey] || 0) + v);
      if (v > maximumAcquired) {
        maximumAcquired = v;
        peak = {
          acquired: v, sector: sectorName[sk],
          dateLabel: d.dateLabel, fullDateLabel: d.fullDateLabel
        };
      }
    });
  });

  var busiestDay = { dateKey: '', fullDateLabel: '', acquired: 0 };
  dates.forEach(function (d) {
    var t = dayTotal[d.dateKey] || 0;
    if (t > busiestDay.acquired) {
      busiestDay = { dateKey: d.dateKey, fullDateLabel: d.fullDateLabel, acquired: t };
    }
  });

  var mostActive = { sector: '', total: 0, percent: 0 };
  totalAcquired = round3_(totalAcquired);
  if (sectorKeys.length) {
    var top = sectorKeys[0];
    mostActive = {
      sector: sectorName[top],
      total: round3_(sectorTotal[top]),
      percent: totalAcquired > 0 ? round3_((sectorTotal[top] / totalAcquired) * 100) : 0
    };
  }

  return {
    ok: true,
    dates: dates,
    sectors: sectorKeys.map(function (sk) { return sectorName[sk]; }),
    cells: cells,
    maximumAcquired: maximumAcquired,
    recordCount: recordCount,
    totalAcquired: totalAcquired,
    dateCount: dates.length,
    partyCount: sectorKeys.length,
    peak: peak,
    busiestDay: busiestDay,
    mostActive: mostActive,
    truncated: truncated,
    windowDays: HEATMAP_WINDOW_DAYS,
    truncationNote: truncated
      ? ('Showing the most recent ' + REPORT_CONFIG.MAX_HEATMAP_DATES +
         ' dates. Narrow the range to see earlier dates.')
      : ''
  };
}


/** Compact column label for the heatmap, e.g. '01 Sep'. */
function shortDateLabel_(key) {
  if (!isValidDateKey_(key)) return String(key || '');
  return Utilities.formatDate(dateKeyToStorageDate_(key), getAppTimeZone_(), 'dd MMM');
}


/**
 * Trims flow rows to the heatmap's fixed 30 day window.
 *
 * The grid is only legible for about a month of columns, so however wide a
 * date range the user applies, the heatmap shows the newest date in that
 * range and the 29 days before it. Everything else on the page - the KPI
 * cards, the share chart, the record counts - still covers the full range;
 * only this one chart is windowed.
 *
 * The cut-off is calendar based rather than a count of saved dates, so a
 * month with gaps still spans the same month on screen.
 *
 * @param {Array<Object>} rows Matched flow rows carrying a dateKey.
 * @return {Array<Object>} Rows falling inside the window.
 */
function limitFlowToWindow_(rows) {
  if (!rows.length) return rows;

  var newest = '';
  rows.forEach(function (r) {
    if (r.dateKey && (!newest || r.dateKey > newest)) newest = r.dateKey;
  });
  if (!newest) return rows;

  var cutoff = shiftDateKey_(newest, -(HEATMAP_WINDOW_DAYS - 1));
  return rows.filter(function (r) { return r.dateKey >= cutoff; });
}
