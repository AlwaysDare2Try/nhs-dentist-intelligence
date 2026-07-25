"""Tests for the snapshot parser (ledger 2.3).

Fixtures are trimmed from real captured nhs.uk payloads, so the markup shapes
here are the ones actually in the store.
"""

from __future__ import annotations

import pytest
from parse import (
    ACCEPTING,
    NOT_ACCEPTING,
    NOT_CONFIRMED,
    REFERRAL_ONLY,
    UNRECOGNISED,
    parse_day,
    parse_last_confirmed,
    parse_practice,
    routine_care_region,
)
from snapshot import Record, SnapshotWriter

URGENT_SECTION = """
<h2>Urgent or emergency dental care</h2>
<p>Contact the practice for:</p>
<ul>
  <li>an urgent appointment at short notice</li>
  <li>advice where to get out-of-hours treatment</li>
</ul>
"""


def page(routine_body: str, *, urgent: bool = True) -> str:
    return f"""<html><body>
<h1>Appointments</h1>
<h2 id="routine-care-header">Routine dental care</h2>
{routine_body}
{URGENT_SECTION if urgent else ""}
</body></html>"""


ACCEPTING_ALL = page("""
<p>This dentist currently accepts new NHS patients for routine dental care if they are:</p>
<ul>
  <li>adults aged 18 or over</li>
  <li>adults entitled to free routine dental care</li>
  <li>children aged 17 or under</li>
</ul>
<p id="dentist-accepting-patients-last-updated" class="nhsuk-review-date">Last confirmed: 14 May 2026</p>
""")

ACCEPTING_CHILDREN_ONLY = page("""
<p>This dentist currently only accepts new NHS patients for routine dental care if they are
children aged 17 or under.</p>
<p id="dentist-accepting-patients-last-updated">Last confirmed: 27 May 2026</p>
""")

NOT_ACCEPTING_PAGE = page("""
<p>This dentist does not currently accept new NHS patients for routine dental care.</p>
<p id="dentist-accepting-patients-last-updated">Last confirmed: 24 June 2026</p>
""")

NOT_CONFIRMED_PAGE = page("""
<p>This dentist has not confirmed if they currently accept new NHS patients for routine dental care.</p>
""")

REFERRAL_ONLY_PAGE = """<html><body>
<h2>Specialist dental care</h2>
<p>This dentist does not accept new NHS patients for routine dental care.</p>
<p>This dentist only accepts new NHS patients for specialist dental care by clinical
referral from another dentist.</p>
</body></html>"""


def parse(html: str, pid: str = "V1"):
    return parse_practice(pid, "2026-07-25", html)


def test_accepting_all_cohorts():
    row = parse(ACCEPTING_ALL)
    assert row.status == ACCEPTING
    assert (row.accepting_adults, row.accepting_children, row.accepting_free_care) == (True, True, True)
    assert row.last_confirmed.isoformat() == "2026-05-14"


def test_accepting_children_only_inline_cohort():
    """The single-cohort wording states the cohort inline, with no bullet list."""
    row = parse(ACCEPTING_CHILDREN_ONLY)
    assert row.status == ACCEPTING
    assert row.accepting_children is True
    assert row.accepting_adults is False
    assert row.accepting_free_care is False


def test_not_accepting_still_carries_a_date():
    row = parse(NOT_ACCEPTING_PAGE)
    assert row.status == NOT_ACCEPTING
    assert row.accepting_adults is False
    assert row.last_confirmed.isoformat() == "2026-06-24"


def test_not_confirmed_has_no_date_and_no_cohort_claims():
    """Absence of the date element is a finding, not missing data — the cohort
    flags must stay None rather than defaulting to False."""
    row = parse(NOT_CONFIRMED_PAGE)
    assert row.status == NOT_CONFIRMED
    assert row.last_confirmed is None
    assert row.accepting_adults is None
    assert row.accepting_children is None


def test_referral_only_specialist():
    row = parse(REFERRAL_ONLY_PAGE)
    assert row.status == REFERRAL_ONLY
    assert row.referral_only is True
    assert row.accepting_adults is False


def test_urgent_care_bullets_never_leak_into_cohorts():
    """The urgent-care section lists bullets on every page in England. Reading
    list items document-wide would mark the whole estate as accepting."""
    row = parse(NOT_ACCEPTING_PAGE)
    assert row.accepting_adults is False
    assert "urgent appointment" not in row.statement.lower()

    region = routine_care_region(NOT_ACCEPTING_PAGE)
    assert "out-of-hours" not in region


def test_routine_region_falls_back_when_anchor_absent():
    assert routine_care_region(REFERRAL_ONLY_PAGE) == REFERRAL_ONLY_PAGE


def test_unrecognised_markup_is_flagged_not_guessed():
    row = parse(page("<p>Something entirely new happened here.</p>"))
    assert row.status == UNRECOGNISED
    assert not row.recognised
    assert row.parse_note


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Last confirmed: 1 January 2026", "2026-01-01"),
        ("Last confirmed: 24 July 2026", "2026-07-24"),
        ("Last confirmed: 6 Jan 2011", "2011-01-06"),
    ],
)
def test_date_formats(raw, expected):
    html = f'<p id="dentist-accepting-patients-last-updated">{raw}</p>'
    parsed, _ = parse_last_confirmed(html)
    assert parsed.isoformat() == expected


def test_unparseable_date_is_retained_raw():
    """Keep the raw string so a format we have not seen is visible rather than lost."""
    html = '<p id="dentist-accepting-patients-last-updated">Last confirmed: sometime</p>'
    parsed, raw = parse_last_confirmed(html)
    assert parsed is None
    assert raw == "sometime"


def test_parse_day_reads_the_store_and_skips_sitemap(tmp_path):
    pages = {
        "V001": ACCEPTING_ALL,
        "V002": NOT_ACCEPTING_PAGE,
        "V003": NOT_CONFIRMED_PAGE,
        "V004": REFERRAL_ONLY_PAGE,
    }
    with SnapshotWriter(root=tmp_path, day="2026-07-25", route="nhsuk-html") as w:
        w.add(Record("_sitemap", "u", "t", 200, b"<urlset/>", meta={"page": "sitemap"}))
        for pid, html in pages.items():
            w.add(Record(pid, f"u/{pid}", "t", 200, html.encode(), meta={"page": "appointments"}))

    rows, report = parse_day(tmp_path, "2026-07-25")

    assert report.total == 4, "sitemap record must not become a practice row"
    assert report.recognised == 4
    assert report.with_date == 2
    assert report.by_status == {
        ACCEPTING: 1,
        NOT_ACCEPTING: 1,
        NOT_CONFIRMED: 1,
        REFERRAL_ONLY: 1,
    }
    assert {r.practice_id for r in rows} == set(pages)


def test_report_flags_markup_change(tmp_path):
    """If nhs.uk changes its markup, the recognised share collapses — that must
    be visible rather than emitting a table of nulls."""
    with SnapshotWriter(root=tmp_path, day="2026-07-25") as w:
        for i in range(10):
            html = ACCEPTING_ALL if i < 3 else page("<p>Totally new wording.</p>")
            w.add(Record(f"V{i}", "u", "t", 200, html.encode(), meta={"page": "appointments"}))

    _, report = parse_day(tmp_path, "2026-07-25")
    assert report.recognised_share == pytest.approx(0.3)
    assert report.recognised_share < 0.90
