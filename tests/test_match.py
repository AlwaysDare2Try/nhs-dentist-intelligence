"""Tests for entity resolution (ledger 3.3).

The property under test is restraint: a wrong link silently attributes one
practice's decade of activity to another, so refusing to guess must be as
reliable as matching.
"""

from __future__ import annotations

import pytest
from match import (
    MATCH_AMBIGUOUS,
    MATCH_NO_POSTCODE,
    MATCH_NO_POSTCODE_MATCH,
    MATCH_POSTCODE_AND_NAME,
    MATCH_POSTCODE_UNIQUE,
    build_postcode_index,
    format_summary,
    name_score,
    normalise_name,
    normalise_postcode,
    resolve_all,
    resolve_contract,
    summarise,
)


class Practice:
    """Stands in for ods.OdsPractice."""

    def __init__(self, org_id, name, postcode):
        self.org_id = org_id
        self.name = name
        self.postcode = postcode


# -- normalisation ---------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("SMILE DENTAL PRACTICE LTD", "smile"),
        ("The Smile Dental Care Limited", "smile"),
        ("MR K J KHAN", "mr k j khan"),
        ("St. Mary's Dental Surgery", "st marys"),
    ],
)
def test_normalise_name_strips_boilerplate(raw, expected):
    assert normalise_name(raw) == expected


def test_normalise_postcode():
    assert normalise_postcode("gu29 9hh") == "GU299HH"
    assert normalise_postcode(" GU29  9HH ") == "GU299HH"
    assert normalise_postcode("") == ""


def test_name_score_ignores_corporate_noise():
    """These are the same practice; boilerplate must not separate them."""
    assert name_score("SMILE DENTAL PRACTICE LTD", "Smile Dental Care Limited") > 90


def test_name_score_tolerates_reordering():
    assert name_score("Mr K J Khan Dental Surgery", "Khan, K J - Dental Practice") > 80


def test_name_score_separates_genuinely_different_practices():
    assert name_score("Bridge Street Dental", "Oakwood Dental") < 60


def test_name_score_refuses_to_score_empty_names():
    """All-boilerplate names normalise to nothing — scoring them 100 against
    each other would auto-match unrelated practices."""
    assert name_score("Dental Practice Ltd", "The Dental Surgery") == 0.0
    assert name_score("", "Smile") == 0.0


# -- resolution ------------------------------------------------------------


def index_of(*practices):
    return build_postcode_index(list(practices))


def test_unique_postcode_resolves_without_needing_the_name():
    """A renamed practice must not be dropped when the postcode is unambiguous."""
    idx = index_of(Practice("V001", "Completely Different Name", "GU29 9HH"))
    m = resolve_contract("C1", "Smile Dental", "GU29 9HH", idx)

    assert m.resolved
    assert m.org_id == "V001"
    assert m.method == MATCH_POSTCODE_UNIQUE
    assert m.candidates == 1


def test_shared_postcode_resolved_by_a_clear_name_win():
    idx = index_of(
        Practice("V001", "Bridge Street Dental Practice", "E1 1AA"),
        Practice("V002", "Oakwood Orthodontics", "E1 1AA"),
    )
    m = resolve_contract("C1", "Bridge Street Dental", "E1 1AA", idx)

    assert m.method == MATCH_POSTCODE_AND_NAME
    assert m.org_id == "V001"
    assert m.score - m.runner_up_score >= 10


def test_near_tie_is_queued_not_guessed():
    """Two similar practices in one building is a coin toss. Guessing would
    misattribute a decade of activity."""
    idx = index_of(
        Practice("V001", "Bridge Dental Practice", "E1 1AA"),
        Practice("V002", "Bridge Dental Practice", "E1 1AA"),
    )
    m = resolve_contract("C1", "Bridge Dental", "E1 1AA", idx)

    assert not m.resolved
    assert m.needs_review
    assert m.method == MATCH_AMBIGUOUS
    assert m.candidates == 2


def test_shared_postcode_with_no_good_name_match_is_queued():
    idx = index_of(
        Practice("V001", "Oakwood Orthodontics", "E1 1AA"),
        Practice("V002", "Riverside Periodontics", "E1 1AA"),
    )
    m = resolve_contract("C1", "Bridge Street Dental", "E1 1AA", idx)

    assert not m.resolved
    assert m.method == MATCH_AMBIGUOUS


