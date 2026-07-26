# CLAUDE_PROGRESS.md — live build status

**Project:** NHS Dentist Intelligence Platform (England)
**Plan of record:** `Documenting the Journey/Build-Plan-v1_2026-07-25_Delivery-Ledger-and-North-Star.md`
**Last updated:** 2026-07-25 — end of Loop 11

> Read this file first on any resume. It is the single source of truth for where the build stands.

---

## Overall objective

Build the public longitudinal record of NHS dental provision in England: nightly availability snapshots that accrue history nobody else holds, joined to ~10 years of NHSBSA activity data and LSOA population, published as a free searchable site plus open bulk downloads.

**The one thing that matters most:** history accrues only in wall-clock time. Every night the crawler does not run is history no later effort recovers.

---

## Current loop

**Loops 0–11 complete.** The spend limit that halted Loop 7 has been reset; work resumed and 4.1 is now done properly.

### What is being worked on next

All of §1–§4 is now complete. **Next: §5 — the public surface** (static build, postcode search, map, profile pages, downloads). That needs Node.js installed (P4). Also outstanding: 7.2, the data-quality dashboard.

### Night one is captured, parsed and committed

**6,407 practices, zero failures, 43.1 MB.** All four health checks passed. The parser recognised **100%** of pages.

| Reported state | Practices | Share |
|---|---:|---:|
| Accepting (any cohort) | 2,545 | 39.7% |
| Not accepting | 1,997 | 31.2% |
| Not confirmed | 1,281 | 20.0% |
| Referral-only | 584 | 9.1% |

**By cohort — the number that matters for product framing:** adults 18+ accepted at only **27.8%** of practices, free-care adults 29.0%, children 39.5%. A headline "39.7% accepting" would mislead. This confirms decision D2 with our own data: leading with an "accepting" filter still returns mostly nothing.

**Checking capture progress.** Counting blobs only works for the *first* night. From night two on, pages are byte-identical so almost no new blobs are written — night two added 1 blob against night one's 6,408. Watch the run log instead, or check the day's `run.json` once it completes:

```bash
tail -3 data/snapshots/$(date -u +%F)/run.json   # after completion
```

Runs are resumable: re-running `uv run python ingest/fetch.py` picks up where it stopped rather than re-fetching, and a completed day refuses to be overwritten.

---

## Completed work

| Ledger | Item | Where | Notes |
|---|---|---|---|
| 0.1 | Repo, skeleton, toolchain, CI | `.github/workflows/ci.yml` | `uv` + Python 3.12.13 installed (system was 3.9) |
| 0.2 | **ADR-001** | `docs/ADR-001-…md` | Locks decisions D1–D10 and constraints C1–C9 |
| 1.1 | Polite HTTP client | `ingest/client.py` | Global 1 req/s, honest UA, `Retry-After`, 429 backs off whole crawl |
| 1.1 | **Full-estate fetcher** | `ingest/fetch.py` | Sitemap enumeration → per-practice capture, resumable |
| 1.2 | Append-only snapshot store | `ingest/snapshot.py` | Content-addressed; completed days refuse overwrite |
| 1.3 | Nightly workflow | `.github/workflows/snapshot.yml` | 03:00 UTC cron — **cannot run until P2 is resolved** |
| 1.4 | Failure alarms | `ingest/health.py` | ±10% volume drift, 5,000 floor, 5% failure ceiling |
| 2.1 | Field-level spike → **Q1 closed** | ADR-002 | **Gate DG1 cleared** |
| 2.2 | **ADR-002** — route decision | `docs/ADR-002-…md` | Scrape nhs.uk; defer the API |
| 2.3 | Snapshot parser | `ingest/parse.py` | All five acceptance states; markup-change alarm |
| 3.1 | ODS register loader | `ingest/ods.py` | 9,779 active practices; **99.2%** map to nhs.uk |
| 3.2 | Geocoding + geography | `ingest/geo.py` | **99.8%** matched; England filter, LSOA, ICB, IMD |
| 3.4 | LSOA population denominator | `ingest/pop.py` | 33,755 LSOAs; 58,620,101 people; clean 0–17 / 18+ |
| 7.1 | Session 02 journal | `Documenting the Journey/Session-02_…md` | Loops, deviations, dead ends |
| 4.3 | Freshness / trust scoring | `analysis/freshness.py` | Two age signals; **100%** of the estate now has an age |
| 4.1 | NHSBSA activity history | `ingest/bsa.py` | 847,405 contract-months, 120 months, 9,891 contracts |
| 3.3 | **Entity resolution** | `ingest/match.py` | **91.4%** matched; 495 queued for review |
| 4.2 | **Dental-desert model** | `analysis/desert.py` + `ingest/lsoa.py` | **Gate DG3 cleared.** 2SFCA over 33,755 LSOAs |

