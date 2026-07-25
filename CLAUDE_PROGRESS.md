# CLAUDE_PROGRESS.md — live build status

**Project:** NHS Dentist Intelligence Platform (England)
**Plan of record:** `Documenting the Journey/Build-Plan-v1_2026-07-25_Delivery-Ledger-and-North-Star.md`
**Last updated:** 2026-07-25 — end of Loop 6

> Read this file first on any resume. It is the single source of truth for where the build stands.

---

## Overall objective

Build the public longitudinal record of NHS dental provision in England: nightly availability snapshots that accrue history nobody else holds, joined to ~10 years of NHSBSA activity data and LSOA population, published as a free searchable site plus open bulk downloads.

**The one thing that matters most:** history accrues only in wall-clock time. Every night the crawler does not run is history no later effort recovers.

---

## Current loop

**Loop 7 — in flight.** Loops 0–6 complete.

### What is being worked on now

**A full-estate capture is running in the background** — the first night of history. 6,407 practices at ~0.96 req/s, **zero failures**, roughly 1,100 done as of last check.

**A sub-agent is building step 4.1** — the NHSBSA activity history ingest, the plan's "escape hatch" giving ~10 years of delivered-activity truth on day one. It has also been asked to measure the BSA↔ODS join key situation, which is the key input to 3.3.

Progress is checkable at any time:

```bash
find data/snapshots/blobs -name '*.gz' | wc -l    # out of 6,407
```

The run is resumable. If it dies, re-running `uv run python ingest/fetch.py` picks up where it stopped rather than re-fetching.

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
| 4.3 | Freshness / trust scoring | `analysis/freshness.py` | 90-day mandate buckets, volatility, C1-compliant wording |

**122 tests green, lint clean.** Suite runs in ~6s.

### Key findings so far

- **Q1 answered YES.** nhs.uk carries acceptance status *and* a "Last confirmed" date, at the same cohort granularity the v3 API offers. Scraping loses nothing material, so the build did not wait on an API key.
- **The estate is 6,407 published profiles**, not ~9,000. The 9,779 figure is ODS *active dental practices*, which includes private-only practices and prison dental units with no public profile.
- **Q2, first leg answered.** 6,358 / 6,407 nhs.uk practices (99.2%) resolve to an active ODS record via the zero-padding convention alone. The NHSBSA contract leg remains for 3.3.
- **Freshness is visible on day one.** The sitemap's `lastmod` values span 2026-07-24 back to **2011-01-06** — some practices have not confirmed their status in fifteen years. One request yields a freshness distribution for the whole estate, before any history of our own accrues. This materially strengthens step 4.3.
- **80.6% of English LSOAs contain no dental practice at all** — 27,193 of 33,755. This settles a design question for 4.2: the dental-desert model must be **catchment-based** (distance to nearest N practices), because "practices in my LSOA" would report four-fifths of England as a total desert.
- **Population reconciles exactly.** England mid-2024 = 58,620,101, matching the published ONS figure; children + adults sums to total; 100% of practice-bearing LSOAs have a population figure.
- **Compliance is clean.** robots.txt permits these paths, terms carry no anti-scraping clause, content is OGL. Our honest bot User-Agent is accepted — no browser spoofing is used. Required attribution wording is pinned in ADR-002 for the 6.1 pass.

---

## Remaining DO items

§8 items are **excluded** (deferred/cut — not to be built).

| Ledger | Item | State |
|---|---|---|
| 1.1 | First full capture | **Running now** |
| 4.1 | Ingest NHSBSA activity history | **Sub-agent in flight** |
| 3.3 | Entity resolution nhs.uk ↔ ODS ↔ BSA | **Highest schedule risk — timebox 2 days.** Waiting on 4.1's join-key findings |
| 4.2 | Supply-vs-demand / dental-desert model | **Gate DG3.** Must be catchment-based, per the 80.6% finding |
| 4.3 | Freshness / trust scoring | ✅ Module + tests done; needs the capture to run against real data |
| 5.1–5.5 | Static build, postcode search, map, profile pages, downloads | Weeks 4–5; needs Node (P4) |
| 6.1–6.3 | Compliance pass, deploy, tell three people | **Gates DG5 / DG4** |
| 7.1 | Session journal | Continuous — **owed for this session** |
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

## Tests or checks run

| Check | Result |
|---|---|
| `uv run pytest -q` | **96 passed**, ~6s |
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

1. **When the capture finishes** (highest priority), run:
   ```bash
   export PATH="$HOME/.local/bin:$PATH"
   uv run python ingest/health.py     # assert the night is sane
   uv run python ingest/parse.py      # first practice-day table
   ```
   Then record the real acceptance distribution across England, commit the snapshot, and note the recognised-share figure.
2. **Step 3.3 — entity resolution**, once 4.1 reports what join key the BSA data carries. Timebox to two days; ship at whatever match rate is reached and publish the number (C8).
3. **Step 4.2 — dental-desert model** (gate DG3). Catchment-based, not LSOA-contains-practice.
4. **Step 4.3 — freshness scoring**, exploiting the sitemap `lastmod` distribution that already reaches back to 2011.

---

## Resume protocol

If a session ends mid-flight, restart with:

> Read `CLAUDE_PROGRESS.md` in `/Users/dare2try/Claude Projects/CLD DentistApp` and continue the loops from **Next planned action**.

Rules on resume:

- Do not re-derive the plan; the ledger is agreed ground. Do not build §8 items.
- **Check `data/snapshots/` for the most recent capture date first. If last night's snapshot is missing, running `uv run python ingest/fetch.py` outranks every other task.** It is resumable and safe to re-run — a completed day refuses to be overwritten.
- `export PATH="$HOME/.local/bin:$PATH"` — `uv` lives there and is not on the default PATH.
- Update this file after every loop and after every sub-agent completion.
