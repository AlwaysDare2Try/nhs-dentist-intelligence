"""Entity resolution: nhs.uk ↔ ODS ↔ NHSBSA (ledger step 3.3).

**The hidden cost the charter never listed.** No shared key exists across the
three sources, and every supply-versus-demand output in §4 depends on bridging
them. The build plan calls this the highest schedule risk and timeboxes it to two
days, shipping at whatever match rate is reached — and publishing that number
(constraint C8). This module is built to that instruction: it does not pretend to
a certainty it lacks, and it reports its failures as prominently as its successes.

The three legs are not equally hard
-----------------------------------
**nhs.uk ↔ ODS is mechanical.** nhs.uk zero-pads the ODS numeric part to six
digits (``V01699`` → ``V001699``). Measured at 99.2%. Handled in ``ods.py``;
nothing fuzzy is needed and nothing fuzzy is used.

**BSA ↔ ODS is the real problem.** The BSA key is ``CONTRACT_NUMBER``, which
exists in no other source. What every contract does carry is a postcode, and
88.5% of contracts sit at a postcode holding exactly one ODS practice — those
resolve on postcode alone, with the name comparison kept only as evidence.

The residual is the interesting part: contracts at a postcode holding several
practices (dental centres, health hubs, multi-site providers). Those are decided
by name similarity within the postcode block, and only when one candidate is
clearly better than the runner-up. A near-tie is *not* guessed — it goes to a
review queue, because a wrong link silently attributes one practice's activity to
another and would corrupt every downstream rate.

Contracts are many-to-many with sites by design: one contract can cover several
practices and a practice can hold several contracts. This module resolves
contract → best practice and records the ambiguity rather than flattening it.

Why the name scores look bad, and why that is fine
--------------------------------------------------
The two sources do not name the same *kind* of thing. BSA's ``PROVIDER_NAME`` is
the **contract holder**, usually the dentists personally — "Dr H S Thiara, Mrs R
K Mattu". ODS's ``Name`` is the **site**, and is very often pure boilerplate —
"DENTAL SURGERY", "THE SURGERY", "THE HEALTH CENTRE". Around a quarter of ODS
names reduce to nothing at all once boilerplate is stripped.

So a low name score is usually a semantic mismatch between the sources, not
evidence of a bad link. This is exactly why postcode-unique matches are accepted
**without** a name gate: gating on name similarity would have discarded ~1,700
correct matches whose ODS name carries no identifying content. ``summarise()``
reports unscoreable names separately from genuinely weak ones so the distinction
is visible rather than buried in an average.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

from rapidfuzz import fuzz

# Accept a name match inside an ambiguous postcode block only when the best
# candidate scores at least this well...
NAME_ACCEPT_SCORE = 80.0
# ...and beats the runner-up by at least this margin. Two practices scoring 88
# and 86 in the same building is a coin toss, and a coin toss here silently
# misattributes a decade of activity.
NAME_ACCEPT_MARGIN = 10.0

MATCH_POSTCODE_UNIQUE = "postcode_unique"
MATCH_POSTCODE_AND_NAME = "postcode_and_name"
MATCH_AMBIGUOUS = "ambiguous_review"
MATCH_NO_POSTCODE_MATCH = "no_postcode_match"
MATCH_NO_POSTCODE = "no_postcode"

# Corporate and descriptive noise that carries no identifying signal. Removing it
# stops "SMILE DENTAL PRACTICE LTD" and "SMILE DENTAL CARE LIMITED" scoring apart
# on boilerplate rather than on the part that actually names the practice.
_NOISE = re.compile(
    r"\b("
    r"limited|ltd|llp|plc|uk|the|and|t/?a|"
    r"dental|dentist|dentists|dentistry|surgery|surgeries|practice|practices|"
    r"clinic|clinics|centre|center|care|health|healthcare|group|associates"
    r")\b",
    re.IGNORECASE,
)
_PUNCT = re.compile(r"[^a-z0-9 ]+")
# Apostrophes are dropped rather than split on, so "St Mary's" collapses to
# "marys" and matches "St Marys" — possessives are common in practice names.
_APOSTROPHE = re.compile(r"['’]")
_WS = re.compile(r"\s+")


def normalise_name(name: str) -> str:
    """Reduce a practice name to its identifying core."""
    text = (name or "").lower()
    text = _APOSTROPHE.sub("", text)
    text = _PUNCT.sub(" ", text)
    text = _NOISE.sub(" ", text)
    return _WS.sub(" ", text).strip()


def normalise_postcode(postcode: str) -> str:
    return "".join((postcode or "").split()).upper()


def name_score(a: str, b: str) -> float:
    """Similarity of two practice names, 0–100.

    ``token_set_ratio`` is deliberate: practice names reorder freely and carry
    extra tokens ("Mr K J Khan" vs "Khan Dental Surgery"), which punishes
    sequence-based ratios for no reason.
    """
    left, right = normalise_name(a), normalise_name(b)
    if not left or not right:
        # Nothing identifying survived normalisation — refuse to score rather
        # than return a misleading 0 or 100.
        return 0.0
    return float(fuzz.token_set_ratio(left, right))


@dataclass(slots=True)
class Candidate:
    org_id: str
    name: str
    postcode: str
    score: float = 0.0


@dataclass(slots=True)
class Match:
    """One contract's resolution, with the evidence that produced it."""

    contract_number: str
    provider_name: str
    postcode: str
    org_id: str = ""
    ods_name: str = ""
    method: str = MATCH_NO_POSTCODE
    score: float = 0.0
    runner_up_score: float = 0.0
    candidates: int = 0

    @property
    def resolved(self) -> bool:
        return bool(self.org_id)

    @property
    def needs_review(self) -> bool:
        return self.method == MATCH_AMBIGUOUS


