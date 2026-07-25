"""Tests for freshness and trust scoring (ledger 4.3).

Constraint C1 is the thing under test as much as the arithmetic: no output of
this module may assert a current fact.
"""

from __future__ import annotations

from datetime import date

import pytest
from freshness import (
    ANCIENT,
    FRESH,
    NEVER_CONFIRMED,
    OVERDUE,
    STALE,
    VERY_STALE,
    bucket_for,
    format_summary,
    score_all,
    score_practice,
    summarise,
)

AS_OF = date(2026, 7, 25)


@pytest.mark.parametrize(
    ("days", "expected"),
    [
        (0, FRESH),
        (89, FRESH),
        (90, FRESH),  # the mandate boundary is inclusive
        (91, OVERDUE),
        (180, OVERDUE),
        (181, STALE),
        (365, STALE),
        (366, VERY_STALE),
        (730, VERY_STALE),
        (731, ANCIENT),
        (5_000, ANCIENT),
        (None, NEVER_CONFIRMED),
    ],
)
def test_bucket_boundaries(days, expected):
    assert bucket_for(days) == expected


def test_single_observation_scores_cleanly():
    f = score_practice("V1", [(AS_OF, "accepting", date(2026, 5, 14))])
    assert f.days_since_confirmed == 72
    assert f.bucket == FRESH
    assert f.meets_mandate
    assert not f.never_confirmed
    assert f.observations == 1
    assert f.status_changes == 0


def test_practice_that_never_confirmed():
    """Absence of a date is a finding — it must not be scored as fresh."""
    f = score_practice("V1", [(AS_OF, "not_confirmed", None)])
    assert f.never_confirmed
    assert f.days_since_confirmed is None
    assert f.bucket == NEVER_CONFIRMED
    assert not f.meets_mandate


def test_fifteen_year_old_confirmation():
    """The sitemap shows real practices last confirmed in 2011."""
    f = score_practice("V1", [(AS_OF, "accepting", date(2011, 1, 6))])
    assert f.bucket == ANCIENT
    assert not f.meets_mandate
    assert f.days_since_confirmed > 5_000


def test_future_confirmation_date_is_clamped_not_negative():
    """A source error must not produce a negative age or a nonsense bucket."""
    f = score_practice("V1", [(AS_OF, "accepting", date(2026, 12, 1))])
    assert f.days_since_confirmed == 0
    assert f.bucket == FRESH


def test_observations_are_ordered_regardless_of_input_order():
    f = score_practice(
        "V1",
        [
            (date(2026, 7, 25), "not_accepting", date(2026, 7, 20)),
            (date(2026, 7, 23), "accepting", date(2026, 5, 1)),
            (date(2026, 7, 24), "accepting", date(2026, 5, 1)),
        ],
    )
    assert f.as_of == date(2026, 7, 25)
    assert f.status == "not_accepting"
    assert f.first_seen == date(2026, 7, 23)


def test_status_change_is_counted_and_dated():
    f = score_practice(
        "V1",
        [
            (date(2026, 7, 23), "accepting", date(2026, 5, 1)),
            (date(2026, 7, 24), "accepting", date(2026, 5, 1)),
            (date(2026, 7, 25), "not_accepting", date(2026, 7, 25)),
        ],
    )
    assert f.status_changes == 1
    assert f.last_changed == date(2026, 7, 25)
    assert not f.volatile, "a single change is the system working, not volatility"


def test_repeated_flipping_is_volatile():
    obs = [
        (date(2026, 7, 21), "accepting", None),
        (date(2026, 7, 22), "not_accepting", None),
        (date(2026, 7, 23), "accepting", None),
    ]
    assert score_practice("V1", obs).volatile


def test_empty_observations_raise():
    with pytest.raises(ValueError, match="no observations"):
        score_practice("V1", [])


# -- C1 compliance ---------------------------------------------------------


def test_describe_never_asserts_current_fact():
    f = score_practice("V1", [(AS_OF, "accepting", date(2026, 5, 14))])
    text = f.describe()
    assert text.startswith("Reported ")
    assert "14 May 2026" in text
    assert "currently" not in text.lower()
    assert "is accepting" not in text.lower()


def test_describe_handles_never_confirmed():
    f = score_practice("V1", [(AS_OF, "not_confirmed", None)])
    text = f.describe()
    assert "never confirmed" in text
    assert "Reported" in text


# -- aggregation -----------------------------------------------------------


class Row:
    """Stands in for parse.PracticeDay."""

    def __init__(self, practice_id, snapshot_date, status, last_confirmed):
        self.practice_id = practice_id
        self.snapshot_date = snapshot_date
        self.status = status
        self.last_confirmed = last_confirmed


def test_score_all_groups_by_practice_and_accepts_iso_strings():
    rows = [
        Row("V1", "2026-07-24", "accepting", date(2026, 5, 1)),
        Row("V1", "2026-07-25", "not_accepting", date(2026, 7, 25)),
        Row("V2", "2026-07-25", "not_confirmed", None),
    ]
    scores = {s.practice_id: s for s in score_all(rows)}

    assert set(scores) == {"V1", "V2"}
    assert scores["V1"].observations == 2
    assert scores["V1"].status_changes == 1
    assert scores["V2"].never_confirmed


def test_summarise_reports_mandate_compliance():
    scores = [
        score_practice("V1", [(AS_OF, "accepting", date(2026, 7, 1))]),  # fresh
        score_practice("V2", [(AS_OF, "accepting", date(2026, 1, 1))]),  # stale
        score_practice("V3", [(AS_OF, "not_confirmed", None)]),  # never
        score_practice("V4", [(AS_OF, "not_accepting", date(2011, 1, 6))]),  # ancient
    ]
    stats = summarise(scores)

    assert stats["total"] == 4
    assert stats["meets_mandate"] == 1
    assert stats["mandate_compliance_rate"] == pytest.approx(0.25)
    assert stats["never_confirmed"] == 1
    assert stats["buckets"][ANCIENT] == 1
    assert stats["oldest_days_since_confirmed"] > 5_000


def test_summarise_handles_empty():
    assert summarise([])["total"] == 0
    assert format_summary({"total": 0}) == "No practices scored."


def test_format_summary_warns_when_volatility_not_yet_meaningful():
    scores = [score_practice("V1", [(AS_OF, "accepting", date(2026, 7, 1))])]
    text = format_summary(summarise(scores))
    assert "not yet meaningful" in text
    assert "90-day mandate" in text
