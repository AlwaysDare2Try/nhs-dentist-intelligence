"""Tests for the LSOA population denominator (ledger 3.4)."""

from __future__ import annotations

import pytest
from pop import (
    AGE_0_15,
    AGE_16_17,
    AGE_ALL,
    LsoaPopulation,
    _assemble,
    _parse_csv,
    check_plausible,
    coverage,
    load_population,
    page_url,
    summarise,
)
from snapshot import Record, SnapshotWriter

HEADER = '"DATE","GEOGRAPHY_CODE","GEOGRAPHY_NAME","C_AGE","OBS_VALUE","RECORD_COUNT"'


def csv_page(rows: list[tuple[str, str, str, int]], record_count: int = 9) -> bytes:
    """Synthetic Nomis CSV: (lsoa_code, lsoa_name, age_code, value)."""
    lines = [HEADER]
    for code, name, age, value in rows:
        lines.append(f'"2024","{code}","{name}","{age}",{value},{record_count}')
    return ("\n".join(lines) + "\n").encode()


def lsoa_rows(code: str, name: str, total: int, u16: int, age16_17: int) -> list[tuple]:
    return [
        (code, name, AGE_ALL, total),
        (code, name, AGE_0_15, u16),
        (code, name, AGE_16_17, age16_17),
    ]


def write_pull(root, day, pages: list[bytes]) -> None:
    with SnapshotWriter(root=root, day=day, route="nomis-nm2014") as w:
        for i, body in enumerate(pages):
            w.add(
                Record(
                    practice_id=f"page-{i:08d}",
                    url=page_url(i * 25_000),
                    fetched_at="2026-07-25T00:00:00+00:00",
                    status=200,
                    body=body,
                    content_type="text/csv",
                    meta={"offset": i * 25_000},
                )
            )


# -- request shape ---------------------------------------------------------


def test_page_url_pins_the_query():
    """A typo here returns HTTP 200 with an empty body, not an error, so the
    exact parameter set is worth pinning."""
    url = page_url(25_000)
    assert url.startswith("https://www.nomisweb.co.uk/api/v01/dataset/NM_2014_1.data.csv?")
    assert "geography=TYPE151" in url  # 2021 LSOA boundaries, matching lsoa21
    assert "c_age=200,201,204" in url
    assert "gender=0" in url  # both sexes
    assert "measures=20100" in url  # value, not confidence interval
    assert "RecordOffset=25000" in url


def test_parse_csv_reads_rows_and_record_count():
    rows, count = _parse_csv(csv_page(lsoa_rows("E01000001", "City of London 001A", 2172, 147, 18)))
    assert count == 9
    assert len(rows) == 3
    assert rows[0]["GEOGRAPHY_CODE"] == "E01000001"
    assert rows[0]["OBS_VALUE"] == "2172"


def test_parse_csv_handles_header_only_page():
    rows, count = _parse_csv((HEADER + "\n").encode())
    assert rows == []
    assert count is None


# -- the age split ---------------------------------------------------------


def test_assemble_splits_children_and_adults_exactly():
    """0-17 is 'Aged 0 to 15' + 'Aged 16 to 17'; 18+ is the remainder."""
    counts = {
        "E01000001": {
            "name": "City of London 001A",
            "year": "2024",
            "ages": {AGE_ALL: 2172, AGE_0_15: 147, AGE_16_17: 18},
        }
    }
    row = _assemble(counts)["E01000001"]
    assert row.total == 2172
    assert row.children == 165
    assert row.adults == 2007
    assert row.children + row.adults == row.total
    assert row.child_share == pytest.approx(165 / 2172)


def test_assemble_drops_lsoa_missing_an_age_band():
    """A partial band would silently understate children — drop it instead."""
    counts = {
        "E01000002": {"name": "x", "year": "2024", "ages": {AGE_ALL: 1000, AGE_0_15: 200}},
    }
    assert _assemble(counts) == {}


def test_assemble_drops_irreconcilable_bands():
    """children > total would publish a negative adult denominator."""
    counts = {
        "E01000003": {
            "name": "x",
            "year": "2024",
            "ages": {AGE_ALL: 100, AGE_0_15: 90, AGE_16_17: 30},
        },
    }
    assert _assemble(counts) == {}


def test_assemble_allows_a_genuinely_empty_lsoa():
    counts = {
        "E01000004": {"name": "x", "year": "2024", "ages": {AGE_ALL: 0, AGE_0_15: 0, AGE_16_17: 0}},
    }
    row = _assemble(counts)["E01000004"]
    assert row.total == 0
    assert row.child_share == 0.0


# -- loading from the store ------------------------------------------------


