# Session 01 — Concept Ingestion & Viability Analysis

**Date:** 2026-07-25
**Participants:** Project owner (mateega@gmail.com) · Claude Opus 5 (Claude Code CLI)
**Working directory:** `/Users/dare2try/Claude Projects/CLD DentistApp`
**Session purpose:** Ingest the ChatGPT-authored starting concept, confirm shared understanding, then stress-test viability before committing to a build.

> **Why this file exists.** Programme Charter objective **O5** ("Document the development process") and workstream **WS7** treat documentation as a first-class deliverable, not an afterthought. This folder is the primary evidence base for the second stated objective of the programme: *"Document a repeatable approach to AI-assisted product development."* Sessions are recorded verbatim in sequence, including the reasoning, the research performed, and the points where the AI disagreed with the source material.

---

## Table of Contents

1. [Session Inputs](#session-inputs)
2. [Exchange 1 — Ingest and summarise the concept](#exchange-1--ingest-and-summarise-the-concept)
3. [Exchange 2 — Run viability analysis](#exchange-2--run-viability-analysis)
4. [Decisions Reached](#decisions-reached-this-session)
5. [Open Questions Carried Forward](#open-questions-carried-forward)
6. [Appendix A — Research Log](#appendix-a--research-log-tool-calls-made)
7. [Appendix B — Notes on the AI-Assisted Method](#appendix-b--notes-on-the-ai-assisted-method-for-o5)

---

## Session Inputs

Two files were provided in `Starting Docs/`, both produced in prior work with ChatGPT:

| File | Size | Nature |
|---|---|---|
| `NHS_Dentist_Intelligence_Platform_Programme_Charter.md` | 9.5 KB | Programme charter, draft v0.1 — purpose, problem statement, objectives O1–O5, scope, 7 workstreams, 15-activity delivery plan, decision gates DG1–DG5, success criteria |
| `ChatGPT Image Jul 22, 2026, 11_43_55 PM.png` | 1.8 MB | High-level workflow & system architecture diagram — data sources, pipeline, core services, infrastructure, UI, audiences, cross-cutting concerns |

Model in use: **Opus 5** (set as session default via `/model` at session start).

---

## Exchange 1 — Ingest and summarise the concept

### 👤 User

> I want you to study the 2 files in this folder. I have worked with chatgpt to come up with the initial concept. I want you to study both these files and ingest them and fully understand what we are trying to achieve. Then summarise it back to be.
>
> After that i will ask you to assess viability based on a number of conditions. But that is the next step.
>
> The files are in this folder: 'Starting Docs'

### 🤖 Claude

*(Read both files — the markdown charter in full, and the PNG architecture diagram visually.)*

I've read both. Here's my understanding.

#### What you're building

**NHS Dentist Intelligence Platform** — a public-facing web platform that ingests scattered, point-in-time NHS dental data and turns it into *longitudinal intelligence*: not just "who's near me" but "who is actually accepting NHS patients, how has that changed, and where are the gaps."

There's a **dual purpose** stated up front, and it matters: (1) ship a genuinely useful public tool, and (2) produce a documented, repeatable case study in AI-assisted product delivery. Objective O5 and WS7 make documentation a first-class deliverable, not an afterthought.

#### The core insight / value proposition

NHS Find a Dentist shows you a snapshot. Nobody keeps the history. The differentiator — codified as Decision Gate DG3 ("insight beyond basic directory search") — is **change over time**: first-seen/last-seen, reopening patterns, dental deserts, supply vs. demand.

#### Architecture (from the diagram)

**Inputs (7 sources):** NHS Find a Dentist (API/scrape — live acceptance status, accessibility, emergency appts) · General Dental Practices open data (data.gov.uk — practices, addresses, UPRNs, ICBs) · ONS/OS postcode & boundary reference data · ONS population by LSOA & age band (for supply/demand) · transport data (OSRM/TfL for travel times) · optional reviews (CQC, Google Places). Scheduled re-ingestion every 1–6 hours.

**Pipeline:** Ingestion → Cleaning/Normalisation (dedupe, address standardisation, geocoding) → Storage (raw + processed), with a Data Quality & Monitoring loop watching freshness, completeness and change/error rates.

**Core services (5):** Practice Intelligence (master list + attributes) · Geo-Spatial Engine (1/3/5/10/20-mile radii, drive & public transport time, catchment, nearest-available) · Availability Intelligence (adults/children acceptance, first-seen/last-seen, change history) · Analytics & Insights (dental desert heatmaps, supply vs demand, trends, reopening patterns) · Alerts & Notifications (notify when new availability appears nearby).

**Infrastructure:** PostgreSQL + PostGIS, REST API, map tiles/geocoding/routing, Redis/CDN caching, auth + rate limiting + GDPR, cloud hosting with CI/CD.

**UI:** postcode search with filters, interactive map with heatmaps and catchments, practice profiles, analytics dashboard, alert management, export/API access.

**Cross-cutting:** privacy/GDPR, security, audit logging, data quality checks, performance monitoring, backup/DR, scalability.

#### Audiences (six, plus stated public impact)

General public (access to care) · patients with specific needs (wheelchair access, children, emergency) · healthcare analysts (exports, trends) · policy makers (regional shortages, resource planning) · dental practices (competitive/BI) · researchers & press (transparency, journalism).

#### Delivery approach

Strictly linear, dependency-chained: Discovery → Data Acquisition → Data Engineering → Intelligence → Application → Automation → Documentation → Release. 15 sequenced activities across 7 workstreams, gated by DG1–DG5 (sources sufficient → ingestion reliable → insight beyond directory → usable & performant → fit for public release). Everything is currently `Planned` except documentation, which is `Ongoing`.

**Explicitly out of scope for v1:** booking, clinical advice, patient records, meaningful auth, predictive modelling.

#### Two tensions I noticed while reading

Not assessing viability yet — just flagging that the docs aren't perfectly consistent, and these will likely come up when you do ask:

1. **Alerts vs. auth/scope.** The diagram makes Alerts & Notifications a core service with an alert-management UI, but the charter excludes "user authentication beyond basic requirements" — persistent per-user alerts implies accounts, storage of contact details, and GDPR/consent handling.
2. **The intelligence depends on data you don't have yet.** DG3 and every trend output rest on historical availability, which doesn't exist in any source — it only accrues from the moment *you* start capturing it. That has implications for when the platform's differentiating value becomes real.

Ready for the viability conditions when you are.

---

## Exchange 2 — Run viability analysis

### 👤 User

> run viability analysis

### 🤖 Claude

Before I judge feasibility I want to verify the load-bearing assumptions about the data sources rather than assert them from memory — the whole thing stands or falls on whether the availability signal is actually obtainable.

*(Performed 6 web searches and 5 page fetches — see [Appendix A](#appendix-a--research-log-tool-calls-made).)*

I verified the load-bearing assumptions rather than assuming them. Two findings materially change the shape of the project.

---

# Viability Analysis — NHS Dentist Intelligence Platform

**Verdict: viable, and cheap to build — but the concept as drawn is aimed at the wrong product.** Nothing here is technically hard or legally blocked. The risks are all in *positioning* and *timing*, and one of them is a clock you're currently losing.

You said you'd give me conditions and then didn't, so I've assessed against what I take to be the implicit ones: solo builder + AI assistance, near-zero budget, public release, no NHS partnership. Say the word if your conditions differ and I'll re-run.

## Scorecard

| Dimension | Rating | Note |
|---|---|---|
| Data availability | **Strong** | Every input exists under OGL |
| Legal / licensing | **Strong** | With two sources dropped (below) |
| Technical difficulty | **Very low** | ~8–9k practices. This is a spreadsheet, not big data |
| Cost | **Very low** | £10–30/month all-in |
| Data *quality* | **Weak — and unfixable by you** | The crux |
| Differentiation | **Narrow but real** | Not where the charter thinks it is |
| Plan realism | **Weak** | Sequencing inverts the true critical path |

## The two findings that change the design

**1. The core search use case mostly returns nothing.** BBC/BDA research found ~9 in 10 UK practices are not accepting new adult NHS patients — 98% in the South West, Yorkshire & Humber and North West. A postcode search filtered to "accepting NHS adults" is an empty page for most users on most days. And the underlying signal is self-reported: dentists have publicly called the nhs.uk status *"a work of fiction"* — in one sample, 3 of 34 practices listed as accepting actually had space.

This does **not** kill the project. It relocates the value:

- Searching a 10%-dense field is a bad product. **Detecting transitions in a 10%-dense field is a great one** — rare events are exactly what's worth watching for you.
- Nobody exposes *staleness*. The 90-day update rule exists and is widely ignored. A per-practice trust/freshness score ("reported accepting 4 days ago" vs "not updated in 11 months") is genuine, defensible intelligence derived from data nobody retains — and it's honest about the fiction problem instead of laundering it.

**2. You are losing history every day you plan.** Availability history exists nowhere. It only accrues from the moment your crawler starts. Your plan puts ingestion at step 4 of 15 and gates DG3 ("insight beyond directory search") at step 9 — so the differentiating asset starts accumulating two-thirds of the way through a waterfall. Wall-clock time is the one input you cannot parallelise, backfill, or accelerate with AI.

**The single highest-value action: get a dumb, ugly nightly snapshot crawler running this week**, before any architecture, API, or UI work. It can write JSON to a directory. Everything else can be built later against data you already own.

**Partial escape hatch:** NHS BSA's *English Contractor Monthly General Dental Activity* dataset gives you contract-level monthly UDA and FP17 activity back to 2016 — retroactive longitudinal truth about what practices actually *delivered*, not what they claim. That's arguably a stronger signal than acceptance status and it's available on day one. It's the fastest route through DG3.

## What to cut

- **Google reviews/ratings** — ToS forbids storing and redistributing, and specifically forbids building a competing directory. Straight out.
- **CQC ratings** — CQC inspects but does not *rate* primary dental care. That box is mostly empty for dentistry.
- **Redis/CDN layer, separate routing service, five "core services"** — the entire dataset is a few megabytes. One Postgres+PostGIS instance and one app, with precomputed distances. The diagram is an enterprise architecture for a dataset that fits in RAM. Over-engineering here also directly damages objective O5: the case study is more valuable if the build is legibly small.
- **1–6 hour ingestion** — the source updates on a *90-day* mandate. You're proposing to poll three orders of magnitude faster than the data changes, against NHS infrastructure. Daily is generous.
- **UK-wide** — Scotland, Wales and NI run entirely separate systems. England-only for v1; the charter's problem statement says "UK" and should be corrected.

## Competitive reality (the charter has no competitor analysis)

Two products already exist. [DentistAlert](https://www.dentistalert.co.uk/) sells exactly the alerts feature — £4.99/month, England-only, no maps, no history, no analytics. [rjackson/dentists](https://github.com/rjackson/dentists) is free and open source: map, filters, email notifications, nightly refresh via GitHub Action.

So consumer search + alerts is **taken, on both the free and paid ends**. The white space is what neither does and the one-off analyses (LGA, Nuffield, academic spatial studies) can't sustain:

1. A continuous public longitudinal record with freshness/trust scoring
2. Supply vs. demand per LSOA — BSA activity joined to ONS population
3. Open API and bulk exports for analysts, press and policy — your charter already names these audiences

That's the defensible product. Lead with it.

## The hidden engineering cost nobody's costed

Joining the three datasets. nhs.uk organisation IDs, ODS dental practice codes, and BSA *contract* numbers share no clean key — you'll be fuzzy-matching on name and postcode, and contracts are many-to-many with sites. This is the one genuinely fiddly piece of work in the whole project, it's a prerequisite for every supply-vs-demand output, and it appears nowhere in your 15 activities. Budget real time for it.

## One thing I couldn't confirm

Whether Service Search API v3 actually exposes acceptance status. The NHS Digital catalogue pages are too thin to say, and the evidence conflicts: rjackson's project appears to take it from the API, while DentistAlert says it uses the API for practice details but checks the nhs.uk website directly for *accepting status* — which implies the API does not reliably carry it. Note also that v1/v2 were deprecated on 2 February 2026, so v3 is the only target.

**This is the real content of your DG1 gate.** Spike it in week one: get a key, pull one dentist record, inspect the fields. If acceptance status isn't in the API, your entire availability pipeline depends on scraping — which is doable but changes the risk, cadence and terms-of-use picture materially.

## Reshaped sequence

1. **Now:** nightly snapshot crawler → append-only storage. Ugly is fine. Start the clock.
2. **Week 1:** API field spike (DG1 answered properly).
3. **Weeks 2–3:** ODS ↔ BSA ↔ nhs.uk entity resolution; ONSPD geocoding; LSOA population join.
4. **Weeks 3–4:** supply-vs-demand and dental-desert outputs from BSA history — DG3 passed on *retroactive* data.
5. **Weeks 4–6:** thin public web app: map, search, practice profiles with freshness scoring, exports.
6. **Later, if at all:** accounts and alerts. Note this collides with the charter's exclusion of auth, and brings email deliverability and GDPR controller duties — the highest-effort, most-contested-by-incumbents feature. Defer it.

Compliance notes: don't use the NHS logo or imply endorsement (the disclaimer on DentistAlert isn't decorative), attribute OGL and OSM/ODbL, and always render status as *"practice reported X on DATE"* — never as fact. Given how wrong the source data is, that framing is both your legal shield and your product.

### Sources cited

- [Service Search API](https://digital.nhs.uk/developer/api-catalogue/directory-of-healthcare-services)
- [v1/v2 deprecation notice](https://digital.nhs.uk/developer/api-catalogue/directory-of-healthcare-services/service-search-versions-1-and-2)
- [ODS General Dental Practices](https://www.odsdatasearchandexport.nhs.uk/referenceDataCatalogue/General-Dental-Practices_580652996.html)
- [ODS CSV downloads](https://digital.nhs.uk/services/organisation-data-service/data-search-and-export/csv-downloads)
- [NHSBSA English Contractor Monthly General Dental Activity](https://opendata.nhsbsa.net/dataset/english-contractor-monthly-general-dental-activity)
- [NHSBSA Dental Statistics England 2024/25](https://www.nhsbsa.nhs.uk/statistical-collections/dental-england/dental-statistics-england-202425)
- [nhs.uk data described as "work of fiction"](https://www.aol.com/articles/nhs-dentist-website-fiction-061802700.html)
- [LGA dental deserts analysis](https://www.local.gov.uk/about/news/nhs-dental-deserts-persist-rural-and-deprived-communities-lga-analysis)
- [High-need dental deserts: national spatial analysis](https://www.researchsquare.com/article/rs-9117997/v1)
- [DentistAlert](https://www.dentistalert.co.uk/)
- [rjackson/dentists](https://github.com/rjackson/dentists)
- [Commons Library: Finding an NHS dentist in England](https://commonslibrary.parliament.uk/finding-an-nhs-dentist-in-england/)

---

## Decisions Reached This Session

| # | Decision | Rationale | Status |
|---|---|---|---|
| D1 | Proceed with the project | Viable, low cost, low technical risk, real white space exists | **Agreed** — owner: *"I like the results of your viability checks"* |
| D2 | Reposition away from consumer availability search as the lead product | ~90–98% of practices closed to new adult NHS patients; search returns empty. Both free and paid consumer-alert niches already occupied | **Accepted into planning** |
| D3 | Lead on longitudinal record + freshness/trust scoring + supply-vs-demand + open data access | The defensible, unoccupied ground; serves the analyst/policy/press audiences already named in the charter | **Accepted into planning** |
| D4 | Snapshot crawler is the first build action, before architecture | History accrues only in wall-clock time; it cannot be backfilled or parallelised | **Accepted into planning** |
| D5 | Drop Google reviews and CQC ratings from scope | Google ToS prohibits storage/redistribution and competing directories; CQC does not rate primary dental care | **Accepted into planning** |
| D6 | England only for v1 | Scotland, Wales and NI run separate systems; charter's "UK" framing to be corrected | **Accepted into planning** |
| D7 | Daily ingestion cadence, not 1–6 hourly | Source data operates on a 90-day update mandate | **Accepted into planning** |
| D8 | Radically simplify the architecture from the diagram | Dataset is a few MB; Redis/CDN/service-split is unjustified and harms the O5 case study | **Accepted into planning** |
| D9 | Defer accounts and alerts | Highest effort, most GDPR exposure, most directly contested by incumbents | **Accepted into planning** |
| D10 | Record the journey in `Documenting the Journey/`, Markdown format | Preserves session tables/headings, renders everywhere, diff-able as the log grows | **Done — this file** |

## Open Questions Carried Forward

| # | Question | Why it matters | Resolution route |
|---|---|---|---|
| Q1 | Does Service Search API v3 expose acceptance status (adults/children/referrals) and a last-updated date? | Determines whether the availability pipeline is API-based or scrape-based — changes risk, cadence and ToS posture | Week-1 spike. This is the true content of gate DG1 |
| Q2 | Can nhs.uk org IDs, ODS practice codes and BSA contract numbers be reliably joined? | Prerequisite for every supply-vs-demand output; contracts are many-to-many with sites | Entity-resolution work package; measure match rate |
| Q3 | Are the owner's viability *conditions* different from the assumed ones (solo, near-zero budget, public release, no NHS partnership)? | Would change the assessment | Asked; awaiting confirmation |
| Q4 | Is there any usable retroactive availability history (e.g. Wayback captures of nhs.uk dentist pages)? | Would partially offset the zero-history-at-launch problem | Opportunistic investigation, low priority |

---

## Appendix A — Research Log (tool calls made)

Recorded for objective O5: this is what the AI actually did, not just what it concluded.

| # | Tool | Target / Query | What it established |
|---|---|---|---|
| 1 | `Bash` | `ls` project + `Starting Docs` | Two input files located |
| 2 | `Read` | Programme charter (225 lines) | Full charter ingested |
| 3 | `Read` | Architecture PNG | Diagram interpreted visually |
| 4 | `WebSearch` | NHS Service Search API — dentist acceptance fields | Found API exists; surfaced two existing competitor products |
| 5 | `WebSearch` | nhs.uk data accuracy, 90-day update rule | Confirmed the "work of fiction" quality problem and the 90-day mandate |
| 6 | `WebSearch` | NHSBSA practice-level UDA open data | Found the retroactive-history escape hatch |
| 7 | `WebSearch` | ODS General Dental Practices dataset licensing | Confirmed OGL, England/Wales/IoM coverage |
| 8 | `WebFetch` | NHS Digital Service Search API catalogue | v1/v2 deprecated 2026-02-02; v3 in production; docs too thin on fields |
| 9 | `WebFetch` | dentistalert.co.uk | Paid incumbent: £4.99/mo alerts, England-only, no maps/history/analytics; sources acceptance status from the *website*, not the API |
| 10 | `WebFetch` | github.com/rjackson/dentists | Free OSS incumbent: map + filters + email alerts, nightly GitHub Action refresh |
| 11 | `WebFetch` | Commons Library (HTTP 403 — failed) | Blocked; figures obtained via search instead |
| 12 | `WebFetch` | Service Search API v3 page | Still insufficient detail → became open question Q1 |
| 13 | `WebSearch` | Dental deserts / acceptance statistics 2026 | ~9 in 10 practices closed to new adults; 98% in worst regions; ~13m people in dental deserts |

## Appendix B — Notes on the AI-Assisted Method (for O5)

Observations worth capturing while they are fresh, since the *method* is half the programme:

1. **The AI disagreed with the source concept, and that was the valuable output.** The ChatGPT-authored charter and diagram were internally coherent but rested on two unverified assumptions (that availability search is a viable product, and that history would be available when needed). Coherence is not validation.
2. **Refusing to answer from memory was the decisive move.** The findings that reshaped the project — competitor existence, the 90% closure rate, the retroactive BSA dataset, the API field ambiguity — all came from live research, not from the model's prior knowledge. A viability analysis written from memory would have confirmed the original plan.
3. **The most important finding was a scheduling one, not a technical one.** No amount of AI acceleration recovers lost wall-clock time. AI compresses build effort; it does not compress data accrual. Plans built around AI speed should be re-examined for anything that accrues in real time.
4. **An honest "I could not confirm this" is a deliverable.** Q1 was left explicitly open rather than guessed, and converted into a one-day spike at the front of the plan.
5. **Over-architecture is anti-documentation.** A build small enough to explain is worth more to the case study than a build that looks impressive. The two objectives pull in the same direction here.

---

*End of Session 01.*
