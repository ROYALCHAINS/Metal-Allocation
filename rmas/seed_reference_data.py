"""
seed_reference_data.py
Royal Metal Allocation System — Python port

Loads reference data (parties, flow sectors, allocation sectors) from the CSV
files in seed/ into the database. Sector and party names are data, never code
(CLAUDE.md section 6, rule 15) — this script contains no names, only the
loading logic.

Idempotent: re-running updates existing rows rather than duplicating them,
matched on the normalised key.

Usage (from inside this directory):
    python seed_reference_data.py                 # load everything available
    python seed_reference_data.py --dry-run       # report what would change
    python seed_reference_data.py --report        # print the mapping, write nothing
"""

import argparse
import csv
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from database import SessionLocal
from models.party import Party
from models.sector import FlowSector, Sector
from services.validation_service import normalize_key

SEED_DIR = Path(__file__).resolve().parent.parent / "seed"
FLOW_SECTORS_CSV = SEED_DIR / "flow_sectors.csv"

# The allocation list may arrive under either name: the sheet export keeps its
# own filename, so both are accepted rather than forcing a rename.
ALLOCATION_CSV_CANDIDATES = ("allocation_sectors.csv", "sector names.csv")

# Column aliases. The sheet's own headers (Priority/Party/Sector/Purity) are the
# labels DATABASE_OVERVIEW.md's extraction prompt specifies, so an export lands
# with those; the snake_case forms are accepted too. This is a one-off import of
# sheet data, NOT the runtime header-detection logic CLAUDE.md rule 16
# deliberately drops — the database schema itself stays explicit.
_COLUMN_ALIASES = {
    "priority": ("priority", "Priority"),
    "party": ("party_name", "Party", "Party Name"),
    "sector": ("sector_name", "Sector", "Sector Name"),
    "purity": ("purity", "Purity"),
    "display_order": ("display_order", "Display Order"),
}

def _field(row: dict[str, str], logical_name: str) -> str | None:
    """Read a column by any of its accepted header spellings."""
    for alias in _COLUMN_ALIASES[logical_name]:
        if alias in row and row[alias] is not None:
            return row[alias]
    return None


def read_priority(raw: str | None, sector_name: str) -> str:
    """Return the sheet's priority cell verbatim, only trimmed.

    `sector.priority` is TEXT and holds exactly what the sheet says
    ('Priority 1'…'Priority 6'), because legacy treats it as a user-visible
    label — ReportService.gs uses it as the filter-dropdown label, the
    "by priority" dashboard grouping key and in text search. Nothing is parsed,
    renamed or renumbered here; the only rule is that the column is NOT NULL, so
    a blank is refused rather than filled in.
    """
    text = "" if raw is None else str(raw).strip()
    if not text:
        raise ValueError(
            f"Sector {sector_name!r} has a blank priority. sector.priority is TEXT NOT "
            "NULL — resolve this against the sheet rather than inventing a value."
        )
    return text


def _upsert_party(db: Session, party_name: str) -> Party:
    """Find a party by its normalised key, or create it."""
    key = normalize_key(party_name)
    if not key:
        raise ValueError("Party name is blank")

    party = db.scalar(select(Party).where(Party.party_key == key))
    if party is None:
        party = Party(party_name=party_name.strip(), party_key=key)
        db.add(party)
        db.flush()
    return party


def load_flow_sectors(db: Session, path: Path) -> tuple[int, int]:
    """Returns (parties_seen, flow_sectors_written)."""
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    parties: set[str] = set()
    written = 0

    for row in rows:
        sector_name = row["sector_name"].strip()
        party_name = row["party_name"].strip()
        if not sector_name:
            continue

        party = _upsert_party(db, party_name)
        parties.add(party.party_key)

        key = normalize_key(sector_name)
        existing = db.scalar(select(FlowSector).where(FlowSector.sector_key == key))
        display_order = int(row["display_order"]) if row.get("display_order") else None

        if existing is None:
            db.add(
                FlowSector(
                    sector_name=sector_name,
                    sector_key=key,
                    party_id=party.party_id,
                    display_order=display_order,
                )
            )
        else:
            existing.sector_name = sector_name
            existing.party_id = party.party_id
            existing.display_order = display_order
        written += 1

    return len(parties), written