def test_postcode_absent_from_register():
    m = resolve_contract("C1", "Smile", "ZZ99 9ZZ", index_of(Practice("V001", "A", "E1 1AA")))
    assert not m.resolved
    assert m.method == MATCH_NO_POSTCODE_MATCH
    assert m.candidates == 0


def test_contract_without_a_postcode():
    m = resolve_contract("C1", "Smile", "", index_of(Practice("V001", "A", "E1 1AA")))
    assert not m.resolved
    assert m.method == MATCH_NO_POSTCODE


def test_index_skips_practices_without_postcodes():
    idx = build_postcode_index([Practice("V001", "A", ""), Practice("V002", "B", "E1 1AA")])
    assert set(idx) == {"E11AA"}


# -- aggregate reporting ---------------------------------------------------


def test_summarise_reports_rate_and_review_queue():
    idx = index_of(
        Practice("V001", "Bridge Street Dental", "E1 1AA"),
        Practice("V002", "Oakwood Orthodontics", "E1 1AB"),
        Practice("V003", "Twin Dental", "E1 1AC"),
        Practice("V004", "Twin Dental", "E1 1AC"),
    )
    matches = resolve_all(
        [
            ("C1", "Bridge Street Dental", "E1 1AA"),  # unique
            ("C2", "Oakwood Orthodontics", "E1 1AB"),  # unique
            ("C3", "Twin Dental", "E1 1AC"),  # ambiguous
            ("C4", "Nowhere Dental", "ZZ99 9ZZ"),  # no postcode match
        ],
        idx,
    )
    stats = summarise(matches)

    assert stats["total_contracts"] == 4
    assert stats["resolved"] == 2
    assert stats["match_rate"] == pytest.approx(0.5)
    assert stats["needs_review"] == 1
    assert stats["by_method"][MATCH_POSTCODE_UNIQUE] == 2
    assert stats["by_method"][MATCH_NO_POSTCODE_MATCH] == 1
    assert stats["distinct_ods_matched"] == 2


def test_summarise_surfaces_many_to_many():
    """One practice holding several contracts is expected, not an error — but
    it must be visible."""
    idx = index_of(Practice("V001", "Bridge Street Dental", "E1 1AA"))
    matches = resolve_all(
        [("C1", "Bridge Street Dental", "E1 1AA"), ("C2", "Bridge Street Dental", "E1 1AA")],
        idx,
    )
    stats = summarise(matches)

    assert stats["resolved"] == 2
    assert stats["distinct_ods_matched"] == 1
    assert stats["ods_with_multiple_contracts"] == 1


def test_summarise_flags_matches_kept_on_a_weak_name():
    idx = index_of(Practice("V001", "Totally Unrelated", "E1 1AA"))
    stats = summarise(resolve_all([("C1", "Bridge Street Dental", "E1 1AA")], idx))

    assert stats["resolved"] == 1, "postcode-unique matches are kept"
    assert stats["resolved_with_weak_name"] == 1, "but the weak name must be flagged"


def test_unscoreable_names_are_counted_apart_from_weak_ones():
    """ODS site names are often pure boilerplate ("DENTAL SURGERY") and carry no
    identifying content. Averaging those in as zeros would misrepresent match
    quality — and gating on them would discard correct postcode-unique links."""
    idx = index_of(
        Practice("V001", "Dental Surgery", "E1 1AA"),  # normalises to nothing
        Practice("V002", "Totally Unrelated", "E1 1AB"),  # comparable but poor
    )
    stats = summarise(
        resolve_all(
            [("C1", "Dr H S Thiara", "E1 1AA"), ("C2", "Bridge Street Dental", "E1 1AB")],
            idx,
        )
    )

    assert stats["resolved"] == 2, "both are postcode-unique and must be kept"
    assert stats["unscoreable_name"] == 1
    assert stats["resolved_with_weak_name"] == 1
    assert stats["mean_name_score_where_comparable"] > 0


def test_summarise_handles_empty():
    assert summarise([])["match_rate"] == 0.0
    assert format_summary(summarise([])) == "No contracts to resolve."


def test_format_summary_mentions_the_review_queue():
    idx = index_of(
        Practice("V001", "Twin Dental", "E1 1AC"),
        Practice("V002", "Twin Dental", "E1 1AC"),
    )
    text = format_summary(summarise(resolve_all([("C1", "Twin Dental", "E1 1AC")], idx)))
    assert "REVIEW" in text
