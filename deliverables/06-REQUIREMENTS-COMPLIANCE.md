# Requirements Compliance Matrix

Every row states the requirement, the verdict, where it lives in the code, and
what was actually run to confirm it. Raw output in
[07-VERIFICATION-EVIDENCE.md](07-VERIFICATION-EVIDENCE.md).

**Audited 2026-09-08 against the running system.**

---

## A. Functional requirements

### A1. "Use public APIs to gather airport/aviation data" ✅

| | |
|---|---|
| **Code** | `etl/build.py:32-33`, `etl/fetch_t100.py`, `etl/traffic.py`, `api/websearch.py` |
| **Sources** | OurAirports (structure + runway geometry) · BTS T-100 Segment All Carriers (traffic) · FAA & operator filings (curated) · Tavily/Brave (optional) |
| **Verified** | `GET /meta` → `data_mode: "real"`, `traffic_source: "BTS T-100 Segment (All Carriers), real"`, 624 airports, 52,649 routes |
| **On disk** | `t100_segment_2019.csv` 152 MB · `t100_segment_2024.csv` 172 MB · `airports.csv` 12.7 MB · `runways.csv` 4.0 MB |
| **Caveat** | BTS publishes no REST API; `fetch_t100.py` drives the TranStats ASP.NET form and documents that it will break if BTS changes it |

### A2. "Rank or compare airports based on your defined logic or KPI" ✅

| | |
|---|---|
| **Code** | `api/scoring/` — `pillars.py` · `composite.py` · `profiles.py` · `normalize.py` |
| **Logic** | 5 pillars → winsorised percentile rank → weighted **geometric** mean → 0–100 score → FAA AC 150/5060-5 tier |
| **Profiles** | `investment` · `terminal` · `congestion` · `airfield`, each with declared weights, echoed in every response |
| **Compare** | `compare_airports` tool + `POST /compare` |
| **Verified** | `congestion` tops New England with **BOS**; `terminal` tops it with **PWM** — the profiles genuinely separate |

### A3. "Explain its reasoning clearly" ✅

| | |
|---|---|
| **Code** | `composite.pillar_contributions` (log-space attribution) · `composite.assign_tier` (rationale text) · `tools._sources` (source pills) · `explain_score` tool |
| **Mechanism** | Additive log-contribution shares; pillars below 0.35 flagged as actively dragging; FAA sentence attached to every tier; provenance returned with every value |
| **Verified** | The SFO answer separated **Measured / Inferred / Unknown** unprompted and named BTS DB1B as the missing dataset |

### A4. "Support conversational follow-up questions" ✅

| | |
|---|---|
| **Code** | `loop.run(state=...)` · `prompts.system_prompt(state=...)` memory block · `web/conversations.js` |
| **Verified** | 4-turn conversation: "the first one" → PWM; "it" → BOS; "compare it to Providence" carried context. No airport code spoken after turn 1. |
| **Tests** | `test_conversations.mjs` (20) · `test_memory_and_search.py` |

---

## B. Stated requirements

### B1. "Include some deterministic scoring or ranking logic (not only LLM output)" ✅ — *the strongest area*

| Evidence | Detail |
|---|---|
| **Ranking runs with no LLM** | `POST /rank`, `/compare`, `/sensitivity` produce the full analysis through pure Python |
| **Bit-for-bit deterministic** | 5 identical calls → 5 identical SHA hashes (`c3d35f8af2519e63`) |
| **Numeric guard** | `loop.numeric_guard` flagged a fabricated `999,777` while passing a real `21,280,480` |
| **Complete keyless mode** | `providers.RuleBasedProvider` (764 lines) + `render.py` (699 lines) run the same tools with no model at all |
| **Zero dependencies in the scoring path** | `api/scoring/` is stdlib-only pure functions |

### B2. "Include a chat interface to talk with the agent (voice is a bonus)" ✅ + bonus ✅

