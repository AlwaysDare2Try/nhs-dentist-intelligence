# ADR-001 — Repositioning, Architecture and Scope

- **Status:** Accepted
- **Date:** 2026-07-25
- **Supersedes:** the delivery plan and architecture in `Starting Docs/NHS_Dentist_Intelligence_Platform_Programme_Charter.md` (v0.1)
- **Evidence:** `Documenting the Journey/Session-01_2026-07-25_Concept-Ingestion-and-Viability-Analysis.md`
- **Plan of record:** `Documenting the Journey/Build-Plan-v1_2026-07-25_Delivery-Ledger-and-North-Star.md`

## Context

The programme charter (v0.1, ChatGPT-authored) proposed a consumer-facing "find a dentist accepting NHS patients" search over a service-split architecture, with ingestion at step 4 of a 15-step waterfall. A viability analysis on 2026-07-25 found two facts that invalidate that shape:

1. **The lead use case mostly returns nothing.** Around 9 in 10 UK practices are not accepting new adult NHS patients — 98% in the South West, Yorkshire & Humber and North West. The underlying signal is self-reported and unreliable; dentists have publicly called the nhs.uk status *"a work of fiction"* (in one sample, 3 of 34 practices listed as accepting actually had space). Both the free and paid consumer-alert niches are already occupied.
2. **History is lost every day spent planning.** Availability history exists nowhere. It accrues only in wall-clock time and cannot be backfilled, parallelised, or accelerated. Putting ingestion two-thirds of the way through a waterfall destroys the differentiating asset.

## Decision

Ten decisions are locked by this ADR.

| # | Decision | Rationale |
|---|---|---|
| D1 | Proceed with the project | Viable; low cost, low technical risk, genuine white space |
| D2 | Reposition away from consumer availability search as the lead product | Search returns empty for most users on most days; niche already contested |
| D3 | Lead on longitudinal record + freshness/trust scoring + supply-vs-demand + open data | The defensible unoccupied ground; serves the analyst, policy and press audiences the charter already names |
| D4 | The snapshot crawler is the first build action, before architecture | History accrues only in wall-clock time |
| D5 | Drop Google reviews and CQC ratings from scope | Google ToS prohibits storage, redistribution and competing directories; CQC does not rate primary dental care |
| D6 | England only for v1 | Scotland, Wales and NI run separate systems; the charter's "UK" framing is corrected to England |
| D7 | Daily ingestion cadence, not hourly | Source operates on a 90-day update mandate; hourly polling is waste and reads as abusive |
| D8 | Radically simplify the architecture | The dataset is a few megabytes; Redis/CDN/service-split is unjustified and harms the O5 case study |
| D9 | Defer accounts and email alerts | Highest effort, greatest GDPR exposure, most directly contested by a paid incumbent |
| D10 | Record the journey in `Documenting the Journey/` as Markdown | Preserves tables, renders everywhere, diffs cleanly as the log grows |

### Two architectural consequences

**No server database for v1.** ~9,000 practices is a few megabytes. Pipelines run offline in Python, DuckDB and GeoPandas and emit static JSON and Parquet; the web app reads those files. Postgres and PostGIS arrive only when something genuinely needs them.

**Capture raw, parse later.** The crawler stores unparsed source payloads from the first night. This is why it can start *before* we know whether the source carries acceptance status (open question Q1): yesterday cannot be re-fetched, but it can always be re-parsed.

**Stack:** Python 3.12 · GitHub Actions cron · append-only snapshots committed to the repo · DuckDB · Next.js + MapLibre GL on Vercel · Protomaps/OSM tiles.

## Binding constraints

These are conditions on every step, not optional polish.

| # | Rule |
|---|---|
| C1 | Never present a practice's status as current fact. Always "reported X on DATE" |
| C2 | No NHS logo, branding, or implied endorsement. Carry an explicit "not affiliated with the NHS" statement |
| C3 | Attribute OGL for NHS/ONS data, ODbL for OSM-derived data |
| C4 | No Google reviews or ratings, ever |
| C5 | No CQC ratings for dental practices |
| C6 | Daily ingestion cadence, not hourly |
| C7 | England only for v1 |
| C8 | Publish our own match rates and data-quality limitations |
| C9 | No predictive modelling |

## Consequences

**Positive.** The differentiating asset starts accruing on day 1 rather than week 6. Infrastructure cost falls to £0–15/month. Gate DG3 (insight beyond directory search) clears in week 3 rather than week 9, because NHSBSA activity data supplies ~10 years of retroactive history on day one.

**Negative.** At launch we have no availability history of our own — the timeline product is thin until roughly week 6 of accrual. Committing snapshots to git will grow the repository over time; at a few MB gzipped per night this is tolerable for years, but it is a known future migration.

**Accepted risks.** Entity resolution across nhs.uk, ODS and NHSBSA has no shared key and is the highest schedule risk; it is timeboxed to two days and we ship at whatever match rate we reach, publishing the number (C8). If the availability route turns out to be scrape-only, fragility rises and change-detection on page structure becomes mandatory — that decision is deferred to ADR-002.

## Not in scope for v1

Accounts and email alerts, a public REST API, public-transport travel times, Scotland/Wales/Northern Ireland (all deferred); reviews, ratings and predictive modelling (cut, not deferred).
