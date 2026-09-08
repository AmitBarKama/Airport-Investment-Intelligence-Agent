# 09 — Decisions & tradeoffs (interview prep)

You said you need to know *why* you chose each thing. This is that document. Format: **decision → why → what it costs you → what you'd do with more time.**

If you internalise nothing else, internalise the pattern: **every choice has a cost, and naming the cost yourself is what separates an engineer from someone who Googled a stack.** Volunteering the downside before you're asked is the single strongest move in a technical interview.

---

## A. Product framing

### A1. Score investment attractiveness, not airport size
- **Why:** the brief asks where renovation is *most profitable*, not which airport is biggest. Opportunity = suppressed demand × monetization ÷ buildability.
- **Cost:** more complex than a passenger-count sort; more assumptions to defend.
- **More time:** attach real capex from NPIAS and output an actual ROI/NPV rather than an index.

### A2. Feasibility as a *discount*, not a bonus
- **Why:** LGA is the most congested airport in the US and one of the worst places to spend expansion capital — land-locked, noise-constrained, perimeter-ruled. Congestion without buildability is a value trap.
- **Cost:** the feasibility data is hand-curated for ~60 airports, so it doesn't scale as-is.
- **More time:** parse NPIAS project lists and Part 150 noise filings; use land-area and parcel data.
- 🎯 **This is your best single answer. Lead with it.**

### A3. Tier first, score second
- **Why:** the 0–100 composite is mine; the 60%/80%-of-ASV thresholds are the FAA's. Leading with the tier means leading with the regulator's judgment, not my weighting.
- **Cost:** tiers are coarse; many airports bunch in Tier C.
- **More time:** delay-based tiering using actual ASPM data rather than a D/C proxy.

---

## B. Scoring