def load_allocation_sectors(db: Session, path: Path) -> tuple[int, int]:
    """Returns (parties_seen, sectors_written).

    Expects columns: display_order, priority, sector_name, purity, party_name.
    `purity` is stored verbatim as TEXT — never parsed into a number.
    """
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))

    parties: set[str] = set()
    written = 0

    for index, row in enumerate(rows, start=1):
        sector_name = (_field(row, "sector") or "").strip()
        if not sector_name:
            continue

        party = _upsert_party(db, _field(row, "party") or "")
        parties.add(party.party_key)

        priority = read_priority(_field(row, "priority"), sector_name)

        purity = (_field(row, "purity") or "").strip()
        if not purity:
            raise ValueError(
                f"Sector {sector_name!r} has a blank purity. sector.purity is TEXT NOT "
                "NULL. Legacy substituted the literal 'Any' for a blank Purity cell "
                "(DataService.gs:111) — confirm whether to do the same here before "
                "loading, rather than inventing a value."
            )

        key = normalize_key(sector_name)
        existing = db.scalar(select(Sector).where(Sector.sector_key == key))
        order_raw = _field(row, "display_order")
        # No Display Order column in the sheet export — fall back to row order.
        display_order = int(order_raw) if order_raw else index

        if existing is None:
            db.add(
                Sector(
                    sector_name=sector_name,
                    sector_key=key,
                    priority=priority,
                    purity=purity,
                    party_id=party.party_id,
                    display_order=display_order,
                )
            )
        else:
            existing.sector_name = sector_name
            existing.priority = priority
            existing.purity = purity
            existing.party_id = party.party_id
            existing.display_order = display_order
        written += 1

    return len(parties), written


def prune_flow_sectors(db: Session, path: Path) -> list[str]:
    """Delete flow_sector rows whose name is not in the CSV.

    Off by default. The CSV is meant to be the authoritative description of the
    table, but the loader only ever inserts/updates, so a name removed from the
    file would otherwise linger in the database forever. Deliberately fails loud
    if a row is still referenced (metal_flow_master, staging, user_flow_scope) —
    reference data in use must not vanish silently.
    """
    with path.open(newline="", encoding="utf-8-sig") as handle:
        wanted = {
            normalize_key(row["sector_name"]) for row in csv.DictReader(handle) if row["sector_name"].strip()
        }

    removed = []
    for sector in db.scalars(select(FlowSector)).all():
        if sector.sector_key not in wanted:
            removed.append(sector.sector_name)
            db.delete(sector)
    return removed


