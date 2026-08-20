# NHS Dentist Intelligence Platform

An open record of NHS dental provision in England: nightly availability snapshots, ~10 years of NHSBSA activity history, and a supply-versus-demand view of where dental deserts actually are.

**Not affiliated with, endorsed by, or connected to the NHS.**

## Why this exists

The nhs.uk dentist directory tells you what a practice reported. It does not tell you *when* they reported it, and it keeps no history. Practices operate under a 90-day update mandate that is widely unmet — dentists themselves have called the published status "a work of fiction". This project records what was reported and when, keeps every snapshot, and publishes its own error rates.

Availability history exists nowhere and accrues only in wall-clock time. That is the whole reason the crawler runs before anything else is designed.

## Status

Pre-v1, in active build. See [`CLAUDE_PROGRESS.md`](CLAUDE_PROGRESS.md) for live status and [the build plan](Documenting%20the%20Journey/Build-Plan-v1_2026-07-25_Delivery-Ledger-and-North-Star.md) for the full delivery ledger.

## How it works

Pipelines run offline in Python and emit static JSON and Parquet; the web app reads those files. There is no server database — ~9,000 practices is a few megabytes.

```
ingest/    fetch, parse, ODS register, geocoding, entity resolution
data/      snapshots/YYYY-MM-DD/  append-only raw captures (committed)
           dist/                  generated static build outputs
analysis/  supply-vs-demand, freshness scoring
web/       Next.js + MapLibre GL front end
docs/      architecture decision records
```

**Capture raw, parse later.** The crawler stores unparsed payloads. Yesterday cannot be re-fetched, but it can always be re-parsed.

## Development

### Fresh clone → running

Requires Python 3.12 (see `.python-version`) and [`uv`](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/learndca/nhs-dentist-intelligence.git
cd nhs-dentist-intelligence
uv sync --all-extras
uv run ruff check .
uv run pytest -q
```

To run a capture yourself (writes into `data/snapshots/`, ~2 hours for the
full estate, no credentials needed):

```bash
uv run python ingest/fetch.py --route auto
uv run python ingest/health.py
```

The front end is a separate Next.js app:

```bash
cd web && npm install && npm run dev
```

[`AGENTS.md`](AGENTS.md) is the canonical brief for this repository — the
architecture, the nightly snapshot contract and what not to change.

## Data sources and licensing

| Source | Licence |
|---|---|
| nhs.uk service search / NHS Service Search API | Crown copyright, OGL |
| ODS organisation register | OGL |
| ONS Postcode Directory, mid-year population estimates | OGL |
| NHSBSA dental activity open data | OGL |
| Map tiles (OpenStreetMap-derived) | ODbL |

Practice status is always presented as *"reported X on DATE"*, never as current fact.
