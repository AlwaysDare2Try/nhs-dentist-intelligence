# NHS Dentist Intelligence Platform — Build Plan v1

**Delivery Ledger & North Star**

| | |
|---|---|
| **Version** | v1 |
| **Date agreed** | 2026-07-25 |
| **Scope** | England only |
| **Status** | Agreed — pending build kick-off |
| **Supersedes** | The 15-activity delivery plan in `Starting Docs/NHS_Dentist_Intelligence_Platform_Programme_Charter.md` (v0.1) |
| **Basis** | Viability analysis recorded in `Documenting the Journey/Session-01_2026-07-25_Concept-Ingestion-and-Viability-Analysis.md` |
| **Rendered version** | `Build-Plan-v1_2026-07-25_Delivery-Ledger-and-North-Star.html` (same folder) |

> **How to use this document during build.** This is the reference of record for what was agreed. Before starting any work session, check the ledger for the lowest-numbered step still open and work from there. Do not re-litigate decisions captured here or in Session 01 without writing a new ADR — the point of this file is that agreed ground stays agreed. Update the **Status** column as steps complete, and log each session to `Documenting the Journey/` per step 7.1.

---

## Contents

1. [Two decisions that make this fast](#two-decisions-that-make-this-fast)
2. [North Star](#north-star)
3. [The Ledger](#the-ledger)
4. [Shape of the commitment](#shape-of-the-commitment)
5. [Inherited constraints and compliance rules](#inherited-constraints-and-compliance-rules)
6. [Open questions at time of agreement](#open-questions-at-time-of-agreement)

---

## Two decisions that make this fast

Stated once here so every row in the ledger can stay terse.

**1. No server database for v1.** Roughly 9,000 practices is a few megabytes. Pipelines run offline in Python, DuckDB and GeoPandas and emit static JSON and Parquet; the web app reads those files. Postgres and PostGIS arrive only when something genuinely needs them. This deletes most of the original architecture diagram's infrastructure row.

**2. Capture raw, parse later.** The crawler stores unparsed source payloads from the first night. That is why it can start *before* we know whether the API carries acceptance status: yesterday cannot be re-fetched, but it can always be re-parsed.

**Stack:** Python 3.12 pipelines · GitHub Actions cron (free, durable scheduling) · append-only snapshots committed to the repo · DuckDB for analysis · Next.js + MapLibre GL on Vercel · Protomaps/OSM tiles.

---

## North Star

Three tiers, each defined by what is actually true of the platform at that point — not by effort spent. Every tier is a shippable state.

| Tier | In a phrase | Definition | Product & UX | Data & Intelligence | Audiences Truly Served | Measurable Proof | Realistic Timeframe | Why This Tier Isn't Enough — What Unlocks The Next |
|---|---|---|---|---|---|---|---|---|
| 1 | **Good** | An honest, working directory that adds the one thing nhs.uk withholds: *when* each claim was made | Postcode search returning ranked nearby practices, each showing "reported X on DATE"; stale listings visibly flagged; usable map on a phone | Nightly snapshots accruing; ODS register geocoded to LSOA and ICB; a freshness score on every practice | General public; patients with specific access needs | Site live; refreshes unattended for 30 nights; any valid English postcode returns sane results; mobile Lighthouse above 90 | End of week 6 | It is a better-labelled directory. An incumbent could copy the freshness label in a fortnight. The moat only appears once history is public and the demand denominator exists |
| 2 | **Great** | The longitudinal record and the supply-versus-demand picture are public, queryable and downloadable | Per-practice availability timelines; England-wide dental-desert choropleth; bulk CSV and Parquet downloads with a real data dictionary; a self-published data-quality dashboard | ~10 years of NHSBSA activity joined to LSOA population; entity resolution across nhs.uk, ODS and BSA at a **published** match rate; volatility and reopening patterns | Adds healthcare analysts, policy makers, researchers and press — 4 of the 6 charter audiences | An ICB analyst or journalist answers "how has provision changed here since 2016?" in under 2 minutes without contacting you; first external citation; repeat non-search traffic to profile and data pages | ~3 months (v1 + 4–6 weeks accrual) | You are a good dataset that people find. Not yet the thing people *check*, and the method is not yet reusable by anyone else |
| 3 | **Exceptional** | The reference source for NHS dental access in England — and a reusable worked example of how it was built | Open API others build on; embeddable maps and charts; stable versioned data releases that people cite by version | A multi-year continuous availability record existing nowhere else; freshness scoring creating live accountability pressure on the 90-day update rule; method published and independently reproducible | All 6 charter audiences, plus a secondary audience of builders following the O5 case study | Cited in Parliament, national press or peer-reviewed work; third-party tools consuming the data; NHS or ICB engagement; the documented method demonstrably reused | 12+ months of sustained accrual | This is the ceiling. Sustaining it becomes the challenge rather than reaching it |

**Explicitly not the goal at any tier:** beating DentistAlert at consumer alerts.

---

## The Ledger

Rows are steps, grouped into eight phases.

**Status key:** `NEXT` · `PLANNED` · `CONTINUOUS` · `DEFERRED` · `CUT` — update this column as work completes.

| Seq | Step | Status | What · Who · Where · When | Why Needed & Why In This Position | How It Will Be Carried Out | Output → Done When | Effort | Gate / Risk |
|---|---|---|---|---|---|---|---|---|
| | **§0 — FOUNDATIONS** *(Day 0. Deliberately thin — 90 minutes, not a week.)* | | | | | | | |
| 0.1 | Init repo & skeleton | NEXT | Git repo with `/ingest`, `/data`, `/web`, `/docs` · you · local + GitHub · day 0 | Nothing is reproducible or schedulable until it is in version control. Must precede the crawler because GitHub Actions *is* the scheduler | `git init`, private-then-public GitHub repo, OGL-compatible licence, `uv` for Python dependencies | Repo pushed; CI hello-world green | 1 h | — |
| 0.2 | Decision record | NEXT | ADR-001 capturing the ten decisions from the viability analysis · you · `/docs` · day 0 | Locks the repositioning so it is not silently re-litigated in week three. Feeds objective O5 directly | One-page Markdown ADR linking back to the Session 01 log | ADR committed | 30 min | — |
| 0.3 | Register for NHS API access | NEXT | Request Service Search API v3 key · you · NHS Digital developer portal · day 0 | Approval has unknown lead time, so start the bureaucratic clock in parallel with everything else. Becomes blocking if left late | Online application through the digital.nhs.uk developer portal | Key issued, or the refusal understood | 30 min + wait | **RISK** — unknown approval lead time; the crawler must not depend on it |
| | **§1 — START THE CLOCK** *(Week 1, days 1–3. The most time-critical section in the plan.)* | | | | | | | |
| 1.1 | Crude full-estate capture | NEXT | Fetch raw records for all ~9,000 English dental practices · you · local script · day 1 | **History accrues only in wall-clock time.** Every day without this is a day of the differentiating asset permanently lost. That alone puts it ahead of all design work | Python with `httpx`, polite rate limit around 1 req/sec, retries. Whichever route works on the day: API if the key has landed, otherwise nhs.uk pages | Raw payloads for the full estate on disk | 4–6 h | **CRITICAL PATH** — highest-value step in the plan |
| 1.2 | Append-only snapshot store | NEXT | Date-stamped immutable raw payloads · you · `/data/snapshots/YYYY-MM-DD/` · day 1 | Capture raw, parse later: you can re-parse forever but never re-fetch yesterday. Immutability must be in place *before* automation, or early history gets overwritten | Gzipped JSON per practice in dated directories, committed to the repo — free, durable, versioned, zero infrastructure | Two consecutive days captured and diffable | 2 h | — |
| 1.3 | Automate nightly | NEXT | GitHub Actions cron around 03:00 UTC · you · GitHub · day 2 | Makes accrual survive your attention. Daily rather than hourly: the source operates on a 90-day mandate, so hourly polling is three orders of magnitude of waste and reads as abusive | `.github/workflows/snapshot.yml`, repository secret for the API key, auto-commit of results | Three consecutive unattended nights succeed | 2 h | **GATE DG2** — ingestion reliability, satisfied at step 3 instead of step 13 |
| 1.4 | Failure alarm | NEXT | Notify on crawl failure or volume anomaly · you · GitHub Actions · day 3 | Silent crawler death is the one failure that destroys irreplaceable data. Cheap insurance, so it happens immediately rather than at hardening time | Workflow-failure email, plus an assertion that record count sits within ±10% of the prior run | A deliberately broken run alerts you | 1 h | **RISK** — guards the core asset |
| | **§2 — PROVE THE SIGNAL** *(Week 1, days 4–5. This is the real DG1.)* | | | | | | | |
| 2.1 | Field-level API spike | PLANNED | Answer Q1: does v3 carry acceptance status for adults, children and referrals, plus a last-updated date? · you · notebook · day 4 | The one thing viability could *not* confirm. Determines whether the availability pipeline is sanctioned-API or scrape-based, changing risk, cadence and terms-of-use posture. Cheap to answer, expensive to assume | Pull a single record, dump every field, compare against the live nhs.uk profile for the same practice | Documented field map; Q1 closed | 3 h | **GATE DG1** — genuine go/no-go on the availability product |
| 2.2 | Choose the availability route | PLANNED | Decide API-only, hybrid or scrape · you · ADR-002 · day 4 | Forces an explicit recorded decision instead of drift. Must follow the spike and precede any parser work | ADR-002 carrying the field evidence. If scraping: record robots.txt position, rate-limit posture and the no-NHS-branding rule | ADR committed; crawler updated | 1 h | **RISK** — if scrape-only, higher fragility; add change-detection on page structure |
| 2.3 | Snapshot → structured parser | PLANNED | Parse raw snapshots into a tidy practice-day table · you · `/ingest/parse.py` · day 5 | Separating parse from fetch means a parser bug costs a re-run rather than lost data. Only possible once the spike says where the fields are | Python to Parquet, one row per practice per snapshot date, schema documented in `/docs` | The full snapshot history parses clean | 4 h | — |
| | **§3 — THE SPINE** *(Week 2. The unglamorous work everything else depends on.)* | | | | | | | |
| 3.1 | Load ODS practice register | PLANNED | Authoritative practice list and codes · you · `/ingest/ods.py` · week 2 | Provides a stable identity backbone and the ODS codes nhs.uk does not expose. Needed before any joining can start | ODS CSV download under OGL, filtered to England, refreshed monthly | ODS table loaded; count sanity-checked | 2 h | — |
| 3.2 | Geocode via ONSPD | PLANNED | Postcode to lat/long, LSOA, ICB, region · you · `/ingest/geo.py` · week 2 | Unlocks every spatial feature. ONSPD is free under OGL and removes any need for a paid geocoder | ONSPD quarterly CSV, joined on postcode, unmatched rows flagged | Over 99% of practices geocoded | 3 h | **RISK** — unmatched postcodes need a manual fallback |
| 3.3 | Entity resolution: nhs.uk ↔ ODS ↔ BSA | PLANNED | Fuzzy-match on name and postcode; resolve many-to-many contract-to-site links · you · `/ingest/match.py` · week 2 | **The hidden cost the charter never listed.** No shared key exists between the three sources. Prerequisite for every supply-versus-demand output — all of §4 stalls without it | `rapidfuzz` over normalised name and postcode, postcode-blocked candidate generation, a manual review queue for low-confidence pairs, and a reported match rate | Documented match rate plus reviewed exceptions | 1–2 days | **HIGHEST SCHEDULE RISK** — timebox to two days; ship at whatever match rate you reach and publish the number |
| 3.4 | LSOA population join | PLANNED | ONS population by LSOA and age band · you · `/ingest/pop.py` · week 2 | The demand denominator. Without it, "dental desert" is an opinion; with it, it is a rate | ONS mid-year estimates under OGL, aggregated to LSOA with child and adult splits | Population table joined to geography | 2 h | — |
| | **§4 — RETROACTIVE INTELLIGENCE** *(Week 3. Passes DG3 without waiting for history to accrue.)* | | | | | | | |
| 4.1 | Ingest NHSBSA activity history | PLANNED | Contract-level monthly UDA and FP17 data, 2016 to present · you · `/ingest/bsa.py` · week 3 | **The escape hatch.** Gives roughly ten years of longitudinal truth on day one — what practices actually *delivered*, not what they claim. Only usable once 3.3 links contracts to sites | NHSBSA Open Data Portal CSVs under OGL, loaded into DuckDB, refreshed monthly and incrementally | Full history loaded; totals reconciled against published statistics | 4 h | — |
| 4.2 | Supply-vs-demand & dental-desert model | PLANNED | Activity per 1,000 population by LSOA and ICB · you · `/analysis/` · week 3 | The genuinely unoccupied ground identified in viability. Needs both 3.4 and 4.1 in place | DuckDB and GeoPandas; catchments by straight-line distance first, refined by drive time. Method published rather than hidden | Reproducible notebook plus static GeoJSON and Parquet outputs | 2 days | **GATE DG3** — insight beyond directory search, cleared in week 3 rather than week 9 |
| 4.3 | Freshness / trust scoring | PLANNED | Per-practice staleness score against the 90-day rule · you · `/analysis/` · week 3 | The most honest differentiator and simultaneously the legal shield. Nobody else exposes it. Needs §1 history and the 2.3 parser | Days-since-reported buckets, a volatility flag and a never-updated flag. Always rendered as "reported X on DATE", never as fact | Score attached to every practice | 4 h | **COMPLIANCE** — no claim is ever presented as current fact |
| | **§5 — PUBLIC SURFACE** *(Weeks 4–5. Thin on purpose.)* | | | | | | | |
| 5.1 | Static data build step | PLANNED | Pipelines to versioned static JSON and Parquet for the web app · you · `/data/dist/` · week 4 | The decision that deletes the whole infrastructure row: no server database, no Redis, no API layer for v1. Must precede UI work so the UI has a stable contract | Build script producing a bundled practice file, tiles and geo layers, with a versioned schema | The app boots from static files alone | 4 h | — |
| 5.2 | Postcode search & results | PLANNED | Enter a postcode, get ranked nearby practices with freshness labels · you · `/web` · week 4 | Table-stakes entry point for the general-public audience — framed around freshness rather than an acceptance filter that returns nothing | Next.js with client-side distance calculation (the dataset fits in the browser) and ONSPD lookup | Works for any valid English postcode | 1 day | **PRODUCT RISK** — never lead with "accepting" as a filter; ~90% of results would be empty |
| 5.3 | Interactive map & desert layer | PLANNED | Practice markers plus an LSOA choropleth · you · `/web` · week 4 | Where the §4 analysis becomes legible. Follows 5.2 so that search is proven first | MapLibre GL with Protomaps/OSM tiles (ODbL attribution) over static GeoJSON | Map renders England, layers toggle, usable on mobile | 1–2 days | — |
| 5.4 | Practice profile pages | PLANNED | Per-practice detail: contact, reported status and date, availability timeline, activity history · you · `/web` · week 5 | Where the longitudinal record meets an individual user need — and the most search-visible surface on the site | Static generation, one page per practice, sparkline timeline | ~9,000 pages build and deploy | 1 day | — |
| 5.5 | Open data downloads | PLANNED | Bulk CSV and Parquet plus method notes · you · `/web/data` · week 5 | Serves analysts, policy makers, press and researchers — four of the six named audiences — at near-zero cost. The cheapest credibility in the plan | Static file hosting, a data dictionary page and OGL attribution | Downloads live with a dictionary | 3 h | — |
| | **§6 — SHIP** *(Week 6.)* | | | | | | | |
| 6.1 | Compliance & framing pass | PLANNED | No NHS logo or implied endorsement; disclaimers, privacy notice, attributions · you · whole site · week 6 | Cheap now, expensive to retrofit after launch. Must precede public release | Checklist review against NHS identity rules, OGL and ODbL attribution, an explicit "not affiliated with the NHS" statement, and status-as-reported wording everywhere | Checklist signed off in `/docs` | 3 h | **GATE DG5** — fit for public release |
| 6.2 | Deploy & measure | PLANNED | Production deploy, domain, privacy-respecting analytics · you · Vercel · week 6 | Nothing is real until it is public. Last because DG3 and DG4 must clear first | Vercel deploy, custom domain, Plausible or Fathom, Lighthouse check | Live URL; mobile Lighthouse above 90 | 4 h | **GATE DG4** — usability and performance |
| 6.3 | Tell three people who matter | PLANNED | Approach a journalist, an ICB analyst and a dental-access campaigner · you · email · week 6 | The exceptional tier runs through being *used*, not being built. Distribution is a build step, not an afterthought | Short email with a link and one striking finding drawn from your own data | Three approaches made; feedback logged | 2 h | **RISK** — the most-skipped step in projects like this |
| | **§7 — CONTINUOUS** *(Runs alongside everything above.)* | | | | | | | |
| 7.1 | Session journal | CONTINUOUS | Log each working session to `Documenting the Journey/` · you · ongoing | Objective O5 and half the programme's stated purpose. Continuous because reconstructing reasoning after the fact is impossible | One Markdown file per session: decisions, dead ends and observations on the AI-assisted method | Every session logged | 15 min per session | — |
| 7.2 | Data-quality dashboard | CONTINUOUS | Freshness, completeness, match rate, crawl health · you · static page · from week 3 | Publishing your own limitations *is* the trust product. It doubles as your early-warning system | Static page generated by the nightly build | Page live and updating itself | 4 h | — |
| | **§8 — DEFERRED** *(Explicitly not now. Recorded so they stay decided rather than nagging.)* | | | | | | | |
| 8.1 | Accounts & email alerts | DEFERRED | — | Highest effort, greatest GDPR exposure (controller duties, consent, deliverability), and the feature most directly contested by a paid incumbent. Also contradicts the charter's own exclusion of authentication | Revisit only if users ask unprompted | — | — | Post-v1 |
| 8.2 | Public REST API | DEFERRED | — | Static bulk downloads at 5.5 serve roughly 95% of real demand at close to 0% of the operational cost | Revisit when someone actually requests programmatic access | — | — | Post-v1 |
| 8.3 | Public-transport travel times | DEFERRED | — | Straight-line plus drive time answers the question well enough. TfL and GTFS integration is a multi-week rabbit hole for marginal gain | Revisit after user feedback | — | — | Post-v1 |
| 8.4 | Scotland, Wales & Northern Ireland | DEFERRED | — | Entirely separate systems and datasets — effectively three further projects. The charter's "UK" wording should be corrected to "England" | Revisit only once England v1 is stable | — | — | Post-v1 |
| 8.5 | Reviews, ratings & predictive modelling | CUT | — | Google's terms prohibit storage, redistribution and competing directories; CQC does not rate primary dental care; and prediction built on data this unreliable is indefensible | Cut, not deferred | — | — | Closed |

---

## Shape of the commitment

| Dimension | Value | Note |
|---|---|---|
| Timeline | ~6 weeks | Of evenings and weekends to a public v1 |
| Running cost | £0–15 / month | A domain, plus free tiers on GitHub Actions, Vercel and map tiles |
| Critical path | §1, then 3.3 | Start the clock immediately; defend the two-day entity-resolution timebox |
| Open question | Q1 by day 4 | Whether the API carries acceptance status decides the whole availability route |

### The one thing that matters this week

**Steps 1.1 through 1.4.** Everything else in this ledger can slip a month without lasting harm. Those four cannot — each night they are not running is a night of history that no amount of later effort recovers.

---

## Inherited constraints and compliance rules

Carried forward from the viability analysis. These are binding on every step, not optional polish.

| # | Rule | Origin |
|---|---|---|
| C1 | Never present a practice's status as current fact. Always "reported X on DATE" | Source data is self-reported and widely inaccurate — dentists have called it "a work of fiction" |
| C2 | No NHS logo, branding, or anything implying NHS endorsement. Carry an explicit "not affiliated with the NHS" statement | NHS identity guidelines; both existing competitors carry this disclaimer for good reason |
| C3 | Attribute OGL for NHS/ONS data and ODbL for OSM-derived data | Licence conditions |
| C4 | No Google reviews or ratings, ever | Google's terms prohibit storage, redistribution, and building a competing directory |
| C5 | No CQC ratings for dental practices | CQC inspects but does not rate primary dental care — the field is largely empty |
| C6 | Daily ingestion cadence, not hourly | Source operates on a 90-day update mandate; hourly polling is waste and reads as abusive |
| C7 | England only for v1 | Scotland, Wales and NI run entirely separate systems |
| C8 | Publish your own match rates and data-quality limitations | Transparency about weakness *is* the trust product |
| C9 | No predictive modelling | Indefensible on data this unreliable; also excluded by the charter |

---

## Open questions at time of agreement

| # | Question | Why It Matters | Resolution Route |
|---|---|---|---|
| Q1 | Does Service Search API v3 expose acceptance status (adults/children/referrals) and a last-updated date? | Decides whether the availability pipeline is API-based or scrape-based — changing risk, cadence and terms-of-use posture | Step 2.1, day 4. This is the true content of gate DG1 |
| Q2 | Can nhs.uk org IDs, ODS practice codes and BSA contract numbers be reliably joined? | Prerequisite for every supply-versus-demand output; contracts are many-to-many with sites | Step 3.3. Measure and publish the match rate |
| Q3 | Are the owner's viability conditions different from the assumed ones (solo builder, near-zero budget, public release, no NHS partnership)? | Would change the assessment and possibly the plan | Asked in Session 01; awaiting confirmation |
| Q4 | Is there any usable retroactive availability history, e.g. Wayback captures of nhs.uk dentist pages? | Would partially offset the zero-history-at-launch problem | Opportunistic; low priority |

---

*Build Plan v1 · agreed 2026-07-25 · NHS Dentist Intelligence Platform*
