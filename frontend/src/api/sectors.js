/**
 * api/sectors.js — reference data the caller is allowed to see.
 *
 * The response is already scope-filtered by the server, so dropdowns built from
 * it can never offer a sector the user may not see (rule 8 / the page spec's
 * "Sector dropdown values are scope-filtered too").
 */

export async function getSectors() {
  const response = await fetch('/sectors');
  if (!response.ok) throw new Error(`Could not load sectors (${response.status})`);
  return response.json();
}
