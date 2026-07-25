# CLAUDE_PROGRESS.md — live build status

**Project:** NHS Dentist Intelligence Platform (England)
**Plan of record:** `Documenting the Journey/Build-Plan-v1_2026-07-25_Delivery-Ledger-and-North-Star.md`
**Last updated:** 2026-07-25 — Loop 0

> Read this file first on any resume. It is the single source of truth for where the build stands.

---

## Overall objective

Build the public longitudinal record of NHS dental provision in England: nightly availability snapshots that accrue history nobody else holds, joined to ~10 years of NHSBSA activity data and LSOA population, published as a free searchable site plus open bulk downloads.

**The one thing that matters most:** ledger steps 1.1–1.4 (capture → store → automate → alarm). History accrues only in wall-clock time. Every night the crawler is not running is history that no later effort recovers. Everything else in the plan can slip a month without lasting harm.

---

## Current loop

**Loop 1 — Start the clock** (ledger §1). In progress. Loop 0 complete.

### What is being worked on now

Everything in §1 *except the fetching itself* is now built and tested — the store, the alarms, the schedule. What remains is `ingest/fetch.py`, which is gated on one unknown.

- A sub-agent is investigating the **fetch route**: how to enumerate all ~9,000 English dental practices and pull per-practice detail without an API key, and whether that data carries acceptance status and a last-updated date (open question **Q1**, gate **DG1**). Result pending — the fetcher is written the moment it lands.

### Design deviation logged this loop

The ledger specifies *"gzipped JSON per practice in dated directories"* for step 1.2. Built instead as a **content-addressed store**: raw payloads in `data/snapshots/blobs/<sha256>.gz`, plus a per-night manifest mapping practice → hash.

**Why:** taken literally the ledger design writes ~9,000 files per night into git — 3.3M files a year, and far worse if the route turns out to be HTML pages rather than JSON records. Content addressing means an unchanged practice costs zero additional bytes, while every night still resolves to a complete, independently parseable view of the estate. The append-only guarantee is unchanged. No ADR raised — this is an implementation choice, not a reversal of an agreed decision.

---

## Completed work

| Ledger | Item | Notes |
|---|---|---|
| 0.1 | Git repo initialised | Repo root is the project folder; `/ingest` `/data` `/docs` `/analysis` `/web` `.github/workflows` created |
| 0.1 | Python toolchain | `uv` installed (was absent); Python 3.12.13 installed; deps synced — httpx, selectolax, tenacity, duckdb, polars, pyarrow, rapidfuzz, pytest, ruff |
| 0.1 | CI workflow | `.github/workflows/ci.yml` — ruff + pytest on push/PR |
| 0.2 | **ADR-001** written | `docs/ADR-001-repositioning-and-architecture.md` — locks decisions D1–D10 and constraints C1–C9 |
| 1.2 | **Append-only snapshot store** | `ingest/snapshot.py` — content-addressed blobs + nightly manifest + run metadata. Completed days refuse overwrite; aborted days can be retried |
| 1.4 | **Failure alarm logic** | `ingest/health.py` — ±10% volume drift vs prior run, 5,000-record floor, 5% failure-rate ceiling. Non-zero exit fails the workflow, which sends the email |
| 1.3 | **Nightly workflow** | `.github/workflows/snapshot.yml` — 03:00 UTC cron, 5.5h timeout, auto-commit of captures. Cannot *run* until the repo has a remote (P2) |
| — | README + Apache-2.0 licence | Carries the C2 "not affiliated with the NHS" statement and the OGL/ODbL attribution table |

---

## Remaining DO items

Ordered by the sequence actually being worked, not by ledger number. §8 items are **excluded** (deferred/cut — not to be built).

