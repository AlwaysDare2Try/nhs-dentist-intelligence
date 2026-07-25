"""Tests for postcode geocoding and geography resolution (ledger 3.2)."""

from __future__ import annotations

import json

import pytest
from geo import Geocoded, _norm, _row, load_geocoded, summarise
from snapshot import Record, SnapshotWriter


def api_result(postcode: str, country: str = "England", **over) -> dict:
    base = {
        "country": country,
        "region": "South East",
        "latitude": 50.98,
        "longitude": -0.74,
        "lsoa": "Chichester 004C",
        "lsoa21": "Chichester 004C",
        "msoa": "Chichester 004",
        "icb": "NHS Sussex Integrated Care Board",
        "nhs_region": "South East",
        "admin_district": "Chichester",
        "index_of_multiple_deprivation": 7,
        "codes": {
            "lsoa": "E01031511",
            "lsoa21": "E01031511",
            "msoa21": "E02006534",
            "icb": "E54000064",
        },
    }
    base.update(over)
    return {"query": postcode, "result": base}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("GU29 9HH", "GU299HH"), ("gu29 9hh", "GU299HH"), (" GU29  9HH ", "GU299HH")],
)
def test_postcode_normalisation(raw, expected):
    assert _norm(raw) == expected


def test_row_extracts_geography():
    row = _row("GU29 9HH", api_result("GU29 9HH")["result"])
    assert row.matched
    assert row.postcode == "GU299HH"
    assert row.in_england
    assert row.lsoa_code == "E01031511"
    assert row.icb_code == "E54000064"
    assert row.latitude == 50.98
    assert row.imd_decile == 7


def test_row_handles_no_match():
    """An unmatched postcode is recorded, not dropped — it needs a fallback."""
    row = _row("ZZ99 9ZZ", None)
    assert not row.matched
    assert not row.in_england
    assert row.latitude is None


def test_row_prefers_2021_lsoa_boundaries():
    result = api_result("GU29 9HH")["result"]
    result["codes"]["lsoa"] = "E01000000"
    result["codes"]["lsoa21"] = "E01031511"
    assert _row("GU29 9HH", result).lsoa_code == "E01031511"


def test_row_falls_back_when_lsoa21_absent():
    result = api_result("GU29 9HH")["result"]
    del result["codes"]["lsoa21"]
    del result["lsoa21"]
    assert _row("GU29 9HH", result).lsoa_code == "E01031511"


def test_non_england_is_not_in_england():
    row = _row("CF10 1EP", api_result("CF10 1EP", country="Wales")["result"])
    assert row.matched
    assert not row.in_england
    assert row.country == "Wales"


def write_pull(root, day, payloads):
    with SnapshotWriter(root=root, day=day, route="postcodes-io") as w:
        for i, payload in enumerate(payloads):
            w.add(
                Record(
                    practice_id=f"batch-{i:05d}",
                    url="https://api.postcodes.io/postcodes",
                    fetched_at="2026-07-25T00:00:00+00:00",
                    status=200,
                    body=json.dumps({"result": payload}).encode(),
                    content_type="application/json",
                )
            )


def test_load_geocoded_across_batches(tmp_path):
    write_pull(
        tmp_path,
        "2026-07-25",
        [
            [api_result("GU29 9HH"), api_result("CF10 1EP", country="Wales")],
            [{"query": "ZZ99 9ZZ", "result": None}],
        ],
    )
    rows = load_geocoded(tmp_path, "2026-07-25")

    assert set(rows) == {"GU299HH", "CF101EP", "ZZ999ZZ"}
    assert rows["GU299HH"].in_england
    assert not rows["ZZ999ZZ"].matched


def test_load_geocoded_errors_when_absent(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_geocoded(tmp_path / "nothing")


def test_summarise_reports_country_split_and_gaps():
    """The England filter is the point of this step — the split must be visible,
    since the register spans Wales and the Isle of Man too."""
    rows = {
        "A": Geocoded("A", True, country="England", lsoa_code="E01", icb_code="E54"),
        "B": Geocoded("B", True, country="England", lsoa_code="E02", icb_code="E54"),
        "C": Geocoded("C", True, country="Wales", lsoa_code="W01"),
        "D": Geocoded("D", False),
    }
    stats = summarise(rows)

    assert stats["total"] == 4
    assert stats["matched"] == 3
    assert stats["unmatched"] == 1
    assert stats["match_rate"] == pytest.approx(0.75)
    assert stats["countries"] == {"England": 2, "Wales": 1}
    assert stats["england"] == 2
    assert stats["england_with_lsoa"] == 2
    assert stats["england_with_icb"] == 2


def test_summarise_flags_england_rows_missing_lsoa():
    """An English practice without an LSOA cannot enter the demand model."""
    rows = {
        "A": Geocoded("A", True, country="England", lsoa_code="E01", icb_code="E54"),
        "B": Geocoded("B", True, country="England"),
    }
    stats = summarise(rows)
    assert stats["england"] == 2
    assert stats["england_with_lsoa"] == 1


def test_summarise_handles_empty():
    assert summarise({})["match_rate"] == 0.0
