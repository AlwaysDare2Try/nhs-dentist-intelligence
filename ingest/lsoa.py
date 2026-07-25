"""LSOA population-weighted centroids (supports ledger step 4.2).

The demand model needs to know *where* people are, not just how many. ONS
publishes population-weighted centroids — the point that best represents where
an LSOA's residents actually live, rather than its geometric middle, which in
rural areas can sit on an empty hillside.

Source: ONS Open Geography Portal, ``LSOA_PopCentroids_EW_2021_V4``, OGL. 2021
boundaries, matching the LSOA21 codes ``geo.py`` and ``pop.py`` emit.

Deliberately fetched rather than derived: approximating a centroid from the
postcodes we happen to have would bias every rural LSOA towards its practices,
which is precisely the bias the dental-desert model exists to detect.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlencode

from client import PoliteClient
from snapshot import Record, SnapshotWriter, iter_payloads, latest_day, utc_today

SERVICE = (
    "https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services/"
    "LSOA_PopCentroids_EW_2021_V4/FeatureServer/0/query"
)
PAGE_SIZE = 2000  # the service's transfer limit
LSOA_RATE = 3.0
DEFAULT_STORE = Path(__file__).resolve().parent.parent / "data" / "reference" / "lsoa"

# England and Wales together are ~35,700 LSOAs. Far fewer means a truncated pull.
MIN_EXPECTED_CENTROIDS = 30_000


@dataclass(slots=True)
class Centroid:
    lsoa_code: str
    latitude: float
    longitude: float

    @property
    def in_england(self) -> bool:
        return self.lsoa_code.startswith("E")


def _page_url(offset: int) -> str:
    return f"{SERVICE}?" + urlencode(
        {
            "where": "1=1",
            "outFields": "LSOA21CD",
            "outSR": "4326",
            "resultOffset": offset,
            "resultRecordCount": PAGE_SIZE,
            "f": "json",
        }
    )


def parse_centroids(payload: bytes) -> list[Centroid]:
    data = json.loads(payload)
    out: list[Centroid] = []
    for feature in data.get("features", []):
        attrs = feature.get("attributes") or {}
        geom = feature.get("geometry") or {}
        code = (attrs.get("LSOA21CD") or "").strip()
        x, y = geom.get("x"), geom.get("y")
        if code and x is not None and y is not None:
            out.append(Centroid(lsoa_code=code, latitude=float(y), longitude=float(x)))
    return out


async def fetch_centroids(
    *, store: Path | str = DEFAULT_STORE, day: str | None = None, rate: float = LSOA_RATE
) -> int:
    day = day or utc_today()

    async with PoliteClient(rate_per_sec=rate, concurrency=2) as client:
        with SnapshotWriter(root=store, day=day, route="ons-arcgis", resume=True) as writer:
            offset, total, page = 0, 0, 0
            while True:
                key = f"page-{offset:06d}"
                if key in writer.already_captured:
                    offset += PAGE_SIZE
                    page += 1
                    continue

                result = await client.get(_page_url(offset))
                if not result.ok:
                    print(f"FATAL: centroid page at offset {offset} failed", file=sys.stderr)
                    return 1

                count = len(parse_centroids(result.body))
                writer.add(
                    Record(
                        practice_id=key,
                        url=_page_url(offset),
                        fetched_at=result.fetched_at,
                        status=result.status,
                        body=result.body,
                        content_type=result.content_type,
                        meta={"offset": offset, "count": count},
                    )
                )
                total += count
                page += 1
                if count < PAGE_SIZE:
                    break
                offset += PAGE_SIZE
                if page > 40:  # ~80k records; the dataset is nowhere near this
                    print("FATAL: pagination did not terminate", file=sys.stderr)
                    return 1

            print(f"Captured {total:,} centroids in {page} pages", flush=True)
            if total < MIN_EXPECTED_CENTROIDS:
                print(
                    f"FATAL: only {total:,} centroids "
                    f"(expected at least {MIN_EXPECTED_CENTROIDS:,})",
                    file=sys.stderr,
                )
                return 1
    return 0


def load_centroids(
    store: Path | str = DEFAULT_STORE, day: str | None = None, england_only: bool = True
) -> dict[str, Centroid]:
    store = Path(store)
    day = day or latest_day(store)
    if not day:
        raise FileNotFoundError(f"no centroid pull found under {store}")

    out: dict[str, Centroid] = {}
    for _entry, body in iter_payloads(store, day):
        for c in parse_centroids(body):
            if england_only and not c.in_england:
                continue
            out[c.lsoa_code] = c
    return out


def write_parquet(centroids: dict[str, Centroid], out_path: Path | str) -> Path:
    import polars as pl

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame([asdict(c) for c in centroids.values()]).write_parquet(
        out_path, compression="zstd"
    )
    return out_path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Load ONS LSOA population-weighted centroids.")
    ap.add_argument("--store", default=str(DEFAULT_STORE))
    ap.add_argument("--day", default=None)
    ap.add_argument("--out", default="data/dist/lsoa_centroids.parquet")
    ap.add_argument("--skip-fetch", action="store_true")
    args = ap.parse_args(argv)

    if not args.skip_fetch:
        code = asyncio.run(fetch_centroids(store=args.store, day=args.day))
        if code:
            return code

    centroids = load_centroids(args.store, args.day)
    out = write_parquet(centroids, args.out)
    print(f"Wrote {len(centroids):,} England centroids to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
