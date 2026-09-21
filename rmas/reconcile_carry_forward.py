"""
reconcile_carry_forward.py
Royal Metal Allocation System — carry-forward drift report

Legacy's revision path rewrote only the date being edited. Every later saved
date kept the previous_requirement it was saved with, carried from the OLD
balance — so any revision ever made has left stale figures behind it. The
forward cascade stops that happening from now on; this reports what is already
there.

REPORT ONLY. There is deliberately no --fix flag, and adding one would be a
mistake: some of these differences are drift, but some may be deliberate manual
adjustments, and this script cannot tell them apart. A person has to look.

It recomputes using cascade_service.cascade_forward(propagate_only=False) —
the SAME function the live revision path uses — so the report can never drift
away from the rule it is reporting against.

    python reconcile_carry_forward.py
    python reconcile_carry_forward.py --csv drift.csv
    python reconcile_carry_forward.py --strict      # exit 1 when drift is found
"""

from __future__ import annotations

import argparse
import csv
import sys

from database import SessionLocal
from repository import allocation_repo, sector_repo
from services import cascade_service
from services.weight_service import grams_to_kg

FIELDS = ("previous_requirement", "balance")


def _ledger_rows(rows) -> tuple[cascade_service.LedgerRow, ...]:
    return tuple(
        cascade_service.LedgerRow(
            sector_id=row.sector_id,
            previous_requirement_g=row.previous_requirement_g,
            today_required_g=row.today_required_g,
            alloted_g=row.alloted_g,
            balance_g=row.balance_g,
        )
        for row in rows
    )


def collect_drift(db) -> list[dict]:
    """Every (date, sector, field) whose stored figure differs from the rule."""
    saved_dates = allocation_repo.all_saved_dates(db)
    if not saved_dates:
        return []

    names = {s.sector_id: s.sector_name for s in sector_repo.get_all_sectors(db)}

    by_date: dict[str, list] = {iso: [] for iso in saved_dates}
    for row in allocation_repo.get_rows_for_dates(db, saved_dates):
        by_date[row.allocation_date].append(row)

    first, *rest = saved_dates
    # The earliest date is the anchor: it is taken as correct, because there is
    # nothing before it to carry from. Everything after it is recomputed.
    result = cascade_service.cascade_forward(
        edited_date=first,
        edited_rows=_ledger_rows(by_date[first]),
        later_ledgers=[
            cascade_service.DateLedger(iso, _ledger_rows(by_date[iso])) for iso in rest
        ],
        saved_dates=saved_dates,
        propagate_only=False,
    )

    drift: list[dict] = []
    for entry in result.recalculated:
        for change in entry.changes:
            pairs = (
                ("previous_requirement", change.before_previous_requirement_g,
                 change.previous_requirement_g),
                ("balance", change.before_balance_g, change.balance_g),
            )
            for field, stored_g, recomputed_g in pairs:
                if stored_g == recomputed_g:
                    continue
                drift.append(
                    {
                        "date": entry.allocation_date,
                        "sector": names.get(change.sector_id, str(change.sector_id)),
                        "field": field,
                        "stored_kg": str(grams_to_kg(stored_g)),
                        "recomputed_kg": str(grams_to_kg(recomputed_g)),
                        "delta_kg": str(grams_to_kg(recomputed_g - stored_g)),
                    }
                )
    return drift


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Report rows whose carry-forward figures disagree with the rule."
    )
    parser.add_argument("--csv", help="also write the rows to this file")
    parser.add_argument(
        "--strict", action="store_true", help="exit 1 when any drift is found"
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        saved_dates = allocation_repo.all_saved_dates(db)
        drift = collect_drift(db)
    finally:
        # Read-only by construction; rolled back so nothing can leak out of it.
        db.rollback()
        db.close()

    if not drift:
        print(f"No carry-forward drift across {len(saved_dates)} saved dates.")
        return 0

    header = f"{'date':<12} {'sector':<28} {'field':<21} {'stored':>12} {'recomputed':>12} {'delta':>12}"
    print(header)
    print("-" * len(header))
    for row in drift:
        print(
            f"{row['date']:<12} {row['sector'][:28]:<28} {row['field']:<21} "
            f"{row['stored_kg']:>12} {row['recomputed_kg']:>12} {row['delta_kg']:>12}"
        )

    dates = {row["date"] for row in drift}
    sectors = {row["sector"] for row in drift}
    print()
    print(
        f"{len(drift)} differing figures across {len(dates)} dates and "
        f"{len(sectors)} sectors, of {len(saved_dates)} saved dates examined."
    )
    print(f"Earliest affected date: {min(dates)}")
    print()
    print(
        "Nothing has been changed. Some of these may be deliberate manual\n"
        "adjustments rather than drift — decide date by date before correcting."
    )

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(drift[0]))
            writer.writeheader()
            writer.writerows(drift)
        print(f"\nWritten to {args.csv}")

    return 1 if args.strict else 0


if __name__ == "__main__":
    sys.exit(main())
