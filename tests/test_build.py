"""Tests for the static data build (ledger 5.1).

This file is the contract between the pipeline and the web app, so the tests
care most about two things: that the schema stays stable, and that gaps in our
own coverage are declared rather than smoothed over.
"""

from __future__ import annotations

import json

from build import (
    ACCESS_FIELDS,
    CHANGE_FIELDS,
    PRACTICE_FIELDS,
    SCHEMA_VERSION,
    _tri,
    _write,
    build_changes,
)


def test_tri_state_preserves_unknown():
    """"The practice has not said" is a different fact from "no". Flattening
    None to 0 would invent an answer the source never gave."""
    assert _tri(True) == 1
    assert _tri(False) == 0
    assert _tri(None) is None


def test_write_emits_columnar_payload(tmp_path):
    path = tmp_path / "out.json"
    n = _write(path, ["a", "b"], [[1, 2], [3, 4]], as_of="2026-07-28")

    payload = json.loads(path.read_text())
    assert n == 2
    assert payload["schema"] == SCHEMA_VERSION
    assert payload["fields"] == ["a", "b"]
    assert payload["rows"] == [[1, 2], [3, 4]]
    assert payload["as_of"] == "2026-07-28"


def test_write_serialises_dates(tmp_path):
    from datetime import date

    path = tmp_path / "out.json"
    _write(path, ["d"], [[date(2026, 7, 28)]])
    assert json.loads(path.read_text())["rows"] == [["2026-07-28"]]


def test_field_lists_are_stable():
    """The web app indexes rows positionally, so reordering these silently
    corrupts every downstream surface. Pin them."""
    assert PRACTICE_FIELDS[:5] == ["id", "name", "postcode", "lat", "lon"]
    assert PRACTICE_FIELDS[7] == "status"
    assert CHANGE_FIELDS == ["id", "date", "from", "to", "spans_gap"]
    assert ACCESS_FIELDS[0] == "lsoa"


# -- the change log --------------------------------------------------------


def test_changes_records_only_transitions():
    per_day = {
        "2026-07-25": {"V1": "accepting", "V2": "not_accepting"},
        "2026-07-26": {"V1": "not_confirmed", "V2": "not_accepting"},
    }
    changes = build_changes(per_day, ["2026-07-25", "2026-07-26"])

    assert changes == [["V1", "2026-07-26", "accepting", "not_confirmed", 0]]


def test_consecutive_nights_do_not_span_a_gap():
    per_day = {
        "2026-07-25": {"V1": "accepting"},
        "2026-07-26": {"V1": "not_accepting"},
    }
    assert build_changes(per_day, ["2026-07-25", "2026-07-26"])[0][4] == 0


def test_missing_night_marks_the_change_as_ungrounded():
    """A change seen across a gap is real, but we cannot say which day it
    happened. The build must declare that rather than imply precision."""
    per_day = {
        "2026-07-26": {"V1": "accepting"},
        "2026-07-28": {"V1": "not_accepting"},
    }
    changes = build_changes(per_day, ["2026-07-26", "2026-07-28"])

    assert len(changes) == 1
    assert changes[0][4] == 1, "spans_gap must be set when a night is missing"
    assert changes[0][1] == "2026-07-28", "dated to when we saw it, not when it happened"


def test_practice_appearing_mid_history_is_not_a_change():
    """A newly published practice has no prior status; calling that a
    transition would fabricate an event."""
    per_day = {
        "2026-07-25": {"V1": "accepting"},
        "2026-07-26": {"V1": "accepting", "V2": "not_accepting"},
    }
    assert build_changes(per_day, ["2026-07-25", "2026-07-26"]) == []


def test_practice_disappearing_is_not_a_change():
    per_day = {
        "2026-07-25": {"V1": "accepting", "V2": "accepting"},
        "2026-07-26": {"V1": "accepting"},
    }
    assert build_changes(per_day, ["2026-07-25", "2026-07-26"]) == []


def test_changes_accumulate_across_three_nights():
    per_day = {
        "2026-07-25": {"V1": "accepting"},
        "2026-07-26": {"V1": "not_accepting"},
        "2026-07-28": {"V1": "accepting"},
    }
    changes = build_changes(per_day, ["2026-07-25", "2026-07-26", "2026-07-28"])

    assert len(changes) == 2
    assert [c[4] for c in changes] == [0, 1]


def test_single_night_yields_no_changes():
    assert build_changes({"2026-07-25": {"V1": "accepting"}}, ["2026-07-25"]) == []


def test_no_days_yields_no_changes():
    assert build_changes({}, []) == []
