"""Crawl health assertions (ledger step 1.4).

Silent crawler death is the one failure that destroys irreplaceable data. A run
that "succeeds" while quietly returning 400 practices instead of 9,000 is worse
than a run that crashes, because nothing alerts and the gap is only noticed
weeks later when the history is already unrecoverable.

Exit codes are what the GitHub Actions workflow keys on: non-zero fails the job,
which sends the failure email.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from snapshot import DEFAULT_ROOT, available_days, read_run

# Ledger 1.4: record count must sit within ±10% of the prior run.
VOLUME_TOLERANCE = 0.10
# Below this, something is structurally wrong regardless of what yesterday said.
MIN_PLAUSIBLE_RECORDS = 5_000
# A few practices failing is normal internet weather; a tenth of them is not.
MAX_FAILURE_RATE = 0.05


@dataclass(slots=True)
class Check:
    name: str
    passed: bool
    detail: str

    def __str__(self) -> str:
        return f"[{'PASS' if self.passed else 'FAIL'}] {self.name}: {self.detail}"


def check_run(root: Path | str = DEFAULT_ROOT, day: str | None = None) -> list[Check]:
    """Assert a capture is sane, comparing against the previous capture."""
    days = available_days(root)
    if not days:
        return [Check("snapshot exists", False, "no captures found in the store")]

    day = day or days[-1]
    if day not in days:
        return [Check("snapshot exists", False, f"no capture found for {day}")]

    run = read_run(root, day)
    ok = run.get("records_ok", 0)
    failed = run.get("records_failed", 0)
    total = ok + failed
    checks = [
        Check(
            "run completed",
            bool(run.get("complete")),
            f"{day} complete={run.get('complete')} aborted={run.get('aborted')}",
        ),
        Check(
            "plausible volume",
            ok >= MIN_PLAUSIBLE_RECORDS,
            f"{ok:,} records captured (floor {MIN_PLAUSIBLE_RECORDS:,})",
        ),
    ]

    rate = (failed / total) if total else 1.0
    checks.append(
        Check(
            "failure rate",
            rate <= MAX_FAILURE_RATE,
            f"{failed:,}/{total:,} failed ({rate:.1%}, ceiling {MAX_FAILURE_RATE:.0%})",
        )
    )

    prior_days = [d for d in days if d < day]
    if not prior_days:
        checks.append(Check("volume vs prior run", True, "first capture — nothing to compare against"))
        return checks

    prior = read_run(root, prior_days[-1])
    prior_ok = prior.get("records_ok", 0)
    if prior_ok == 0:
        checks.append(Check("volume vs prior run", True, f"prior run {prior_days[-1]} captured nothing"))
        return checks

    drift = (ok - prior_ok) / prior_ok
    checks.append(
        Check(
            "volume vs prior run",
            abs(drift) <= VOLUME_TOLERANCE,
            f"{ok:,} vs {prior_ok:,} on {prior_days[-1]} ({drift:+.1%}, tolerance ±{VOLUME_TOLERANCE:.0%})",
        )
    )
    return checks


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Assert the latest snapshot capture is healthy.")
    ap.add_argument("--root", default=str(DEFAULT_ROOT), help="snapshot store root")
    ap.add_argument("--day", default=None, help="capture date to check (default: latest)")
    args = ap.parse_args(argv)

    checks = check_run(args.root, args.day)
    for check in checks:
        print(check)

    failures = [c for c in checks if not c.passed]
    if failures:
        print(f"\n{len(failures)} check(s) failed — the crawl needs attention.", file=sys.stderr)
        return 1
    print(f"\nAll {len(checks)} checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
