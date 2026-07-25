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

**Loop 0 — Foundations** (ledger §0). In progress.

Getting the repo, decision record and toolchain in place so that Loop 1 (the crawler) has somewhere to land and something to schedule it.

### What is being worked on now

- Repo scaffolding and first commit.
- A sub-agent is investigating the **fetch route** for step 1.1 — how to enumerate all ~9,000 English dental practices and pull per-practice detail without an API key, and whether that data carries acceptance status and a last-updated date (open question **Q1**). Result pending.

---

## Completed work

| Ledger | Item | Notes |
|---|---|---|
| 0.1 | Git repo initialised | Repo root is the project folder; `/ingest` `/data` `/docs` `/analysis` `/web` `.github/workflows` created |
| 0.1 | Python toolchain | `uv` installed (was absent); Python 3.12.13 installed; deps synced — httpx, selectolax, tenacity, duckdb, polars, pyarrow, rapidfuzz, pytest, ruff |
| 0.1 | CI workflow | `.github/workflows/ci.yml` — ruff + pytest on push/PR |
| 0.2 | **ADR-001** written | `docs/ADR-001-repositioning-and-architecture.md` — locks decisions D1–D10 and constraints C1–C9 |

---

## Remaining DO items

Ordered by the sequence actually being worked, not by ledger number. §8 items are **excluded** (deferred/cut — not to be built).

| Ledger | Item | State |
|---|---|---|
| 0.1 | Push to GitHub, confirm CI green | Blocked — see Parked |
| 1.1 | Crude full-estate capture (~9,000 practices) | **Next — critical path** |
| 1.2 | Append-only snapshot store `data/snapshots/YYYY-MM-DD/` | Next |
| 1.3 | Nightly GitHub Actions cron ~03:00 UTC | After 1.2 |
| 1.4 | Failure alarm — workflow failure + ±10% volume anomaly | After 1.3 |
| 2.1 | Field-level spike → answers Q1 (**gate DG1**) | Partly folded into the Loop 0 investigation |
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

## Files changed this loop

```
pyproject.toml                                    new
.gitignore                                        new
.github/workflows/ci.yml                          new
docs/ADR-001-repositioning-and-architecture.md    new
CLAUDE_PROGRESS.md                                new
ingest/ data/ analysis/ web/                      new (empty scaffolding)
```

## Tests or checks run

| Check | Result |
|---|---|
| Network reachability — `nhs.uk/service-search/find-a-dentist` | 200 OK |
| Network reachability — `api.nhs.uk` host | Resolves (404 on bare path, as expected without a key) |
| `uv sync --all-extras` | Clean |
| ruff / pytest | Not yet run — no source code exists yet |

## Issues found

- System Python was 3.9.6; plan requires 3.12. Resolved by installing `uv` + Python 3.12.13.
- `uv`, `node` and `gh` were all absent from the environment. `uv` resolved; the other two recorded as P2/P4.

---

## Next planned action

**Loop 1 — Start the clock** (ledger 1.1 + 1.2). Build `ingest/fetch.py`: enumerate the full English dental estate, fetch each practice's raw payload at ~1 req/sec with retries, and write gzipped raw records to `data/snapshots/YYYY-MM-DD/`. Raw and unparsed — parsing comes later at 2.3, per ADR-001.

Gated on the sub-agent's fetch-route report. **Target: a full-estate capture completed tonight**, because tonight's data cannot be fetched tomorrow.

---

## Resume protocol

If a session ends mid-flight, restart with:

> Read `CLAUDE_PROGRESS.md` in `/Users/dare2try/Claude Projects/CLD DentistApp` and continue the loops from **Next planned action**.

Rules on resume: do not re-derive the plan; the ledger is agreed ground. Do not build §8 items. Check `data/snapshots/` for the most recent capture date first — **if last night's snapshot is missing, running the crawler outranks every other task.** Update this file after every loop and after every sub-agent completion.