def build_postcode_index(practices) -> dict[str, list[Candidate]]:
    """Index ODS practices by normalised postcode — the blocking key."""
    index: dict[str, list[Candidate]] = defaultdict(list)
    for p in practices:
        pc = normalise_postcode(p.postcode)
        if pc:
            index[pc].append(Candidate(org_id=p.org_id, name=p.name, postcode=pc))
    return index


def resolve_contract(
    contract_number: str,
    provider_name: str,
    postcode: str,
    index: dict[str, list[Candidate]],
) -> Match:
    """Resolve one BSA contract to an ODS practice."""
    pc = normalise_postcode(postcode)
    match = Match(contract_number=contract_number, provider_name=provider_name, postcode=pc)

    if not pc:
        return match

    block = index.get(pc, [])
    match.candidates = len(block)

    if not block:
        match.method = MATCH_NO_POSTCODE_MATCH
        return match

    if len(block) == 1:
        only = block[0]
        match.org_id = only.org_id
        match.ods_name = only.name
        match.method = MATCH_POSTCODE_UNIQUE
        # Recorded as evidence, not used as a gate: the postcode is already
        # strong, and a renamed practice should not be dropped for it.
        match.score = name_score(provider_name, only.name)
        return match

    scored = sorted(
        (Candidate(c.org_id, c.name, c.postcode, name_score(provider_name, c.name)) for c in block),
        key=lambda c: -c.score,
    )
    best, runner_up = scored[0], scored[1]
    match.score = best.score
    match.runner_up_score = runner_up.score

    if best.score >= NAME_ACCEPT_SCORE and (best.score - runner_up.score) >= NAME_ACCEPT_MARGIN:
        match.org_id = best.org_id
        match.ods_name = best.name
        match.method = MATCH_POSTCODE_AND_NAME
    else:
        # Deliberately unresolved. A wrong link here misattributes activity.
        match.method = MATCH_AMBIGUOUS
        match.ods_name = best.name

    return match


def resolve_all(contracts, index: dict[str, list[Candidate]]) -> list[Match]:
    """Resolve every contract. ``contracts`` yields (number, name, postcode)."""
    return [resolve_contract(num, name, pc, index) for num, name, pc in contracts]


