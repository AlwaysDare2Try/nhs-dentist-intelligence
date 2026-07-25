"""NHSBSA dental activity — what practices actually delivered (ledger step 4.1).

The plan's escape hatch. Our own availability history is one night deep, but
NHSBSA publishes, at **individual contract level and monthly**, what every NHS
dental contract in England actually delivered — UDAs, treatment bands, and
patients seen — back to April 2016. That is a decade of longitudinal truth
available immediately, and it records what practices *did* rather than what they
*claim*. It is the supply side of the 4.2 model.

Source
------
NHSBSA Open Data Portal (CKAN), dataset ``english-contractor-monthly-general-dental-activity``,
Open Government Licence 3.0. One CSV per month, ~1 MB each.

Two schema facts that shape everything downstream
-------------------------------------------------
**1. The key is ``CONTRACT_NUMBER``, not an ODS code.** There is no free join to
nhs.uk or ODS. This is precisely the "hidden engineering cost" the viability
analysis flagged, and it is why entity resolution (3.3) is the highest schedule
risk in the plan. What this file *does* provide is ``LATEST_PPC_ADDRESS_POSTCODE``,
which is a strong bridge: postcode-blocked matching is exactly how 3.3 is meant
to generate candidates. ``join_report()`` measures how far that bridge reaches,
so 3.3 starts from a number rather than a hope.

**2. ``LSOA11_CODE`` is on 2011 boundaries.** Our geocoding (3.2) deliberately
emits 2021 LSOAs. These are *not* interchangeable — boundaries were redrawn.
This module therefore keeps the published LSOA11 as-is and does not pretend it
is LSOA21; the demand model should join on postcode via ``geo.py`` instead, and
treat ``lsoa11_code`` as provenance only.

Contracts are many-to-many with sites: one contract can cover several practices,
and a practice can hold more than one contract. Nothing here flattens that.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import io
import json
import re
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

from client import PoliteClient
from snapshot import Record, SnapshotWriter, iter_payloads, latest_day, utc_today

CKAN_PACKAGE = (
    "https://opendata.nhsbsa.net/api/3/action/package_show"
    "?id=english-contractor-monthly-general-dental-activity"
)
# Monthly contractor files are named UDA_CONTRACTOR_YYYYMM. The dataset also
# carries differently-shaped MONTHLY_DATA_* extracts, which we ignore.
_RESOURCE_NAME = re.compile(r"^UDA_CONTRACTOR_(\d{6})$", re.IGNORECASE)

BSA_RATE = 2.0
DEFAULT_STORE = Path(__file__).resolve().parent.parent / "data" / "reference" / "bsa"

# The series starts 2016-04. Far fewer months than that means the portal changed.
MIN_EXPECTED_MONTHS = 60


@dataclass(frozen=True, slots=True)
class Resource:
    year_month: str
    url: str
    name: str


@dataclass(slots=True)
class ActivityRow:
    """One contract's delivery in one month."""

    year_month: str
    contract_number: str
    provider_name: str
    postcode: str
    commissioner_code: str
    commissioner_name: str
    lsoa11_code: str
    uda_target: float | None
    uda_delivered: float | None
    uda_financial_value: float | None
    band_1: float | None
    band_2: float | None
    band_3: float | None
    band_urgent: float | None
    child_patients_12m: int | None
    adult_patients_24m: int | None


def _num(value: str) -> float | None:
    value = (value or "").strip().replace(",", "")
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _int(value: str) -> int | None:
    parsed = _num(value)
    return int(parsed) if parsed is not None else None


def _norm_postcode(value: str) -> str:
    return "".join((value or "").split()).upper()


def parse_resources(payload: bytes) -> list[Resource]:
    """Pick the monthly contractor CSVs out of the CKAN package record."""
    data = json.loads(payload)
    if not data.get("success"):
        raise ValueError("CKAN package_show did not succeed")

    found: dict[str, Resource] = {}
    for res in data["result"].get("resources", []):
        match = _RESOURCE_NAME.match((res.get("name") or "").strip())
        if not match or (res.get("format") or "").upper() != "CSV":
            continue
        ym = match.group(1)
        # Guard against duplicate publications of the same month.
        found.setdefault(ym, Resource(year_month=ym, url=res["url"], name=res["name"]))
    return [found[k] for k in sorted(found)]


