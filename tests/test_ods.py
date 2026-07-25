"""Tests for the ODS register loader (ledger 3.1)."""

from __future__ import annotations

import json

import pytest
from ods import OdsPractice, coverage, load_register, nhsuk_id
from snapshot import Record, SnapshotWriter


@pytest.mark.parametrize(
    ("ods", "expected"),
    [
        ("V01699", "V001699"),  # the case that 404s everything if got wrong
        ("V00004", "V000004"),
        ("V123456", "V123456"),  # already six digits
        ("v00004", "V000004"),  # case is normalised
        (" V00004 ", "V000004"),
    ],
)
def test_nhsuk_id_padding(ods, expected):
    assert nhsuk_id(ods) == expected


def test_nhsuk_id_passes_through_unexpected_shapes():
    """An id we do not understand must not be silently mangled into a wrong one."""
    assert nhsuk_id("ABC-123") == "ABC-123"
    assert nhsuk_id("") == ""


def org(org_id: str, name: str = "DENTAL SURGERY", postcode: str = "GU29 9HH") -> dict:
    return {
        "Name": name,
        "OrgId": org_id,
        "Status": "Active",
        "OrgRecordClass": "RC1",
        "PostCode": postcode,
        "LastChangeDate": "2026-04-01",
        "PrimaryRoleId": "RO110",
    }


def write_pull(root, day: str, pages: list[list[dict]]) -> None:
    with SnapshotWriter(root=root, day=day, route="ods-ord") as w:
        for i, page in enumerate(pages):
            w.add(
                Record(
                    practice_id=f"page-{i:06d}",
                    url=f"https://ord.test/?Offset={i}",
                    fetched_at="2026-07-25T00:00:00+00:00",
                    status=200,
                    body=json.dumps({"Organisations": page}).encode(),
                    content_type="application/json",
                )
            )


def test_load_register_across_pages(tmp_path):
    write_pull(tmp_path, "2026-07-25", [[org("V00001"), org("V00002")], [org("V00003")]])
    practices = load_register(tmp_path, "2026-07-25")

    assert [p.org_id for p in practices] == ["V00001", "V00002", "V00003"]
    assert practices[0].nhsuk_id == "V000001"
    assert practices[0].postcode == "GU29 9HH"
    assert practices[0].last_change_date == "2026-04-01"


def test_load_register_deduplicates_overlapping_pages(tmp_path):
    """Paging is offset-based; an overlap must not double-count the estate."""
    write_pull(tmp_path, "2026-07-25", [[org("V00001"), org("V00002")], [org("V00002"), org("V00003")]])
    assert len({p.org_id for p in load_register(tmp_path, "2026-07-25")}) == 3


def test_load_register_skips_blank_ids(tmp_path):
    write_pull(tmp_path, "2026-07-25", [[org("V00001"), org("")]])
    assert len(load_register(tmp_path, "2026-07-25")) == 1


def test_load_register_uses_latest_pull_by_default(tmp_path):
    write_pull(tmp_path, "2026-06-01", [[org("V00001")]])
    write_pull(tmp_path, "2026-07-25", [[org("V00001"), org("V00002")]])
    assert len(load_register(tmp_path)) == 2


def test_load_register_errors_when_absent(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_register(tmp_path / "nothing")


def test_coverage_reports_both_directions():
    """Neither source is a subset of the other, and the report must say so
    rather than quoting a single flattering number (C8)."""
    practices = [
        OdsPractice("V00001", "A", "E1 1AA", "Active", "2026-01-01", "RC1", "V000001"),
        OdsPractice("V00002", "B", "E1 1AB", "Active", "2026-01-01", "RC1", "V000002"),
        OdsPractice("V00003", "Prison unit", "E1 1AC", "Active", "2026-01-01", "RC1", "V000003"),
    ]
    stats = coverage(practices, {"V000001", "V000002", "V000009"})

    assert stats["ods_active"] == 3
    assert stats["nhsuk_published"] == 3
    assert stats["matched"] == 2
    assert stats["nhsuk_without_ods"] == 1  # V000009 published but not in register
    assert stats["ods_without_nhsuk"] == 1  # the prison unit has no public profile
    assert stats["nhsuk_match_rate"] == pytest.approx(2 / 3)


def test_coverage_handles_empty_input():
    assert coverage([], set())["nhsuk_match_rate"] == 0.0
