"""Static data build (ledger step 5.1).

The decision that deletes the entire infrastructure row: no server database, no
Redis, no API layer for v1. The pipelines run offline and emit static files; the
web app reads them and does the rest in the browser. ~6,400 practices is a few
megabytes, and the whole of England fits in a fetch.

This is the **contract** between the pipeline and the web app, which is why it
precedes any UI work. Everything downstream — search, map, profile pages, bulk
downloads — reads what this emits and nothing else.

Outputs, all under ``data/dist/site/v{SCHEMA_VERSION}/``
--------------------------------------------------------
``practices.json``  Current reported state for every published practice.
``changes.json``    Every status change we have observed, as an event log.
``access.json``     Per-LSOA supply-vs-demand metrics for the map.
``meta.json``       Schema version, build provenance, and the data-quality
                    figures that constraint C8 requires us to publish.

Columnar, not a list of objects
-------------------------------
Each file carries a ``fields`` array and a ``rows`` array-of-arrays rather than
repeating key names 6,400 times. It roughly halves the payload for no real cost
— the web app zips the two together once on load.

Why the history is an event log
-------------------------------
A per-practice daily timeline would grow by 6,407 rows a night forever, and
would be almost entirely repetition: on a normal night, two practices change and
6,405 do not. ``changes.json`` records only transitions, which is exactly what a
profile-page timeline draws. It also makes the gaps in our own coverage legible
rather than hidden — an event spanning a missing night is marked as such.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from itertools import pairwise
from pathlib import Path

_INGEST = Path(__file__).resolve().parent.parent / "ingest"
if str(_INGEST) not in sys.path:
    sys.path.insert(0, str(_INGEST))

from freshness import score_all
from parse import parse_day
from snapshot import DEFAULT_ROOT, available_days

SCHEMA_VERSION = 1

PRACTICE_FIELDS = [
    "id",           # nhs.uk / ODS-padded practice id
    "name",         # from the ODS register
    "postcode",
    "lat",
    "lon",
    "lsoa",
    "icb",
    "status",       # accepting | not_accepting | not_confirmed | referral_only
    "adults",       # 1 / 0 / null — null means the practice has not said
    "children",
    "free_care",
    "confirmed",    # ISO date the practice last confirmed, or null
    "age_days",     # best available age signal
    "age_evidence", # confirmed_date | page_lastmod | none
    "bucket",       # freshness bucket
]

CHANGE_FIELDS = ["id", "date", "from", "to", "spans_gap"]

ACCESS_FIELDS = ["lsoa", "pop", "nearest_km", "practices_in_reach", "uda_per_1000"]


def _tri(value) -> int | None:
    """Tri-state cohort flag. None is a real answer — "the practice has not
    said" is different from "no", and flattening them would invent data."""
    return None if value is None else int(bool(value))


@dataclass(slots=True)
class BuildResult:
    out_dir: Path
    practices: int
    changes: int
    lsoas: int
    days: list[str]


def _write(path: Path, fields: list[str], rows: list[list], **extra) -> int:
    payload = {"schema": SCHEMA_VERSION, "fields": fields, "rows": rows, **extra}
    path.write_text(json.dumps(payload, separators=(",", ":"), default=str))
    return len(rows)


def build_changes(per_day: dict[str, dict[str, str]], days: list[str]) -> list[list]:
    """Status transitions across every captured night.

    ``spans_gap`` marks a transition observed across non-consecutive captures —
    the change is real, but the date we attribute it to is the date we *saw* it,
    not necessarily the date it happened. Publishing that distinction is the
    honest thing to do, and it is the visible price of every missed night.
    """
    changes: list[list] = []
    for prev_day, curr_day in pairwise(days):
        gap = (date.fromisoformat(curr_day) - date.fromisoformat(prev_day)).days > 1
        before, after = per_day[prev_day], per_day[curr_day]
        for practice_id, new_status in after.items():
            old_status = before.get(practice_id)
            if old_status is not None and old_status != new_status:
                changes.append([practice_id, curr_day, old_status, new_status, int(gap)])
    return changes


