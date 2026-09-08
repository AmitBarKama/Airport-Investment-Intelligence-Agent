# Deliverable 2c — Where and How AI Is Used

*Required by the assignment: "a short design/architecture document explaining:
… **where/how AI is used**".*

---

## 1. The rule

> **The model chooses and narrates. Python computes. Neither does the other's job.**

Stated as a boundary:

| The LLM **does** | The LLM **never** |
|---|---|
| Interpret the question | Compute a number |
| Choose which tool to call | Estimate or recall a figure |
| Choose the arguments | Decide a weight or a threshold |
| Decide when it has enough to answer | Decide a tier |
| Write the prose | Rank anything |
| Resolve "the first one" / "it" from context | Judge feasibility |

Every number the user sees is born in `api/scoring/` or `api/agent/tools.py`,
in Python, from SQLite. This is the direct answer to the requirement for
"deterministic scoring or ranking logic (not only LLM output)".

---

## 2. Where AI actually sits in a turn

```
  user question
       │
       ▼
┌──────────────────┐
│  🤖 LLM          │  Interpret · choose tool · set arguments
└────────┬─────────┘
         │  tool name + args
         ▼
┌──────────────────┐
│  schemas.py      │  ⚙️ Hard validation. Rejects anything off-schema
└────────┬─────────┘  BEFORE it can execute. The model cannot smuggle
         │            a value past this.
         ▼
┌──────────────────┐
│  tools.py        │  ⚙️ Query SQLite
│  scoring/        │  ⚙️ Normalise · pillars · geometric mean · FAA tier
└────────┬─────────┘  ⚙️ confidence · spill · sensitivity
         │            ── NO MODEL REACHES THIS LAYER ──
         │  value + denominator + assumptions + vintage + sources
         ▼
┌──────────────────┐
│  🤖 LLM          │  Narrate the tool output. Nothing else.
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  numeric_guard   │  ⚙️ Every figure ≥100 in the prose must appear in
└────────┬─────────┘  some tool's output, or it is flagged.
         ▼
     answer + evidence + sources + confidence
```

Two AI touchpoints. Deterministic code on both sides of each, and a validator
at every boundary.

---

## 3. The four mechanisms that enforce the rule

**3.1 Tools are the only path to a number.** The model has no database access,
no calculator and no arithmetic instruction. It can only call one of ten tools.
Anything it cannot get from a tool, it cannot state.

**3.2 Arguments are validated before execution.** `schemas.validate_args`
checks every argument against the tool's schema and rejects off-schema calls.
Argument validation deliberately lives in our own code rather than in
LangChain's `StructuredTool` wrapper, keeping the framework surface small and
the validation auditable.

**3.3 Provenance travels *with* the value.** Every tool returns `assumptions`,
`data_vintage`, `sources` and often `confidence` in the same payload as the
number. The model therefore cannot have the figure in context without also
having its caveat in context — which is why the caveats reliably survive into
the prose. It also returns **denominators, not just ratios**: "1,083 of 42,816
departures" is checkable; "2.5%" is not.

**3.4 The numeric guard is the backstop.** After generation, every figure ≥100
is extracted and matched against tool output, tolerating comma-grouping
(`2,600` vs `2600`) and rounding. Small integers and years are skipped as
ordinals and dates.

Verified live — given a tool output containing `21280480`:

```
input : "BOS handled 21,280,480 passengers and 999,777 cargo tonnes."
output: flagged=['999,777']   external=[]
```

The real figure passed; the invented one was caught. The guard also separates
*unverified* from *externally sourced*, because a figure from a press release is
traceable — to a publisher, not to us — and merging the two would make the guard
certify exactly what it exists to detect. Web content is kept in a separate
payload stream through the whole loop to make that distinction possible.

---

## 4. Which model, and why it barely matters

Configured through **one line**:

```
LLM=google_genai:gemini-3.5-flash-lite
```

