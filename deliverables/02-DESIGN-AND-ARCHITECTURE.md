# Deliverable 2 — Design & Architecture

*The assignment asks the design document to explain three things. They get a
file each: [scoring methodology](03-SCORING-METHODOLOGY.md),
[key tradeoffs](04-KEY-TRADEOFFS.md), [where AI is used](05-WHERE-AI-IS-USED.md).
This file is the system design those three sit inside.*

---

## 1. The organising principle

> **The language model chooses and narrates. Python computes. The two never swap jobs.**

Every architectural decision below follows from that one line. It is what makes
numeric hallucination *structurally impossible* rather than merely discouraged,
and it is the direct answer to the requirement for "deterministic scoring or
ranking logic (not only LLM output)".

---

## 2. Layers

```
┌──────────────────────────────────────────────────────────────────┐
│  BROWSER          web/  — chat, streaming, voice, tool trace     │
│                   No framework. No build step.                   │
└───────────────────────────┬──────────────────────────────────────┘
                            │  SSE:  tool_trace → token → done
┌───────────────────────────┴──────────────────────────────────────┐
│  HTTP             api/server.py  — stdlib http.server            │
│                   /chat /rank /compare /sensitivity /meta /speak │
└───────────────────────────┬──────────────────────────────────────┘
                            │
┌───────────────────────────┴──────────────────────────────────────┐
│  AGENT            api/agent/                                     │
│    loop.py        turn orchestration · hop cap · NUMERIC GUARD   │
│    graph.py       LangGraph state machine   ─┐                   │
│    providers.py   keyless rule-based planner ┘ same event stream │
│    render.py      deterministic prose for every tool result      │
│    schemas.py     tool schemas + argument validation             │
└───────────────────────────┬──────────────────────────────────────┘
                            │  10 tools — the ONLY way to a number
┌───────────────────────────┴──────────────────────────────────────┐
│  TOOLS            api/agent/tools.py                             │
│    Every result carries: value + denominator + assumptions       │
│                          + data_vintage + sources + confidence   │
└───────────────────────────┬──────────────────────────────────────┘
                            │
┌───────────────────────────┴──────────────────────────────────────┐
│  SCORING          api/scoring/   ← NO LLM REACHES THIS LAYER     │
│    normalize · pillars · composite · profiles · spill · sensitivity│
│    Pure functions. Stdlib only. Bit-for-bit reproducible.        │
└───────────────────────────┬──────────────────────────────────────┘
                            │
┌───────────────────────────┴──────────────────────────────────────┐
│  DATA             data/airports.db  (SQLite)                     │
│    mart_airport_annual   624 airports × 60 columns               │
│    fact_route_annual     52,649 routes                           │
│    meta                  vintage, sources, data_mode             │
└───────────────────────────┬──────────────────────────────────────┘
                            │  built once by etl/
┌───────────────────────────┴──────────────────────────────────────┐
│  PUBLIC SOURCES                                                  │
│    OurAirports CSV        structure + runway geometry            │
│    BTS T-100 Segment      passengers, seats, departures, distance│
│    FAA / operator filings slot levels, settlements, curfews      │
│    Tavily / Brave         announced programmes (optional)        │
└──────────────────────────────────────────────────────────────────┘
```

---

## 3. Why a build step, not live API calls

The ETL runs once and writes SQLite. The agent never calls an upstream API
during a conversation. Three reasons:

1. **Latency.** T-100 is a 172 MB CSV. Ranking 624 airports means touching all
   of them. A conversational agent cannot wait on that.
2. **Determinism.** Two identical questions must produce identical numbers. A
   live source that updates mid-conversation makes that impossible, and
   destroys the reproducibility the scoring layer depends on.
3. **Honest vintage.** A materialised build has *one* stamped vintage, which
   travels with every answer. Live-joining sources of different ages produces a
   number no one can date.

The cost is staleness — the window is 2024 and the system says so, out loud,
in the confidence reasons ("data is about 27 months old").

---

## 4. The turn lifecycle

1. **Question arrives** at `/chat`.
2. **Route.** If a model is configured and importable, the LangGraph path runs;
   otherwise the keyless planner does. Both emit an identical event stream,
   which is why the frontend never needs to know which one ran.
3. **Plan.** The model picks a tool and its arguments — *or* the rule-based
   planner matches a route. Arguments are validated by `schemas.validate_args`
   before anything executes.
