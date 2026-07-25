"""LSOA population denominator for the demand model (ledger step 3.4).

Without a denominator, "dental desert" is an opinion. With one it is a rate:
practices — or accepting practices — per 10,000 residents in the LSOAs a person
can actually reach. Step 3.2 geocoded every practice to a **2021** LSOA code, so
the population table has to be on 2021 boundaries too or the join is a lie.

Source
------
ONS mid-year population estimates for lower-layer super output areas, served by
the **Nomis** API (Office for National Statistics, OGL v3, no API key):

    https://www.nomisweb.co.uk/api/v01/dataset/NM_2014_1.data.csv
        ?geography=TYPE151&date=latest&gender=0&c_age=200,201,204
        &measures=20100&select=date,geography_code,geography_name,c_age,
                               obs_value,record_count
        &RecordOffset=0

``NM_2014_1`` is *"Population estimates - small area (2021 based) by single year
of age - England and Wales"*. ``TYPE151`` is the 2021 LSOA geography — the same
vintage as ``codes.lsoa21`` from postcodes.io, which is why this dataset was
chosen over the older ``NM_2010_1`` (2011 boundaries). ``date=latest`` currently
resolves to **mid-2024** estimates.

Two things worth knowing about the endpoint:

* There is no England-only parent geography exposed on this dataset, so the pull
  covers England **and Wales** (35,672 LSOAs) and England is selected on the
  ``E01`` code prefix. Wales is kept in the raw store rather than thrown away.
* Guest (unauthenticated) requests are capped at **25,000 rows**. The pull pages
  on ``RecordOffset`` and stops when it has seen the ``RECORD_COUNT`` the API
  itself reports, so a silent truncation cannot masquerade as a complete pull.

Age bands — the 0–17 / 18+ split is exact, not approximated
-----------------------------------------------------------
NHS dentistry treats under-18s as a distinct demand group (free NHS treatment,
different recall intervals), so the denominator splits there. Nomis offers three
aggregate age codes that compose the split exactly, with no overlap and no gap:

    C_AGE 201  "Aged 0 to 15"   ─┐
    C_AGE 204  "Aged 16 to 17"  ─┴─ children  = 201 + 204   (ages 0–17)
    C_AGE 200  "All Ages"          adults     = 200 − children  (ages 18+)

**There is no discrepancy against a clean 0–17 / 18+ split.** The dataset also
carries single years of age (``C_AGE`` 101–191, where code = 101 + age), which
would give the same answer in 18× the rows; the aggregates are used because they
are cheaper and are ONS's own arithmetic rather than ours. ``adults`` is derived
by subtraction, so an LSOA whose bands do not reconcile (children > total) is
dropped rather than published with a negative adult count.

Counts are ``GENDER=0`` (Total) and ``MEASURES=20100`` (Value). Estimates are
rounded by ONS at source, so LSOA figures will not sum exactly to published
national totals; the difference is immaterial at the rates we compute.

Raw CSV pages go through the same append-only store as nightly snapshots, so the
pull is reproducible and re-parseable without touching the network again.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import io
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from client import PoliteClient
from snapshot import Record, SnapshotWriter, iter_payloads, latest_day, utc_today

NOMIS_DATA = "https://www.nomisweb.co.uk/api/v01/dataset/NM_2014_1.data.csv"

GEOGRAPHY = "TYPE151"  # 2021 lower-layer super output areas
GENDER_TOTAL = "0"
MEASURE_VALUE = "20100"

AGE_ALL = "200"  # All ages
AGE_0_15 = "201"  # Aged 0 to 15
AGE_16_17 = "204"  # Aged 16 to 17
AGE_CODES = (AGE_ALL, AGE_0_15, AGE_16_17)

SELECT = "date,geography_code,geography_name,c_age,obs_value,record_count"
PAGE_SIZE = 25_000  # the endpoint's guest limit; exceeding it truncates silently
MAX_PAGES = 40
NOMIS_RATE = 1.0  # a handful of requests against a free public service

DEFAULT_STORE = Path(__file__).resolve().parent.parent / "data" / "reference" / "population"

ENGLAND_PREFIX = "E01"

# England had 33,755 LSOAs on 2021 boundaries. Anything materially below this
# means a truncated or re-shaped response — refuse it rather than publish rates
# computed against a partial denominator.
MIN_EXPECTED_ENGLAND_LSOAS = 33_000
# England's mid-year population is ~58.6m. These bounds only catch catastrophe
# (double-counted bands, wrong geography level), not drift.
MIN_EXPECTED_ENGLAND_POP = 45_000_000
MAX_EXPECTED_ENGLAND_POP = 70_000_000


@dataclass(slots=True)
class LsoaPopulation:
    lsoa_code: str
    lsoa_name: str
    year: str
    total: int
    children: int  # ages 0-17
    adults: int  # ages 18+

    @property
    def child_share(self) -> float:
        return self.children / self.total if self.total else 0.0

    @property
    def in_england(self) -> bool:
        return self.lsoa_code.startswith(ENGLAND_PREFIX)


def page_url(offset: int) -> str:
    """The exact request issued for one page. Pinned by a test — a typo here
    returns HTTP 200 with an empty body rather than an error."""
    return (
        f"{NOMIS_DATA}?geography={GEOGRAPHY}&date=latest&gender={GENDER_TOTAL}"
        f"&c_age={','.join(AGE_CODES)}&measures={MEASURE_VALUE}"
        f"&select={SELECT}&RecordOffset={offset}"
    )


def _parse_csv(body: bytes) -> tuple[list[dict], int | None]:
    """Return ``(rows, record_count)`` for one CSV page.

    ``RECORD_COUNT`` is the API's own count of rows matching the whole query, and
    is how the pager knows when it is finished.
    """
    reader = csv.DictReader(io.StringIO(body.decode("utf-8-sig")))
    rows: list[dict] = []
    record_count: int | None = None
    for row in reader:
        rows.append(row)
        if record_count is None:
            raw = (row.get("RECORD_COUNT") or "").strip()
            if raw.isdigit():
                record_count = int(raw)
    return rows, record_count


async def fetch_population(
    *,
    store: Path | str = DEFAULT_STORE,
    day: str | None = None,
    rate: float = NOMIS_RATE,
    max_pages: int = MAX_PAGES,
) -> int:
    """Page the Nomis LSOA estimates and store every raw CSV. Returns an exit code."""
    day = day or utc_today()

    async with PoliteClient(rate_per_sec=rate, concurrency=1) as client:
        with SnapshotWriter(root=store, day=day, route="nomis-nm2014") as writer:
            offset = 0
            expected: int | None = None
            seen = 0

            for page in range(max_pages):
                url = page_url(offset)
                result = await client.get(url)
                if not result.ok:
                    print(f"FATAL: Nomis page {page} failed ({result.status})", file=sys.stderr)
                    return 1

                rows, record_count = _parse_csv(result.body)
                if not rows:
                    if seen == 0:
                        print(
                            "FATAL: Nomis returned no rows — the geography or age "
                            "parameters are wrong (this endpoint answers 200 with an "
                            "empty body rather than erroring).",
                            file=sys.stderr,
                        )
                        return 1
                    break

                if expected is None:
                    expected = record_count

                writer.add(
                    Record(
                        practice_id=f"page-{offset:08d}",
                        url=url,
                        fetched_at=result.fetched_at,
                        status=result.status,
                        body=result.body,
                        content_type=result.content_type,
                        meta={"offset": offset, "rows": len(rows), "record_count": record_count},
                    )
                )
                seen += len(rows)
                print(
                    f"  offset {offset:>7}: {len(rows):>6} rows "
                    f"(running total {seen:,} of {expected or '?'})",
                    flush=True,
                )

                if expected is not None and seen >= expected:
                    break
                offset += PAGE_SIZE
            else:
                print(f"FATAL: still paging after {max_pages} pages", file=sys.stderr)
                return 1

            if expected is not None and seen < expected:
                print(
                    f"FATAL: pull is short — {seen:,} rows of {expected:,} expected.",
                    file=sys.stderr,
                )
                return 1

            print(f"\nCaptured {seen:,} observation rows", flush=True)
    return 0


def _assemble(counts: dict[str, dict]) -> dict[str, LsoaPopulation]:
    """Turn per-LSOA age-code counts into the children/adults split.

    An LSOA missing any of the three age codes, or whose bands do not reconcile,
    is dropped: a denominator that is quietly wrong is worse than one that is
    visibly absent.
    """
    out: dict[str, LsoaPopulation] = {}
    for code, rec in counts.items():
        ages = rec["ages"]
        if not all(a in ages for a in AGE_CODES):
            continue
        total = ages[AGE_ALL]
        children = ages[AGE_0_15] + ages[AGE_16_17]
        if total < 0 or children < 0 or children > total:
            continue
        out[code] = LsoaPopulation(
            lsoa_code=code,
            lsoa_name=rec["name"],
            year=rec["year"],
            total=total,
            children=children,
            adults=total - children,
        )
    return out


def _read_counts(store: Path, day: str) -> dict[str, dict]:
    counts: dict[str, dict] = {}
    for _entry, body in iter_payloads(store, day):
        rows, _ = _parse_csv(body)
        for row in rows:
            code = (row.get("GEOGRAPHY_CODE") or "").strip()
            age = (row.get("C_AGE") or "").strip()
            value = (row.get("OBS_VALUE") or "").strip()
            if not code or age not in AGE_CODES:
                continue
            try:
                observation = int(float(value))
            except ValueError:
                continue
            rec = counts.setdefault(
                code,
                {
                    "name": (row.get("GEOGRAPHY_NAME") or "").strip(),
                    "year": (row.get("DATE") or "").strip(),
                    "ages": {},
                },
            )
            rec["ages"][age] = observation
    return counts


def load_population(
    store: Path | str = DEFAULT_STORE,
    day: str | None = None,
    *,
    england_only: bool = True,
) -> dict[str, LsoaPopulation]:
    """Read a stored population pull, keyed by LSOA (2021) code.

    Wales is captured because the endpoint has no England-only geography, but is
    filtered out by default — this platform is England-scoped, and leaving W01
    rows in would flatter any national coverage figure we publish.
    """
    store = Path(store)
    day = day or latest_day(store)
    if not day:
        raise FileNotFoundError(f"no population pull found under {store}")

    rows = _assemble(_read_counts(store, day))
    if england_only:
        rows = {k: v for k, v in rows.items() if v.in_england}
    return rows


def summarise(rows: dict[str, LsoaPopulation]) -> dict:
    """Coverage and totals — published per constraint C8."""
    england = [r for r in rows.values() if r.in_england]
    total = sum(r.total for r in rows.values())
    children = sum(r.children for r in rows.values())
    england_total = sum(r.total for r in england)
    england_children = sum(r.children for r in england)
    years = sorted({r.year for r in rows.values() if r.year})
    return {
        "lsoas": len(rows),
        "england_lsoas": len(england),
        "other_lsoas": len(rows) - len(england),
        "years": years,
        "total_population": total,
        "children": children,
        "adults": total - children,
        "child_share": children / total if total else 0.0,
        "england_population": england_total,
        "england_children": england_children,
        "england_adults": england_total - england_children,
        "empty_lsoas": sum(1 for r in rows.values() if r.total == 0),
    }


def coverage(rows: dict[str, LsoaPopulation], lsoa_codes: set[str]) -> dict:
    """How many of our geocoded practices' LSOAs have a population figure.

    Anything short of ~100% means practices that cannot enter the demand model,
    so the gap is reported rather than silently inner-joined away.
    """
    wanted = {c for c in lsoa_codes if c}
    matched = wanted & set(rows)
    return {
        "practice_lsoas": len(wanted),
        "matched": len(matched),
        "missing": len(wanted - matched),
        "match_rate": len(matched) / len(wanted) if wanted else 0.0,
        "missing_sample": sorted(wanted - matched)[:10],
    }


def check_plausible(stats: dict) -> list[str]:
    """Guardrails against publishing a denominator we know is wrong."""
    problems: list[str] = []
    if stats["england_lsoas"] < MIN_EXPECTED_ENGLAND_LSOAS:
        problems.append(
            f"only {stats['england_lsoas']:,} English LSOAs "
            f"(expected at least {MIN_EXPECTED_ENGLAND_LSOAS:,})"
        )
    pop = stats["england_population"]
    if not MIN_EXPECTED_ENGLAND_POP <= pop <= MAX_EXPECTED_ENGLAND_POP:
        problems.append(
            f"England population {pop:,} is outside the plausible range "
            f"{MIN_EXPECTED_ENGLAND_POP:,}–{MAX_EXPECTED_ENGLAND_POP:,}"
        )
    return problems


def write_parquet(rows: dict[str, LsoaPopulation], out_path: Path | str) -> Path:
    import polars as pl

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    frame = [
        {**asdict(r), "child_share": round(r.child_share, 6)}
        for r in sorted(rows.values(), key=lambda r: r.lsoa_code)
    ]
    pl.DataFrame(frame).write_parquet(out_path, compression="zstd")
    return out_path


def _practice_lsoas(path: Path) -> set[str]:
    """England LSOA codes from the step 3.2 geocode output, if it exists."""
    if not path.exists():
        return set()
    import polars as pl

    frame = pl.read_parquet(path)
    england = frame.filter(pl.col("country") == "England")
    return {c for c in england["lsoa_code"].to_list() if c}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="LSOA population denominator (ONS via Nomis).")
    ap.add_argument("--store", default=str(DEFAULT_STORE))
    ap.add_argument("--day", default=None)
    ap.add_argument("--out", default="data/dist/lsoa_population.parquet")
    ap.add_argument("--postcodes", default="data/dist/postcodes.parquet")
    ap.add_argument("--skip-fetch", action="store_true", help="parse an existing pull only")
    ap.add_argument("--keep-wales", action="store_true", help="do not filter to England")
    args = ap.parse_args(argv)

    if not args.skip_fetch:
        code = asyncio.run(fetch_population(store=args.store, day=args.day))
        if code:
            return code

    rows = load_population(args.store, args.day, england_only=not args.keep_wales)
    stats = summarise(rows)

    print(f"\nLSOAs: {stats['lsoas']:,} ({stats['england_lsoas']:,} in England)")
    print(f"Estimate year: {', '.join(stats['years']) or 'unknown'}")
    print(f"England population: {stats['england_population']:,}")
    print(f"  children 0-17: {stats['england_children']:,}")
    print(f"  adults 18+:    {stats['england_adults']:,}")
    print(f"  child share:   {stats['child_share']:.1%}")
    if stats["empty_lsoas"]:
        print(f"  LSOAs with zero population: {stats['empty_lsoas']:,}")

    problems = check_plausible(stats)
    if problems:
        for problem in problems:
            print(f"FATAL: {problem}", file=sys.stderr)
        return 1

    practice_lsoas = _practice_lsoas(Path(args.postcodes))
    if practice_lsoas:
        join = coverage(rows, practice_lsoas)
        print(
            f"\nJoin to geocoded practices: {join['matched']:,}/{join['practice_lsoas']:,} "
            f"distinct LSOAs ({join['match_rate']:.2%})"
        )
        if join["missing"]:
            print(f"  unmatched sample: {', '.join(join['missing_sample'])}")

    out = write_parquet(rows, args.out)
    print(f"\nWrote {len(rows):,} LSOA population rows to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
