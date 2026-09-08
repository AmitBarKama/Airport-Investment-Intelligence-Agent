# Airport Investment Intelligence Agent

**[▶ Try it live](https://airport-investment-intelligence-age-iota.vercel.app/)**

A conversational agent that helps an investment firm find **US airports where
modernization or expansion capex will pay off**. Ask it a question in writing or
out loud; it answers from a deterministic scoring model over real traffic data,
shows the evidence behind every number, and states the assumptions it used.

> **Q — "Which airports in the east are worth expanding?"**
>
> EWR (Tier A, score 71.6) and CLT (Tier A, score 69.7) lead eastern US
> commercial airports for investment attractiveness. Both sit in FAA Tier A
> ("Build now", at or above 80% of Annual Service Volume per FAA AC 150/5060-5).
> JFK is Tier C ("Monitor", 60%–80% ASV, score 72.1).
>
> *Data vintage: BTS T-100 Segment (2024), OurAirports. Long-haul threshold:
> 2,500 nmi. Cargo excluded.*

## Run it locally

```bash
cd airport-agent
make serve      # http://127.0.0.1:8000
```

That is the whole setup. No `pip install`, no `npm install`, no API key and no
build step — the ETL, scoring, tools, keyless planner and web UI are Python
standard library and vanilla JS. The built database is committed, so the app has
real data the moment you clone it.

```bash
make install    # optional: LangChain, for the model-driven agent path
make test       # 126 Python tests + 77 JS tests
make etl        # rebuild the database from source CSVs (~30s)
```

## The three ideas that matter

**1. The score is anchored to a published federal standard.** FAA Advisory
Circular 150/5060-5 says to begin *planning* capacity at 60% of Annual Service
Volume and *building* at 80%. The agent applies the FAA's thresholds rather than
inventing its own, which turns "my opinion" into "the regulator's rule, computed
from data".

**2. The LLM never does arithmetic.** Every number in every answer comes from a
Python function. The model chooses tools, sets parameters and narrates — nothing
else. That is what "deterministic scoring, not only LLM output" requires, and it
is the easiest thing to get quietly wrong. Turn on developer mode in the UI to
watch which tools ran, with what arguments, and how long each took.

**3. Uncertainty ships as a feature.** Every answer carries a data-vintage stamp,
a confidence score, and the assumptions behind it — for example "long-haul =
≥2,500 nmi", noting that neither ICAO nor IATA actually defines the term. A
weight-sensitivity run shows how stable a ranking is before you rely on it.

## How it works

```
BTS T-100 + OurAirports  ──▶  etl/  ──▶  airports.db  (SQLite, committed)
                                              │
                    api/scoring/  ── deterministic KPIs, profiles, sensitivity
                                              │
      api/agent/  ── tool-calling loop (LangChain) ─or─ keyless planner
                                              │
                    api/server.py  ── SSE chat + REST + static host
                                              │
                         web/  ── chat, voice, developer mode
```

The deterministic REST endpoints (`/rank`, `/compare`, `/airport/{code}`,
`/explain/{code}`, `/sensitivity`) exist separately from `/chat` on purpose: the
analytics are the product, and chat is one interface onto them. They also keep
the system demonstrable when no model key is set — the app falls back to a
built-in keyword planner and says so rather than going quiet.

```bash
curl -X POST https://airport-investment-intelligence-age-iota.vercel.app/rank \
     -H 'Content-Type: application/json' -d '{"top_n":5}'
# DFW 75.6 · DEN 73.7 · ORD 73.5 · JFK 72.1 · IAH 72.0
```

## Data

All traffic volumes are real. The database is built from BTS T-100 Segment (All
Carriers) for 2019 and 2024 — **624 US commercial-service airports and 52,649
routes** — joined to OurAirports structure and runway geometry.

The 321 MB of source CSVs are not in git; they are freely re-downloadable and
`make etl` rebuilds from them. `scripts/verify_sources.sh` checks which data
endpoints are currently live.

## Submission documents

| File | What it covers |
|---|---|
| [`deliverables/01-DESIGN-AND-ARCHITECTURE.md`](deliverables/01-DESIGN-AND-ARCHITECTURE.md) | System design and the reasoning behind each choice |
| [`deliverables/02-SCORING-METHODOLOGY.md`](deliverables/02-SCORING-METHODOLOGY.md) | KPIs, formulas and the standards they are anchored to |
| [`deliverables/03-KEY-TRADEOFFS.md`](deliverables/03-KEY-TRADEOFFS.md) | Every significant decision, its cost, and what more time would buy |
| [`deliverables/04-WHERE-AI-IS-USED.md`](deliverables/04-WHERE-AI-IS-USED.md) | Exactly where the model acts and where it is kept out |

[`airport-agent/README.md`](airport-agent/README.md) is the full guide to
running, configuring and deploying;
[`airport-agent/DESIGN.md`](airport-agent/DESIGN.md) is the design deliverable.

## Deploying

Deployed on Vercel as a single Python function, with **Root Directory** set to
`airport-agent`. `api.server.Handler` already subclasses `BaseHTTPRequestHandler`,
which is what Vercel's Python runtime drives, so `vercel_app.py` is a re-export
rather than a second server to keep in sync — local and production run the same
code down to the routing table.

Set `LLM` and the matching provider key as environment variables to enable the
model path; without them the deploy still serves the UI and the full
deterministic API. See
[the deployment section](airport-agent/README.md#deploying-vercel) for details
and for the two ways serverless behaves differently.
