"""Full-estate capture of English NHS dental practices (ledger step 1.1).

This is the most time-critical code in the project. Availability history exists
nowhere else and accrues only in wall-clock time: a night this does not run is a
night that no later effort recovers.

Route (see ADR-002): enumerate from the published dentist sitemap — one request
for the authoritative set of profile URLs — then fetch each practice's
``/appointments`` page, which carries both the acceptance status and the
"Last confirmed" date. Practices that accept only by clinical referral have no
``/appointments`` page at all, so a 404 falls back to the overview page rather
than silently dropping them.

Nothing here parses. Payloads are stored raw and interpreted later at step 2.3,
because yesterday cannot be re-fetched but it can always be re-parsed.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from client import DEFAULT_CONCURRENCY, DEFAULT_RATE_PER_SEC, PoliteClient
from snapshot import DEFAULT_ROOT, Record, SnapshotWriter, utc_today

SITEMAP_URL = "https://www.nhs.uk/sitemap-profiles-dentist.xml"
SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

# Practices below this count mean the sitemap itself changed shape — abort
# rather than record a bogus night that later looks like a real collapse.
MIN_EXPECTED_PRACTICES = 3_000


@dataclass(frozen=True, slots=True)
class Practice:
    practice_id: str
    profile_url: str
    lastmod: str = ""

    @property
    def appointments_url(self) -> str:
        return f"{self.profile_url}/appointments"


def parse_sitemap(xml_bytes: bytes) -> list[Practice]:
    """Extract practices from the dentist sitemap.

    URLs look like ``https://www.nhs.uk/services/dentist/{slug}/{ODS_ID}``. The
    slug is cosmetic — nhs.uk redirects any slug to canonical — so the trailing
    ID is the only part we depend on.
    """
    root = ET.fromstring(xml_bytes)
    practices: list[Practice] = []
    seen: set[str] = set()

    for url in root.findall("sm:url", SITEMAP_NS):
        loc = (url.findtext("sm:loc", default="", namespaces=SITEMAP_NS) or "").strip()
        if not loc:
            continue
        practice_id = loc.rstrip("/").rsplit("/", 1)[-1]
        if not practice_id or practice_id in seen:
            continue
        seen.add(practice_id)
        practices.append(
            Practice(
                practice_id=practice_id,
                profile_url=loc,
                lastmod=(url.findtext("sm:lastmod", default="", namespaces=SITEMAP_NS) or "").strip(),
            )
        )
    return practices


async def _capture_one(client: PoliteClient, practice: Practice) -> Record:
    """Fetch one practice, falling back to the overview page for referral-only
    specialists (which have no appointments page)."""
    page = "appointments"
    result = await client.get(practice.appointments_url)

    if result.status == 404:
        page = "overview"
        result = await client.get(practice.profile_url)

    return Record(
        practice_id=practice.practice_id,
        url=result.url,
        fetched_at=result.fetched_at,
        status=result.status,
        body=result.body,
        content_type=result.content_type,
        error=result.error,
        meta={"page": page, "lastmod": practice.lastmod, "attempts": result.attempts},
    )


async def capture(
    *,
    root: Path | str = DEFAULT_ROOT,
    day: str | None = None,
    limit: int | None = None,
    rate: float = DEFAULT_RATE_PER_SEC,
    concurrency: int = DEFAULT_CONCURRENCY,
    resume: bool = True,
    min_expected: int = MIN_EXPECTED_PRACTICES,
) -> int:
    """Capture the full estate into one night's snapshot. Returns an exit code."""
    day = day or utc_today()

    async with PoliteClient(rate_per_sec=rate, concurrency=concurrency) as client:
        print(f"Fetching sitemap: {SITEMAP_URL}", flush=True)
        sitemap = await client.get(SITEMAP_URL)
        if not sitemap.ok:
            print(f"FATAL: sitemap unavailable ({sitemap.status} {sitemap.error})", file=sys.stderr)
            return 1

        practices = parse_sitemap(sitemap.body)
        print(f"Sitemap lists {len(practices):,} practices", flush=True)

        if len(practices) < min_expected:
            print(
                f"FATAL: only {len(practices):,} practices in the sitemap "
                f"(expected at least {min_expected:,}) — the source has "
                "probably changed shape. Refusing to record a misleading night.",
                file=sys.stderr,
            )
            return 1

        if limit:
            practices = practices[:limit]
            print(f"Limited to first {len(practices):,} practices (smoke test)", flush=True)

        with SnapshotWriter(root=root, day=day, route="nhsuk-html", resume=resume) as writer:
            # Store the sitemap itself: it is the provenance of this night's
            # estate, and its lastmod values are evidence in their own right.
            writer.add(
                Record(
                    practice_id="_sitemap",
                    url=SITEMAP_URL,
                    fetched_at=sitemap.fetched_at,
                    status=sitemap.status,
                    body=sitemap.body,
                    content_type=sitemap.content_type,
                    meta={"page": "sitemap", "practice_count": len(practices)},
                )
            )

            todo = [p for p in practices if p.practice_id not in writer.already_captured]
            if writer.already_captured:
                print(
                    f"Resuming: {len(writer.already_captured):,} already captured, "
                    f"{len(todo):,} remaining",
                    flush=True,
                )

            queue: asyncio.Queue[Practice] = asyncio.Queue()
            for practice in todo:
                queue.put_nowait(practice)

            total = len(todo)
            done = 0

            async def worker() -> None:
                nonlocal done
                while True:
                    try:
                        practice = queue.get_nowait()
                    except asyncio.QueueEmpty:
                        return
                    try:
                        record = await _capture_one(client, practice)
                        # add() is synchronous, so it is atomic on the event loop
                        # and needs no lock despite the concurrent workers.
                        writer.add(record)
                    finally:
                        done += 1
                        queue.task_done()
                        if done % 250 == 0 or done == total:
                            print(
                                f"  {done:,}/{total:,} "
                                f"(ok {writer.written:,}, failed {writer.failed:,})",
                                flush=True,
                            )

            try:
                await asyncio.gather(*(worker() for _ in range(concurrency)))
            except (KeyboardInterrupt, asyncio.CancelledError):
                # Leaves run.json marked incomplete, so --resume picks it up.
                print("\nInterrupted — partial capture retained and resumable.", file=sys.stderr)
                raise

            print(
                f"\nCaptured {writer.written:,} records "
                f"({writer.failed:,} failed), "
                f"{writer.bytes_new / 1e6:.1f} MB new, "
                f"{writer.bytes_deduped / 1e6:.1f} MB deduplicated",
                flush=True,
            )

    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Capture the full English NHS dental estate.")
    ap.add_argument("--root", default=str(DEFAULT_ROOT), help="snapshot store root")
    ap.add_argument("--day", default=None, help="capture date (default: today, UTC)")
    ap.add_argument("--limit", type=int, default=None, help="only fetch the first N practices")
    ap.add_argument("--rate", type=float, default=DEFAULT_RATE_PER_SEC, help="requests per second")
    ap.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY, help="parallel workers")
    ap.add_argument("--no-resume", action="store_true", help="ignore any partial capture for the day")
    # Accepted so the workflow can pass a route through; only one route exists today.
    ap.add_argument("--route", default="auto", choices=["auto", "html", "api"])
    args = ap.parse_args(argv)

    if args.route == "api":
        print("The API route is not implemented — no key yet (see ADR-002).", file=sys.stderr)
        return 2

    try:
        return asyncio.run(
            capture(
                root=args.root,
                day=args.day,
                limit=args.limit,
                rate=args.rate,
                concurrency=args.concurrency,
                resume=not args.no_resume,
            )
        )
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
