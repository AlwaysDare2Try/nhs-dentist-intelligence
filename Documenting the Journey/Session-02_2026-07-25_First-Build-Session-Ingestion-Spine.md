# Session 02 — First Build Session: The Ingestion Spine

**Date:** 2026-07-25
**Preceded by:** `Session-01_2026-07-25_Concept-Ingestion-and-Viability-Analysis.md`
**Plan of record:** `Build-Plan-v1_2026-07-25_Delivery-Ledger-and-North-Star.md`
**Outcome:** §0 complete, §1 complete, §2 complete, 3.1 and 3.2 complete. Gate **DG1 cleared**. First full-estate capture running.

---

## What this session was

The first session that wrote code. The owner supplied an operating rhythm — *Plan → Implement → Check → Improve*, run as iterative loops with a coordinator/sub-agent split and a live `CLAUDE_PROGRESS.md` — and authorised working without waiting for approval between loops.

Six loops ran. Five ledger phases moved.

| Loop | Ledger | Delivered |
|---|---|---|
| 0 | 0.1, 0.2 | Repo, toolchain, CI, ADR-001 |
| 1a | 1.2, 1.3, 1.4 | Snapshot store, health alarms, nightly workflow |
| 1b | 1.1 | Polite HTTP client |
| 2 | 1.1, 2.1, 2.2 | Full-estate fetcher, ADR-002, **Q1 answered** |
| 3 | 2.3 | Snapshot parser |
| 4 | 3.1 | ODS register loader |
| 5 | 3.2 | Geocoding and geography |

---

## The decision that shaped the session

**Build everything around the unknown, so the unknown never blocks.**

The one thing the viability analysis could not confirm (Q1) was whether the source carries acceptance status and a last-updated date. Rather than answering it first and building second, the session dispatched that investigation to a sub-agent and simultaneously built every part of §1 that did not depend on the answer: the storage layer, the health alarms, the schedule, and the HTTP client. All four are route-agnostic by construction.

When the answer arrived — **yes, both are present** — the only thing left to write was the fetcher itself. Roughly 90 minutes of wall-clock investigation cost nothing in delivery time.

This is the same principle as *capture raw, parse later*, applied to the build order rather than the data.

---

## Findings

**Q1: answered YES. Gate DG1 cleared.** nhs.uk carries acceptance status *and* a "Last confirmed" date, at the same cohort granularity the Service Search API v3 offers. Scraping loses nothing material except timestamp precision. Recorded in ADR-002.

**The estate is 6,407 practices, not ~9,000.** The plan's figure was an approximation. 6,407 is the published nhs.uk profile count; 9,779 is ODS *active dental practices*, which includes private-only practices and prison dental units with no public profile. Both numbers are correct and they measure different things — a distinction that would have caused a false alarm later when the crawler "only" returned 6,407.

**Freshness is visible on day one — but not in the way first assumed.** The sitemap's `lastmod` values span 2026-07-24 back to **2011-01-06**, and this was initially written up as "some practices have not confirmed their status in fifteen years."

**That was wrong, and the first full capture disproved it.** `lastmod` is *page* modification, not status confirmation. The correction matters, because the truth changes the product:

Every practice carrying a declared acceptance status was confirmed within **89 days**. Not one sat between 90 days and fifteen years. Cross-referencing status against `lastmod` year made the mechanism obvious — no practice with a pre-2026 `lastmod` has *any* declared status; all 447 of them read `not_confirmed` or `referral_only`.

**nhs.uk resets a practice's acceptance status to "not confirmed" once the 90-day declaration lapses.** So `days_since_confirmed` is capped at 90 by construction and is nearly worthless as a differentiator — the freshness score cannot range beyond a single quarter.

The real signal is in the other population. 29.1% of the estate has *no* declared status, and their `lastmod` is where the decade of silence actually lives: 51 practices have not touched their profile since 2011, and every one of them reads "not confirmed". Step 4.3's design changes accordingly — freshness for the undeclared majority must come from `lastmod`, not from a confirmation date that does not exist.

*Lesson: the most interesting finding of the session was a correction to an earlier finding of the same session. Recording the first claim confidently is what made it checkable.*

**Q2, first leg: 99.2%.** 6,358 of 6,407 nhs.uk practices resolve to an active ODS record using nothing but the zero-padding convention (`V01699` → `V001699`). The NHSBSA contract leg — the genuinely hard one, because contracts are many-to-many with sites — remains for step 3.3.

