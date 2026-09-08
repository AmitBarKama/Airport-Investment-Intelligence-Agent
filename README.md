# Airport Investment Intelligence Agent — Research & Build Pack

Everything needed to build the Wonderful assignment in ~1 day.
Read the docs in order; each one answers **what** to build *and* **why that choice over the alternatives**.

## The assignment in one sentence
Build a conversational agent that helps an investment firm find **US airports where modernization/expansion capex will pay off**, backed by **deterministic scoring** (not vibes), with **chat + voice**, that **explains its reasoning** and **states its assumptions**.

## Doc index

| # | File | What it answers |
|---|------|-----------------|
| 00 | [docs/00-company-context.md](docs/00-company-context.md) | Who Wonderful is and how that should shape your choices |
| 01 | [docs/01-data-sources.md](docs/01-data-sources.md) | Every free API/dataset, what it gives you, verified status, tradeoffs |
| 02 | [docs/02-scoring-methodology.md](docs/02-scoring-methodology.md) | The KPIs, the formulas, the published standards they're anchored to |
| 03 | [docs/03-architecture.md](docs/03-architecture.md) | System design + every "why not X" |
| 04 | [docs/04-agent-design.md](docs/04-agent-design.md) | Tool schemas, prompts, conversation memory, uncertainty handling |
| 05 | [docs/05-voice.md](docs/05-voice.md) | Voice options, recommendation, the airport-code accuracy trick |
| 06 | [docs/06-llm-provider.md](docs/06-llm-provider.md) | Free API keys compared; which to pick |
| 07 | [docs/07-backend-spec.md](docs/07-backend-spec.md) | ETL, DB schema, REST/SSE endpoints |
| 08 | [docs/08-frontend-spec.md](docs/08-frontend-spec.md) | UI layout, components, states |
| 09 | [docs/09-tradeoffs-cheatsheet.md](docs/09-tradeoffs-cheatsheet.md) | **Interview prep: every decision, pros, cons, what you'd do with more time** |
| 10 | [docs/10-build-plan.md](docs/10-build-plan.md) | Hour-by-hour plan with cut lines |
| 11 | [docs/11-demo-questions.md](docs/11-demo-questions.md) | The 4 sample questions, worked end-to-end |

`scripts/verify_sources.sh` — run this **first** on your own machine to confirm which data endpoints are live.

## The build

`airport-agent/` contains the working implementation. See
[`airport-agent/README.md`](airport-agent/README.md) to run it and
[`airport-agent/DESIGN.md`](airport-agent/DESIGN.md) for the design deliverable.

```bash
cd airport-agent
python3 -m etl.build      # build the database (~30s)
python3 -m api.server     # http://127.0.0.1:8000
python3 -m unittest discover -s tests    # 126 Python tests
node tests/test_conversations.mjs        # + 77 JS tests across 3 files
```

No `pip install`, no `npm install`, no API key required to run the deterministic
analytics. **All traffic volumes are real**: the database is built from BTS
T-100 Segment (All Carriers) for 2019 and 2024 — 624 US commercial-service
airports and 52,649 routes — joined to OurAirports structure and runway
geometry. An earlier draft shipped synthetic volumes as a fallback; that is no
longer the case. Docs 01–11 below are the research that informed the build.

**Start here:** [`deliverables/`](deliverables/) holds the submission set —
the requirement-by-requirement compliance audit, the design deliverable split
into its three required parts, and the verification evidence behind every
claim on this page.

## The three ideas that make this submission stand out

1. **Anchor the score to a published federal standard.** FAA Advisory Circular 150/5060-5 says: start *planning* capacity at 60% of Annual Service Volume, start *building* at 80%. So the agent doesn't invent thresholds — it applies the FAA's. That converts "my opinion" into "the regulator's rule, computed from data."
2. **The LLM never does arithmetic.** Every number in every answer comes from a Python function. The model picks tools, sets parameters, and narrates. This is exactly what "deterministic scoring, not only LLM output" is asking for, and it's the single easiest thing to get wrong.
3. **Ship uncertainty as a feature.** Every answer carries a data-vintage stamp, a confidence score, and the assumptions used (e.g. "long-haul = ≥2,500 nmi; there is no ICAO/IATA standard"). A weight-sensitivity run shows how stable the ranking is. Most candidates will ship a ranked list with false precision; you ship one that knows what it doesn't know.

## Quick start (once built)

```bash
bash scripts/verify_sources.sh        # confirm data endpoints reachable
make etl                              # build data/airports.duckdb (~10 min, one time)
make dev                              # API :8000 + web :5173
```
