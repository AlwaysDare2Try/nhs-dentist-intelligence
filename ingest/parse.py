"""Parse raw snapshots into a tidy practice-day table (ledger step 2.3).

Separating parse from fetch is what makes a parser bug cost a re-run instead of
lost data. This module never touches the network — it reads the append-only
store and emits one row per practice per snapshot date.

Constraint C1 governs the output: nothing here produces a "current status". It
produces *what a practice reported, and when it says it last confirmed it*. The
`last_confirmed` column is not decoration; it is the point.

**Scoping matters.** The appointments page has two sections — "Routine dental
care" and "Urgent or emergency dental care" — and both contain bullet lists. The
urgent section always lists "an urgent appointment at short notice" and "advice
where to get out-of-hours treatment". Reading list items document-wide would mark
every practice in England as offering those. All cohort extraction is therefore
scoped to the routine-care region.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path

from snapshot import DEFAULT_ROOT, available_days, iter_payloads

# Acceptance states, in the wording nhs.uk actually uses.
ACCEPTING = "accepting"
NOT_ACCEPTING = "not_accepting"
NOT_CONFIRMED = "not_confirmed"
REFERRAL_ONLY = "referral_only"
UNRECOGNISED = "unrecognised"

# ADR-002 mitigation 2: if markup changes, fail loudly rather than silently
# emitting a table of nulls that looks like a real collapse in provision.
MIN_RECOGNISED_SHARE = 0.90

_WS = re.compile(r"\s+")
_TAG = re.compile(r"<[^>]+>")
_LI = re.compile(r"<li[^>]*>(.*?)</li>", re.DOTALL | re.IGNORECASE)
_DATE_EL = re.compile(
    r'id="dentist-accepting-patients-last-updated"[^>]*>\s*Last confirmed:\s*([^<]+)',
    re.IGNORECASE,
)
_STATEMENT = re.compile(r"This dentist[^<]{0,200}", re.IGNORECASE)
_ROUTINE_ANCHOR = re.compile(r'id="routine-care-header"', re.IGNORECASE)
_NEXT_H2 = re.compile(r"<h2", re.IGNORECASE)

# Cohort phrasing, matched within the routine-care region only.
_COHORT_ADULTS = re.compile(r"adults aged 18 or over", re.IGNORECASE)
_COHORT_FREE = re.compile(r"adults entitled to free routine dental care", re.IGNORECASE)
_COHORT_CHILDREN = re.compile(r"children aged 17 or under", re.IGNORECASE)


@dataclass(slots=True)
class PracticeDay:
    """One practice, as reported on one snapshot date."""

    practice_id: str
    snapshot_date: str
    page: str
    status: str
    accepting_adults: bool | None = None
    accepting_children: bool | None = None
    accepting_free_care: bool | None = None
    referral_only: bool = False
    last_confirmed: date | None = None
    last_confirmed_raw: str = ""
    statement: str = ""
    source_url: str = ""
    parse_note: str = ""

    @property
    def recognised(self) -> bool:
        return self.status != UNRECOGNISED


def _text(html: str) -> str:
    return _WS.sub(" ", _TAG.sub(" ", html)).strip()


def routine_care_region(html: str) -> str:
    """The routine-care section only, so urgent-care bullets never leak in.

    Falls back to the whole document when the anchor is absent — overview pages
    for referral-only specialists have no routine-care header at all.
    """
    anchor = _ROUTINE_ANCHOR.search(html)
    if not anchor:
        return html
    tail = html[anchor.end() :]
    nxt = _NEXT_H2.search(tail)
    return tail[: nxt.start()] if nxt else tail


def parse_last_confirmed(html: str) -> tuple[date | None, str]:
    """Extract the "Last confirmed" date.

    Absence is meaningful, not missing: practices that have never declared a
    status have no such element at all. Returning ``None`` here is a finding.
    """
    match = _DATE_EL.search(html)
    if not match:
        return None, ""
    raw = _WS.sub(" ", match.group(1)).strip()
    for fmt in ("%d %B %Y", "%d %b %Y"):
        try:
            # A display date carries no timezone; .date() discards the naive time.
            return datetime.strptime(raw, fmt).date(), raw  # noqa: DTZ007
        except ValueError:
            continue
    return None, raw


def parse_practice(practice_id: str, snapshot_date: str, html: str, *, page: str = "", url: str = "") -> PracticeDay:
    """Parse one captured payload into a practice-day row."""
    region = routine_care_region(html)
    region_text = _text(region)
    full_text = _text(html)
    last_confirmed, raw = parse_last_confirmed(html)

    statement_match = _STATEMENT.search(region_text) or _STATEMENT.search(full_text)
    statement = statement_match.group(0).strip() if statement_match else ""

    row = PracticeDay(
        practice_id=practice_id,
        snapshot_date=snapshot_date,
        page=page,
        status=UNRECOGNISED,
        last_confirmed=last_confirmed,
        last_confirmed_raw=raw,
        statement=statement,
        source_url=url,
    )

    lowered = statement.lower()

    # Order matters: "has not confirmed" and "does not" both contain "not", and
    # the referral-only wording appears alongside a "does not accept" sentence.
    if "only accepts new nhs patients for specialist dental care" in full_text.lower():
        row.status = REFERRAL_ONLY
        row.referral_only = True
        row.accepting_adults = False
        row.accepting_children = False
        row.accepting_free_care = False
        return row

    if "has not confirmed" in lowered:
        row.status = NOT_CONFIRMED
        return row

    if "does not currently accept" in lowered or "does not accept" in lowered:
        row.status = NOT_ACCEPTING
        row.accepting_adults = False
        row.accepting_children = False
        row.accepting_free_care = False
        return row

    if "currently accepts" in lowered or "currently only accepts" in lowered:
        row.status = ACCEPTING
        # Two shapes: a bullet list after "if they are:", or a single cohort
        # named inline ("...if they are children aged 17 or under.").
        cohort_text = " ".join(_text(li) for li in _LI.findall(region)) + " " + statement
        row.accepting_adults = bool(_COHORT_ADULTS.search(cohort_text))
        row.accepting_free_care = bool(_COHORT_FREE.search(cohort_text))
        row.accepting_children = bool(_COHORT_CHILDREN.search(cohort_text))
        if not any((row.accepting_adults, row.accepting_free_care, row.accepting_children)):
            row.parse_note = "accepting but no cohort recognised"
        return row

    row.parse_note = "no recognised acceptance statement"
    return row


@dataclass
class ParseReport:
    """Outcome of parsing one day. Published, per constraint C8."""

    day: str
    total: int = 0
    recognised: int = 0
    with_date: int = 0
    by_status: dict[str, int] = field(default_factory=dict)

    @property
    def recognised_share(self) -> float:
        return self.recognised / self.total if self.total else 0.0

    @property
    def dated_share(self) -> float:
        return self.with_date / self.total if self.total else 0.0

    def summary(self) -> str:
        lines = [
            f"{self.day}: {self.total:,} practices parsed",
            f"  recognised: {self.recognised:,} ({self.recognised_share:.1%})",
            f"  with a Last-confirmed date: {self.with_date:,} ({self.dated_share:.1%})",
        ]
        lines.extend(
            f"    {status:<15} {count:>6,} ({count / self.total:.1%})"
            for status, count in sorted(self.by_status.items(), key=lambda kv: -kv[1])
        )
        return "\n".join(lines)


def parse_day(root: Path | str, day: str) -> tuple[list[PracticeDay], ParseReport]:
    rows: list[PracticeDay] = []
    report = ParseReport(day=day)

    for entry, body in iter_payloads(root, day):
        if entry["practice_id"] == "_sitemap":
            continue
        html = body.decode("utf-8", errors="replace")
        row = parse_practice(
            entry["practice_id"],
            day,
            html,
            page=(entry.get("meta") or {}).get("page", ""),
            url=entry.get("url", ""),
        )
        rows.append(row)
        report.total += 1
        report.recognised += int(row.recognised)
        report.with_date += int(row.last_confirmed is not None)
        report.by_status[row.status] = report.by_status.get(row.status, 0) + 1

    return rows, report


def write_parquet(rows: list[PracticeDay], out_path: Path | str) -> Path:
    import polars as pl

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    frame = pl.DataFrame([asdict(r) for r in rows])
    frame.write_parquet(out_path, compression="zstd")
    return out_path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Parse snapshots into a practice-day table.")
    ap.add_argument("--root", default=str(DEFAULT_ROOT))
    ap.add_argument("--day", default=None, help="capture date (default: every available day)")
    ap.add_argument("--out", default="data/dist/practice_days.parquet")
    ap.add_argument(
        "--min-recognised",
        type=float,
        default=MIN_RECOGNISED_SHARE,
        help="fail if the recognised share falls below this (markup-change alarm)",
    )
    args = ap.parse_args(argv)

    days = [args.day] if args.day else available_days(args.root)
    if not days:
        print("No snapshots found.", file=sys.stderr)
        return 1

    all_rows: list[PracticeDay] = []
    failed = False
    for day in days:
        rows, report = parse_day(args.root, day)
        all_rows.extend(rows)
        print(report.summary())
        if report.recognised_share < args.min_recognised:
            print(
                f"\nFAIL: only {report.recognised_share:.1%} of pages for {day} yielded a "
                f"recognised acceptance state (floor {args.min_recognised:.0%}). "
                "nhs.uk markup has probably changed — the raw payloads are intact, "
                "so fix the parser and re-run.",
                file=sys.stderr,
            )
            failed = True

    if all_rows:
        out = write_parquet(all_rows, args.out)
        print(f"\nWrote {len(all_rows):,} practice-day rows to {out}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
