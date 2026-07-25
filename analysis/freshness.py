"""Freshness and trust scoring (ledger step 4.3).

The most honest differentiator in the project, and simultaneously its legal
shield. nhs.uk publishes what a practice claims; nobody publishes *how old the
claim is*. Practices operate under a 90-day update mandate that is widely unmet
— dentists have called the published status "a work of fiction".

Constraint C1 is absolute here: nothing in this module produces a "current
status". Everything it produces is *what was reported, and when it was last
confirmed*. `describe()` exists so that phrasing is generated in one place
rather than reinvented by each surface that renders it.

Two independent signals of staleness
------------------------------------
1. **Declared** — the practice's own "Last confirmed" date, parsed from the page.
2. **Observed** — whether *we* have seen the reported status change across our
   own snapshots.

They disagree usefully. A practice can re-confirm the same answer every month
(fresh but never-changing), or never re-confirm while its page churns. Volatility
is only meaningful once several nights have accrued; with one night it is
correctly zero, not unknown.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from itertools import pairwise

# The mandate practices are meant to meet.
UPDATE_MANDATE_DAYS = 90

NEVER_CONFIRMED = "never_confirmed"
FRESH = "fresh"
OVERDUE = "overdue"
STALE = "stale"
VERY_STALE = "very_stale"
ANCIENT = "ancient"

# Upper bound of days-since-confirmed for each bucket, in order.
_BUCKETS: list[tuple[int, str]] = [
    (UPDATE_MANDATE_DAYS, FRESH),  # within the mandate
    (180, OVERDUE),  # missed the mandate, but recently
    (365, STALE),
    (730, VERY_STALE),
]

_BUCKET_LABELS = {
    FRESH: "confirmed within the 90-day mandate",
    OVERDUE: "past the 90-day mandate",
    STALE: "not confirmed for over 6 months",
    VERY_STALE: "not confirmed for over a year",
    ANCIENT: "not confirmed for over 2 years",
    NEVER_CONFIRMED: "never confirmed",
}


def bucket_for(days: int | None) -> str:
    """Map days-since-confirmed to a freshness bucket."""
    if days is None:
        return NEVER_CONFIRMED
    for limit, name in _BUCKETS:
        if days <= limit:
            return name
    return ANCIENT


@dataclass(slots=True)
class Freshness:
    """A practice's trust profile as of one observation date."""

    practice_id: str
    as_of: date
    status: str
    last_confirmed: date | None
    days_since_confirmed: int | None
    bucket: str
    meets_mandate: bool
    never_confirmed: bool
    # Observed from our own snapshots; requires history to become meaningful.
    observations: int = 1
    status_changes: int = 0
    first_seen: date | None = None
    last_changed: date | None = None

    @property
    def volatile(self) -> bool:
        """Changed status more than once across the nights we have seen.

        One change is a practice updating itself, which is the system working.
        Repeated flipping is the signal worth flagging.
        """
        return self.status_changes > 1

    def describe(self) -> str:
        """C1-compliant rendering. Never asserts a current fact."""
        if self.last_confirmed is None:
            return f"Reported {self.status.replace('_', ' ')}; never confirmed by the practice"
        return (
            f"Reported {self.status.replace('_', ' ')} "
            f"on {self.last_confirmed:%-d %B %Y} "
            f"({self.days_since_confirmed} days before {self.as_of:%-d %B %Y})"
        )

    def label(self) -> str:
        return _BUCKET_LABELS[self.bucket]


def score_practice(
    practice_id: str,
    observations: list[tuple[date, str, date | None]],
) -> Freshness:
    """Score one practice from its observation history.

    ``observations`` is ``(snapshot_date, status, last_confirmed)`` per night,
    in any order. The most recent night defines the reported state; the whole
    series defines volatility.
    """
    if not observations:
        raise ValueError(f"no observations for {practice_id}")

    ordered = sorted(observations, key=lambda o: o[0])
    as_of, status, last_confirmed = ordered[-1]

    days = (as_of - last_confirmed).days if last_confirmed else None
    # A confirmation date in the future is a source error, not negative age.
    if days is not None and days < 0:
        days = 0

    changes = 0
    last_changed: date | None = None
    for prev, curr in pairwise(ordered):
        if prev[1] != curr[1]:
            changes += 1
            last_changed = curr[0]

    return Freshness(
        practice_id=practice_id,
        as_of=as_of,
        status=status,
        last_confirmed=last_confirmed,
        days_since_confirmed=days,
        bucket=bucket_for(days),
        meets_mandate=days is not None and days <= UPDATE_MANDATE_DAYS,
        never_confirmed=last_confirmed is None,
        observations=len(ordered),
        status_changes=changes,
        first_seen=ordered[0][0],
        last_changed=last_changed,
    )


def score_all(rows: list) -> list[Freshness]:
    """Score every practice from a practice-day table (``parse.PracticeDay``)."""
    grouped: dict[str, list[tuple[date, str, date | None]]] = defaultdict(list)
    for row in rows:
        snapshot = row.snapshot_date
        if isinstance(snapshot, str):
            snapshot = date.fromisoformat(snapshot)
        grouped[row.practice_id].append((snapshot, row.status, row.last_confirmed))

    return [score_practice(pid, obs) for pid, obs in sorted(grouped.items())]


def summarise(scores: list[Freshness]) -> dict:
    """Estate-wide freshness. This is the headline the project exists to publish."""
    total = len(scores)
    if not total:
        return {"total": 0}

    buckets: dict[str, int] = defaultdict(int)
    for s in scores:
        buckets[s.bucket] += 1

    dated = [s for s in scores if s.days_since_confirmed is not None]
    ages = sorted(s.days_since_confirmed for s in dated)
    meeting = sum(1 for s in scores if s.meets_mandate)

    return {
        "total": total,
        "buckets": dict(buckets),
        "never_confirmed": buckets[NEVER_CONFIRMED],
        "meets_mandate": meeting,
        "mandate_compliance_rate": meeting / total,
        "median_days_since_confirmed": ages[len(ages) // 2] if ages else None,
        "oldest_days_since_confirmed": ages[-1] if ages else None,
        "volatile": sum(1 for s in scores if s.volatile),
        "observations_per_practice": (
            sum(s.observations for s in scores) / total if total else 0
        ),
    }


def format_summary(stats: dict) -> str:
    if not stats.get("total"):
        return "No practices scored."

    lines = [
        f"{stats['total']:,} practices scored",
        (
            f"  meeting the {UPDATE_MANDATE_DAYS}-day mandate: "
            f"{stats['meets_mandate']:,} ({stats['mandate_compliance_rate']:.1%})"
        ),
        f"  never confirmed: {stats['never_confirmed']:,}",
        f"  median days since confirmed: {stats['median_days_since_confirmed']}",
        f"  oldest: {stats['oldest_days_since_confirmed']} days",
        "",
        "  freshness distribution:",
    ]
    order = [FRESH, OVERDUE, STALE, VERY_STALE, ANCIENT, NEVER_CONFIRMED]
    for name in order:
        count = stats["buckets"].get(name, 0)
        if count:
            lines.append(
                f"    {name:<16} {count:>6,} ({count / stats['total']:>5.1%})  "
                f"{_BUCKET_LABELS[name]}"
            )
    if stats["observations_per_practice"] < 2:
        lines.append("")
        lines.append(
            "  Volatility is not yet meaningful — it needs several nights of "
            "accrued history. This is expected on early runs."
        )
    return "\n".join(lines)