| Ledger | Item | State |
|---|---|---|
| 0.1 | Push to GitHub, confirm CI green | Blocked — see Parked |
| 1.1 | Crude full-estate capture (~9,000 practices) | **Next — critical path.** Gated on the route investigation |
| 1.2 | Append-only snapshot store | ✅ Done |
| 1.3 | Nightly GitHub Actions cron ~03:00 UTC | ✅ Written — blocked on P2 to actually run |
| 1.4 | Failure alarm | ✅ Done |
| 2.1 | Field-level spike → answers Q1 (**gate DG1**) | In flight — folded into the route investigation |
| 2.2 | ADR-002 — choose availability route (API / hybrid / scrape) | After 2.1 |
| 2.3 | Snapshot → structured parser, one row per practice per date | After 2.2 |
| 3.1 | Load ODS practice register | Week 2 |
| 3.2 | Geocode via ONSPD → lat/long, LSOA, ICB, region | Week 2 |
| 3.3 | Entity resolution nhs.uk ↔ ODS ↔ BSA | Week 2 — **highest schedule risk, timebox 2 days** |
| 3.4 | LSOA population join (demand denominator) | Week 2 |
| 4.1 | Ingest NHSBSA activity history 2016→ | Week 3 |
| 4.2 | Supply-vs-demand / dental-desert model (**gate DG3**) | Week 3 |
| 4.3 | Freshness / trust scoring | Week 3 |
| 5.1 | Static data build → `data/dist/` | Week 4 |
| 5.2 | Postcode search & ranked results | Week 4 |
| 5.3 | Interactive map + desert choropleth | Week 4 |
| 5.4 | Practice profile pages (~9,000 static) | Week 5 |
| 5.5 | Open data downloads + data dictionary | Week 5 |
| 6.1 | Compliance & framing pass (**gate DG5**) | Week 6 |
| 6.2 | Deploy & measure (**gate DG4**) | Week 6 |
| 6.3 | Tell three people who matter | Week 6 |
| 7.1 | Session journal | Continuous |
| 7.2 | Data-quality dashboard | Continuous, from week 3 |

---

## Parked / blocked — needs human action

| # | Item | Why blocked | What I need from you |
|---|---|---|---|
| P1 | **0.3 — NHS Service Search API v3 key** | Registration requires a human to complete an application on the NHS Digital developer portal. Unknown approval lead time | You to submit the application. The crawler is deliberately built **not** to depend on it, so this is not on the critical path — but the clock should start early |
| P2 | **GitHub remote / push** | No `gh` CLI installed and no authenticated GitHub account in this environment. CI cannot run and the nightly cron cannot be scheduled until the repo has a remote | Create an empty GitHub repo and either install+auth `gh`, or give me the remote URL with push access. **This one does gate step 1.3 (nightly automation).** Local snapshots still accrue in the meantime |
| P3 | **Q3 — your viability conditions** | Plan assumes solo builder, near-zero budget, public release, no NHS partnership | Confirm or correct. A budget or an NHS/ICB relationship changes the plan, not just the estimates. Proceeding on the assumed conditions until told otherwise |
| P4 | Node.js not installed | Needed for §5 web app (week 4) | Not urgent — I'll install it when §5 starts |

---

## Files changed

**Loop 0** — `pyproject.toml`, `.gitignore`, `.github/workflows/ci.yml`, `docs/ADR-001-repositioning-and-architecture.md`, `README.md`, `LICENSE`, `CLAUDE_PROGRESS.md`, directory skeleton. Commit `6409125`.

**Loop 1a** — `ingest/snapshot.py`, `ingest/health.py`, `tests/test_snapshot.py`, `.github/workflows/snapshot.yml`. Commit `e2c7a07`.

## Tests or checks run

| Check | Result |
|---|---|
| `uv run pytest -q` | **16 passed** — roundtrip fidelity, cross-night dedup, overwrite refusal, abort-and-retry, failure recording, all four health alarms |
| `uv run ruff check .` | Clean |
| `uv sync --all-extras` | Clean |
| Network — `nhs.uk/service-search/find-a-dentist` | 200 OK |
| Network — `api.nhs.uk` host | Resolves (404 on bare path, as expected without a key) |
| CI green on GitHub | Not yet — blocked on P2 (no remote) |

## Issues found

- System Python was 3.9.6; plan requires 3.12. Resolved by installing `uv` + Python 3.12.13.
- `uv`, `node` and `gh` were all absent. `uv` resolved; the other two recorded as P4/P2.
- Ledger 1.2's literal file layout does not scale — see the design deviation above.

---

## Next planned action

**Loop 1b — build `ingest/fetch.py`** (ledger 1.1) the moment the route investigation reports. Enumerate the full English dental estate, fetch each practice's raw payload at ~1 req/sec with retries and resume-on-interrupt, and hand each one to `SnapshotWriter`. Raw and unparsed — parsing is step 2.3.

Then run a real full-estate capture. **Target: night one of history captured today**, because today's data cannot be fetched tomorrow.

After that: ADR-002 recording the chosen route (2.2), then the parser (2.3).

---

## Resume protocol

If a session ends mid-flight, restart with:

> Read `CLAUDE_PROGRESS.md` in `/Users/dare2try/Claude Projects/CLD DentistApp` and continue the loops from **Next planned action**.

Rules on resume: do not re-derive the plan; the ledger is agreed ground. Do not build §8 items. Check `data/snapshots/` for the most recent capture date first — **if last night's snapshot is missing, running the crawler outranks every other task.** Update this file after every loop and after every sub-agent completion.
