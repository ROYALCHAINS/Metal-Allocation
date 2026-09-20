/**
 * views/analysis.js — the Analysis Dashboard.
 *
 * Built to PROMPT_analysis_dashboard.md. The only page that joins BOTH
 * ledgers: Metal Master (demand) and Metal Flow Master (supply), from one
 * endpoint. Read-only — it never writes.
 *
 * Charts are the hand-written SVG engine in components/charts.js. CLAUDE.md
 * section 7: legacy's chart engine and its stylesheet are a matched pair, and
 * substituting a charting library would change the appearance.
 *
 * TWO RATIOS THAT LOOK ALIKE AND ARE NOT:
 *   utilisation = alloted / acquired   — how much of supply was consumed
 *   fulfilment  = alloted / required   — how much of demand was met
 * Different denominators, different questions. Note also that Allocation
 * History's fulfilment rate divides by (previous_requirement + today_required)
 * instead. Both are deliberate; each matches its own screenshot.
 *
 * CLOSING BALANCE TREND SUBTITLE. Legacy labels this chart "cumulative
 * physical vault stock position" while plotting summed outstanding balance —
 * neither cumulative nor vault stock. CLAUDE.md records it as a known
 * inconsistency where "the label is wrong, not the data", so the data is
 * plotted unchanged and the subtitle says what it actually is.
 */

import { getDashboard } from '../api/reports.js';
import { getSectors } from '../api/sectors.js';
import { escapeHtml } from '../components/appHeader.js';
import { groupedBarChart, kgToGrams, lineChart, sectorBarChart } from '../components/charts.js';
import { bindFilterBar, renderFilterBar } from '../components/filterBar.js';
import { fmt3, formatGrams } from '../lib/format.js';

const TOP_SECTOR_LIMIT = 10;

const shortDate = (iso) => (iso ? iso.slice(5) : '—');

