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

/** The balance-value CSS modifier legacy uses for the closing balance cell. */
export function balanceClass(grams) {
  if (grams === 0) return 'balance-value balance-value--zero';
  if (grams < 0) return 'balance-value balance-value--negative';
  return 'balance-value balance-value--positive';
}