def summarise(matches: list[Match]) -> dict:
    """The match rate, reported honestly — this number gets published (C8)."""
    total = len(matches)
    by_method: dict[str, int] = defaultdict(int)
    for m in matches:
        by_method[m.method] += 1

    resolved = [m for m in matches if m.resolved]
    # One ODS practice claimed by several contracts is expected (many-to-many),
    # but worth surfacing rather than hiding.
    per_org: dict[str, int] = defaultdict(int)
    for m in resolved:
        per_org[m.org_id] += 1

    return {
        "total_contracts": total,
        "resolved": len(resolved),
        "match_rate": len(resolved) / total if total else 0.0,
        "needs_review": by_method[MATCH_AMBIGUOUS],
        "by_method": dict(by_method),
        "distinct_ods_matched": len(per_org),
        "ods_with_multiple_contracts": sum(1 for n in per_org.values() if n > 1),
        # Split deliberately: a 0 means the names carried no identifying content
        # (usually a generic ODS site name), which is a different fact from a
        # name that could be compared and came out poor.
        "unscoreable_name": sum(1 for m in resolved if m.score == 0),
        "resolved_with_weak_name": sum(1 for m in resolved if 0 < m.score < 60),
        "mean_name_score_of_resolved": (
            sum(m.score for m in resolved) / len(resolved) if resolved else 0.0
        ),
        "mean_name_score_where_comparable": (
            sum(m.score for m in resolved if m.score > 0)
            / max(1, sum(1 for m in resolved if m.score > 0))
        ),
    }


def format_summary(stats: dict) -> str:
    total = stats["total_contracts"]
    if not total:
        return "No contracts to resolve."

    lines = [
        f"{total:,} BSA contracts resolved against the ODS register",
        f"  matched:      {stats['resolved']:,} ({stats['match_rate']:.1%})",
        f"  needs review: {stats['needs_review']:,}",
        "",
        "  by method:",
    ]
    labels = {
        MATCH_POSTCODE_UNIQUE: "postcode held exactly one practice",
        MATCH_POSTCODE_AND_NAME: "postcode shared; name decided it",
        MATCH_AMBIGUOUS: "postcode shared; name too close to call — REVIEW",
        MATCH_NO_POSTCODE_MATCH: "postcode not in the ODS register",
        MATCH_NO_POSTCODE: "contract carries no postcode",
    }
    for method, label in labels.items():
        count = stats["by_method"].get(method, 0)
        if count:
            lines.append(f"    {count:>6,} ({count / total:>5.1%})  {label}")

    lines += [
        "",
        f"  distinct ODS practices matched: {stats['distinct_ods_matched']:,}",
        (
            f"  practices holding >1 contract:  {stats['ods_with_multiple_contracts']:,} "
            "(expected — contracts are many-to-many with sites)"
        ),
        "",
        "  name-evidence quality (names are a weak signal between these sources —",
        "  BSA names the contract holder, ODS names the site, often generically):",
        (
            f"    unscoreable (no identifying content either side): "
            f"{stats['unscoreable_name']:,}"
        ),
        (
            f"    comparable but weak (<60):                       "
            f"{stats['resolved_with_weak_name']:,}"
        ),
        (
            f"    mean score where names were comparable:          "
            f"{stats['mean_name_score_where_comparable']:.1f}"
        ),
    ]
    return "\n".join(lines)


def write_outputs(matches: list[Match], out_dir: Path | str) -> tuple[Path, Path]:
    """Write the crosswalk and the manual review queue."""
    import polars as pl

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    frame = pl.DataFrame([asdict(m) for m in matches])
    crosswalk = out_dir / "contract_to_ods.parquet"
    frame.write_parquet(crosswalk, compression="zstd")

    review = out_dir / "match_review_queue.csv"
    queue = frame.filter(pl.col("method") == MATCH_AMBIGUOUS).sort("postcode")
    queue.write_csv(review)
    return crosswalk, review


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Resolve BSA contracts to ODS practices.")
    ap.add_argument("--out-dir", default="data/dist")
    ap.add_argument("--month", default=None, help="BSA month to resolve (default: latest)")
    args = ap.parse_args(argv)

    from bsa import load_activity
    from ods import load_register

    try:
        practices = load_register()
        activity = load_activity()
    except FileNotFoundError as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 1

    month = args.month or max((r.year_month for r in activity if r.year_month), default="")
    latest = [r for r in activity if r.year_month == month]
    print(f"Resolving contracts active in {month} against {len(practices):,} ODS practices")

    seen: dict[str, tuple[str, str]] = {}
    for r in latest:
        seen.setdefault(r.contract_number, (r.provider_name, r.postcode))

    index = build_postcode_index(practices)
    matches = resolve_all(((num, n, pc) for num, (n, pc) in seen.items()), index)

    stats = summarise(matches)
    print()
    print(format_summary(stats))

    crosswalk, review = write_outputs(matches, args.out_dir)
    print(f"\nWrote crosswalk to {crosswalk}")
    print(f"Wrote {stats['needs_review']:,} rows needing review to {review}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
