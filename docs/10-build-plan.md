# 10 — One-day build plan

The brief says ~1 day and to prioritise **clarity, reasoning and thoughtful design over completeness or polish**. Take that literally: a small system that reasons well beats a large one that doesn't.

## Before you start (30 min)
1. `bash scripts/verify_sources.sh` — find out which endpoints are actually live *before* you depend on them.
2. Get a Groq key (`console.groq.com`) — 2 min, no card, and it covers LLM *and* Whisper STT.
3. `git init`, scaffold from `03-architecture.md`, commit.

## Hours 1–2 — Data spine
- OurAirports → DuckDB (`dim_airport`, `dim_runway`). ✅ verified working, so this can't block you.
- Write the three curated CSVs by hand: `slot_levels`, `constraints`, `capacity_profiles`.
- **Milestone:** `SELECT * FROM dim_airport WHERE iso_region IN ('US-MA','US-CT',...)` returns New England airports.

## Hours 2–4 — T-100 + metrics
- Download T-100 Segment (last 5 years + latest 12 months), load, **filter to passenger service classes**.
- Compute `mart_airport_annual`: pax, seats, deps, SLF, gauge, long-haul share, CAGRs.
- **Milestone:** long-haul share for ANC computes. That's sample question #3 already answered.

## Hours 4–5 — Scoring engine
- Five pillars, percentile normalisation, geometric aggregate, FAA tiering.
- **Write `test_backtest.py` now, not later.** If the FAA Level 2/3 airports don't surface, you have a bug and you want to know at hour 5, not hour 11.
- **Milestone:** `POST /rank` returns a sane ranked list.

## Hours 5–7 — Agent
- Provider interface + Groq. Tool schemas from Pydantic. The ~150-line loop. System prompt.
- **Milestone:** all four sample questions answered in the terminal, no UI.

## Hours 7–9 — Frontend
- Chat pane + SSE streaming + tool trace + rank table + assumptions panel.
- **Milestone:** end-to-end in the browser.

## Hour 9 — Voice
- `useVoice.ts` (~40 lines), mic button, `speech_text` field, airport-code normalisation.
- **Milestone:** ask a question out loud, hear the answer.

## Hours 10–11 — The differentiators
Pick in this order as time allows:
1. `sensitivity_analysis` + rank-stability display ⭐ highest value per minute
2. On-Time Performance → peak hour + taxi-out (unlocks the *terminal* question properly)
3. Editable assumptions in the UI
4. Numeric guard

## Hour 11–12 — Deliverables
- **The design document is a graded deliverable — do not let it become an afterthought.** Compress docs 02/03/09 into one 2–3 page doc: scoring methodology, key tradeoffs, where AI is used.
- README with run instructions. Record a 3-minute demo video (insurance against a live-demo failure).
- Commit, push, write the submission email.

---

## Cut lines, in the order you should cut
1. Map view
2. FAA TAF forecast → substitute historical CAGR only, and *say* you did
3. Catchment-gap signal (Census)
4. On-Time Performance → use annual metrics only, note that peak-hour is the right basis
5. Sensitivity analysis
6. Voice

**Never cut:** deterministic scoring, tool trace visibility, assumptions/uncertainty display, the design doc.
If you're 4 hours out with no frontend: **fall back to Streamlit.** A working Streamlit chat with a good scoring engine beats a half-built React app.

## Scope discipline
The brief's requirements are a checklist — hit every one visibly:
- ✅ public APIs for data
- ✅ deterministic ranking logic
- ✅ explains reasoning
- ✅ conversational follow-up
- ✅ chat interface (voice bonus)
- ✅ communicates assumption, uncertainty, scoping
- ✅ source code + design doc

Anything not on that list is optional. Build depth on the listed items instead of breadth beyond them.
