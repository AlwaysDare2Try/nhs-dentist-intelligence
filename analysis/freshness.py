"""Freshness and trust scoring (ledger step 4.3).

The most honest differentiator in the project, and simultaneously its legal
shield. nhs.uk publishes what a practice claims; nobody publishes *how old the
claim is*. Practices operate under a 90-day update mandate that is widely unmet
— dentists have called the published status "a work of fiction".

Constraint C1 is absolute here: nothing in this module produces a "current
status". Everything it produces is *what was reported, and when it was last
confirmed*. `describe()` exists so that phrasing is generated in one place
rather than reinvented by each surface that renders it.

The 90-day reset, and why this module has two age signals
---------------------------------------------------------
Night one established something that changes the design: **nhs.uk resets a
practice's acceptance status to "not confirmed" once its declaration lapses.**
Every practice carrying a declared status had confirmed within 89 days; not one
sat between 90 days and the fifteen-year range the sitemap spans.

So ``days_since_confirmed`` is **capped at 90 by construction** and is nearly
worthless on its own — it cannot distinguish a practice that lapsed last week
from one silent since 2011. Both simply read "not confirmed".

The age of the silent majority lives elsewhere: in the sitemap's ``<lastmod>``
for that profile. 51 practices have not had their page touched since 2011, and
every one reads "not confirmed".

This module therefore carries two age signals and keeps them distinct:

1. **Declared age** — the practice's own "Last confirmed" date. Precise, but
   bounded to a single quarter, and only exists for ~71% of the estate.
2. **Silence age** — days since the profile page last changed. Coarser (a page
   can change for reasons unrelated to acceptance), but unbounded, and it is the
   *only* signal available for the ~29% that have never declared.

``effective_days`` picks the right one per practice and records which in
``age_evidence``, so no downstream surface has to guess.

A third, independent signal is **observed** volatility: whether *we* have seen
the reported status change across our own snapshots. It needs several nights to
mean anything; with one night it is correctly zero, not unknown.
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

# Deliberately neutral wording. A practice can land in FRESH on either signal,
# and only the confirmation signal means the mandate was actually met — so the
# bucket must not claim confirmation. Mandate compliance is reported separately
# and exactly, from `meets_mandate`.
_BUCKET_LABELS = {
    FRESH: "sign of activity within the last 3 months",
    OVERDUE: "no sign of activity for over 3 months",
    STALE: "no sign of activity for over 6 months",
    VERY_STALE: "no sign of activity for over a year",
    ANCIENT: "no sign of activity for over 2 years",
    NEVER_CONFIRMED: "never confirmed, and age unknown",
}

# Which signal produced effective_days.
EVIDENCE_CONFIRMED = "confirmed_date"
EVIDENCE_LASTMOD = "page_lastmod"
EVIDENCE_NONE = "none"


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
    # Silence signal, for practices nhs.uk has reset to "not confirmed".
    page_lastmod: date | None = None
    days_since_page_change: int | None = None
    effective_days: int | None = None
    age_evidence: str = EVIDENCE_NONE
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
            base = f"Reported {self.status.replace('_', ' ')}; never confirmed by the practice"
            if self.page_lastmod is not None:
                return (
                    f"{base}. Profile last changed {self.page_lastmod:%-d %B %Y} "
                    f"({self.days_since_page_change} days before {self.as_of:%-d %B %Y})"
                )
            return base
        return (
            f"Reported {self.status.replace('_', ' ')} "
            f"on {self.last_confirmed:%-d %B %Y} "
            f"({self.days_since_confirmed} days before {self.as_of:%-d %B %Y})"
        )

    def label(self) -> str:
        """Bucket wording, qualified by which signal produced it.

        Only the practice's own confirmation date evidences the 90-day mandate;
        a recently-changed page does not, and must not be described as though
        it did.
        """
        base = _BUCKET_LABELS[self.bucket]
        if self.age_evidence == EVIDENCE_CONFIRMED and self.bucket == FRESH:
            return "confirmed within the 90-day mandate"
        if self.age_evidence == EVIDENCE_LASTMOD:
            return f"{base} (profile change only — never confirmed)"
        return base


def _days_between(as_of: date, then: date | None) -> int | None:
    """Age in days, clamped at zero — a future date is a source error, not a
    negative age."""
    if then is None:
        return None
    return max(0, (as_of - then).days)


def score_practice(
    practice_id: str,
    observations: list[tuple[date, str, date | None]],
    page_lastmod: date | None = None,
) -> Freshness:
    """Score one practice from its observation history.

    ``observations`` is ``(snapshot_date, status, last_confirmed)`` per night,
    in any order. The most recent night defines the reported state; the whole
    series defines volatility. ``page_lastmod`` supplies the silence signal for
    practices nhs.uk has reset to "not confirmed".
    """
    if not observations:
        raise ValueError(f"no observations for {practice_id}")

    ordered = sorted(observations, key=lambda o: o[0])
    as_of, status, last_confirmed = ordered[-1]

    days = _days_between(as_of, last_confirmed)
    lastmod_days = _days_between(as_of, page_lastmod)

    # Prefer the practice's own declaration; fall back to page silence. Without
    # either, age is genuinely unknown and must not be implied.
    if days is not None:
        effective, evidence = days, EVIDENCE_CONFIRMED
    elif lastmod_days is not None:
        effective, evidence = lastmod_days, EVIDENCE_LASTMOD
    else:
        effective, evidence = None, EVIDENCE_NONE

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
        # Bucketed on the effective signal, so a practice silent since 2011
        # lands in ANCIENT rather than collapsing into NEVER_CONFIRMED.
        bucket=bucket_for(effective) if effective is not None else NEVER_CONFIRMED,
        meets_mandate=days is not None and days <= UPDATE_MANDATE_DAYS,
        never_confirmed=last_confirmed is None,
        page_lastmod=page_lastmod,
        days_since_page_change=lastmod_days,
        effective_days=effective,
        age_evidence=evidence,
        observations=len(ordered),
        status_changes=changes,
        first_seen=ordered[0][0],
        last_changed=last_changed,
    )


def score_all(rows: list) -> list[Freshness]:
    """Score every practice from a practice-day table (``parse.PracticeDay``)."""
    grouped: dict[str, list[tuple[date, str, date | None]]] = defaultdict(list)
    lastmods: dict[str, date | None] = {}
    for row in rows:
        snapshot = row.snapshot_date
        if isinstance(snapshot, str):
            snapshot = date.fromisoformat(snapshot)
        grouped[row.practice_id].append((snapshot, row.status, row.last_confirmed))

        raw = getattr(row, "page_lastmod", "") or ""
        if raw and lastmods.get(row.practice_id) is None:
            try:
                lastmods[row.practice_id] = date.fromisoformat(raw[:10])
            except ValueError:
                lastmods[row.practice_id] = None

    return [
        score_practice(pid, obs, lastmods.get(pid))
        for pid, obs in sorted(grouped.items())
    ]


def summarise(scores: list[Freshness]) -> dict:
    """Estate-wide freshness. This is the headline the project exists to publish."""
    total = len(scores)
    if not total:
        return {"total": 0}

    buckets: dict[str, int] = defaultdict(int)
    for s in scores:
        buckets[s.bucket] += 1

    ages = sorted(s.effective_days for s in scores if s.effective_days is not None)
    meeting = sum(1 for s in scores if s.meets_mandate)
    evidence: dict[str, int] = defaultdict(int)
    for s in scores:
        evidence[s.age_evidence] += 1

    return {
        "total": total,
        "buckets": dict(buckets),
        "never_confirmed": sum(1 for s in scores if s.never_confirmed),
        "age_unknown": buckets[NEVER_CONFIRMED],
        "evidence": dict(evidence),
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
        f"  never confirmed (status reset by nhs.uk): {stats['never_confirmed']:,}",
        f"  median age (best available signal): {stats['median_days_since_confirmed']} days",
        f"  oldest: {stats['oldest_days_since_confirmed']} days",
        "",
        "  age evidence:",
        (
            f"    from the practice's own confirmation date: "
            f"{stats['evidence'].get(EVIDENCE_CONFIRMED, 0):,}"
        ),
        (
            f"    from profile last-changed date (silence):  "
            f"{stats['evidence'].get(EVIDENCE_LASTMOD, 0):,}"
        ),
        (
            f"    no age signal at all:                      "
            f"{stats['evidence'].get(EVIDENCE_NONE, 0):,}"
        ),
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