LangChain's `provider:model` form. Switching to `openai:gpt-4o-mini`,
`groq:llama-3.3-70b-versatile`, `anthropic:claude-sonnet-4-6` or `ollama:llama3`
touches nothing else in the codebase — each provider reads its own conventional
key variable.

**Verified working:** `google_genai:gemini-3.5-flash-lite`, 5,913 ms round trip,
live tool call `list_airports({'region': 'New England'})`, 1,363 input tokens.

Model choice barely matters *because* of the boundary. The model needs to pick
the right tool and write clean prose. It does not need to be good at arithmetic,
because it never does any. A small, cheap, fast model is the right choice — and
a bad model degrades fluency, not correctness.

Temperature is 0.2: enough variation for natural prose, little enough to keep
tool selection stable.

---

## 5. The agent loop

When a model is configured, a **LangGraph** state machine runs: an `agent` node
calls the model, a `tools` node executes what it asked for, and a conditional
edge returns control until the model stops calling tools or the hop cap
(`MAX_AGENT_HOPS`, default 5) is reached.

LangGraph is used for the state machine only. Tools are bound as **raw
OpenAI-format schemas** rather than wrapped as `StructuredTool`s, so the
framework surface stays small and argument validation stays in our code. What
the graph carries alongside the messages is the part a stock agent executor
would not preserve: progress events, tool traces, the separation of
deterministic from web-sourced payloads, the hop cap, and the conversation
memory block injected into the system prompt.

---

## 6. AI is optional — the system is not

There is a **complete keyless fallback**: a 764-line hand-written planner that
routes questions to the same ten tools by rule, with a deterministic prose
renderer (`render.py`, 699 lines) writing the answers.

With no API key, the app still:

- resolves regions, states, metros and airport codes
- ranks, compares, and explains scores
- serves the full web UI and voice
- produces **identical numbers**

What is lost is fluency, not correctness. This matters for the assignment
because it makes the claim testable: if you can unplug the LLM and still get
every number, the numbers were never coming from the LLM.

The fallback also catches transient failures per-turn. During the audit an LLM
call failed mid-conversation; the loop degraded to the keyless planner for that
turn and said so, rather than dropping the stream. (It then misfired on a
context-only follow-up.)

---

## 7. What AI is used for that Python could not do

Being fair in both directions — the model earns its place on four jobs:

1. **Intent → tool.** "What is the unmet flight demand in SFO and why?" maps to
   `unmet_demand(code='SFO')`. The rule-based planner does this too, but
   brittlely; the model generalises to phrasings nobody enumerated.
2. **Context resolution.** "Why did you rank **the first one** above Boston?"
   resolved to PWM with no airport named. Verified live.
3. **Multi-tool composition.** The New England question spontaneously ran
   `list_airports` → `rank_airports` → `explain_score` → a second
   `rank_airports` filtered to large hubs, because the model decided the
   regional answer needed the large-hub comparison to be useful. Nobody scripted
   that sequence.
4. **Narration that respects the caveats.** The Anchorage answer volunteered
   that excluding cargo "matters significantly for Anchorage" — a domain-aware
   caveat the deterministic renderer would not have produced, grounded in an
   assumption the tool actually returned.

---

## 8. Where AI is explicitly *not* used

| Not used for | Instead |
|---|---|
| Any arithmetic | `api/scoring/`, pure Python |
| Weights | Declared in `profiles.py` |
| Thresholds | FAA AC 150/5060-5 |
| Feasibility judgments | Curated CSV with a source URL per row |
| Ranking | `score_cohort`, deterministic sort |
| Confidence | A formula over coverage, source quality and recency |
| Deciding data is missing | `safe_div` returns `None`; missing stays missing |
| Web content as a score input | Web findings are **qualitative context only**, never an input to any score |

That last row is a deliberate firewall. `capital_programmes` and `web_research`
can tell you what an airport has *announced*; announcements are not delivered
capacity, and letting a press release move a score would corrupt the
deterministic layer with unverifiable claims.