def parse_activity_csv(payload: bytes, year_month: str = "") -> list[ActivityRow]:
    """Parse one monthly contractor CSV."""
    text = payload.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    # Files published before 2023-04 put a space after each comma, so the raw
    # field names arrive as " CONTRACT_NUMBER". Normalising the header is what
    # keeps seven years of history from being silently dropped.
    header = [h.strip().upper() for h in next(reader, [])]
    if not header:
        return []

    rows: list[ActivityRow] = []
    for values in reader:
        if not values:
            continue
        rec = {k: (v or "").strip() for k, v in zip(header, values, strict=False)}
        contract = (rec.get("CONTRACT_NUMBER") or "").strip()
        if not contract:
            continue
        rows.append(
            ActivityRow(
                year_month=(rec.get("YEAR_MONTH") or year_month).strip(),
                contract_number=contract,
                provider_name=(rec.get("PROVIDER_NAME") or "").strip(),
                postcode=_norm_postcode(rec.get("LATEST_PPC_ADDRESS_POSTCODE", "")),
                commissioner_code=(rec.get("COMMISSIONER_CODE") or "").strip(),
                commissioner_name=(rec.get("COMMISSIONER_NAME") or "").strip(),
                lsoa11_code=(rec.get("LSOA11_CODE") or "").strip(),
                uda_target=_num(rec.get("UDA_PERF_TARGET", "")),
                uda_delivered=_num(rec.get("UDA_DELIVERED", "")),
                uda_financial_value=_num(rec.get("UDA_FIN_VAL", "")),
                band_1=_num(rec.get("BAND_1_DELIVERED", "")),
                band_2=sum(
                    v
                    for k in ("BAND_2A_DELIVERED", "BAND_2B_DELIVERED", "BAND_2C_DELIVERED")
                    if (v := _num(rec.get(k, ""))) is not None
                )
                or None,
                band_3=_num(rec.get("BAND_3_DELIVERED", "")),
                band_urgent=_num(rec.get("BAND_URGENT_DELIVERED", "")),
                child_patients_12m=_int(rec.get("CHILD_12M_COUNT", "")),
                adult_patients_24m=_int(rec.get("ADULT_24M_COUNT", "")),
            )
        )
    return rows


async def fetch_activity(
    *,
    store: Path | str = DEFAULT_STORE,
    day: str | None = None,
    rate: float = BSA_RATE,
    months: int | None = None,
) -> int:
    """Download every monthly contractor CSV, storing each raw. Returns exit code."""
    day = day or utc_today()

    async with PoliteClient(rate_per_sec=rate, concurrency=2) as client:
        listing = await client.get(CKAN_PACKAGE)
        if not listing.ok:
            print(f"FATAL: CKAN listing failed ({listing.status})", file=sys.stderr)
            return 1

        resources = parse_resources(listing.body)
        print(f"Dataset lists {len(resources)} monthly files "
              f"({resources[0].year_month} → {resources[-1].year_month})", flush=True)

        if len(resources) < MIN_EXPECTED_MONTHS and months is None:
            print(
                f"FATAL: only {len(resources)} months listed "
                f"(expected at least {MIN_EXPECTED_MONTHS}).",
                file=sys.stderr,
            )
            return 1

        if months:
            resources = resources[-months:]
            print(f"Limited to the most recent {len(resources)} months", flush=True)

        with SnapshotWriter(root=store, day=day, route="nhsbsa-ckan", resume=True) as writer:
            writer.add(
                Record(
                    practice_id="_package",
                    url=CKAN_PACKAGE,
                    fetched_at=listing.fetched_at,
                    status=listing.status,
                    body=listing.body,
                    content_type=listing.content_type,
                    meta={"months": len(resources)},
                )
            )

            todo = [r for r in resources if r.year_month not in writer.already_captured]
            if writer.already_captured:
                print(f"Resuming: {len(todo)} of {len(resources)} months remaining", flush=True)

            for i, res in enumerate(todo, 1):
                result = await client.get(res.url)
                writer.add(
                    Record(
                        practice_id=res.year_month,
                        url=res.url,
                        fetched_at=result.fetched_at,
                        status=result.status,
                        body=result.body,
                        content_type=result.content_type,
                        error=result.error,
                        meta={"year_month": res.year_month, "name": res.name},
                    )
                )
                if i % 20 == 0 or i == len(todo):
                    print(f"  {i}/{len(todo)} months "
                          f"(ok {writer.written}, failed {writer.failed})", flush=True)

            print(f"\nCaptured {writer.written} files, {writer.bytes_new / 1e6:.1f} MB new",
                  flush=True)
    return 0


def load_activity(store: Path | str = DEFAULT_STORE, day: str | None = None) -> list[ActivityRow]:
    store = Path(store)
    day = day or latest_day(store)
    if not day:
        raise FileNotFoundError(f"no BSA pull found under {store}")

    rows: list[ActivityRow] = []
    for entry, body in iter_payloads(store, day):
        if entry["practice_id"] == "_package":
            continue
        rows.extend(parse_activity_csv(body, (entry.get("meta") or {}).get("year_month", "")))
    return rows


def summarise(rows: list[ActivityRow]) -> dict:
    months = sorted({r.year_month for r in rows if r.year_month})
    contracts = {r.contract_number for r in rows}
    total_uda = sum(r.uda_delivered or 0 for r in rows)

    by_year: dict[str, float] = defaultdict(float)
    for r in rows:
        if r.year_month and r.uda_delivered:
            by_year[r.year_month[:4]] += r.uda_delivered

    return {
        "rows": len(rows),
        "months": len(months),
        "first_month": months[0] if months else None,
        "last_month": months[-1] if months else None,
        "contracts": len(contracts),
        "with_postcode": sum(1 for r in rows if r.postcode),
        "total_uda_delivered": total_uda,
        "uda_by_year": dict(sorted(by_year.items())),
    }