**Geocoding: 99.8%**, clearing the ledger's >99% gate. England 8,714, Wales 363, Isle of Man 14, 19 unmatched.

**Compliance is clean.** robots.txt permits these paths, the terms contain no anti-scraping clause, and content is OGL. Our honest bot User-Agent — naming the project with a contact URL — was tested and accepted, so **no browser spoofing is used anywhere**. That mattered: spoofing would have been easy and would have quietly made the project harder to defend.

---

## Where the plan was wrong, and what changed

Two ledger specifications were implemented differently. Neither reverses an agreed decision, so neither raised an ADR — but both are recorded here rather than left as silent drift.

**1. "Gzipped JSON per practice in dated directories" (step 1.2).**
Taken literally, ~9,000 files per night is 3.3 million files a year in git. Replaced with a **content-addressed store**: payloads live at `blobs/<sha256>.gz` and each night writes a manifest mapping practice → hash. An unchanged practice costs zero additional bytes, while every night still resolves to a complete, independently parseable view of the estate.

This was validated before committing to it: the same appointments page fetched twice, three seconds apart, is **byte-identical**. Had the pages carried per-request nonces, dedup would have gained nothing and the design would have been wrong. Evidence first, then the design.

**2. "ONSPD quarterly CSV" (step 3.2).**
Replaced with the postcodes.io bulk API, which serves the same ONS-derived data under OGL and returns everything the plan asked for *plus* ICB and IMD — in 92 requests rather than a ~1 GB quarterly download. Raw responses are stored, so the pipeline reproduces without re-fetching and the CSV route stays open if the service proves unreliable.

A third decision deliberately *refused* a shortcut: step 3.1 does **not** filter the ODS register to England. The list endpoint carries no country field, and guessing from postcode prefixes would misclassify practices along the Welsh border. Country is resolved properly at 3.2 from authoritative data. The geocoding result vindicated this — 363 Welsh and 14 Isle of Man practices sit in the register, exactly the population a prefix heuristic would have mangled.

---

## Dead ends and mistakes

Recorded because the case study is worth more with them than without.

**The test harness that tested nothing.** Five HTTP client tests monkey-patched `__aenter__` on the *instance*. Python resolves dunder methods on the *type*, so the patch never applied and those five tests were silently hitting the live network — passing for the wrong reason, and slowly. Caught only because the suite was suspiciously slow. Fixed by making the transport injectable, which is the better design anyway.

*Lesson: a test that passes slowly deserves the same suspicion as one that fails.*

**A 90-second test suite.** Tests for 503 handling sat through real exponential backoff. Making the backoff scale injectable took the suite from 90s to 6.5s. Left alone, this would have taxed every future loop and eventually discouraged running tests at all.

**A confident conclusion from a zero-byte file.** A byte-stability check compared two downloads and reported "IDENTICAL — dedup will work". Both files were empty: nhs.uk returned 302 and `curl` had not been told to follow redirects. The comparison was true and worthless. Re-run with `-L`, it gave the same conclusion for a real reason.

*Lesson: verify the measurement produced data before trusting what it says about the data.*

**A misread of the data as a bug in the data.** A first pass at the captured payloads showed four of eight practices with "NO MARKER" and all eight dated identically — read initially as a capture problem. Both were artefacts of the checking script: the regex omitted the "does not currently accept" wording, and the uniform date was correct, because the sitemap is ordered newest-first and the first eight entries genuinely all confirmed on the same day. The data was right; the question was wrong.

**A stall that was not a stall.** Capture progress was briefly diagnosed as too slow. Measured properly over 60 seconds it was 0.97 req/s against a 1.0 target. The error was mental arithmetic about elapsed time, not the crawler.

**A trap that was caught in time.** Every appointments page in England carries an urgent-care bullet list ("an urgent appointment at short notice"). A cohort parser reading list items document-wide would have marked the entire estate as accepting patients — a plausible-looking, completely wrong national dataset. Scoping extraction to the routine-care region prevented it, and a test now pins that behaviour.

---

## Notes on the AI-assisted method (objective O5)

**Sub-agent economics are not obvious.** Two sub-agents ran this session. The first — investigating the fetch route — consumed ~134,000 tokens producing a report of a few thousand. That was excellent value: the work was dozens of exploratory HTTP calls whose raw output would have flooded the coordinator's context and displaced everything else.