**186 tests green, lint clean.** Suite runs in ~7s.

### Key findings so far

- **Q1 answered YES.** nhs.uk carries acceptance status *and* a "Last confirmed" date, at the same cohort granularity the v3 API offers. Scraping loses nothing material, so the build did not wait on an API key.
- **The estate is 6,407 published profiles**, not ~9,000. The 9,779 figure is ODS *active dental practices*, which includes private-only practices and prison dental units with no public profile.
- **Q2, first leg answered.** 6,358 / 6,407 nhs.uk practices (99.2%) resolve to an active ODS record via the zero-padding convention alone. The NHSBSA contract leg remains for 3.3.
- **⚠️ CORRECTED — nhs.uk resets status after 90 days.** An earlier note here claimed some practices "have not confirmed their status in fifteen years". That was wrong: `lastmod` is *page* modification, not confirmation. Night one proved it — every practice with a declared status was confirmed within **89 days**, and no practice with a pre-2026 `lastmod` has any declared status at all (all 447 read `not_confirmed` or `referral_only`). **`days_since_confirmed` is therefore capped at 90 by construction** and is weak as a differentiator. The decade of silence lives in the `lastmod` of the undeclared 29.1% — 51 practices untouched since 2011, all reading "not confirmed". **Step 4.3 must derive freshness for undeclared practices from `lastmod`, not from a confirmation date that does not exist.**
- **80.6% of English LSOAs contain no dental practice at all** — 27,193 of 33,755. This settles a design question for 4.2: the dental-desert model must be **catchment-based** (distance to nearest N practices), because "practices in my LSOA" would report four-fifths of England as a total desert.
- **NHS dental activity has not recovered from the pandemic.** Pre-COVID ~80M UDAs/yr; 2020 collapsed to 31.4M; recovery has plateaued at ~70M — roughly 12% below pre-pandemic, five years on. This is the strongest headline finding so far, and it doubles as a validity check that the ingest is correct.
- **The BSA join bridge is measured, not assumed** (input to 3.3). The BSA key is `CONTRACT_NUMBER`, not an ODS code, so there is no free join. But every contract carries a postcode, 98.5% of which exist in ODS, and **6,219 of 7,005 contracts (88.8%) resolve to exactly one ODS practice on postcode alone.** 678 are ambiguous (postcode holds >1 practice). That bounds what 3.3 must solve by name matching to roughly 11% of the estate.
- **The worst-served tenth of England gets about half the national median** of accessible NHS dental activity (592 vs 1,159 UDAs per 1,000). 466,027 people live in an LSOA with no practice within 10 km; 3.2M have none within 5 km.
- **Entity resolution landed at 91.4%**, with 495 contracts queued for review rather than guessed. Name similarity turned out to be a weak signal by nature — BSA names the contract holder, ODS names the site, often generically — so postcode does the work and the review queue holds the genuinely ambiguous.
- **Population reconciles exactly.** England mid-2024 = 58,620,101, matching the published ONS figure; children + adults sums to total; 100% of practice-bearing LSOAs have a population figure.
- **Compliance is clean.** robots.txt permits these paths, terms carry no anti-scraping clause, content is OGL. Our honest bot User-Agent is accepted — no browser spoofing is used. Required attribution wording is pinned in ADR-002 for the 6.1 pass.

---

## Remaining DO items

§8 items are **excluded** (deferred/cut — not to be built).

| Ledger | Item | State |
|---|---|---|
| 5.1–5.5 | Static build, postcode search, map, profile pages, downloads | **NEXT.** Needs Node (P4) |
| 6.1–6.3 | Compliance pass, deploy, tell three people | **Gates DG5 / DG4** |
| 7.1 | Session journal | Continuous — Session 02 written; **needs updating for loops 8–11** |
| 7.2 | Data-quality dashboard | From week 3 |

---

## Parked / blocked — needs human action

| # | Item | Why blocked | What I need |
|---|---|---|---|
| **P2** | **GitHub remote** | No `gh` CLI, no authenticated account. CI cannot run and the nightly cron cannot fire | **The real blocker.** Create an empty GitHub repo and give me the URL with push access, or install + auth `gh`. Until then history accrues only when this machine runs it manually |
| P1 | NHS Service Search API v3 key | Human must apply on the NHS Digital developer portal; production needs a signed Online Connection Agreement | Not on the critical path — ADR-002 chose a route that does not need it. Worth starting for the timestamp precision it would later add |
| P3 | Q3 — your viability conditions | Plan assumes solo builder, near-zero budget, public release, no NHS partnership | Confirm or correct. Proceeding on the assumed conditions |
| P4 | Node.js not installed | Needed for §5 web app | Not urgent — will install when §5 starts |

