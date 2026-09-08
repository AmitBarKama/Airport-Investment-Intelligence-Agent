# Airport Investment Intelligence Agent

A conversational agent that helps an investment firm find **US airports where
modernization or expansion capex will pay off** — backed by deterministic
scoring rather than model opinion, with chat and voice, that explains its
reasoning and states its assumptions.

```bash
cd airport-agent
make etl        # build data/airports.db from the source data (~30s)
make serve      # http://127.0.0.1:8000
make test       # 126 Python tests + 77 JS tests
```

No `pip install`, no `npm install` and no API key are needed to run the
deterministic analytics; `make install` adds LangChain when you want the model
path. `airport-agent/data/airports.db` is committed, so `make serve` works
immediately and `make etl` is only needed to rebuild from refreshed source data.

## The three ideas that matter

1. **The score is anchored to a published federal standard.** FAA Advisory
   Circular 150/5060-5 says to begin *planning* capacity at 60% of Annual
   Service Volume and *building* at 80%. The agent applies the FAA's
   thresholds instead of inventing its own, which turns "my opinion" into
   "the regulator's rule, computed from data".

2. **The LLM never does arithmetic.** Every number in every answer comes from
   a Python function. The model chooses tools, sets parameters and narrates —
   nothing else. That is what "deterministic scoring, not only LLM output"
   requires, and it is the easiest thing to get quietly wrong.

3. **Uncertainty ships as a feature.** Every answer carries a data-vintage
   stamp, a confidence score and the assumptions behind it (for example
   "long-haul = ≥2,500 nmi", noting that no ICAO or IATA standard defines it).
   A weight-sensitivity run shows how stable a ranking actually is.

## Data

All traffic volumes are real. The database is built from BTS T-100 Segment
(All Carriers) for 2019 and 2024 — **624 US commercial-service airports and
52,649 routes** — joined to OurAirports structure and runway geometry.

The 321 MB of source CSVs are not in git: they are freely re-downloadable and
`make etl` rebuilds the database from them. `scripts/verify_sources.sh` checks
which data endpoints are currently live.

## Submission documents

| File | What it covers |
|---|---|
| [`deliverables/01-DESIGN-AND-ARCHITECTURE.md`](deliverables/01-DESIGN-AND-ARCHITECTURE.md) | System design and the reasoning behind each choice |
| [`deliverables/02-SCORING-METHODOLOGY.md`](deliverables/02-SCORING-METHODOLOGY.md) | KPIs, formulas and the standards they are anchored to |
| [`deliverables/03-KEY-TRADEOFFS.md`](deliverables/03-KEY-TRADEOFFS.md) | Every significant decision, its cost, and what more time would buy |
| [`deliverables/04-WHERE-AI-IS-USED.md`](deliverables/04-WHERE-AI-IS-USED.md) | Exactly where the model acts and where it is kept out |

[`airport-agent/README.md`](airport-agent/README.md) is the full guide to
running, configuring and deploying the app;
[`airport-agent/DESIGN.md`](airport-agent/DESIGN.md) is the design deliverable.

## Deploying

The app deploys to Vercel as a single Python function, with **Root Directory**
set to `airport-agent`. See
[the deployment section](airport-agent/README.md#deploying-vercel) for the
environment variables and the two ways serverless behaves differently.
