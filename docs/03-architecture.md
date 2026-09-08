# 03 — Architecture

> **What was actually built deviates from this doc — deliberately.** The
> implementation in `airport-agent/` uses the **Python standard library only**
> (`sqlite3`, `http.server`, `csv`, `urllib`) and a **zero-build vanilla-JS**
> frontend, instead of FastAPI + DuckDB + React/Vite recommended below.
>
> Reason: the build environment had no PyPI access, so shipping the recommended
> stack would have meant handing over code that had never been run. The stdlib
> version could be executed and tested for real — 45 tests, all four demo
> questions verified end to end over HTTP. It also means the reviewer runs
> `python3 -m api.server` with no `pip install` and no `npm install`, which is
> a genuine advantage for a take-home.
>
> The **layering below is unchanged** (`etl/` → `scoring/` → `tools/` → agent
> loop → API → UI), so porting to FastAPI + DuckDB + React is a component swap,
> not a rewrite. Keep this section as the "if you have dependencies" design;
> see `airport-agent/DESIGN.md` for what shipped.

## The shape

```
┌──────────────────────────────────────────────────────────────┐
│  BROWSER  (React + Vite + TS)                                │
│  ┌────────────────┐  ┌──────────────────────────────────┐    │
│  │ Chat pane      │  │ Evidence pane                    │    │
│  │ • messages     │  │ • ranked table + tier badges     │    │
│  │ • 🎤 mic       │  │ • pillar breakdown bars          │    │
│  │ • 🔊 speak     │  │ • assumptions + confidence       │    │
│  └────────────────┘  └──────────────────────────────────┘    │
│  Web Speech API: SpeechRecognition (STT) / Synthesis (TTS)   │
└───────────────────────────┬──────────────────────────────────┘
                            │ POST /chat  (SSE stream)
┌───────────────────────────▼──────────────────────────────────┐
│  FastAPI                                                     │
│  ┌────────────────────────────────────────────────────┐      │
│  │ Agent loop  (~150 lines, hand-written)             │      │
│  │   message history → LLM → tool_calls? → execute    │      │
│  │   → append results → repeat (max 5 hops)           │      │
│  └───────────────┬────────────────────────────────────┘      │
│                  │ tool calls (typed, Pydantic)              │
│  ┌───────────────▼────────────────────────────────────┐      │
│  │ TOOL LAYER — deterministic, no LLM                 │      │
│  │  rank_airports · compare_airports · airport_profile│      │
│  │  flight_mix · unmet_demand · explain_score         │      │
│  │  sensitivity_analysis · list_airports_in_region    │      │
│  └───────────────┬────────────────────────────────────┘      │
│  ┌───────────────▼────────────────────────────────────┐      │
│  │ SCORING ENGINE — pure functions, unit-tested       │      │
│  │  normalize · pillars · geometric aggregate · tiers │      │
│  └───────────────┬────────────────────────────────────┘      │
│                  │ SQL                                       │
│  ┌───────────────▼────────────────────────────────────┐      │
│  │ DuckDB  data/airports.duckdb  (built by ETL)       │      │
│  └────────────────────────────────────────────────────┘      │
└──────────────────────────────────────────────────────────────┘
         ▲ offline, run once
   ETL: T-100 · On-Time · OurAirports · TAF · curated CSVs
```

## The one rule that defines this system

**The LLM has no access to raw data and performs no arithmetic.**

It sees tool *descriptions*, chooses tools, and narrates typed JSON results. Every figure originates in Python. Consequences:
- Numbers can't be hallucinated — they're not the model's to invent.
- The scoring logic is unit-testable and reviewable without touching an LLM.
- Swapping models changes tone, never numbers.
- It's the literal reading of the requirement *"deterministic scoring or ranking logic (not only LLM output)."*

**Optional hard guard (~15 lines, great demo moment):** regex every number out of the final response and assert it appears in some tool result. If not, flag it. Catching your own model's slip live is a memorable thing to show.

---

## Decisions, with the alternatives I rejected

### Backend: **Python + FastAPI**
- **Why:** the work is data work — pandas/numpy/duckdb make the scoring engine 200 lines instead of 800. FastAPI gives async, SSE streaming, and Pydantic models that **double as LLM tool schemas** (`model_json_schema()` → function-calling schema, one definition, zero drift).
- **Rejected — Node/TypeScript end-to-end:** one language, better streaming ergonomics, and the Vercel AI SDK is genuinely nice. But writing percentile normalisation and a spill solver in JS is masochism, and the ETL would be worse.
- **Rejected — Streamlit:** fastest possible demo, but the chat UX is stiff and voice is awkward. **Keep as the emergency fallback** if you're 4 hours from the deadline with no frontend.