def test_load_population_across_pages(tmp_path):
    """Paging is offset-based, so a row's three age codes can straddle pages."""
    page_a = csv_page(
        lsoa_rows("E01000001", "City of London 001A", 2172, 147, 18)
        + [("E01000002", "Barking 001A", AGE_ALL, 1500)]
    )
    page_b = csv_page(
        [
            ("E01000002", "Barking 001A", AGE_0_15, 400),
            ("E01000002", "Barking 001A", AGE_16_17, 50),
        ]
    )
    write_pull(tmp_path, "2026-07-25", [page_a, page_b])

    rows = load_population(tmp_path, "2026-07-25")
    assert set(rows) == {"E01000001", "E01000002"}
    assert rows["E01000002"].children == 450
    assert rows["E01000002"].adults == 1050
    assert rows["E01000002"].lsoa_name == "Barking 001A"
    assert rows["E01000002"].year == "2024"


def test_load_population_filters_wales_by_default(tmp_path):
    """The endpoint has no England-only geography, so Wales arrives with it."""
    body = csv_page(
        lsoa_rows("E01000001", "City of London 001A", 2172, 147, 18)
        + lsoa_rows("W01000001", "Isle of Anglesey 001A", 1600, 300, 40)
    )
    write_pull(tmp_path, "2026-07-25", [body])

    assert set(load_population(tmp_path, "2026-07-25")) == {"E01000001"}
    both = load_population(tmp_path, "2026-07-25", england_only=False)
    assert set(both) == {"E01000001", "W01000001"}
    assert not both["W01000001"].in_england


def test_load_population_ignores_unrequested_age_codes(tmp_path):
    """Single-year-of-age rows must never be added on top of the aggregates —
    that is exactly how a denominator gets double-counted."""
    body = csv_page(
        lsoa_rows("E01000001", "City of London 001A", 2172, 147, 18)
        + [("E01000001", "City of London 001A", "101", 30)]  # Age 0
    )
    write_pull(tmp_path, "2026-07-25", [body])
    assert load_population(tmp_path, "2026-07-25")["E01000001"].total == 2172


def test_load_population_errors_when_absent(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_population(tmp_path / "nothing")


# -- summary, guardrails and the join --------------------------------------


def row(code: str, total: int, children: int) -> LsoaPopulation:
    return LsoaPopulation(code, code, "2024", total, children, total - children)


def test_summarise_reports_totals_and_split():
    rows = {
        "E01000001": row("E01000001", 2000, 400),
        "E01000002": row("E01000002", 1000, 100),
        "W01000001": row("W01000001", 500, 50),
    }
    stats = summarise(rows)

    assert stats["lsoas"] == 3
    assert stats["england_lsoas"] == 2
    assert stats["other_lsoas"] == 1
    assert stats["total_population"] == 3500
    assert stats["england_population"] == 3000
    assert stats["england_children"] == 500
    assert stats["england_adults"] == 2500
    assert stats["child_share"] == pytest.approx(550 / 3500)
    assert stats["years"] == ["2024"]


def test_summarise_handles_empty():
    stats = summarise({})
    assert stats["lsoas"] == 0
    assert stats["child_share"] == 0.0


def test_check_plausible_accepts_a_real_shaped_pull():
    stats = summarise({f"E01{i:06d}": row(f"E01{i:06d}", 1_740, 350) for i in range(33_755)})
    assert check_plausible(stats) == []


def test_check_plausible_rejects_a_truncated_pull():
    stats = summarise({f"E01{i:06d}": row(f"E01{i:06d}", 1_740, 350) for i in range(500)})
    problems = check_plausible(stats)
    assert problems
    assert "LSOAs" in problems[0]


def test_check_plausible_rejects_double_counted_population():
    """Summing overlapping age bands would roughly double England's population."""
    stats = summarise({f"E01{i:06d}": row(f"E01{i:06d}", 3_500, 700) for i in range(33_755)})
    assert any("plausible range" in p for p in check_plausible(stats))


def test_coverage_reports_the_join_rate():
    rows = {"E01000001": row("E01000001", 100, 10), "E01000002": row("E01000002", 100, 10)}
    stats = coverage(rows, {"E01000001", "E01000002", "E01999999", ""})

    assert stats["practice_lsoas"] == 3  # the empty string is not an LSOA
    assert stats["matched"] == 2
    assert stats["missing"] == 1
    assert stats["match_rate"] == pytest.approx(2 / 3)
    assert stats["missing_sample"] == ["E01999999"]


def test_coverage_handles_no_practice_lsoas():
    assert coverage({}, set())["match_rate"] == 0.0
