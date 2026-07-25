"""Geocode practice postcodes and resolve their geography (ledger step 3.2).

Unlocks every spatial feature: lat/long for maps and distance ranking, LSOA for
the demand denominator, ICB and region for aggregation — and **country**, which
is the authoritative England filter that step 3.1 deliberately left undone.

Deviation from the ledger, recorded deliberately
------------------------------------------------
The plan specifies the ONSPD quarterly CSV. This uses the postcodes.io bulk API
instead, which serves the same ONS data (ONSPD-derived, OGL) and returns every
field the plan asked for plus ICB and IMD, in 98 requests rather than a ~1 GB
quarterly download. Results are stored raw in the append-only store, so the
pipeline is reproducible without re-fetching and the CSV route remains open if
the service ever proves unreliable. Crude and working now beats designed and
later — but the upgrade path is deliberately preserved.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from client import PoliteClient
from snapshot import Record, SnapshotWriter, iter_payloads, latest_day, utc_today

POSTCODES_API = "https://api.postcodes.io/postcodes"
BATCH_SIZE = 100  # the API's documented maximum per bulk request
GEO_RATE = 3.0  # a free public service; stay modest

DEFAULT_STORE = Path(__file__).resolve().parent.parent / "data" / "reference" / "geo"

ENGLAND = "England"


@dataclass(slots=True)
class Geocoded:
    postcode: str
    matched: bool
    country: str = ""
    region: str = ""
    latitude: float | None = None
    longitude: float | None = None
    lsoa_code: str = ""
    lsoa_name: str = ""
    msoa_code: str = ""
    icb_code: str = ""
    icb_name: str = ""
    nhs_region: str = ""
    admin_district: str = ""
    imd_decile: int | None = None

    @property
    def in_england(self) -> bool:
        return self.country == ENGLAND


def _norm(postcode: str) -> str:
    """Postcodes.io echoes the query string back, so normalise for joining."""
    return "".join(postcode.split()).upper()


def _row(query: str, result: dict | None) -> Geocoded:
    if not result:
        return Geocoded(postcode=_norm(query), matched=False)
    codes = result.get("codes") or {}
    return Geocoded(
        postcode=_norm(query),
        matched=True,
        country=result.get("country") or "",
        region=result.get("region") or "",
        latitude=result.get("latitude"),
        longitude=result.get("longitude"),
        # Prefer the 2021 LSOA boundaries; fall back to the generic field.
        lsoa_code=codes.get("lsoa21") or codes.get("lsoa") or "",
        lsoa_name=result.get("lsoa21") or result.get("lsoa") or "",
        msoa_code=codes.get("msoa21") or codes.get("msoa") or "",
        icb_code=codes.get("icb") or "",
        icb_name=result.get("icb") or "",
        nhs_region=result.get("nhs_region") or "",
        admin_district=result.get("admin_district") or "",
        imd_decile=result.get("index_of_multiple_deprivation"),
    )


async def geocode(
    postcodes: list[str],
    *,
    store: Path | str = DEFAULT_STORE,
    day: str | None = None,
    rate: float = GEO_RATE,
) -> int:
    """Bulk-geocode postcodes, storing every raw response. Returns an exit code."""
    day = day or utc_today()
    unique = sorted({p.strip().upper() for p in postcodes if p and p.strip()})
    batches = [unique[i : i + BATCH_SIZE] for i in range(0, len(unique), BATCH_SIZE)]
    print(f"Geocoding {len(unique):,} unique postcodes in {len(batches)} batches", flush=True)

    async with PoliteClient(rate_per_sec=rate, concurrency=2) as client:
        with SnapshotWriter(root=store, day=day, route="postcodes-io") as writer:
            for i, batch in enumerate(batches):
                result = await client.post(POSTCODES_API, json={"postcodes": batch})
                if not result.ok:
                    print(f"FATAL: batch {i} failed ({result.status})", file=sys.stderr)
                    return 1
                writer.add(
                    Record(
                        practice_id=f"batch-{i:05d}",
                        url=POSTCODES_API,
                        fetched_at=result.fetched_at,
                        status=result.status,
                        body=result.body,
                        content_type=result.content_type,
                        meta={"batch": i, "size": len(batch)},
                    )
                )
                if (i + 1) % 20 == 0 or i + 1 == len(batches):
                    print(f"  {i + 1}/{len(batches)} batches", flush=True)
    return 0


def load_geocoded(store: Path | str = DEFAULT_STORE, day: str | None = None) -> dict[str, Geocoded]:
    """Read a stored geocode pull, keyed by normalised postcode."""
    store = Path(store)
    day = day or latest_day(store)
    if not day:
        raise FileNotFoundError(f"no geocode pull found under {store}")

    out: dict[str, Geocoded] = {}
    for _entry, body in iter_payloads(store, day):
        for item in json.loads(body).get("result") or []:
            row = _row(item.get("query", ""), item.get("result"))
            out[row.postcode] = row
    return out


def summarise(rows: dict[str, Geocoded]) -> dict:
    """Match rate and country split — published per constraint C8."""
    total = len(rows)
    matched = [r for r in rows.values() if r.matched]
    countries: dict[str, int] = {}
    for r in matched:
        countries[r.country or "unknown"] = countries.get(r.country or "unknown", 0) + 1
    england = [r for r in matched if r.in_england]
    return {
        "total": total,
        "matched": len(matched),
        "unmatched": total - len(matched),
        "match_rate": len(matched) / total if total else 0.0,
        "countries": countries,
        "england": len(england),
        "england_with_lsoa": sum(1 for r in england if r.lsoa_code),
        "england_with_icb": sum(1 for r in england if r.icb_code),
    }


def write_parquet(rows: dict[str, Geocoded], out_path: Path | str) -> Path:
    import polars as pl

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame([asdict(r) for r in rows.values()]).write_parquet(out_path, compression="zstd")
    return out_path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Geocode practice postcodes (ONSPD geography).")
    ap.add_argument("--store", default=str(DEFAULT_STORE))
    ap.add_argument("--day", default=None)
    ap.add_argument("--out", default="data/dist/postcodes.parquet")
    ap.add_argument("--skip-fetch", action="store_true")
    args = ap.parse_args(argv)

    if not args.skip_fetch:
        from ods import load_register

        postcodes = [p.postcode for p in load_register()]
        code = asyncio.run(geocode(postcodes, store=args.store, day=args.day))
        if code:
            return code

    rows = load_geocoded(args.store, args.day)
    stats = summarise(rows)

    print(f"\nGeocoded {stats['matched']:,}/{stats['total']:,} postcodes ({stats['match_rate']:.1%})")
    for country, count in sorted(stats["countries"].items(), key=lambda kv: -kv[1]):
        print(f"  {country:<20} {count:>6,}")
    print(f"\nEngland: {stats['england']:,}")
    print(f"  with an LSOA code: {stats['england_with_lsoa']:,}")
    print(f"  with an ICB code:  {stats['england_with_icb']:,}")
    if stats["unmatched"]:
        print(f"\n{stats['unmatched']:,} postcodes did not match — these need a manual fallback.")

    out = write_parquet(rows, args.out)
    print(f"\nWrote {len(rows):,} rows to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
