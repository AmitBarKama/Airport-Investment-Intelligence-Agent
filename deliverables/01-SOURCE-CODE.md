# Deliverable 1 — Source Code

**Location:** [`../airport-agent/`](../airport-agent/)
**Verified:** 2026-09-08 — built, served, queried and tested end to end.

---

## 1. Run it

```bash
cd airport-agent

# 1. Build the database from public sources (one time)
python3 -m etl.build                    # OurAirports + BTS T-100 → data/airports.db

# 2a. Terminal client — no browser, no key
python3 ask.py --demo                   # runs all four sample questions
python3 ask.py                          # interactive; follow-ups keep context

# 2b. Or the web UI
python3 -m api.server                   # → http://127.0.0.1:8000

# 3. Tests
python3 -m unittest discover -s tests   # 126 tests (7 skipped)
node tests/test_conversations.mjs       # 20
node tests/test_markdown.mjs            # 19
node tests/test_voice_turn_taking.mjs   # 38
```

**To enable the LLM narration layer** (optional — everything above works
without it):

```bash
pip install -r requirements.txt
echo 'LLM=google_genai:gemini-3.5-flash-lite' >> .env
echo 'GOOGLE_API_KEY=your-key-here'           >> .env
python3 check_llm.py                    # confirms the model and a live tool call
```

---

## 2. What is where

```
airport-agent/
├── etl/                    Build the database from public sources
│   ├── build.py       451  Orchestrates; joins traffic to structure, derives all metrics
│   ├── capacity.py    235  Annual Service Volume from runway geometry (FAA AC 150/5060-5)
│   ├── fetch_t100.py  106  Drives the BTS TranStats form (there is no API) → ZIP → CSV
│   ├── traffic.py     140  Parses T-100 Segment into route-level facts
│   └── curated/            Hand-transcribed filings, one source URL per row
│       ├── constraints.csv  21 airports: settlements, curfews, perimeter rules, feasibility
│       └── slot_levels.csv   7 airports: IATA Level 2 / Level 3 designations
│
├── api/
│   ├── scoring/            ← THE DETERMINISTIC CORE. No LLM reaches this.
│   │   ├── normalize.py   109  Winsorise + percentile rank (OECD/JRC handbook)
│   │   ├── pillars.py     147  The five pillars, with coverage tracking
│   │   ├── composite.py   176  Geometric mean, FAA tiering, confidence
│   │   ├── profiles.py    113  The four named weight profiles
│   │   ├── spill.py       134  Belobaba spill model (MIT 16.75J)
│   │   └── sensitivity.py 104  Dirichlet weight perturbation, rank stability
│   │
│   ├── agent/              The conversational layer
│   │   ├── tools.py       805  The 10 tools. Every number the user sees is born here.
│   │   ├── providers.py   764  Keyless rule-based planner (full fallback, no LLM)
│   │   ├── render.py      699  Deterministic prose renderer for tool output
│   │   ├── loop.py        552  Turn orchestration, event stream, numeric guard
│   │   ├── schemas.py     234  Tool schemas + argument validation
│   │   ├── graph.py       179  LangGraph state machine (used when a model is configured)
│   │   ├── llm.py         116  Provider-agnostic model construction
│   │   └── prompts.py     107  System prompt, including the memory block
│   │
│   ├── server.py      311  Dependency-free HTTP server, SSE streaming
│   ├── db.py          289  SQLite access + place resolution
│   ├── config.py      285  Every assumption, as a setting
│   └── websearch.py        Optional Tavily/Brave (qualitative context only)
│
├── web/                    The chat interface — no framework, no build step
│   ├── app.js        1654  Chat, streaming, voice, settings
│   ├── turn-taking.js 307  Barge-in and speech turn-taking
│   ├── markdown.js    163  Renderer (tables land whole, not half-drawn)
│   ├── styles.css     655
│   └── index.html     180
│
├── tests/                  15 files, 203 tests
├── ask.py                  Terminal client
├── check_llm.py            Diagnoses the model path
├── DESIGN.md               The design deliverable
└── README.md               Full operator documentation
```

**7,687 lines of Python + 3,045 lines of web.**

---

## 3. Dependencies

