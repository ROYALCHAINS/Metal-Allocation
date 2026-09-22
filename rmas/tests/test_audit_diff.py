"""tests/test_audit_diff.py — snapshot decoding and the revision comparison.

Pure functions over JSON, so no database. These pin the diff semantics from
AuditReportService.gs, several of which a reasonable implementation gets wrong:
a one-sided sector marks EVERY field changed, comparison is epsilon-based, a
malformed snapshot degrades to empty rather than raising, and the union
preserves before-first ordering.
"""

import json

from services.audit_report_service import (
    format_audit_timestamp,
    decode_allocation_snapshot,
    decode_flow_snapshot,
    diff_allocation_snapshots,
    diff_flow_snapshots,
    allocation_totals,
    preview_reason,
)


def alloc(name, pr="0.000", tr="0.000", al="0.000", bl="0.000", priority="Priority 1"):
    return {"p": priority, "s": name, "pu": "Any", "pr": pr, "tr": tr, "al": al, "bl": bl}


def test_short_keys_decode_to_integer_grams() -> None:
    [row] = decode_allocation_snapshot(json.dumps([alloc("RC", tr="7.839", al="7.500")]))
    assert row.sector_name == "RC"
    assert row.values_g["today_required"] == 7_839
    assert row.values_g["alloted"] == 7_500
    assert row.priority == "Priority 1"
    assert row.purity == "Any"


def test_unchanged_value_is_not_a_change() -> None:
    before = decode_allocation_snapshot(json.dumps([alloc("RC", al="5.000")]))
    after = decode_allocation_snapshot(json.dumps([alloc("RC", al="5.000")]))
    [entry] = diff_allocation_snapshots(before, after)

    assert entry.any_change is False
    assert entry.changed == dict.fromkeys(
        ("previous_requirement", "today_required", "alloted", "balance"), False
    )
    assert entry.only_before is False and entry.only_after is False


def test_only_the_field_that_moved_is_flagged() -> None:
    before = decode_allocation_snapshot(json.dumps([alloc("RC", al="5.000", bl="2.000")]))
    after = decode_allocation_snapshot(json.dumps([alloc("RC", al="5.001", bl="2.000")]))
    [entry] = diff_allocation_snapshots(before, after)

    assert entry.changed["alloted"] is True
    assert entry.changed["balance"] is False
    assert entry.any_change is True


def test_one_gram_apart_is_a_real_change_not_float_noise() -> None:
    """The epsilon absorbs representation error, never a genuine gram."""
    before = decode_allocation_snapshot(json.dumps([alloc("RC", al="5.000")]))
    after = decode_allocation_snapshot(json.dumps([alloc("RC", al="5.001")]))
    assert diff_allocation_snapshots(before, after)[0].changed["alloted"] is True


def test_added_sector_marks_every_field_changed() -> None:
    """An added sector is a change in all its values, not just the non-zero
    ones — marking only some would understate it."""
    before = decode_allocation_snapshot(json.dumps([alloc("RC")]))
    after = decode_allocation_snapshot(json.dumps([alloc("RC"), alloc("New", tr="1.000")]))
    entries = {e.sector_name: e for e in diff_allocation_snapshots(before, after)}

    added = entries["New"]
    assert added.only_after is True and added.only_before is False
    assert added.before is None
    assert all(added.changed.values())
    assert added.any_change is True


def test_removed_sector_marks_every_field_changed() -> None:
    before = decode_allocation_snapshot(json.dumps([alloc("RC"), alloc("Gone", tr="1.000")]))
    after = decode_allocation_snapshot(json.dumps([alloc("RC")]))
    entries = {e.sector_name: e for e in diff_allocation_snapshots(before, after)}

    removed = entries["Gone"]
    assert removed.only_before is True and removed.only_after is False
    assert removed.after is None
    assert all(removed.changed.values())


def test_union_keeps_before_rows_first_then_appends_added() -> None:
    before = decode_allocation_snapshot(json.dumps([alloc("Alpha"), alloc("Beta")]))
    after = decode_allocation_snapshot(json.dumps([alloc("Zulu"), alloc("Beta")]))
    assert [e.sector_name for e in diff_allocation_snapshots(before, after)] == [
        "Alpha",
        "Beta",
        "Zulu",
    ]


def test_sectors_match_on_the_normalised_name() -> None:
    """Casing and spacing drift must not read as a removal plus an addition."""
    before = decode_allocation_snapshot(json.dumps([alloc("RC  Customer Orders", al="1.000")]))
    after = decode_allocation_snapshot(json.dumps([alloc("rc customer orders", al="1.000")]))
    entries = diff_allocation_snapshots(before, after)

    assert len(entries) == 1
    assert entries[0].any_change is False