### Store: **DuckDB (single file)**
- **Why:** in-process (no server, no docker), reads Parquet/CSV directly, real SQL with window functions and percentiles, sub-50 ms on this data size, and the whole DB is one committable file so the reviewer can run it instantly.
- **Rejected — Postgres:** needs a server; you'd spend setup time buying nothing at this scale.
- **Rejected — pandas in memory:** fine at first, but you'll want SQL for the region/peer-group aggregations, and reload time hurts iteration.
- **Rejected — SQLite:** works, but DuckDB's columnar engine and percentile/window support are built for exactly this.

### Agent: **hand-written tool-calling loop, no framework**
- **Why:** ~150 lines you can explain line by line to people who build agents professionally. Full control of the trace you render in the UI. Provider-swappable. No hidden prompt-mangling.
- **Rejected — LangChain/LangGraph:** LangGraph is genuinely good for branching/multi-agent state machines. Here it adds a dependency, an abstraction layer, and opacity, to solve a loop that is 150 lines. Worth naming as "what I'd reach for if this grew persistent multi-step workflows with checkpointing."
- **Rejected — Pydantic AI:** the closest call. Typed, provider-agnostic, minimal. Legitimate alternative — if you'd rather not hand-roll, use it and say why.
- **Say this:** *"I hand-rolled the loop because in a one-day project the agent loop is the thing being evaluated. Hiding it inside a framework would hide exactly what you asked me to demonstrate."*

### Frontend: **React + Vite + TypeScript + Tailwind**
- **Why:** instant dev server, no SSR needed (it's a single stateful screen), Web Speech API is browser-native so voice needs zero backend.
- **Rejected — Next.js:** SSR/routing/server-actions buy nothing for one screen; slower to stand up.

### Transport: **SSE, not WebSockets**
- **Why:** the flow is one-way streaming (server → client tokens); the client sends discrete POSTs. SSE is plain HTTP, auto-reconnects, and FastAPI does it in a few lines.
- **Rejected — WebSockets:** the right call *only* if you later add native speech-to-speech with barge-in, which needs bidirectional audio. Mention that as the upgrade trigger — it shows you know why the answer would change.

### LLM: **provider-abstracted, Groq default** → see `06-llm-provider.md`
### Voice: **Web Speech API default, Groq Whisper upgrade** → see `05-voice.md`

---

## Layout

```
airport-agent/
├── data/                    # gitignored except curated CSVs
│   ├── raw/
│   ├── curated/             # slot_levels.csv, constraints.csv, capacity_profiles.csv
│   └── airports.duckdb
├── etl/
│   ├── fetch.py             # download + cache raw sources
│   ├── build.py             # normalize → DuckDB tables
│   └── curated/
├── api/
│   ├── main.py              # FastAPI app, /chat SSE, /rank, /airport/{code}
│   ├── agent/
│   │   ├── loop.py          # the ~150-line agent loop
│   │   ├── tools.py         # tool defs + dispatch
│   │   ├── prompts.py       # system prompt
│   │   └── providers.py     # groq | gemini | anthropic behind one interface
│   ├── scoring/
│   │   ├── metrics.py       # SLF, gauge, long-haul, peaking, PHP
│   │   ├── pillars.py       # five pillars
│   │   ├── composite.py     # normalize, geometric aggregate, tiers
│   │   ├── spill.py         # unmet-demand solver
│   │   └── sensitivity.py   # Dirichlet weight perturbation
│   └── db.py
├── web/
│   └── src/{App.tsx, components/, hooks/useVoice.ts, lib/api.ts}
├── tests/
│   ├── test_scoring.py
│   └── test_backtest.py     # the FAA Level 2/3 validation
└── docs/                    # this pack + the deliverable design doc
```

## Failure modes to handle explicitly
| Failure | Handling |
|---|---|
| Airport code not found | Fuzzy-match on name/city/IATA, offer top 3 candidates |
| Ambiguous region ("LA") | Return candidate set, ask one clarifying question |
| Missing data for an airport | Return partial result + lowered confidence, never silently impute |
| LLM emits malformed tool args | Pydantic validation error → feed back to model, retry once, then degrade gracefully |
| Tool loop won't terminate | Hard cap 5 hops, then answer with what's collected |
| No LLM API key | Tools still work via REST — degrade to a non-conversational ranked view |