### B1. Geometric mean, not arithmetic
- **Why:** partially non-compensatory. A near-zero pillar (can't build here) must drag the total down and *not* be offset by extreme congestion. Arithmetic averaging would rank un-expandable airports at the top — the exact error A2 exists to prevent.
- **Cost:** harder to explain; sensitive near zero (hence the 0.01 floor); contributions aren't additive so the breakdown needs care.
- **More time:** compare against an outranking method (PROMETHEE/ELECTRE) which is fully non-compensatory.
- 🎯 **Highly likely to be asked. Have the LGA example ready.**

### B2. Percentile rank within hub class, not min-max on raw values
- **Why:** robust to outliers (ATL doesn't flatten the distribution), directly interpretable ("96th percentile among large hubs"), and it compares like with like — BDL vs BOS on raw volume is meaningless.
- **Cost:** loses magnitude information (rank 1 vs 2 might be a hair or a chasm); small peer groups make percentiles jumpy.
- **More time:** report both rank and standardised magnitude; bootstrap CIs on percentile positions.

### B3. Equal-ish hand-set weights
- **Why:** transparent and defensible. Any data-driven weighting (PCA) optimises for variance, not for investment relevance — it would silently encode "whatever varies most" as "whatever matters most."
- **Cost:** they're my judgment, not evidence.
- **Mitigation — and this is the good part:** I don't defend the weights, I defend the *conclusion's robustness to* the weights, via the sensitivity analysis. "BOS is #1 in 92% of weight draws" is a stronger claim than any argument for a specific weight.
- **More time:** budget-allocation elicitation with the firm's actual analysts (OECD handbook, ch. on weighting).

### B4. Upgauging as an unmet-demand signal
- **Why:** if average aircraft size grows while departures stay flat, airlines are adding seats the only way they're allowed to. That's a physical/administrative constraint showing up in data, and it's computable from T-100 alone.
- **Cost:** confounded by fleet renewal and airline economics — the industry has been upgauging generally.
- **Mitigation:** measure *relative to peer-group* upgauging, not absolute.
- 🎯 **Your most original metric. Bring it up unprompted.**

### B5. Spill model for latent demand
- **Why:** established airline revenue-management method (Belobaba/MIT, Boeing spill model). Observed load systematically understates demand exactly where capacity binds — which is exactly the set of airports you care about.
- **Cost:** needs a demand-variability assumption (K≈0.35) that I'm importing rather than estimating; normal-distribution assumption is crude at very high load factors.
- **More time:** estimate K per airport from monthly variance; use a gamma distribution; validate against DB1B fare data.

### B6. 95th-percentile design hour, not maximum
- **Why:** one Thanksgiving Sunday shouldn't size a terminal. Standard practice is a design *day*, not a peak day.
- **Cost:** understates true peak stress at heavily seasonal airports (ANC, HYA, ACK).
- **More time:** proper design-day selection per ACRP 25 (average day of the peak month).

---

## C. Data

### C1. Offline ETL into DuckDB rather than live API calls
- **Why:** determinism (same question → same answer, required for a defensible score), <50 ms queries so multi-tool voice turns stay usable, no rate limits mid-demo, and it works if the wifi dies.
- **Cost:** staleness — T-100 lags ~2 months.
- **Mitigation:** stamp data vintage on every answer; a live layer (FAA NAS Status) for genuinely real-time claims.
- 🎯 **Expect "why not just call APIs live?" Answer: investment decisions run on annual traffic patterns, not on what's happening right now.**

### C2. BTS T-100 as the backbone
- **Why:** one free, authoritative, public-domain table gives passengers, seats, departures and distance at segment grain — which is nearly the whole assignment. Current through May 2026.
- **Cost:** two-month lag; US-reporting carriers; no time-of-day.
- **Mitigation:** On-Time Performance supplies time-of-day (peak hour, taxi-out).
- ⚠️ **Trap to mention before they find it:** T-100 includes all-cargo operations. Filter by service class or Anchorage's long-haul share becomes a freighter statistic.

### C3. Hand-curated constraint/slot/capacity CSVs
- **Why:** ~60 rows of domain knowledge (curfews, passenger caps, slot levels, published called rates) that don't exist in any free API and carry more signal per row than anything else in the system.
- **Cost:** doesn't scale; ages; it's my judgment encoded as data.
- **More time:** parse NPIAS, Part 150 filings, and FAA capacity profile PDFs programmatically.
- **Honest framing:** *"I curated it deliberately — that's where the domain expertise lives, and I'd rather 60 accurate rows than 400 guessed ones."*

### C4. Skipped OpenSky / real-time flight APIs
- **Why:** live ADS-B answers "where is that plane now", not "should we invest here". OpenSky also moved to OAuth2-only in March 2026 with a daily credit system — setup cost for no scoring value.
- **Cost:** no live map eye-candy.
- **More time:** live layer for current ground stops and taxi queues.

---

## D. Architecture

### D1. LLM never computes; tools return all numbers
- **Why:** it's the literal requirement, it makes numeric hallucination structurally impossible, and it makes the scoring unit-testable without an LLM in the loop.
- **Cost:** less flexible — the model can only answer what a tool exposes; novel questions need new tools.
- **Mitigation:** tools are compositional (list → rank → explain → compare) so they cover a wide question space.
- 🎯 **Say the structural version: "It can't hallucinate the numbers because the numbers were never its to invent."**

### D2. Hand-written agent loop, no framework
- **Why:** ~150 lines I can explain line by line, full control of the trace I render, provider-swappable. In a one-day project the agent loop is the artefact being evaluated — hiding it in a framework hides the thing you asked to see.
- **Cost:** no free retries, checkpointing, or observability.
- **More time:** LangGraph if this grew into branching multi-step workflows needing persistence; Pydantic AI is the closest lightweight alternative today.

### D3. Python/FastAPI backend + React/Vite frontend (not one language)
- **Why:** the scoring is data work — pandas/numpy/duckdb make it ~200 lines instead of ~800. Pydantic models double as LLM tool schemas, so schema and validation never drift.
- **Cost:** two languages, two dev servers, CORS.
- **Rejected:** Node end-to-end (numeric work is painful), Streamlit (fast but stiff chat, awkward voice — kept as the emergency fallback).

### D4. SSE over WebSockets
- **Why:** one-way token streaming over plain HTTP, auto-reconnect, a few lines in FastAPI.
- **Cost:** can't do bidirectional audio.
- **Upgrade trigger — name it:** native speech-to-speech with barge-in needs WebSockets. That's the point at which the answer changes.

### D5. Deterministic REST endpoints alongside `/chat`
- **Why:** the analytics are the product; chat is one interface onto them. Also means the scoring demos fine even if the LLM key fails.
- **Cost:** slightly more surface to maintain.

---

## E. Voice

### E1. Web Speech API rather than Deepgram/ElevenLabs
- **Why:** $0, no key, ~40 lines, can't blow a quota mid-demo. The bonus shouldn't consume the day.
- **Cost:** no Firefox; HTTPS-only; Chrome ships audio to Google; OS-dependent TTS quality; no barge-in.
- **More time:** Groq Whisper v3 Turbo (free tier) for accuracy, ElevenLabs Flash for output quality.

### E2. Airport-code normalisation between STT and LLM
- **Why:** generic ASR mangles aviation vocabulary — "BDL" → "bee dee el". Untreated, the voice demo fails on question one.
- **Cost:** a fuzzy-match layer that can itself mis-correct.
- **Mitigation:** show corrections in the UI ("heard 'bradley' → BDL") so a mistake is visible, not silent.
- 🎯 **This is a voice-product instinct at a voice company. Bring it up.**

### E3. Pipeline (STT→LLM→TTS), not native speech-to-speech
- **Why:** free, every stage inspectable, identical tool path to text mode.
- **Cost:** additive latency, no barge-in, and **prosody is destroyed at the STT boundary** — the model never learns *how* something was said.
- **More time:** Gemini Live / OpenAI Realtime over WebSockets.

---

## F. Questions you should expect, and the short answers

**"How do you know your score is right?"**
I don't — but I can show it isn't arbitrary. The FAA independently publishes which airports are capacity-constrained (Level 3: JFK/LGA/DCA; Level 2: EWR/ORD/SFO/LAX). My saturation pillar recovers those in the top 15 without ever seeing that list. That's a backtest against an external regulator, and it's an automated test in the repo.

**"What would you do differently with a week?"**
DB1B fare data for real monetization; programmatic NPIAS/Part 150 parsing instead of curated CSVs; proper ASV from FAA capacity profiles for all 40 published airports; and an eval set of ~30 question/expected-behaviour pairs so I could measure agent quality instead of eyeballing it.

**"What's the weakest part?"**
The ASV denominator. For airports where the FAA hasn't published a capacity profile I'm approximating from runway configuration, which is coarse. It's flagged in the confidence score, and it's the first thing I'd fix.

**"Why should I trust an LLM with investment analysis?"**
You shouldn't, and the design reflects that. The LLM does routing and explanation. Every number comes from deterministic Python that's unit-tested and independently backtested. If you swapped the model, the numbers wouldn't move.

**"Is this a real investment tool?"**
No — it's a screening tool. It narrows 500 airports to 10 worth a human week. It doesn't do site-specific engineering, cost estimation, or diligence, and I'd resist anyone using it as though it did.
