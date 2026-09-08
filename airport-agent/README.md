# Airport Investment Intelligence Agent

**[▶ Try it live](https://airport-investment-intelligence-age-iota.vercel.app/)**

A conversational agent that helps analysts find **US airports where modernization
capital is most likely to pay off**, backed by deterministic scoring anchored to
published FAA standards.

```bash
python3 -m etl.build     # build the database (~10s, downloads ~17MB once)
python3 -m api.server    # http://127.0.0.1:8000

# or skip the browser entirely:
python3 ask.py --demo                       # the four sample questions
python3 ask.py "unmet demand at SFO?"       # one question
python3 ask.py                              # interactive, keeps context
```

**No `pip install`. No `npm install`. No API key required.** Python 3.9+ standard
library only. With an LLM key it is fully conversational; without one it falls
back to a rule-based planner that drives the same deterministic tools.

---

## What it does

Ask it things like:

| Question | What happens |
|---|---|
| *Which airports in New England are strong candidates for terminal expansion?* | resolves the region → ranks on the `terminal` profile → BDL, PWM, PVD lead; BOS is 4th because it can barely be expanded |
| *Compare LA and Santa Ana airport congestion levels.* | resolves "LA" → LAX, compares against SNA, and flags that SNA is **legally capped**, not merely uncongested |
| *What is the percentage of long haul flights out of Anchorage airport?* | computes the share **and** discloses that no ICAO/IATA standard for "long haul" exists, showing how the answer moves with the threshold |
| *What is the unmet flight demand in SFO airport and why?* | spill model + slot level + the fact that SFO's parallel runways are **750 ft apart** (computed from real coordinates), separating measured from inferred from unknown |

Follow-ups work: *"why is BDL ahead?"*, *"what if growth mattered more?"*,
*"is that ranking stable?"*

---

## The three ideas that matter

**1. The score is anchored to a federal standard, not invented.**
FAA Advisory Circular 150/5060-5 says: begin *planning* additional capacity at
**60% of Annual Service Volume**, begin *construction* at **80%**. Airports are
tiered on that rule. The composite score only ranks *within* a tier.

**2. The LLM never does arithmetic.**
Every figure is produced by Python in `api/scoring/` and returned through a tool.
The model chooses tools and narrates results. A `numeric_guard` scans the final
answer and flags any number that appears in no tool output. Numeric hallucination
isn't discouraged — it's structurally impossible, because the numbers were never
the model's to invent.

**3. Uncertainty ships as a feature.**
Every answer carries its data vintage, a confidence score with reasons, and the
assumptions used. `sensitivity_analysis` re-ranks under 400 perturbed weight
vectors and reports rank stability — so the defensible claim is not *"my weights
are right"* but *"the conclusion survives reasonable changes to them."*

---

## Data

**All traffic is real.** There is no synthetic mode; an earlier version had one
and it has been removed, because clearly-labelled invented numbers are still
invented numbers.

| Layer | Source |
|---|---|
| Traffic: passengers, seats, departures, distance | **BTS T-100 Segment (All Carriers)**, 423,697 real segment rows |
| Airports, coordinates, regions | OurAirports |
| Runway geometry, parallel separation | OurAirports (48,231 runways) |
| Slot levels, curfews, passenger caps | Curated from FAA and airport filings, each with a source |
| Capacity thresholds | FAA AC 150/5060-5 |
| Delay, taxi-out, peaking | **Not loaded.** Needs BTS On-Time Performance; reported as missing, never estimated |

Get the data (BTS has no API, so this drives their download form):

```bash
python3 -m etl.fetch_t100 --years 2019,2023,2024
python3 -m etl.build
```

With a single year loaded, growth rates are reported as **unknown** rather than
computed as 0%. Load a second year and they become real.

Sanity check on the result: ATL 52.6M passengers, DFW/DEN/ORD/LAX/JFK next, BOS
21.3M, BDL 3.3M, MHT 634k, and destination counts of 233 for ATL and 12 for MHT.
Those match published figures closely.

## Architecture

```
browser (vanilla JS, no build)
   │  POST /chat  → SSE: tool_trace → token → done
   ▼
api/server.py            stdlib http.server, SSE + REST + static
   ▼
api/agent/loop.py        ~150-line hand-written agent loop
   ▼
api/agent/tools.py       8 deterministic tools  ← ALL numbers originate here
   ▼
api/scoring/             pillars · geometric composite · spill · sensitivity
   ▼
data/airports.db         SQLite, built by etl/
```

| Choice | Why | Cost |
|---|---|---|
| stdlib only | runs anywhere, zero install, reviewer needs no setup | no pandas/DuckDB ergonomics |
| SQLite not DuckDB | ~600 airports; queries are single-digit ms | no columnar speed at scale |
| hand-written loop | in a project where the agent *is* the deliverable, hiding it in a framework hides the thing being evaluated | no free retries/checkpointing |
| geometric mean | an unbuildable airport can't be rescued by congestion | harder to explain than a weighted sum |
| SSE not WebSockets | one-way token streaming over plain HTTP | would need WS for native speech-to-speech |
| vanilla JS | no build step, no npm | no component framework |

Full reasoning and the alternatives rejected:
[`../deliverables/03-KEY-TRADEOFFS.md`](../deliverables/03-KEY-TRADEOFFS.md).

---

## Scoring in one screen

Five pillars, percentile-normalised within the cohort, combined geometrically:

| Pillar | Weight | What it measures |
|---|---|---|
| **Saturation** | 0.30 | demand/ASV, taxi-out, delay rate, peaking |
| **Unmet demand** | 0.25 | slot controls, spill model, upgauging, catchment gap |
| **Growth** | 0.20 | historical CAGR + FAA TAF forecast |
| **Feasibility** | 0.15 | can you actually build here? *(a discount, not a bonus)* |
| **Monetization** | 0.10 | international/long-haul share, gauge, destinations |

`Score = 100 × Π pillarᵢ^wᵢ`

**Feasibility is the investor's pillar.** LaGuardia is the most congested airport
in America and one of the worst places to spend expansion capital — land-locked,
perimeter-ruled, slot-controlled. A naive congestion ranking puts it first. This
one doesn't. There is a unit test asserting exactly that
(`tests/test_scoring.py::test_geometric_mean_is_not_compensatory`).

Method detail: [`../deliverables/02-SCORING-METHODOLOGY.md`](../deliverables/02-SCORING-METHODOLOGY.md).

---

## Interface

Built to `docs/front/Wonderful_Frontend_Design_Spec.md`: light-first, minimal,
with the Wonderful orb as the state indicator (idle → thinking → listening →
speaking). Light / dark / system themes, conversation sidebar, settings sheet.

While the agent works, expanding rings animate around its own orb beside the
reply and **human-readable progress** appears next to them ("Estimating spill
against capacity", not "calling tool"). Each phrase describes work the function
actually performs. The raw deterministic calls stay available under
Settings → *Show agent internals*, because "deterministic scoring, not just LLM
output" has to remain demonstrable.

Answers are **written, not pasted**: prose types out a word at a time while
tables drop in whole, so the reply arrives the way a person would say it. Voice
input docks in a bar above the composer rather than taking over the screen, and
the live transcript appears in the thread as you speak, so the previous answer
stays readable while you decide what to ask next.

Every answer follows the same shape: **direct answer → why → evidence →
caveat → next question**, followed by source pills (which say *Synthetic
traffic* when volumes are modelled, rather than implying BTS), an
*Assumptions & uncertainty* disclosure, and a suggested follow-up.

Deep link: `http://127.0.0.1:8000/?q=your+question` asks one question on load.

Screenshots: `docs/front/screenshots/`.

## Geography and memory

Ask about **any US region or state**: compass groupings ("the east", "out west",
"down south"), Census regions, colloquial ones ("Gulf Coast", "Great Lakes"), or
any of the 50 states by name. When the reading is not obvious it says so, e.g.
*"I read 'the east' as the east: 18 states, ME, NH, VT, ..."*, so you can correct it.

If it hears a place it cannot resolve, it **asks**. It never quietly answers about
the whole country instead, which is how "which airports in the east" and "and in
the west" once produced the same answer.

Conversation memory is structured, not just a transcript. It keeps the ordered
result of the last ranking (so "the second one" resolves), everything discussed
so far, and sticky preferences like a long-haul threshold you set earlier.
"What did I ask you first?" and "give me a recap" are answered **from memory with
no tool call**. The same memory is rendered into the LLM's system prompt, so the
model sees the resolved referents and not only the raw text.

## Announced plans (optional)

`capital_programmes` answers *"what has this airport said it will build?"* — news,
which the traffic data cannot contain. It is deliberately walled off:

- qualitative, cited snippets only; no computed figures
- **never** read by anything in `api/scoring/`, enforced by a test that walks the
  import graph
- web-sourced figures are classified separately by the numeric guard as
  *externally sourced* rather than being certified as ours, and are shown in a
  visually distinct source pill
- with no API key it degrades to the curated constraints file

## Conversations

The sidebar holds **conversations, not past prompts**. Reopening one restores
its answers and the agent's context (which airports were ranked, under which
weights), so a follow-up carries on rather than starting over. Stored in
`localStorage`, capped at 20.

Each row can be **pinned, renamed or deleted** on hover, and there is a
**Clear all** at the foot of the sidebar. Delete and Clear all are two-step —
the second click confirms — because the app has no modal confirm anywhere and
adding one for this would be more machinery than the action deserves.

**Pinned conversations are exempt from the cap.** That is the whole reason
`web/conversations.js` exists as a separate, tested module: the cap used to be
two hardcoded `slice(0, 20)` calls that knew nothing about pins, so a pinned
conversation that drifted past the twentieth slot was evicted like any other
and pinning it bought nothing. Pin more than 20 and every pin is kept — it is
explicit intent, and honouring it beats honouring a number nobody chose.
Covered by `tests/test_conversations.mjs`.

## Settings

Voice only. The theme toggle lives in the header, the build-detail panels
(data sources, engine) were noise, and the headphones setting went with the
energy detector it existed to tune.

Reachable from the sidebar and from the **voice conversation** (the gear beside
the ✕), since choosing a voice is the thing you most want to do while actually
talking to it. Opening it there **holds the turn**: the answer in progress is
interrupted and truncated to what you heard, and the recogniser is closed until
the sheet is shut. Without that hold the microphone would transcribe you reading
the settings, a voice preview would be taken for your next question, and a
preview started mid-answer would cancel the utterance whose completion callback
is what hands the microphone back — leaving the orb stuck on "Speaking".

**Developer mode** — the tool trace under each answer, showing which tool ran,
why, what it returned and where the numbers came from — has no switch in
Settings, because it is a build detail rather than a user preference. Load the
app with **`?dev=1`** to turn it on (`?dev=0` to turn it back off); the choice
is remembered. It is what shows the scoring is deterministic rather than
something the model made up, so it is worth having on when demonstrating this.

Note that removing the engine panel also removed where
`LangChain not installed - using built-in planner` was surfaced. Check the
model path with `make check-llm`; `make install` is the fix.

## Voice

Two separate things, because they are separate jobs:

**Dictation** (🎤) types a question for you. It docks in a bar above the
composer so the previous answer stays readable, and the live transcript appears
in the thread as you speak.

**Voice conversation** (the waveform button) is a spoken back-and-forth: it
listens, answers aloud, then listens again. The orb fills the screen and its
animation is the state indicator (listening / thinking / speaking), with both
sides' words transcribed underneath.

**It is the same conversation as the text one, spoken.** The same
`chatHistory` and agent `convState` are sent on every turn, so follow-ups
carry: ask for a New England ranking, then "Why?", then "What about the second
one?", then "Compare that to Denver." Everything said lands in the chat thread
too, the sidebar list is shared, and entering voice mode mid-conversation
replays what has already been said into the transcript rather than opening on a
blank screen.

Two things used to break that, both on the browser side — the agent was being
sent full context throughout and answering from it:

- A final transcript needed **two words** to count as a turn, so every one-word
  follow-up ("Why?", "Really?", "Denver?") was discarded before it was sent.
  The bar is now only that it is not a backchannel; one word is a perfectly
  good question. Both the raw and normalised transcripts are checked, because
  normalisation spells out letters and turns "i see" into "i c", which no
  longer looks like the backchannel it is.
- The transcript opened empty every time, so a remembering agent looked
  forgetful even when it was not.

**Interruption is explicit, and that is a decision.** While the agent answers,
the microphone is closed. Talking over it does nothing. You interrupt with the
**Stop** button, by **tapping the orb**, or with the **spacebar** — during
"Thinking" as well as "Speaking".

That is a retreat from automatic barge-in, made deliberately after the
automatic version kept cutting the agent off mid-sentence. It is worth being
precise about why, because the reason is structural rather than a tuning
failure.

`SpeechRecognition` opens its own capture. It accepts no `MediaStream` and no
constraints, so echo cancellation cannot be applied to it and its audio is
invisible to us — the only control we have is whether it runs. So detecting a
barge-in meant opening a *second*, echo-cancelled capture and watching its
energy while the agent spoke. That could not work: browser AEC references
**system** playback, and `speechSynthesis` renders outside the page's audio
graph entirely. On laptop speakers the agent's own voice therefore arrived at
the detector as clean, sustained, above-threshold energy, indistinguishable
from a person, and it duly interrupted the agent. Raising the threshold only
trades self-interruption for an interrupt that never fires; the headphones
setting that used to exist was a knob for a detector that was wrong either way.

A real barge-in needs a **far-end reference** — the signal actually being
played — so the test can be "the microphone exceeds our own output" rather than
"the microphone is loud". That requires owning the playback. Two routes exist,
neither free: set `ELEVENLABS_API_KEY` or `OPENAI_API_KEY` and `speak()`
switches to an `<audio>` element we own, which can be routed through
`createMediaElementSource` to give exactly that reference; or move to a
speech-to-speech session (ElevenLabs Conversational AI, Gemini Live) where
turn-taking happens server-side over WebRTC. The second is what makes
commercial voice agents feel the way they do.

So, what actually runs:

1. While thinking or speaking, the **recogniser is closed** — latched shut, so
   nothing the agent says can be transcribed as a question, and nothing samples
   audio to make a decision on its own. `tests/test_voice_turn_taking.mjs`
   asserts that invariant against the source, because it has regressed twice.
2. **The answer is spoken one sentence at a time.** Chrome silently stops
   `speechSynthesis` after roughly fifteen seconds on a single long utterance
   with a network voice — no event, the voice just stops mid-answer — and a
   full analysis read aloud runs well past that. Queueing sentences keeps every
   utterance short enough to finish. Splitting survives the vocabulary that
   actually appears here: `St. Louis`, `U.S.`, `D.C.`, `No. 3`, `52.6 million`.
3. On an interrupt the audio **fades over 50 ms** rather than hard-cutting,
   which clicks, and **the in-flight request is aborted** — so interrupting
   during "Thinking" stops the turn instead of letting a now-unwanted answer
   arrive and start playing.
4. The stored answer is **truncated to what actually reached the speaker**.
   Because we queued the sentences ourselves, this is now *exact*: the chunks
   that finished, plus how far `onboundary` got into the current one. Playback
   position is used for neural audio, and an elapsed-time estimate is the last
   resort. It never falls back to "all of it" — skip this and the model
   believes it said things you never heard, and the next turn goes incoherent.
5. Backchannels are still filtered: "mm-hmm", "yeah", "right" mean keep going,
   not stop.

These decisions live in `web/turn-taking.js` as pure functions, separate from
the audio plumbing in `app.js`, covered by `tests/test_voice_turn_taking.mjs`
(`make test-js`). The split exists because the failure mode here — the agent
reacting to its own voice through the speakers — is invisible to every test
that lacks a microphone next to a speaker, which is all of them.

Known limits: turn-taking uses the browser's own end-of-speech detection rather
than semantic endpointing, so it can cut you off if you pause mid-thought; and
you cannot interrupt by voice. In production this layer is solved plumbing —
**LiveKit Agents** or **Pipecat** ship AEC, barge-in and turn models configured
sanely, and speech-to-speech models handle turn-taking natively, at the cost of
control over interrupt policy and of the deterministic tool trace in the voice
path.

Voice output picks the best installed voice for the chosen gender, preferring
macOS Enhanced/Premium downloads and filtering out the novelty voices
(Bubbles, Zarvox and friends) that make the picker look broken. Settings has
Female/Male plus an explicit picker and a preview button.

Browser Web Speech API: free, no key. Chrome/Edge/Safari (Firefox does not
support recognition).

The part that matters: generic speech recognition mangles aviation vocabulary
("BDL" → "bee dee el", "Logan" → a person's name). `normalizeTranscript()` in
`web/app.js` collapses spelled-out and phonetic letters, maps colloquial names
(Logan→BOS, John Wayne→SNA), and **shows the correction in the UI** rather than
applying it silently. In voice mode the agent returns a separate `speech_text`
capped at three spoken sentences — a markdown table read aloud is unusable.


---

## Tests

```bash
python3 -m unittest discover -s tests -v     # 126 tests (7 skipped)
```

- `test_scoring.py` — normalisation, FAA tier thresholds, the non-compensatory proof
- `test_spill.py` — spill monotonicity, solver round-trip, degenerate inputs
- `test_tools.py` — every tool returns provenance; errors are clean; no unverified numbers
- `test_backtest.py` — **validation against the FAA's own list**: Level 3 (JFK/LGA/DCA)
  and Level 2 (EWR/ORD/SFO/LAX) airports should surface at the top of a saturation
  ranking the model never saw. *Skipped under synthetic traffic* — it would be
  meaningless, and a test that passes on meaningless data is worse than no test.

Structural backtests run in every mode, because runway geometry is always real:
SFO's parallel separation computes to **750 ft** from raw threshold coordinates,
matching the published figure.

---

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/chat` | SSE stream: `tool_trace` → `token` → `done` |
| POST | `/rank` | deterministic ranking (works with no LLM) |
| POST | `/compare`, `/sensitivity` | comparison, rank stability |
| GET | `/airports`, `/airport/{code}`, `/explain/{code}`, `/mix/{code}`, `/unmet/{code}` | |
| GET | `/meta` | data vintage, assumptions, profiles, active provider |

The deterministic endpoints exist separately from `/chat` deliberately: the
analytics are the product, chat is one interface onto them.

## Configuration

`cp .env.example .env` and edit it. The file is read at startup by a small
stdlib parser in `api/config.py` (real exported variables win over it), and
`.env` is git-ignored.

**Choosing a model is one line.** The agent runs on LangChain, so any supported
provider works without touching code:

```
LLM=google_genai:gemini-3.5-flash-lite
GOOGLE_API_KEY=...
```

Swap for `openai:gpt-4o-mini`, `groq:llama-3.3-70b-versatile`,
`anthropic:claude-sonnet-4-6`, `ollama:llama3` — each reads its own conventional
key variable and nothing else changes.

```bash
make install     # LangChain + the Google provider
make check-llm   # one live round trip: model, latency, tool call, tokens
```

Note: `gemini-2.5-flash-lite` is no longer available to new API keys — Google
directs new users to `gemini-3.5-flash-lite`, which is the default here.

**Without LangChain installed, or with no key, the app still runs.** The ETL,
scoring, tools, tests and web UI are Python standard library only; a built-in
keyless planner matches questions to the same deterministic tools. `/meta` and
the startup banner always say which is actually answering.

Every assumption (`LONG_HAUL_NMI`, weights, hop limit) is configuration and is
echoed back through `/meta`.

## Deploying (Vercel)

The deployed app is the same code as the local one. Vercel's Python runtime
drives a module-level `handler` that subclasses `BaseHTTPRequestHandler`, and
`api.server.Handler` already is one, so `vercel_app.py` is a re-export and
there is no second server implementation to keep in sync.

Import the repo at <https://vercel.com/new>, then:

| Setting | Value |
|---|---|
| **Root Directory** | `airport-agent` |
| Framework Preset | Other (`vercel.json` drives the build) |

Add the environment variables under **Settings → Environment Variables** —
the same names `.env` uses locally:

```
LLM=google_genai:gemini-3.5-flash-lite
GOOGLE_API_KEY=...
```

Everything else is optional and degrades cleanly: with no key at all the
deploy still serves the UI and the full deterministic API on the keyless
planner. `ELEVENLABS_API_KEY` / `OPENAI_API_KEY` enable neural voice,
`TAVILY_API_KEY` / `BRAVE_API_KEY` enable announced-plans lookup.

`data/airports.db` is committed for exactly this reason: the ETL needs 321 MB
of BTS/OurAirports CSVs that are not in git and could not be downloaded during
a build, so the deploy ships the built database instead. Rebuild it locally
with `make etl` and commit the result when the source data is refreshed.

### Two things behave differently in serverless

**`/chat` does not stream.** A serverless response is delivered whole, so the
SSE frames arrive in one chunk at the end. The browser parses them identically
— it buffers and splits on the frame separator either way — so the answer is
unchanged; what is lost is the live "thinking" ticker during the wait.

**Agent turns can outrun the function timeout.** A multi-hop answer with a slow
provider can exceed the default limit. Raise it under **Settings → Functions →
Max Duration** (this project pins its build with `builds`, which is mutually
exclusive with a `functions` block in `vercel.json`, so the dashboard is the
place to set it).