4. **Execute.** The tool runs Python against SQLite. It returns the value, its
   **denominator**, the assumptions used, the data vintage, the source list and
   (where meaningful) a confidence score.
5. **Trace.** A `tool_trace` event streams to the UI — name, arguments, timing,
   result summary — so the deterministic layer is visible, not asserted.
6. **Loop** up to `MAX_AGENT_HOPS` (default 5).
7. **Narrate.** The model writes prose over the tool output — or `render.py`
   does, deterministically, when there is no model.
8. **Guard.** `numeric_guard` extracts every figure ≥100 from the answer and
   checks it appears in some tool's output, tolerating comma-grouping and
   rounding. Unmatched figures are flagged; figures traceable to a *web* source
   are classified separately, because a publisher's claim is traceable but is
   not ours.
9. **Done.** Final payload: text, evidence, sources, speech text, updated state.

---

## 5. Graceful degradation — four levels

The system is designed so that each missing capability removes polish, not
function:

| What is missing | What still works |
|---|---|
| Neural TTS key | Browser `speechSynthesis` |
| Web search key | Curated constraints file; the tool reports itself unavailable |
| LLM API key | Full keyless planner: same tools, same numbers, deterministic prose |
| LangChain not installed | Same as above |
| **Nothing installed but Python** | ETL, scoring, all REST endpoints, the entire web UI |

A transient model failure mid-conversation falls back to the keyless planner
*for that turn* and says so, rather than killing the stream. (This is exercised
in [07-VERIFICATION-EVIDENCE.md §6](07-VERIFICATION-EVIDENCE.md) — it happened
during the audit, and the fallback's scope guard then misfired on a
context-only follow-up. See [08](08-GAPS-RISKS-AND-FIXES.md).)

---

## 6. The ten tools

| Tool | Answers |
|---|---|
| `list_airports` | "Which airports are in …?" — region, state, metro, code, hub class |
| `rank_airports` | "Which are the best candidates?" — the full scored ranking |
| `airport_profile` | "Tell me about SFO" — traffic, capacity, geometry, constraints |
| `flight_mix` | "What share is long haul?" — haul, international, gateway splits |
| `unmet_demand` | "What demand is being turned away, and why?" |
| `compare_airports` | "Compare X and Y" |
| `explain_score` | "Why did it rank there?" — pillar-by-pillar attribution |
| `sensitivity_analysis` | "How stable is that ranking?" |
| `capital_programmes` | "What have they announced?" *(web; qualitative only)* |
| `web_research` | Open-ended context *(web; never an input to a score)* |

Web-sourced content is kept in a **separate payload stream** from tool output
all the way through the loop, so the numeric guard can always distinguish "we
computed this" from "a publisher claimed this".

---

## 7. Data model

**`mart_airport_annual`** — one row per airport, 60 columns, the table every
score reads:

- *Identity* — code, name, city, state, lat/lon, type, hub class
- *Traffic* — passengers, seats, departures, operations, load factor, gauge, destinations
- *Mix* — long-haul share, international share, gateway regions
- *Capacity* — ASV, its source, runway configuration, parallel separation, IMC constraint
- *Derived* — demand/ASV, CAGRs, upgauge delta, spill rate, unconstrained demand, catchment gap
- *Curated* — slot level, feasibility + its source, constraint fact, curfew, passenger cap
- *Operational* — taxi-out p50, delay-15 rate, cancel rate, peaking *(all NULL: see [08](08-GAPS-RISKS-AND-FIXES.md))*

Every field that is a *judgment* carries its source alongside it
(`feasibility_source`, `asv_source`), so the confidence calculation can tell a
published FAA capacity profile from a runway-geometry estimate — and does.

---

## 8. What was deliberately not built

- **No vector store / RAG.** The questions are quantitative. Embedding a
  spreadsheet to retrieve numbers approximately, when SQL retrieves them
  exactly, would be worse in every dimension.
- **No agent framework beyond LangGraph.** In a project where the agent design
  is the thing being assessed, hiding the loop inside a framework would hide
  exactly what is being asked for.
- **No frontend framework.** No build step means a reviewer opens one file.
- **No live API calls during conversation.** See §3.
- **No fine-tuning.** The task is tool selection and narration. Prompting plus
  hard argument validation covers it.
