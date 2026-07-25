"""Tests for NHSBSA dental activity ingest (ledger 4.1)."""

from __future__ import annotations

import json

import pytest
from bsa import (
    ActivityRow,
    join_report,
    load_activity,
    parse_activity_csv,
    parse_resources,
    summarise,
)
from snapshot import Record, SnapshotWriter

HEADER = (
    "YEAR_MONTH,COMMISSIONER_CODE,COMMISSIONER_NAME,CONTRACT_NUMBER,PROVIDER_NAME,"
    "LATEST_PPC_ADDRESS_POSTCODE,LSOA11_CODE,UDA_PERF_TARGET,UDA_FIN_VAL,UDA_DELIVERED,"
    "LATE_SUBMITTED_FP17,UDA_DELIVERED_FD,BAND_1_DELIVERED,BAND_2A_DELIVERED,"
    "BAND_2B_DELIVERED,BAND_2C_DELIVERED,BAND_3_DELIVERED,BAND_URGENT_DELIVERED,"
    "BAND_OTHER_DELIVERED,CHILD_12M_COUNT,ADULT_24M_COUNT,GENERAL_DENTAL_FIN_VALUE"
)


def csv_row(contract="C001", postcode="GU29 9HH", uda="1000.5", ym="202603"):
    return (
        f"{ym},QYG,Cheshire,{contract},SMILE DENTAL,{postcode},E01000001,"
        f"1200,25000.00,{uda},0,0,300,100,50,25,40,60,0,120,450,25000"
    )


def make_csv(*rows: str) -> bytes:
    return ("\n".join([HEADER, *rows]) + "\n").encode("utf-8-sig")


def package(resources) -> bytes:
    return json.dumps({"success": True, "result": {"resources": resources}}).encode()


# -- resource discovery ----------------------------------------------------


def test_parse_resources_selects_monthly_contractor_csvs():
    payload = package(
        [
            {"name": "UDA_CONTRACTOR_201604", "format": "CSV", "url": "u1"},
            {"name": "UDA_CONTRACTOR_202603", "format": "CSV", "url": "u2"},
            {"name": "MONTHLY_DATA_UDA_20260715", "format": "CSV", "url": "u3"},
            {"name": "UDA_CONTRACTOR_202602", "format": "PDF", "url": "u4"},
        ]
    )
    resources = parse_resources(payload)

    assert [r.year_month for r in resources] == ["201604", "202603"]
    assert resources[0].url == "u1"


def test_parse_resources_dedupes_republished_months():
    payload = package(
        [
            {"name": "UDA_CONTRACTOR_202603", "format": "CSV", "url": "first"},
            {"name": "UDA_CONTRACTOR_202603", "format": "CSV", "url": "second"},
        ]
    )
    resources = parse_resources(payload)
    assert len(resources) == 1
    assert resources[0].url == "first"


def test_parse_resources_rejects_failed_payload():
    with pytest.raises(ValueError, match="did not succeed"):
        parse_resources(json.dumps({"success": False}).encode())


# -- CSV parsing -----------------------------------------------------------


def test_parse_activity_csv_extracts_fields():
    rows = parse_activity_csv(make_csv(csv_row()))
    assert len(rows) == 1
    r = rows[0]
    assert r.year_month == "202603"
    assert r.contract_number == "C001"
    assert r.postcode == "GU299HH", "postcode must be normalised for joining"
    assert r.uda_delivered == 1000.5
    assert r.uda_target == 1200
    assert r.lsoa11_code == "E01000001"
    assert r.child_patients_12m == 120
    assert r.adult_patients_24m == 450


def test_band_2_sums_its_three_subbands():
    """2A+2B+2C are published separately but are one clinical band."""
    assert parse_activity_csv(make_csv(csv_row()))[0].band_2 == 175


def test_rows_without_a_contract_number_are_dropped():
    rows = parse_activity_csv(make_csv(csv_row(contract=""), csv_row(contract="C002")))
    assert [r.contract_number for r in rows] == ["C002"]


def test_blank_and_malformed_numerics_become_none_not_zero():
    """A missing UDA figure is unknown, not zero delivery — conflating them
    would understate activity in the supply model."""
    bad = csv_row().replace(",1000.5,", ",,")
    assert parse_activity_csv(make_csv(bad))[0].uda_delivered is None

    worse = csv_row().replace(",1000.5,", ",n/a,")
    assert parse_activity_csv(make_csv(worse))[0].uda_delivered is None