def report_mapping(db: Session) -> None:
    """Print how sectors are mapped, as SECTORS_EXPLAINED.md describes it.

    Read-only. Exists because the relationship is the part people get wrong:
    there is no sector-to-sector mapping table, only

        flow sector --(names)--> party --(owns)--> many allocation sectors

    so "which allocation sectors does this supply feed?" is a question about
    the party column, and this prints the answer without anyone writing SQL.
    """
    parties = db.scalars(select(Party).order_by(Party.party_id)).all()
    print("PARTY -> SECTORS\n")

    unowned = []
    for party in parties:
        allocation = db.scalars(
            select(Sector.sector_name)
            .where(Sector.party_id == party.party_id)
            .order_by(Sector.display_order)
        ).all()
        flow = db.scalars(
            select(FlowSector.sector_name)
            .where(FlowSector.party_id == party.party_id)
            .order_by(FlowSector.display_order)
        ).all()

        if not allocation and not flow:
            unowned.append(party.party_name)
            continue

        print(f"{party.party_name}  [key: {party.party_key}]")
        print(f"  supply  - flow sectors      ({len(flow):2}): {', '.join(flow) or '(none)'}")
        print(
            f"  demand  - allocation sectors ({len(allocation):2}): "
            f"{', '.join(allocation) or '(none)'}"
        )
        if flow and not allocation:
            print("  WARNING: acquires metal but owns no allocation sector to spend it on.")
        if allocation and not flow:
            print("  WARNING: has demand but no flow sector, so no supply can be recorded.")
        print()

    if unowned:
        # Not an error: a party can exist without owning anything. But an
        # operator scoped to one sees an empty screen everywhere, so it is
        # worth stating rather than leaving to be discovered.
        print(f"parties owning no sectors at all ({len(unowned)}): {', '.join(unowned)}")
        print("  An operator scoped to one of these would see no data on any page.\n")

    # A name in both sets is two distinct records; a DISAGREEMENT about which
    # party owns them is the thing worth catching.
    allocation_by_key = {s.sector_key: s for s in db.scalars(select(Sector))}
    flow_by_key = {f.sector_key: f for f in db.scalars(select(FlowSector))}
    shared = sorted(set(allocation_by_key) & set(flow_by_key))
    print(
        f"names present in BOTH sets: {len(shared)} "
        f"(of {len(allocation_by_key)} allocation / {len(flow_by_key)} flow)"
    )
    print("  These are separate demand and supply records that share a label.")

    disagree = [
        allocation_by_key[key].sector_name
        for key in shared
        if allocation_by_key[key].party_id != flow_by_key[key].party_id
    ]
    if disagree:
        print(f"  MISMATCH: same name, different party: {', '.join(disagree)}")
    else:
        print("  Every shared name agrees on its party.")

    # A key that has drifted from its name silently breaks every lookup.
    drifted = [
        row.sector_name
        for row in [*allocation_by_key.values(), *flow_by_key.values()]
        if row.sector_key != normalize_key(row.sector_name)
    ] + [p.party_name for p in parties if p.party_key != normalize_key(p.party_name)]
    print(f"\nkeys consistent with their names: {'no — ' + str(drifted) if drifted else 'yes'}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Load reference data from seed/ CSVs.")
    parser.add_argument(
        "--dry-run", action="store_true", help="Roll back instead of committing."
    )
    parser.add_argument(
        "--prune",
        action="store_true",
        help="Also DELETE flow_sector rows that are no longer in the CSV.",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Print the party -> sector mapping currently in the database and exit.",
    )
    args = parser.parse_args()

    if args.report:
        db = SessionLocal()
        try:
            report_mapping(db)
        finally:
            db.close()
        return

    db = SessionLocal()
    try:
        if FLOW_SECTORS_CSV.exists():
            parties, sectors = load_flow_sectors(db, FLOW_SECTORS_CSV)
            print(f"flow sectors: {sectors} rows, {parties} parties")
            if args.prune:
                removed = prune_flow_sectors(db, FLOW_SECTORS_CSV)
                print(f"  pruned {len(removed)} row(s) absent from the CSV: {removed or 'none'}")
        else:
            print(f"skipped: {FLOW_SECTORS_CSV.name} not found")

        allocation_csv = next(
            (SEED_DIR / name for name in ALLOCATION_CSV_CANDIDATES if (SEED_DIR / name).exists()),
            None,
        )
        if allocation_csv is not None:
            parties, sectors = load_allocation_sectors(db, allocation_csv)
            print(f"allocation sectors: {sectors} rows, {parties} parties [{allocation_csv.name}]")
        else:
            print(
                "skipped: no allocation sector CSV found "
                f"(looked for {', '.join(ALLOCATION_CSV_CANDIDATES)})"
            )

        if args.dry_run:
            db.rollback()
            print("dry run — rolled back, nothing written")
        else:
            db.commit()
            print("committed")
    except Exception as exc:  # noqa: BLE001 — surface the reason and fail loudly
        db.rollback()
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    finally:
        db.close()


if __name__ == "__main__":
    main()