The deliberate choice here is worth stating: **the entire deterministic half of
the system — ETL, scoring, tools, the keyless planner, the HTTP server and the
whole web UI — runs on the Python standard library alone.** No numpy, no pandas,
no web framework, no build step, no `npm install`.

That is not minimalism for its own sake. It means:

- the scoring path has no version-drift surface and is trivially unit-testable
- a reviewer can read every line that produces a number
- the app runs on a bare interpreter

`requirements.txt` exists solely for the *optional* LLM layer, where LangChain
provides one uniform tool-calling interface across providers. Switching model
provider is one line in `.env` and nothing else in the codebase.

---

## 4. Tests — 203, all passing

| Suite | Tests | Covers |
|---|---:|---|
| `test_scoring.py` | | Normalisation, FAA tier thresholds, the non-compensatory proof |
| `test_spill.py` | | Spill model inversion and monotonicity |
| `test_tools.py` | | Tool contracts: assumptions, vintage and denominators always present |
| `test_geography.py` | | Region, state and metro resolution |
| `test_entity_extraction.py` | | Airport codes and names out of free text |
| `test_routing_identity.py` | | Which tool a question routes to |
| `test_memory_and_search.py` | | Conversation state; AST checks over the scoring modules |
| `test_backtest.py` | | Holdout ranking *(skipped — needs BTS On-Time Performance)* |
| `test_llm_config.py`, `test_model_path.py` | | Provider resolution and graceful degradation |
| `test_list_requests.py`, `test_offer_acceptance.py` | | Conversational shapes |
| **Python subtotal** | **126** | *(7 skipped)* |
| `test_conversations.mjs` | 20 | Multi-turn state in the browser |
| `test_markdown.mjs` | 19 | Table and block rendering |
| `test_voice_turn_taking.mjs` | 38 | Barge-in, recognition restart, synthesis chunking |
| **JS subtotal** | **77** | |
| **Total** | **203** | |

The 7 skips are honest: they are the FAA delay backtest, which cannot run until
BTS On-Time Performance is loaded. They are skipped rather than stubbed to pass.

---

## 5. HTTP surface

| Method | Path | LLM involved? | Returns |
|---|---|---|---|
| GET | `/health` | no | `{"ok": true}` |
| GET | `/meta` | no | Data vintage + the full assumption registry |
| GET | `/airports` | no | Airport lookup |
| POST | `/rank` | **no** | Full deterministic ranking: scores, tiers, pillars, confidence |
| POST | `/compare` | **no** | Side-by-side metrics |
| POST | `/sensitivity` | **no** | Weight-perturbation rank stability |
| POST | `/chat` | yes | SSE stream: `tool_trace` → `token` → `done` |
| POST | `/speak` | no | Neural TTS proxy (key stays server-side) |

`/rank`, `/compare` and `/sensitivity` are the requirement "deterministic
scoring, not only LLM output" expressed as an API: they produce the complete
analysis with no model in the path.

---

## 6. Verifying the claims yourself

```bash
# Data is real, not synthetic
curl -s localhost:8000/meta | python3 -m json.tool | head -12
#   "data_mode": "real"
#   "traffic_source": "BTS T-100 Segment (All Carriers), real"
#   "n_airports": 624,  "n_routes": 52649

# The ranking is deterministic — five identical hashes
for i in 1 2 3 4 5; do
  curl -s -X POST localhost:8000/rank -H 'Content-Type: application/json' \
    -d '{"region":"New England","profile":"terminal","top_n":5}' | shasum | cut -c1-16
done

# The numeric guard catches a fabricated figure
python3 -c "
from api.agent.loop import numeric_guard
print(numeric_guard('BOS handled 21,280,480 passengers and 999,777 cargo tonnes.',
                    ['{\"pax\": 21280480}']))"
#   (['999,777'], [])
```

---

## 7. One security note

`airport-agent/.env.example` previously contained a **live Google API key** and
is not covered by `.gitignore`. It has been replaced with a commented
placeholder during this audit. **Rotate that key** at
[aistudio.google.com/apikey](https://aistudio.google.com/apikey) before sharing
this repository. `.env` itself is correctly gitignored.