def test_thousands_separators_are_handled():
    row = csv_row(uda='"12,345.5"')
    assert parse_activity_csv(make_csv(row))[0].uda_delivered == 12345.5


def test_empty_csv_yields_no_rows():
    assert parse_activity_csv(make_csv()) == []


def test_legacy_spaced_header_is_parsed():
    """Files published before 2023-04 put a space after each comma. Reading them
    naively drops every row — which silently cost seven years of history."""
    spaced_header = HEADER.replace(",", ", ")
    spaced_row = csv_row().replace(",", ", ")
    rows = parse_activity_csv((f"{spaced_header}\n{spaced_row}\n").encode("utf-8-sig"))

    assert len(rows) == 1
    assert rows[0].contract_number == "C001"
    assert rows[0].uda_delivered == 1000.5
    assert rows[0].postcode == "GU299HH"


def test_blank_lines_are_skipped():
    body = make_csv(csv_row()).decode() + "\n\n"
    assert len(parse_activity_csv(body.encode())) == 1


# -- store round trip ------------------------------------------------------


def write_pull(root, day, months: dict[str, bytes]):
    with SnapshotWriter(root=root, day=day, route="nhsbsa-ckan") as w:
        w.add(Record("_package", "u", "t", 200, package([]), meta={"months": len(months)}))
        for ym, body in months.items():
            w.add(Record(ym, f"u/{ym}", "t", 200, body, meta={"year_month": ym}))


def test_load_activity_skips_package_record(tmp_path):
    write_pull(
        tmp_path,
        "2026-07-25",
        {
            "202602": make_csv(csv_row(ym="202602")),
            "202603": make_csv(csv_row(ym="202603", contract="C002")),
        },
    )
    rows = load_activity(tmp_path, "2026-07-25")
    assert len(rows) == 2
    assert {r.year_month for r in rows} == {"202602", "202603"}


def test_load_activity_errors_when_absent(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_activity(tmp_path / "nothing")


# -- summary ---------------------------------------------------------------


def test_summarise_reports_coverage_and_totals():
    rows = [
        ActivityRow("201604", "C1", "A", "E11AA", "Q", "Q", "E01", 100, 90, 0, 0, 0, 0, 0, 1, 2),
        ActivityRow("202603", "C1", "A", "E11AA", "Q", "Q", "E01", 100, 110, 0, 0, 0, 0, 0, 1, 2),
        ActivityRow("202603", "C2", "B", "", "Q", "Q", "E01", 50, 40, 0, 0, 0, 0, 0, 1, 2),
    ]
    stats = summarise(rows)

    assert stats["rows"] == 3
    assert stats["months"] == 2
    assert stats["first_month"] == "201604"
    assert stats["last_month"] == "202603"
    assert stats["contracts"] == 2
    assert stats["with_postcode"] == 2
    assert stats["total_uda_delivered"] == 240
    assert stats["uda_by_year"] == {"2016": 90, "2026": 150}


# -- the join bridge to ODS (input to step 3.3) ----------------------------


def row(contract, postcode, ym="202603"):
    return ActivityRow(ym, contract, "P", postcode, "Q", "Q", "E01", 0, 0, 0, 0, 0, 0, 0, 0, 0)


def test_join_report_measures_postcode_bridge():
    rows = [
        row("C1", "E11AA"),
        row("C2", "E11AB"),
        row("C3", "ZZ99ZZ"),  # postcode not in ODS
        row("C4", ""),  # no postcode at all
    ]
    ods = {"E11AA": ["V001"], "E11AB": ["V002", "V003"]}
    report = join_report(rows, ods)

    assert report["contracts_in_latest_month"] == 4
    assert report["contracts_with_postcode"] == 3
    assert report["postcode_matched_to_ods"] == 2
    assert report["ambiguous_postcodes"] == 1, "E11AB holds two ODS practices"
    assert report["uniquely_resolved"] == 1
    assert report["postcode_match_rate"] == pytest.approx(2 / 3)


def test_join_report_uses_only_the_latest_month():
    """Contracts churn; measuring across all history would overstate the estate."""
    rows = [row("OLD", "E11AA", ym="201604"), row("NEW", "E11AA", ym="202603")]
    report = join_report(rows, {"E11AA": ["V001"]})

    assert report["latest_month"] == "202603"
    assert report["contracts_in_latest_month"] == 1
    assert report["postcode_matched_to_ods"] == 1


def test_join_report_handles_no_postcodes():
    assert join_report([row("C1", "")], {})["postcode_match_rate"] == 0.0
