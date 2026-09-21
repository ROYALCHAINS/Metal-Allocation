/**
 * lib/format.js — the ONE place weights get formatted or parsed.
 *
 * CLAUDE.md section 3: "All money/weight formatting goes through one helper in
 * src/lib/. Do not scatter toFixed() calls through views."
 *
 * The API sends kilograms as exact decimal STRINGS (e.g. "12.345"), because the
 * server holds integer grams and will not emit a float.
 *
 * Integer grams are the primitive here too, mirroring the server's
 * services/weight_service.py: 3 decimals of a kilogram is exactly 1 gram, so
 * arithmetic on grams is exact. Summing kilograms with JS numbers would
 * reintroduce exactly the float drift the scheme exists to avoid.
 */

/** Integer grams -> a 3-decimal kilogram string. The primitive formatter. */
export function formatGrams(grams) {
  const rounded = Math.round(grams);
  const sign = rounded < 0 ? '-' : '';
  const abs = Math.abs(rounded);
  return `${sign}${Math.floor(abs / 1000)}.${String(abs % 1000).padStart(3, '0')}`;
}

/**
 * Parse a kilogram value (string or number) into integer grams.
 * Returns null when the input is not a valid number, so callers can show an
 * inline error rather than silently treating it as zero.
 */
export function toGrams(value) {
  if (value === null || value === undefined || value === '') return 0;

  const text = String(value).replace(/,/g, '').trim();
  if (text === '') return 0;
  if (!/^-?\d*\.?\d*$/.test(text) || text === '-' || text === '.') return null;

  const negative = text.startsWith('-');
  const [whole = '0', fraction = ''] = text.replace('-', '').split('.');
  const millis = (fraction + '000').slice(0, 3); // pad/truncate to exactly 3 dp
  const grams = (Number(whole) || 0) * 1000 + (Number(millis) || 0);
  return negative ? -grams : grams;
}

/** Format a kilogram value that came from the API. Always 3 decimals. */
export function fmt3(kgValue) {
  const grams = toGrams(kgValue);
  return formatGrams(grams === null ? 0 : grams);
}

/** Drop trailing zeros from a fixed-decimal string. Ports legacy's fmtTrim().
 *
 * The '.' guard is legacy's and is load-bearing: without it a whole number
 * such as "100" would be trimmed to "1".
 */
function trimZeros(text) {
  if (!text.includes('.')) return text;
  return text.replace(/0+$/, '').replace(/\.$/, '');
}

/**
 * A short kilogram label for printing ON a chart, from integer grams.
 *
 * Ports legacy's fmt0() (Reports.html), including its reasoning: precision
 * follows the magnitude of the figure so a genuinely small series stays
 * readable. A party whose allocations clear almost fully each day carries a
 * closing balance of a few hundred grams, and rounding those to whole
 * kilograms collapses every such point to "0" — which makes the trend
 * impossible to read on the plot. Large figures still print as whole
 * kilograms to keep the label short.
 *
 * Exact three-decimal values remain in every tooltip, so this is presentation
 * only and never affects the plotted geometry.
 *
 * Legacy's round3() and its sub-half-gram "-0" guard are NOT ported: the input
 * here is already an integer number of grams, so there is nothing to round
 * away and "-0" is unreachable.
 */
export function formatPlotKg(grams) {
  const value = Math.round(Number(grams) || 0);
  if (value === 0) return '0';

  const magnitude = Math.abs(value);
  if (magnitude >= 10000) return String(Math.round(value / 1000));
  if (magnitude >= 1000) return trimZeros((value / 1000).toFixed(1));
  // Below 1 kg, the same three decimals the database stores, so the label can
  // never disagree with the tooltip beside it.
  return trimZeros(formatGrams(value));
}

/** The balance-value CSS modifier legacy uses for the closing balance cell. */
export function balanceClass(grams) {
  if (grams === 0) return 'balance-value balance-value--zero';
  if (grams < 0) return 'balance-value balance-value--negative';
  return 'balance-value balance-value--positive';
}