---

## Files changed

| Loop | Commit | Files |
|---|---|---|
| 0 | `6409125` | `pyproject.toml`, `.gitignore`, `ci.yml`, `ADR-001`, `README`, `LICENSE` |
| 1a | `e2c7a07` | `ingest/snapshot.py`, `ingest/health.py`, `snapshot.yml`, tests |
| 1b | `01a329e` | `ingest/client.py`, tests |
| 2 | `95e7b0a` | `ingest/fetch.py`, `docs/ADR-002-availability-route.md`, tests |
| 3 | `0dd702d` | `ingest/parse.py`, tests |
| 4 | `da148db` | `ingest/ods.py`, `data/reference/ods/`, tests |
| 5 | `6877cd5` | `ingest/geo.py`, `client.py` POST support, `data/reference/geo/`, tests |
| — | `ee7f901` | `Documenting the Journey/Session-02_…md` |
| 6 | `205bfe7` | `ingest/pop.py`, `data/reference/population/`, tests |
| 7 | `a5589a8` | `analysis/freshness.py`, tests |
| — | `75e55d8`, `a70a900` | **Night one snapshot**, corrections |
| 8 | `d9c6c25` | Freshness rework for the 90-day reset |
| 9 | `6a43387` | `ingest/bsa.py`, `data/reference/bsa/`, tests |
| 10 | `2ac6698` | `ingest/match.py`, tests |
| 11 | `409653e` | `analysis/desert.py`, `ingest/lsoa.py`, `data/reference/lsoa/`, tests |

## Tests or checks run

| Check | Result |
|---|---|
| `uv run pytest -q` | **186 passed**, ~7s |
| `uv run ruff check .` | Clean |
| Live smoke capture (8 practices) | Passed — status + date present in payloads |
| Live ODS register pull | 9,779 practices in 10 requests |
| Live geocode of all register postcodes | 99.8% matched |
| Population totals independently re-verified | 58,620,101 = published ONS figure; children + adults reconciles |
| Byte-stability of appointments pages across fetches | Identical — content-addressed dedup is effective |
| CI green on GitHub | **Not yet — blocked on P2** |

## Issues found and resolved

- Test harness monkey-patched `__aenter__` on the instance, but `async with` resolves dunders on the *type* — five client tests were silently hitting the live network. Fixed by making the transport injectable.
- Test suite took 90s because 503 tests slept through real exponential backoff. Backoff scale is now injectable; suite is 6s.
- Ledger 1.2's literal "gzipped JSON per practice per night" would write ~3.3M files a year. Replaced with a content-addressed store — same guarantee, a fraction of the size. The whole ODS register is 256 KB on disk.
- Cohort parsing initially risked reading urgent-care bullets present on every page in England, which would have marked the entire estate as accepting. Extraction is now scoped to the routine-care region.

---

## Next planned action

**First, tonight's capture.** If the UTC date has rolled over and `data/snapshots/` has no folder for today, this outranks everything:

```bash
export PATH="$HOME/.local/bin:$PATH"
cd "/Users/dare2try/Claude Projects/CLD DentistApp"
uv run python ingest/fetch.py && uv run python ingest/health.py
```

Then, in order:

1. **Rework 4.3** to derive freshness for undeclared practices from sitemap `lastmod`, per the correction above. The sitemap is already captured inside every snapshot as `_sitemap`, so no re-fetch is needed.
2. **Redo 4.1** (NHSBSA activity). Start from the dataset `ingest/bsa.py.wip` identified, but write it fresh with tests — do not trust the draft.
3. **Step 3.3 — entity resolution**, once 4.1 establishes the BSA join key. Timebox two days; ship at whatever match rate is reached and publish it (C8).
4. **Step 4.2 — dental-desert model** (gate DG3). Catchment-based, not LSOA-contains-practice.

---

## Resume protocol

If a session ends mid-flight, restart with:

> Read `CLAUDE_PROGRESS.md` in `/Users/dare2try/Claude Projects/CLD DentistApp` and continue the loops from **Next planned action**.

Rules on resume:

- Do not re-derive the plan; the ledger is agreed ground. Do not build §8 items.
- **Check `data/snapshots/` for the most recent capture date first. If last night's snapshot is missing, running `uv run python ingest/fetch.py` outranks every other task.** It is resumable and safe to re-run — a completed day refuses to be overwritten.
- `export PATH="$HOME/.local/bin:$PATH"` — `uv` lives there and is not on the default PATH.
- Update this file after every loop and after every sub-agent completion.
