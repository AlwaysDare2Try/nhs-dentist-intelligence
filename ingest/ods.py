"""Load the ODS dental practice register (ledger step 3.1).

The Organisation Data Service is the authoritative register of NHS organisations.
It supplies the stable identity backbone that nhs.uk does not: official codes,
registered names, postcodes and a last-change date.

Two things this deliberately does *not* do:

* **It does not filter to England.** The ORD list endpoint carries no country
  field, and guessing from postcode areas would misclassify practices along the
  Welsh border. Country is resolved properly at step 3.2 from ONSPD, which is
  authoritative for it. Loading the register faithfully and filtering later is
  the honest order.
* **It does not decide identity.** Matching ODS to nhs.uk to NHSBSA is step 3.3,
  and it is the highest schedule risk in the plan. This module only exposes the
  one mapping that is mechanical and certain — the ID padding convention.

Raw API pages go through the same append-only store as nightly snapshots, so a
register pull is as re-parseable as a crawl.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from client import PoliteClient
from snapshot import Record, SnapshotWriter, iter_payloads, latest_day, utc_today

ORD_BASE = "https://directory.spineservices.nhs.uk/ORD/2-0-0/organisations"
# RO110 = GENERAL DENTAL PRACTICE. RO65 (private dental practice) is a
# non-primary role and returns nothing on this endpoint.
DENTAL_PRIMARY_ROLE = "RO110"
PAGE_SIZE = 1000  # the endpoint's maximum
# NHS England's catalogue asks for under 5 req/s and calls the service
# "not designed for high volume usage". Ten requests at 2/s is a rounding error.
ORD_RATE = 2.0

DEFAULT_STORE = Path(__file__).resolve().parent.parent / "data" / "reference" / "ods"

# Below this, the register response has changed shape — refuse rather than
# overwrite a good register with a truncated one.
MIN_EXPECTED_ORGS = 5_000

_ID_PARTS = re.compile(r"^([A-Za-z]+)(\d+)$")


@dataclass(slots=True)
class OdsPractice:
    org_id: str
    name: str
    postcode: str
    status: str
    last_change_date: str
    record_class: str
    nhsuk_id: str


def nhsuk_id(org_id: str) -> str:
    """Translate an ODS code into the form nhs.uk uses in profile URLs.

    nhs.uk zero-pads the numeric part to six digits: ``V01699`` → ``V001699``.
    Getting this wrong 404s every single detail fetch, so it is pinned by a test.
    """
    match = _ID_PARTS.match(org_id.strip())
    if not match:
        return org_id.strip().upper()
    prefix, digits = match.groups()
    return f"{prefix.upper()}{digits.zfill(6)}"


async def fetch_register(
    *,
    store: Path | str = DEFAULT_STORE,
    day: str | None = None,
    rate: float = ORD_RATE,
    max_pages: int = 40,
) -> int:
    """Page the ORD API and store every raw response. Returns an exit code."""
    day = day or utc_today()

    async with PoliteClient(rate_per_sec=rate, concurrency=1) as client:
        with SnapshotWriter(root=store, day=day, route="ods-ord") as writer:
            offset = 1  # the endpoint is 1-based; Offset=0 returns an error
            total = 0

            for page in range(max_pages):
                url = (
                    f"{ORD_BASE}?PrimaryRoleId={DENTAL_PRIMARY_ROLE}"
                    f"&Status=Active&Limit={PAGE_SIZE}&Offset={offset}"
                )
                result = await client.get(url)
                if not result.ok:
                    print(f"FATAL: ORD page {page} failed ({result.status})", file=sys.stderr)
                    return 1

                try:
                    orgs = json.loads(result.body).get("Organisations", [])
                except json.JSONDecodeError as exc:
                    print(f"FATAL: ORD page {page} was not JSON ({exc})", file=sys.stderr)
                    return 1

                writer.add(
                    Record(
                        practice_id=f"page-{offset:06d}",
                        url=url,
                        fetched_at=result.fetched_at,
                        status=result.status,
                        body=result.body,
                        content_type=result.content_type,
                        meta={"offset": offset, "count": len(orgs)},
                    )
                )
                total += len(orgs)
                print(f"  offset {offset:>5}: {len(orgs):>5} orgs (running total {total:,})", flush=True)

                if len(orgs) < PAGE_SIZE:
                    break
                offset += PAGE_SIZE

            if total < MIN_EXPECTED_ORGS:
                print(
                    f"FATAL: register returned only {total:,} organisations "
                    f"(expected at least {MIN_EXPECTED_ORGS:,}).",
                    file=sys.stderr,
                )
                return 1

            print(f"\nRegister captured: {total:,} active dental practices", flush=True)
    return 0


def load_register(store: Path | str = DEFAULT_STORE, day: str | None = None) -> list[OdsPractice]:
    """Read a stored register pull into normalised rows."""
    store = Path(store)
    day = day or latest_day(store)
    if not day:
        raise FileNotFoundError(f"no ODS register pull found under {store}")

    practices: list[OdsPractice] = []
    seen: set[str] = set()

    for _entry, body in iter_payloads(store, day):
        for org in json.loads(body).get("Organisations", []):
            org_id = (org.get("OrgId") or "").strip()
            if not org_id or org_id in seen:
                continue
            seen.add(org_id)
            practices.append(
                OdsPractice(
                    org_id=org_id,
                    name=(org.get("Name") or "").strip(),
                    postcode=(org.get("PostCode") or "").strip(),
                    status=(org.get("Status") or "").strip(),
                    last_change_date=(org.get("LastChangeDate") or "").strip(),
                    record_class=(org.get("OrgRecordClass") or "").strip(),
                    nhsuk_id=nhsuk_id(org_id),
                )
            )
    return practices


def coverage(practices: list[OdsPractice], nhsuk_ids: set[str]) -> dict:
    """How far the register and the published nhs.uk estate overlap.

    Published per constraint C8. Neither side is a subset of the other: the
    register includes private-only practices and prison dental units that have
    no public profile, while nhs.uk may publish a profile whose ODS record has
    since been retired.
    """
    register_ids = {p.nhsuk_id for p in practices}
    matched = register_ids & nhsuk_ids
    return {
        "ods_active": len(register_ids),
        "nhsuk_published": len(nhsuk_ids),
        "matched": len(matched),
        "nhsuk_without_ods": len(nhsuk_ids - register_ids),
        "ods_without_nhsuk": len(register_ids - nhsuk_ids),
        "nhsuk_match_rate": len(matched) / len(nhsuk_ids) if nhsuk_ids else 0.0,
    }


def write_parquet(practices: list[OdsPractice], out_path: Path | str) -> Path:
    import polars as pl

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame([asdict(p) for p in practices]).write_parquet(out_path, compression="zstd")
    return out_path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Load the ODS dental practice register.")
    ap.add_argument("--store", default=str(DEFAULT_STORE))
    ap.add_argument("--day", default=None)
    ap.add_argument("--out", default="data/dist/ods_practices.parquet")
    ap.add_argument("--skip-fetch", action="store_true", help="parse an existing pull only")
    args = ap.parse_args(argv)

    if not args.skip_fetch:
        code = asyncio.run(fetch_register(store=args.store, day=args.day))
        if code:
            return code

    practices = load_register(args.store, args.day)
    out = write_parquet(practices, args.out)
    print(f"Wrote {len(practices):,} ODS practices to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