export function renderAnalysisView(container) {
  container.innerHTML = `
    ${renderFilterBar({ prefix: 'db' })}
    <div class="summary-strip" id="dbKpis"></div>

    <div class="chart-grid">
      <div class="chart-card chart-card--full">
        <div class="chart-card__head">
          <h3 class="chart-card__title">Acquired vs Alloted by Date</h3>
          <span class="chip" id="dbChart1Chip">&mdash;</span>
        </div>
        <p class="chart-card__subtitle">
          Comparative inflow versus fulfilment volume over the selected horizon.
        </p>
        <div class="chart-card__body" id="dbChartAcquiredAlloted"></div>
      </div>

      <div class="chart-card chart-card--full">
        <div class="chart-card__head">
          <h3 class="chart-card__title">Closing Balance Trend</h3>
          <span class="chip chip--amber" id="dbChart2Chip">&mdash;</span>
        </div>
        <p class="chart-card__subtitle">
          Total outstanding balance carried at the close of each saved date &mdash; demand
          not yet met, not vault stock.
        </p>
        <div class="chart-card__body" id="dbChartBalance"></div>
      </div>

      <div class="chart-card chart-card--full hidden" id="dbFlowTrendCard">
        <div class="chart-card__head">
          <h3 class="chart-card__title">Your Metal Flow Trend</h3>
          <span class="chip" id="dbFlowTrendChip">&mdash;</span>
        </div>
        <p class="chart-card__subtitle">
          Metal acquired for your party across the selected horizon.
        </p>
        <div class="chart-card__body" id="dbChartFlowTrend"></div>
      </div>

      <div class="chart-card">
        <div class="chart-card__head">
          <h3 class="chart-card__title">Requirement vs Balance by Sector</h3>
          <span class="chip" id="dbChart4Chip">&mdash;</span>
        </div>
        <p class="chart-card__subtitle">
          Comparative outstanding balance against demand volume.
        </p>
        <div class="chart-card__body" id="dbChartSector"></div>
      </div>

      <div class="chart-card">
        <div class="chart-card__head">
          <h3 class="chart-card__title">Top Sectors by Pending Balance</h3>
          <span class="chip">Latest saved date per sector</span>
        </div>
        <p class="chart-card__subtitle">
          Live operational ledger ranking, based on the recorded pending requirement.
        </p>
        <div class="chart-card__body">
          <table class="history-table" id="dbPendingTable">
            <thead>
              <tr>
                <th class="col-rank">#</th>
                <th class="col-sector-name">Sector</th>
                <th class="num col-pending">Pending Balance</th>
                <th class="col-asof">As Of</th>
              </tr>
            </thead>
            <tbody id="dbPendingBody"></tbody>
          </table>
          <div class="empty-state hidden" id="dbPendingEmpty">
            <div class="empty-state__title">No pending balance</div>
            <div class="empty-state__text">
              Every sector is fully cleared for the selected range.
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="dash-footer">
      <div class="dash-footer__status">
        <span class="dash-footer__dot" aria-hidden="true"></span>
        <span class="dash-footer__label">Analytics synchronised</span>
        <span class="dash-footer__sep" aria-hidden="true">|</span>
        <span class="dash-footer__meta" id="dbFootSectors">0 sectors active</span>
        <span class="dash-footer__sep" aria-hidden="true">|</span>
        <span class="dash-footer__meta" id="dbFootSynced">Last synced &mdash;</span>
      </div>
      <div class="dash-footer__actions">
        <span class="dash-footer__badge-label">Total acquired</span>
        <span class="dash-footer__badge" id="dbFootAcquired">0.000 kg</span>
      </div>
    </div>
  `;

  const $ = (id) => container.querySelector(`#${id}`);
  const bar = bindFilterBar(container, 'db', () => load());

  /** One KPI card. `dot`/`badge` are the accents from the screenshot. */
  function kpi({ label, value, unit = '', sub, modifier, dot = null, badge = null }) {
    const head = dot
      ? `<div class="stat-head"><span class="summary-stat__label">${label}</span>
           <span class="stat-dot stat-dot--${dot}" aria-hidden="true"></span></div>`
      : badge
        ? `<div class="stat-head"><span class="summary-stat__label">${label}</span>
             <span class="stat-badge">${badge}</span></div>`
        : `<span class="summary-stat__label">${label}</span>`;

    return `
      <div class="summary-stat summary-stat--${modifier}">
        ${head}
        <span class="summary-stat__value">${escapeHtml(value)}</span>${
          unit ? `<span class="stat-unit"> ${unit}</span>` : ''
        }
        <span class="summary-stat__sub">${sub}</span>
      </div>`;
  }

  /** "↗ +N.N% vs prev N day(s)", or the plain caption when undefined. */
  function cycleSub(cycle) {
    if (cycle.change_percent === null) return 'kg acquired in range';
    const up = cycle.change_percent >= 0;
    return `<span class="summary-stat__sub--${up ? 'up' : 'down'}">${up ? '↗' : '↘'} ${
      up ? '+' : ''
    }${cycle.change_percent}%</span> vs prev ${cycle.day_count} day(s)`;
  }

  function renderKpis(d) {
    $('dbKpis').innerHTML = [
      kpi({
        label: 'Saved Days',
        value: String(d.saved_days),
        sub: escapeHtml(d.latest_saved_date_display || 'no data'),
        modifier: 'indigo',
      }),
      kpi({
        label: 'Total Acquired',
        value: fmt3(d.total_acquired_kg),
        unit: 'kg',
        sub: cycleSub(d.cycle),
        modifier: 'green',
        dot: 'emerald',
      }),
      kpi({
        label: 'Total Alloted',
        value: fmt3(d.total_alloted_kg),
        unit: 'kg',
        // Demand met. NOT the same ratio as Utilisation below.
        sub:
          d.fulfilment_rate === null
            ? 'no requirement raised'
            : `${d.fulfilment_rate}% fulfilment rate`,
        modifier: 'navy',
        dot: 'navy',
      }),
      kpi({
        label: 'Utilisation',
        value: d.utilisation_rate === null ? '—' : `${d.utilisation_rate}%`,
        // Supply consumed. Can exceed 100% — over-allocation is permitted.
        sub: 'alloted vs acquired',
        modifier: 'emerald',
      }),
      kpi({
        label: 'Avg Daily Acquired',
        value: fmt3(d.average_daily_acquired_kg),
        sub: 'kg per saved day',
        modifier: 'rose',
      }),
      kpi({
        label: 'Closing Balance',
        value: fmt3(d.closing_balance_kg),
        unit: 'kg',
        // The latest date's balance, not a sum: balances carry forward.
        sub: d.peak_closing_date
          ? `Trajectory peak: ${fmt3(d.peak_closing_balance_kg)} kg on ${escapeHtml(
              d.peak_closing_date_display
            )}`
          : 'Trajectory peak: —',
        modifier: 'closing',
        badge: 'Latest',
      }),
    ].join('');
  }

  function renderPending(rows) {
    const hasRows = rows.length > 0;
    $('dbPendingTable').classList.toggle('hidden', !hasRows);
    $('dbPendingEmpty').classList.toggle('hidden', hasRows);
    $('dbPendingBody').innerHTML = rows
      .map(
        (r, i) => `
          <tr>
            <td class="col-rank">${i + 1}</td>
            <td class="col-sector-name date-cell">${escapeHtml(r.sector_name)}</td>
            <td class="num col-pending">${fmt3(r.pending_kg)}</td>
            <td class="col-asof">${escapeHtml(r.as_of_display)}</td>
          </tr>`
      )
      .join('');
  }

  function renderFooter(d) {
    $('dbFootSectors').textContent = `${d.by_sector.length} sector${
      d.by_sector.length === 1 ? '' : 's'
    } active`;
    // The client clock at render time, as in legacy — a freshness cue, not a
    // data timestamp.
    $('dbFootSynced').textContent = `Last synced ${new Date().toTimeString().slice(0, 5)}`;
    $('dbFootAcquired').textContent = `${fmt3(d.total_acquired_kg)} kg`;
  }

  function showEmpty() {
    ['dbChartAcquiredAlloted', 'dbChartBalance', 'dbChartSector'].forEach((id) => {
      $(id).innerHTML =
        '<div class="empty-state"><div class="empty-state__title">No saved data in this range</div>' +
        '<div class="empty-state__text">Widen the date range, or save a date on the ' +
        'Daily Allocation screen.</div></div>';
    });
    $('dbFlowTrendCard').classList.add('hidden');
    renderPending([]);
  }

  async function load() {
    $('dbChart1Chip').textContent = 'Loading…';
    try {
      const data = await getDashboard({
        date_from: bar.$('From').value,
        date_to: bar.$('To').value,
        sector_id: bar.$('Sector').value,
      });

      renderKpis(data);
      renderPending(data.top_pending);
      renderFooter(data);

      if (!data.by_date.length) {
        $('dbChart1Chip').textContent = '0 days';
        $('dbChart2Chip').textContent = '—';
        $('dbChart4Chip').textContent = '—';
        showEmpty();
        return;
      }

      const dates = data.by_date.map((p) => ({
        label: p.allocation_date,
        short: shortDate(p.allocation_date),
      }));

      $('dbChart1Chip').textContent = `${data.by_date.length} day${
        data.by_date.length === 1 ? '' : 's'
      }`;
      $('dbChartAcquiredAlloted').innerHTML = groupedBarChart(
        data.by_date.map((p, i) => ({
          ...dates[i],
          a: kgToGrams(p.acquired_kg),
          b: kgToGrams(p.alloted_kg),
        })),
        ['Acquired', 'Alloted']
      );

      $('dbChart2Chip').textContent = `Latest ${fmt3(data.closing_balance_kg)} kg`;
      // NOT a sum. A closing balance carries forward, so adding the daily
      // figures counts the same outstanding metal once per day it stayed
      // outstanding — a number that never existed. The meaningful headline
      // figures are the latest balance and the highest it reached, which is
      // what the KPI card reports too.
      $('dbChartBalance').innerHTML = lineChart(
        data.by_date.map((p, i) => ({ ...dates[i], value: kgToGrams(p.balance_kg) })),
        {
          totals: [
            { label: 'Latest closing', value: kgToGrams(data.closing_balance_kg) },
            {
              label: 'Peak closing',
              value: kgToGrams(data.peak_closing_balance_kg),
              text: data.peak_closing_date
                ? `${Math.round(kgToGrams(data.peak_closing_balance_kg) / 1000).toLocaleString(
                    'en-US'
                  )} kg on ${data.peak_closing_date_display}`
                : undefined,
            },
          ],
        }
      );

      // Operators have no Metal Flow History tab, so their flow trend lives
      // here instead. Strict === false: an undefined flag must leave it hidden,
      // and the flag is resolved server-side, never sent by the browser.
      const showFlowTrend = data.is_admin === false;
      $('dbFlowTrendCard').classList.toggle('hidden', !showFlowTrend);
      if (showFlowTrend) {
        const points = data.by_date.map((p, i) => ({
          ...dates[i],
          value: kgToGrams(p.acquired_kg),
        }));
        // Summed in grams, formatted once — never by adding kilogram floats.
        const totalG = points.reduce((sum, p) => sum + p.value, 0);
        $('dbFlowTrendChip').textContent = `${formatGrams(totalG)} kg over ${points.length} day${
          points.length === 1 ? '' : 's'
        }`;
        // Acquired IS a flow, so unlike the balance above it sums meaningfully.
        $('dbChartFlowTrend').innerHTML = lineChart(points, {
          colour: '#10b981',
          totals: [{ label: 'Total acquired', value: totalG }],
        });
      }

      // by_sector arrives sorted by required descending; the chart takes the top.
      const topSectors = data.by_sector.slice(0, TOP_SECTOR_LIMIT);
      $('dbChart4Chip').textContent = `Top ${topSectors.length} by demand`;
      $('dbChartSector').innerHTML = sectorBarChart(
        topSectors.map((s) => ({
          label: s.sector_name,
          required: kgToGrams(s.today_required_kg),
          balance: kgToGrams(s.balance_kg),
        }))
      );
    } catch (err) {
      $('dbChart1Chip').textContent = 'Error';
      $('dbChartAcquiredAlloted').innerHTML =
        `<div class="banner banner--error"><span>${escapeHtml(err.message)}</span></div>`;
    }
  }

  /** The Sector select is scope-filtered by the server. */
  getSectors()
    .then((data) => {
      const select = bar.$('Sector');
      data.allocation_sectors.forEach((s) => {
        const option = document.createElement('option');
        option.value = s.sector_id;
        option.textContent = s.sector_name;
        select.appendChild(option);
      });
    })
    .catch(() => {
      /* "All sectors" still works without the list. */
    });

  load();
}
