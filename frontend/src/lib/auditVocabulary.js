/**
 * lib/auditVocabulary.js — how stored audit actions are worded on screen.
 *
 * THE STORED VALUE NEVER CHANGES. `REVISE` stays `REVISE` in the database:
 * renaming it would break the Action Type filter, the Revisions KPI, the
 * schema's CHECK constraint, and every entry already recorded. Only the label
 * differs, and only here.
 *
 * It lives in lib/ rather than in the audit view because three separate places
 * need the same wording — the table's Action column, the detail modal's meta
 * grid, and the Action Type dropdown — and because anything that exports data
 * must carry the STORED value, not the label. Keeping the two apart in one
 * named module is what makes that distinction easy to hold onto later.
 */

export const ACTION_LABELS = {
  SAVE: 'SAVE',
  // The administrator edited a date that had already been committed.
  REVISE: 'Edited saved data',
  // A later date recomputed because an earlier one was edited. Deliberately
  // distinct: without it the log would read as though somebody hand-edited
  // every one of these dates.
  RECALCULATE: 'Recalculated from revision',
  BLOCKED_DUPLICATE: 'BLOCKED DUPLICATE',
  FAILED_SAVE: 'FAILED SAVE',
  FAILED_REVISION: 'FAILED REVISION',
  UNAUTHORIZED_REVISION: 'UNAUTHORIZED REVISION',
  SUBMIT_REQUIREMENT: 'SUBMIT REQUIREMENT',
  BLOCKED_RESUBMISSION: 'BLOCKED RESUBMISSION',
  FAILED_SUBMISSION: 'FAILED SUBMISSION',
};

/** The label for a stored action. Unlisted actions fall back to the old rule. */
export function actionLabel(action) {
  return ACTION_LABELS[action] || String(action).replace(/_/g, ' ');
}
