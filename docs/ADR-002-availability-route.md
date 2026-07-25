# ADR-002 — Availability route: scrape nhs.uk, defer the API

- **Status:** Accepted
- **Date:** 2026-07-25
- **Ledger steps:** 2.1 (field-level spike), 2.2 (route decision)
- **Closes:** open question **Q1**. Clears gate **DG1**
- **Supersedes nothing.** Extends ADR-001

## Context

ADR-001 deferred one question: does the source carry per-practice acceptance status *and* a last-updated date? Everything about the availability product depends on it, and the build plan made it the true content of gate DG1. We had no NHS Service Search API v3 key and an unknown approval lead time, so the question had to be answered without one.

An investigation on 2026-07-25 tested the alternatives against live endpoints rather than documentation.

## Decision

**Capture availability by fetching nhs.uk HTML. Enumerate from the published dentist sitemap. Do not wait for an API key.**

The route is:

1. `GET https://www.nhs.uk/sitemap-profiles-dentist.xml` — one request returning the authoritative set of published English dentist profiles (**6,407** on 2026-07-24), each with a `<lastmod>`.
2. For each practice, `GET {profile_url}/appointments` — carries the acceptance statement and `<p id="dentist-accepting-patients-last-updated">Last confirmed: DATE</p>`.
3. On 404, fall back to `{profile_url}` — referral-only specialists have no appointments page and would otherwise be silently dropped.

At ~1 request/second this is roughly 1.8 hours nightly.

## Q1 — answered: YES

Acceptance status is present for every profile. The last-confirmed date is present for every practice that has declared a status, and absent exactly when a practice has not declared one. In a 40-practice random sample there were **zero** cases of status-stated-but-date-missing.

Five observed states:

| State | Marker | Date |
|---|---|---|
| Accepting, some or all cohorts | `This dentist currently accepts new NHS patients … if they are:` + cohort list | Yes |
| Accepting one cohort only | `This dentist currently only accepts new NHS patients … children aged 17 or under.` | Yes |
| Not accepting | `This dentist does not currently accept new NHS patients for routine dental care.` | Yes |
| Not confirmed | `This dentist has not confirmed if they currently accept new NHS patients…` | **No — element absent entirely** |
| Referral-only specialist | Overview page only; `/appointments` returns 404 | No |

Cohort granularity — adults 18+, adults entitled to free care, children 17-under, urgent care, referral-only — matches the v3 API's five `AcceptingPatients.Dentist[]` entries exactly. **We lose nothing material by scraping.** The API's one genuine advantage is a precise ISO timestamp rather than a display date.

## Why not the alternatives

**Service Search API v3.** Requires a key for every call; production onboarding needs a signed Online Connection Agreement and has unknown lead time. The integration tier is capped at 1,500 requests/week — insufficient for 6,407 practices even once. Waiting would have cost nights of irreplaceable history for a marginal gain in date precision.

**The `/service-search/find-a-dentist/results` page.** Server-rendered, no hidden JSON endpoint (the bundle was checked — zero `fetch`/XHR calls). Hard cap of **50 results**, no pagination of any kind, so full coverage would need a geographic sweep of thousands of seed points. It also lacks the last-confirmed date, which is the entire differentiator. Rejected. A 200-outcode sweep did confirm its 4,386 practices are a strict subset of the sitemap, so the sitemap is not missing anything.

**ODS bulk file.** `files.digital.nhs.uk` returns 403 and publishes `Disallow: /`. Not crawled. The ORD API is used instead, but for the *register* (step 3.1), not for availability — it carries no acceptance data.

## Compliance posture

**robots.txt** (`https://www.nhs.uk/robots.txt`, checked in full). Neither `/services/dentist/**` nor `/service-search/find-a-dentist/results` is disallowed; the sitemap is explicitly advertised. There is **no `Crawl-delay` for `User-agent: *`** — the only one present applies to AhrefsBot. The single dentist-related `Disallow` is a legacy ASP.NET path we do not touch.

**Terms.** `https://www.nhs.uk/our-policies/terms-and-conditions/` contains **no anti-scraping clause** — checked for scrape, crawl, robot, automated, harvest, spider, systematic. Content is released under the Open Government Licence.

**Attribution is mandatory and binding on the web app** (constraint C3, now with specific wording). Because we refresh more often than every 7 days, clause 3.6(a) requires:

- `Information from the NHS website`, and
- prominently: `Information from the NHS website is licensed under the Open Government Licence v3.0`

Excluded from OGL: logos, trademarks, third-party content and **personal data** — relevant if named-dentist fields are ever ingested. Combined with C2 (no NHS branding, explicit "not affiliated" statement), this is checked at step 6.1.

**Rate posture.** ~1 request/second globally regardless of worker count; daily, never hourly (C6). An honest User-Agent naming the project with a contact URL — verified accepted, so **no browser spoofing is used or needed**. `Retry-After` is obeyed; a 429 backs off the entire crawl rather than one worker.

**Pages carry `<meta name="robots" content="noindex">`** — an indexing directive, not a crawl prohibition, but recorded here so the compliance pass at 6.1 addresses it explicitly.

## Consequences

**Positive.** History starts accruing immediately, with no dependency on an approval process. We capture strictly more than the search page offers, at a defensible request rate, under a licence that permits reuse.

**Negative — and this is the real cost.** We are now coupled to nhs.uk's HTML. A markup change breaks parsing silently. Three mitigations, all mandatory:

1. **Capture raw** (ADR-001). A markup change costs a re-parse, never lost data — the payloads remain correct even when the parser stops understanding them.
2. **Change detection at step 2.3.** The parser must assert that a known share of pages yield a recognised acceptance state, and fail loudly when that share drops.
3. **Parse for absence, not null.** "Not confirmed" practices have no date element at all; assuming an empty field would silently misread them as dated.

**Known sharp edges.** nhs.uk zero-pads the ODS numeric part to six digits (`V01699` → `V001699`) — getting this wrong 404s every fetch. Expect ~2.5% of sitemap entries to be stale or referral-only; tolerate 404s rather than aborting.

## Revisit when

A production API key arrives. At that point the API becomes the preferred route for its precise timestamps and structured cohort flags, and the scraper becomes the fallback. The snapshot store is route-tagged (`run.json.route`) so a switch is visible in the history rather than silent. This does **not** block anything today.

## Unexpected finding

The sitemap is ordered newest-first and its `<lastmod>` values span **2026-07-24 back to 2011-01-06**. A single request therefore yields a freshness distribution for the entire estate — before any history of our own has accrued. Practices that have not confirmed their status in over a decade are visible on day one. This materially strengthens step 4.3 (freshness scoring) and should be exploited there.