A third delegation was considered and **rejected**: building the ODS loader. That task was mostly writing code from a specification already in hand, which is cheap in the coordinator's context and would have cost far more in a fresh agent that had to rediscover the context first. Delegation pays when the work is *noisy* — high input, low output — not merely when it is separable.

**Specifying the boundary matters more than specifying the task.** The productive sub-agent prompts named the files not to touch, the setup steps that are non-obvious (`uv` is not on the default PATH), the concurrent crawl not to disturb, and demanded an explicit "what I tested vs what I assumed" section. That last section is where the real value sits: the first agent's honest admission that it never verified a bare `curl` User-Agent led directly to testing our own, which is why the project does not spoof a browser.

**The plan held.** Nothing in this session required re-litigating Session 01. The ledger was consulted, followed, and deviated from only twice — both times with the deviation recorded and the original route left open. Having the agreed ground written down meant build decisions were about *implementation*, never about *direction*.

---

## Night one

The capture completed: **6,407 practices, zero failures, 43.1 MB.** All four health checks passed. The parser recognised **100%** of pages.

| Reported state | Practices | Share |
|---|---:|---:|
| Accepting (any cohort) | 2,545 | 39.7% |
| Not accepting | 1,997 | 31.2% |
| Not confirmed | 1,281 | 20.0% |
| Referral-only specialist | 584 | 9.1% |

By cohort — the number that actually matters for product framing:

| Cohort | Accepting | Share |
|---|---:|---:|
| Adults 18+ | 1,778 | **27.8%** |
| Adults entitled to free care | 1,856 | 29.0% |
| Children 17 and under | 2,533 | 39.5% |

This vindicates the repositioning decision (D2) with our own data. A headline "39.7% accepting" is misleading: for the adult searching for a dentist, fewer than three practices in ten are open, and 29.1% of the estate will not say either way. The viability analysis's ~9-in-10-closed figure was drawn from a different denominator and a worse year, but the direction is confirmed — **leading with an "accepting" filter would still return mostly nothing.**

## Blocked mid-session

The NHSBSA activity ingest (4.1) was delegated to a sub-agent that **terminated when the account hit its monthly spend limit**. It had identified the correct dataset — `english-contractor-monthly-general-dental-activity`, contract-level and monthly back to April 2016 — and written 753 lines that reference two names it never defined. The draft is parked at `ingest/bsa.py.wip`, deliberately outside the lint and import path so it cannot be mistaken for working code. Its research is preserved; its claims are not trusted.

## Night two — the record proves itself in 24 hours

The second capture ran on 2026-07-26: 6,408 records, zero failures, and **0.1 MB new against 43.0 MB deduplicated**. The whole store is still 51 MB. A second complete night of England cost about a hundred kilobytes, which settles any doubt about the content-addressed deviation at step 1.2.

Two practices changed status overnight — the first entries in a record that exists nowhere else:

| Practice | Night 1 (25 Jul) | Night 2 (26 Jul) | Last confirmed |
|---|---|---|---|
| V027041 | not accepting | **not confirmed** | 2026-04-27 → gone |
| V016511 | **accepting** | **not confirmed** | 2026-04-27 → gone |

Both had declared on 2026-04-27. On night one that was **89 days** old and still displayed. On night two it was **exactly 90 days** old and had been wiped.

This is the 90-day reset caught in the act. Night one could only infer the mechanism from a cross-section — no practice with a pre-2026 `lastmod` had any declared status. Night two watched it happen to two named practices on precisely day 90, which is why night one's oldest observed confirmation was 89 days rather than 90. The rule is not "roughly 90 days"; the declaration is dropped the moment it reaches 90.

The second row is the one that matters for the product. Yesterday V016511 told the public it was accepting new NHS patients. Today it tells them nothing. **nhs.uk keeps no record that the claim was ever made**, and a patient who saw it yesterday has no way to demonstrate it. That gap is the entire reason this project exists, and it took 24 hours of accrual to produce a concrete example of it.

## State at end of session

**122 tests green, lint clean, suite runs in ~6 seconds.** Sixteen commits.

Night one of a record that exists nowhere else is captured, parsed and committed.

**The one thing that still needs a human:** the repository has no GitHub remote. Until it does, the nightly cron cannot fire, and unattended accrual — the entire differentiating asset — does not start. Local captures work, but they depend on someone remembering.

---

*Session 02 · 2026-07-25 · NHS Dentist Intelligence Platform*
