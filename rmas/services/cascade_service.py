"""
services/cascade_service.py
Royal Metal Allocation System — the forward cascade

When an administrator revises a saved date, every LATER saved date's
previous_requirement and balance were carried forward from the old figures and
are now stale. Legacy never fixed this — reviseDailyAllocation() rewrote only
the selected date — so a revision silently left the rest of the ledger wrong.
This computes the correction.

PURE, ON PURPOSE. No Session, no repository, no ORM, no Decimal, no float.
Integer grams in, integer grams out. The revision service reads the rows,
calls this, and writes the result back; the reconciliation script calls the
same function over the whole ledger. Keeping it pure is what lets the
arithmetic be tested exhaustively without a database, and what stops the
reconciliation report from drifting away from the live rule.

WHAT IT CHANGES, AND WHAT IT MUST NEVER TOUCH:

    previous_requirement   recomputed
    balance                recomputed
    today_required         never
    alloted                never
    acquired (Metal Flow)  never — Metal Flow has no balance column, so the
                           cascade does not touch that ledger at all
    priority / purity      never — those snapshots record what applied ON that
                           date, not what applies now
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from services.date_service import resolve_source_date
from services.validation_service import compute_balance_g, nearly_equal_g


@dataclass(frozen=True)
class LedgerRow:
    sector_id: int
    previous_requirement_g: int
    today_required_g: int
    alloted_g: int
    balance_g: int


@dataclass(frozen=True)
class DateLedger:
    allocation_date: str
    rows: tuple[LedgerRow, ...]


@dataclass(frozen=True)
class SectorChange:
    sector_id: int
    before_previous_requirement_g: int
    before_balance_g: int
    previous_requirement_g: int
    balance_g: int


@dataclass(frozen=True)
class DateRecalculation:
    allocation_date: str
    source_date: str | None
    # Only the sectors that actually moved.
    changes: tuple[SectorChange, ...]
    # The full post-state of the date, for the audit snapshot.
    rows_after: tuple[LedgerRow, ...]
    negative_balance_sector_ids: tuple[int, ...]


@dataclass(frozen=True)
class CascadeResult:
    # Ascending by date, and only dates that changed.
    recalculated: tuple[DateRecalculation, ...]
    examined_date_count: int
    skipped_date_count: int

    @property
    def sector_count(self) -> int:
        """Distinct sectors touched anywhere in the cascade."""
        return len(
            {c.sector_id for rec in self.recalculated for c in rec.changes}
        )

    @property
    def negative_balance_dates(self) -> tuple[str, ...]:
        return tuple(
            rec.allocation_date
            for rec in self.recalculated
            if rec.negative_balance_sector_ids
        )


def cascade_forward(
    *,
    edited_date: str,
    edited_rows: Sequence[LedgerRow],
    later_ledgers: Sequence[DateLedger],
    saved_dates: Sequence[str],
    propagate_only: bool = True,
) -> CascadeResult:
    """Recompute later saved dates after `edited_date` changed.

    `edited_rows` is the POST-revision state of the edited date.
    `later_ledgers` must be ascending — each date depends on the one before it.
    `saved_dates` is EVERY saved allocation date, including dates before the
    edited one, because the fallback rule can reach back behind it through a
    gap.

    `propagate_only=True` (the revision path) recalculates a date only when its
    source date actually changed. A revision must not quietly repair drift it
    did not cause: the audit trail would then claim an edit was responsible for
    corrections it had nothing to do with, and a deliberate manual adjustment
    would be overwritten without anyone asking. Pre-existing drift is surfaced
    by reconcile_carry_forward.py instead.

    `propagate_only=False` recomputes every date from its source regardless.
    That is the reconciliation script's mode, and it is why this is a parameter
    rather than a hard-coded rule — the report has to use the same arithmetic
    as the live path or it is not a report of anything.
    """
    saved_sorted = sorted(saved_dates)
    saved_set = frozenset(saved_sorted)

    def date_exists(iso: str) -> bool:
        return iso in saved_set

    def latest_date_before(iso: str) -> str | None:
        return max((d for d in saved_sorted if d < iso), default=None)

    # Working state, seeded with the edited date's new figures.
    state: dict[str, dict[int, LedgerRow]] = {
        edited_date: {row.sector_id: row for row in edited_rows}
    }
    for ledger in later_ledgers:
        state[ledger.allocation_date] = {row.sector_id: row for row in ledger.rows}

    # Dates whose balances have moved, and can therefore move their dependants.
    dirty: set[str] = {edited_date}

    recalculated: list[DateRecalculation] = []
    examined = 0
    skipped = 0

    for ledger in later_ledgers:
        examined += 1
        source = resolve_source_date(
            date.fromisoformat(ledger.allocation_date),
            date_exists=date_exists,
            latest_date_before=latest_date_before,
        )

        if propagate_only and source.source_date not in dirty:
            # Nothing upstream of this date moved, so nothing on it can. Stated
            # per-date rather than per-sector because a gap fallback can hop
            # over the previous calendar date entirely.
            skipped += 1
            continue

        source_rows = state.get(source.source_date or "", {})

        changes: list[SectorChange] = []
        rows_after: list[LedgerRow] = []
        negative: list[int] = []

        for row in ledger.rows:
            # A sector absent from its source date carries ZERO — never the
            # value from some earlier date.
            carried = source_rows.get(row.sector_id)
            previous_requirement_g = carried.balance_g if carried is not None else 0
            balance_g = compute_balance_g(
                previous_requirement_g, row.today_required_g, row.alloted_g
            )

            updated = LedgerRow(
                sector_id=row.sector_id,
                previous_requirement_g=previous_requirement_g,
                today_required_g=row.today_required_g,
                alloted_g=row.alloted_g,
                balance_g=balance_g,
            )
            rows_after.append(updated)

            if balance_g < 0:
                negative.append(row.sector_id)

            # Epsilon comparison, never ==. In integer grams that IS exact
            # equality, which is why EPSILON must not be converted to "1 gram".
            moved = not nearly_equal_g(
                previous_requirement_g, row.previous_requirement_g
            ) or not nearly_equal_g(balance_g, row.balance_g)
            if moved:
                changes.append(
                    SectorChange(
                        sector_id=row.sector_id,
                        before_previous_requirement_g=row.previous_requirement_g,
                        before_balance_g=row.balance_g,
                        previous_requirement_g=previous_requirement_g,
                        balance_g=balance_g,
                    )
                )

        state[ledger.allocation_date] = {r.sector_id: r for r in rows_after}

        if not changes:
            continue

        # This date's balances moved, so its own dependants must be examined.
        dirty.add(ledger.allocation_date)
        recalculated.append(
            DateRecalculation(
                allocation_date=ledger.allocation_date,
                source_date=source.source_date,
                changes=tuple(changes),
                rows_after=tuple(rows_after),
                negative_balance_sector_ids=tuple(negative),
            )
        )

    return CascadeResult(
        recalculated=tuple(recalculated),
        examined_date_count=examined,
        skipped_date_count=skipped,
    )