def join_report(rows: list[ActivityRow], ods_postcodes: dict[str, list[str]]) -> dict:
    """How far the postcode bridge reaches from BSA contracts to ODS practices.

    This is the input to step 3.3, not a substitute for it. It answers "how many
    contracts can even be blocked against an ODS candidate", which bounds what
    entity resolution can achieve before any name matching is attempted.
    """
    latest = max((r.year_month for r in rows if r.year_month), default="")
    current = [r for r in rows if r.year_month == latest]

    by_contract: dict[str, str] = {}
    for r in current:
        if r.postcode:
            by_contract.setdefault(r.contract_number, r.postcode)

    matched = {c: pc for c, pc in by_contract.items() if pc in ods_postcodes}
    # Many-to-many is the expected shape, not an error — record how bad it is.
    ambiguous = sum(1 for pc in matched.values() if len(ods_postcodes[pc]) > 1)

    return {
        "latest_month": latest,
        "contracts_in_latest_month": len({r.contract_number for r in current}),
        "contracts_with_postcode": len(by_contract),
        "postcode_matched_to_ods": len(matched),
        "postcode_match_rate": len(matched) / len(by_contract) if by_contract else 0.0,
        "ambiguous_postcodes": ambiguous,
        "uniquely_resolved": len(matched) - ambiguous,
    }


def write_parquet(rows: list[ActivityRow], out_path: Path | str) -> Path:
    import polars as pl

    # Declared explicitly rather than inferred: schema inference samples the
    # first N rows, and a column that is empty early but numeric later (common
    # across a decade of changing returns) makes the write fail outright.
    schema = {
        "year_month": pl.Utf8,
        "contract_number": pl.Utf8,
        "provider_name": pl.Utf8,
        "postcode": pl.Utf8,
        "commissioner_code": pl.Utf8,
        "commissioner_name": pl.Utf8,
        "lsoa11_code": pl.Utf8,
        "uda_target": pl.Float64,
        "uda_delivered": pl.Float64,
        "uda_financial_value": pl.Float64,
        "band_1": pl.Float64,
        "band_2": pl.Float64,
        "band_3": pl.Float64,
        "band_urgent": pl.Float64,
        "child_patients_12m": pl.Int64,
        "adult_patients_24m": pl.Int64,
    }
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame([asdict(r) for r in rows], schema=schema).write_parquet(
        out_path, compression="zstd"
    )
    return out_path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Ingest NHSBSA dental activity history.")
    ap.add_argument("--store", default=str(DEFAULT_STORE))
    ap.add_argument("--day", default=None)
    ap.add_argument("--out", default="data/dist/bsa_activity.parquet")
    ap.add_argument("--months", type=int, default=None, help="only the most recent N months")
    ap.add_argument("--skip-fetch", action="store_true")
    args = ap.parse_args(argv)

    if not args.skip_fetch:
        code = asyncio.run(
            fetch_activity(store=args.store, day=args.day, months=args.months)
        )
        if code:
            return code

    rows = load_activity(args.store, args.day)
    stats = summarise(rows)

    print(f"\n{stats['rows']:,} contract-months across {stats['months']} months "
          f"({stats['first_month']} → {stats['last_month']})")
    print(f"  distinct contracts: {stats['contracts']:,}")
    print(f"  rows with a postcode: {stats['with_postcode']:,}")
    print(f"  total UDAs delivered: {stats['total_uda_delivered']:,.0f}")
    print("\n  UDAs delivered by year:")
    for year, uda in stats["uda_by_year"].items():
        print(f"    {year}  {uda:>14,.0f}")

    try:
        from ods import load_register

        ods_postcodes: dict[str, list[str]] = defaultdict(list)
        for p in load_register():
            if p.postcode:
                ods_postcodes[_norm_postcode(p.postcode)].append(p.org_id)
        report = join_report(rows, ods_postcodes)
        print(f"\n  Join bridge to ODS (latest month {report['latest_month']}):")
        print(f"    contracts: {report['contracts_in_latest_month']:,}")
        print(f"    with a postcode: {report['contracts_with_postcode']:,}")
        print(f"    postcode found in ODS: {report['postcode_matched_to_ods']:,} "
              f"({report['postcode_match_rate']:.1%})")
        print(f"    of those, ambiguous (postcode has >1 ODS practice): "
              f"{report['ambiguous_postcodes']:,}")
        print(f"    uniquely resolved by postcode alone: {report['uniquely_resolved']:,}")
    except FileNotFoundError:
        print("\n  (ODS register not loaded — skipping join report)")

    out = write_parquet(rows, args.out)
    print(f"\nWrote {len(rows):,} rows to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