| | |
|---|---|
| **Chat** | `web/` — streamed answers, conversation sidebar, markdown tables, light/dark, suggested questions, developer tool-trace toggle. Also `ask.py` for the terminal. |
| **Voice in** | `SpeechRecognition` / `webkitSpeechRecognition` (`web/app.js:694`) |
| **Voice out** | `speechSynthesis`, or neural TTS proxied server-side via `POST /speak` so the key never reaches the browser |
| **Turn-taking** | `web/turn-taking.js` (307 lines) — barge-in, the three `end` causes, Chrome's ~15 s synthesis cutoff |
| **Tests** | 38 voice tests |

### B3. "Clearly communicate assumption, uncertainty and scoping" ✅

| Dimension | Mechanism | Verified output |
|---|---|---|
| **Assumptions** | `config.assumption_registry()`, attached to every substantive answer | "No ICAO/IATA standard exists for 'long haul'… configurable" |
| **Uncertainty** | `composite.confidence` — coverage 50% + ASV quality 20% + recency 30%, with English reasons | "only 71% of scoring inputs are backed by data" |
| **Coverage** | `pillars._blend` redistributes weight from missing inputs and reports the share actually backed by data | terminal 71% · investment 77% · airfield 78% |
| **Weight fragility** | 400-draw Dirichlet sensitivity | "BGR ranks first in 50% of weight draws"; BDL flagged unstable |
| **Basis disclosure** | Every pillar returns `basis`: relative vs absolute | `"absolute (curated analyst judgment)"` |
| **Missing data** | `safe_div` returns `None`, never a plausible substitute | `taxi_out_p50: n/a` shown as `n/a`, not 0 |
| **Scoping** | Explicit out-of-scope refusal; a named-but-unresolvable place is never answered nationally | Refusal text names what it *can* do |

---

## C. Deliverables

### C1. Source code ✅

7,687 lines Python + 3,045 lines web. **203 tests, all passing** (126 Python
with 7 honest skips, 77 JavaScript). Runs with zero third-party dependencies in
the deterministic path. See [01-SOURCE-CODE.md](01-SOURCE-CODE.md).

### C2. Design / architecture document ✅

`airport-agent/DESIGN.md`, plus the three sub-parts the assignment names:

| Required content | File |
|---|---|
| Scoring methodology | [03-SCORING-METHODOLOGY.md](03-SCORING-METHODOLOGY.md) |
| Key tradeoffs | [04-KEY-TRADEOFFS.md](04-KEY-TRADEOFFS.md) |
| Where/how AI is used | [05-WHERE-AI-IS-USED.md](05-WHERE-AI-IS-USED.md) |

---

## D. The four sample questions ✅ 4/4

| Question | Answer produced | Tools called |
|---|---|---|
| Which airports in New England are strong candidates for terminal expansion? | PWM/BGR top the terminal profile — **and the agent flagged both as FAA Tier D, "no capacity case"**, then surfaced BOS separately | `list_airports` → `rank_airports` → `explain_score` → `rank_airports` |
| Compare LA and Santa Ana airport congestion levels. | LAX Tier B (0.69, Level 2) vs SNA Tier D (0.44) — **SNA's low ratio identified as legally imposed**, not physical | `list_airports` → `compare_airports` → `airport_profile` ×2 |
| What is the percentage of long haul flights out of Anchorage airport? | **2.5%** (1,083 of 42,816 departures), with the 2,500 nmi assumption disclosed and **cargo exclusion flagged as material for Anchorage** | `flight_mix` |
| What is the unmet flight demand in SFO airport and why? | **~2.97 M passengers**, ≈10.5% of unconstrained demand, 4 drivers each tagged Measured/Inferred, plus an explicit Measured/Inferred/Unknown note | `unmet_demand` |

---

## E. Summary

| Category | Met | Total |
|---|---:|---:|
| Functional requirements (A) | 4 | 4 |
| Stated requirements (B) | 3 | 3 |
| Deliverables (C) | 2 | 2 |
| Sample questions (D) | 4 | 4 |
| **Total** | **13** | **13** |

Voice was a bonus and is implemented.

**Nothing is unmet.** The build's real weaknesses are data-coverage gaps and
one cohort-selection issue — documented in
[08-GAPS-RISKS-AND-FIXES.md](08-GAPS-RISKS-AND-FIXES.md) — and the running
system discloses all of them at answer time, which is itself requirement B3.