def test_malformed_snapshot_degrades_to_empty_rather_than_raising() -> None:
    """Rule 12. The entry is still worth showing — often it is the failure
    record that matters most."""
    assert decode_allocation_snapshot("{not json at all") == []
    assert decode_allocation_snapshot('{"an":"object, not a list"}') == []
    assert decode_allocation_snapshot("") == []
    assert decode_allocation_snapshot(None) == []
    assert decode_flow_snapshot("[garbage") == []


def test_unparseable_weight_reads_as_zero_not_an_error() -> None:
    [row] = decode_allocation_snapshot(json.dumps([alloc("RC", al="not-a-number")]))
    assert row.values_g["alloted"] == 0


def test_flow_diff_compares_the_single_acquired_field() -> None:
    before = decode_flow_snapshot(json.dumps([{"s": "RC", "ac": "3.000"}]))
    after = decode_flow_snapshot(json.dumps([{"s": "RC", "ac": "4.250"}]))
    [entry] = diff_flow_snapshots(before, after)

    assert entry.changed == {"acquired": True}
    assert entry.any_change is True
    assert entry.after.values_g["acquired"] == 4_250


def test_totals_sum_the_columns_and_carry_the_row_count() -> None:
    """Row count is in the totals so a change in the number of sectors is
    visible in the footer, not just implied by the rows above it."""
    rows = decode_allocation_snapshot(
        json.dumps([alloc("A", al="1.500", bl="0.250"), alloc("B", al="2.250", bl="0.750")])
    )
    totals = allocation_totals(rows)

    assert totals["alloted"] == 3_750
    assert totals["balance"] == 1_000
    assert totals["row_count"] == 2


def test_empty_snapshot_totals_are_zero_with_no_rows() -> None:
    assert allocation_totals([]) == {
        "previous_requirement": 0,
        "today_required": 0,
        "alloted": 0,
        "balance": 0,
        "row_count": 0,
    }


def test_reason_preview_collapses_whitespace_and_caps_at_140() -> None:
    assert preview_reason("  fixed   the\n\nallotment  ") == "fixed the allotment"

    long_reason = "x" * 200
    preview = preview_reason(long_reason)
    assert len(preview) == 140
    assert preview.endswith("…")

    assert preview_reason(None) == ""


# ------------------------------------------------------- timestamp rendering
#
# Storage stays UTC (SQLite's datetime('now')); the display is Asia/Kolkata,
# the application timezone. Resolved 2026-09-22. These had no coverage at all
# before, which is how the two drifted apart unnoticed.


def test_a_stored_utc_timestamp_displays_in_asia_kolkata() -> None:
    # 13:09:13 UTC is 18:39:13 IST (+5:30).
    assert format_audit_timestamp("2026-09-21 13:09:13") == "21-Sep-2026 18:39:13"


def test_the_offset_rolls_the_DATE_over_not_just_the_clock() -> None:
    """The case that made this visibly wrong rather than merely off by hours:
    an evening submission in India was being filed under the previous day."""
    assert format_audit_timestamp("2026-09-20 19:34:30") == "21-Sep-2026 01:04:30"


def test_the_display_agrees_with_the_audit_id_it_sits_beside() -> None:
    """generate_audit_id() has always stamped Asia/Kolkata, so before this fix
    every row disagreed with itself: id AUD-20260921-183913 next to a column
    reading 13:09:13. The id is the cross-check."""
    assert format_audit_timestamp("2026-09-21 13:09:13").endswith("18:39:13")


def test_an_explicit_offset_is_honoured_rather_than_assumed_utc() -> None:
    """Naive values are read as UTC because that is what they are. A value that
    already carries an offset is converted from that offset, so this stays
    correct if the columns ever become offset-aware."""
    assert format_audit_timestamp("2026-09-21T18:39:13+05:30") == "21-Sep-2026 18:39:13"
    assert format_audit_timestamp("2026-09-21T13:09:13Z") == "21-Sep-2026 18:39:13"


def test_asia_kolkata_has_no_dst_so_january_and_july_shift_alike() -> None:
    """India does not observe DST, so the offset is a constant +5:30 — unlike a
    timezone where a fixed conversion would be wrong for half the year."""
    assert format_audit_timestamp("2026-01-15 12:00:00") == "15-Jan-2026 17:30:00"
    assert format_audit_timestamp("2026-07-15 12:00:00") == "15-Jul-2026 17:30:00"


def test_an_unparseable_or_absent_timestamp_still_degrades_gracefully() -> None:
    """A compliance record must render even when one cell is malformed."""
    assert format_audit_timestamp("not a timestamp") == "not a timestamp"
    assert format_audit_timestamp("") == ""
    assert format_audit_timestamp(None) == ""


def test_the_month_name_does_not_follow_the_machine_locale() -> None:
    """Spelled from a fixed table, not strftime('%b') — a compliance record must
    not render differently on a differently-configured server."""
    months = [
        format_audit_timestamp(f"2026-{m:02d}-15 06:00:00").split("-")[1]
        for m in range(1, 13)
    ]
    assert months == [
        "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    ]