def build(
    root: Path | str = DEFAULT_ROOT,
    dist: Path | str = "data/dist",
    out_dir: Path | str | None = None,
) -> BuildResult:
    import polars as pl

    dist = Path(dist)
    out = Path(out_dir) if out_dir else dist / "site" / f"v{SCHEMA_VERSION}"
    out.mkdir(parents=True, exist_ok=True)

    days = available_days(root)
    if not days:
        raise FileNotFoundError(f"no snapshots found under {root}")
    latest = days[-1]

    # -- reference data ----------------------------------------------------
    from ods import load_register

    register = {p.nhsuk_id: p for p in load_register()}
    postcodes = pl.read_parquet(dist / "postcodes.parquet")
    geo = {
        r["postcode"]: r
        for r in postcodes.filter(pl.col("matched")).iter_rows(named=True)
    }

    # -- current state + observed history ----------------------------------
    per_day: dict[str, dict[str, str]] = {}
    rows_latest = []
    for day in days:
        parsed, _ = parse_day(root, day)
        per_day[day] = {r.practice_id: r.status for r in parsed}
        if day == latest:
            rows_latest = parsed

    scores = {s.practice_id: s for s in score_all(rows_latest)}

    practices: list[list] = []
    for row in rows_latest:
        ods = register.get(row.practice_id)
        pc = "".join((ods.postcode if ods else "").split()).upper()
        g = geo.get(pc, {})
        score = scores.get(row.practice_id)
        practices.append(
            [
                row.practice_id,
                ods.name.title() if ods else "",
                pc,
                g.get("latitude"),
                g.get("longitude"),
                g.get("lsoa_code", ""),
                g.get("icb_name", ""),
                row.status,
                _tri(row.accepting_adults),
                _tri(row.accepting_children),
                _tri(row.accepting_free_care),
                row.last_confirmed.isoformat() if row.last_confirmed else None,
                score.effective_days if score else None,
                score.age_evidence if score else "none",
                score.bucket if score else "",
            ]
        )

    changes = build_changes(per_day, days)

    # -- access layer ------------------------------------------------------
    access_rows: list[list] = []
    access_path = dist / "lsoa_access.parquet"
    if access_path.exists():
        for r in pl.read_parquet(access_path).iter_rows(named=True):
            access_rows.append(
                [
                    r["lsoa_code"],
                    r["population"],
                    r["nearest_practice_km"],
                    r["practices_within_radius"],
                    r["uda_per_1000"],
                ]
            )

    n_practices = _write(out / "practices.json", PRACTICE_FIELDS, practices, as_of=latest)
    n_changes = _write(out / "changes.json", CHANGE_FIELDS, changes, days_observed=days)
    n_access = _write(out / "access.json", ACCESS_FIELDS, access_rows)

    # -- provenance and self-reported quality (C8) -------------------------
    located = sum(1 for p in practices if p[3] is not None)
    named = sum(1 for p in practices if p[1])
    expected_nights = (
        date.fromisoformat(days[-1]) - date.fromisoformat(days[0])
    ).days + 1
    missing = [
        d.isoformat()
        for d in (
            date.fromordinal(o)
            for o in range(
                date.fromisoformat(days[0]).toordinal(),
                date.fromisoformat(days[-1]).toordinal() + 1,
            )
        )
        if d.isoformat() not in days
    ]

    meta = {
        "schema": SCHEMA_VERSION,
        "built_at": datetime.now(UTC).isoformat(),
        "as_of": latest,
        "practices": len(practices),
        "coverage": {
            "geolocated": located,
            "geolocated_rate": round(located / len(practices), 4) if practices else 0,
            "named_from_ods": named,
            "named_rate": round(named / len(practices), 4) if practices else 0,
        },
        "history": {
            "nights_captured": len(days),
            "nights_expected": expected_nights,
            "first": days[0],
            "latest": latest,
            # Published deliberately. A record with holes in it should say so.
            "nights_missing": missing,
            "changes_observed": len(changes),
            "changes_spanning_a_gap": sum(1 for c in changes if c[4]),
        },
        "lsoas": len(access_rows),
        "attribution": [
            "Information from the NHS website",
            "Information from the NHS website is licensed under the Open Government Licence v3.0",
            "Contains ONS and NHSBSA data licensed under the Open Government Licence v3.0",
        ],
        "disclaimer": (
            "Not affiliated with, endorsed by, or connected to the NHS. "
            "Practice status is what the practice reported on the date shown, "
            "not a statement of current fact."
        ),
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2))

    return BuildResult(out, n_practices, n_changes, n_access, days)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build static site data.")
    ap.add_argument("--root", default=str(DEFAULT_ROOT))
    ap.add_argument("--dist", default="data/dist")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    try:
        result = build(args.root, args.dist, args.out)
    except FileNotFoundError as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 1

    meta = json.loads((result.out_dir / "meta.json").read_text())
    print(f"Built schema v{SCHEMA_VERSION} → {result.out_dir}")
    print(f"  practices.json  {result.practices:,} practices (as of {meta['as_of']})")
    print(f"  changes.json    {result.changes:,} observed status changes")
    print(f"  access.json     {result.lsoas:,} LSOAs")
    print("  meta.json       provenance + self-reported quality")
    print()
    print(f"  geolocated: {meta['coverage']['geolocated_rate']:.1%}   "
          f"named: {meta['coverage']['named_rate']:.1%}")
    hist = meta["history"]
    print(f"  history: {hist['nights_captured']}/{hist['nights_expected']} nights "
          f"({hist['first']} → {hist['latest']})")
    if hist["nights_missing"]:
        print(f"  MISSING NIGHTS: {', '.join(hist['nights_missing'])}")
        print(f"  {hist['changes_spanning_a_gap']} of {hist['changes_observed']} changes "
              "cannot be dated to a single day as a result")

    total = sum(f.stat().st_size for f in result.out_dir.glob("*.json"))
    print(f"\n  total payload: {total / 1e6:.2f} MB uncompressed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
