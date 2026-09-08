# 04 — Agent design

## Tool surface

Eight tools. Small, typed, composable, each doing one thing. **Tool design *is* agent design** — a good surface makes the model's job nearly trivial.

| Tool | Args | Returns |
|---|---|---|
| `list_airports` | `region?`, `states?`, `hub_class?`, `min_enplanements?` | candidate airports + why each qualified |
| `rank_airports` | `airport_codes[]` or filter, `profile` (investment/terminal/congestion/airfield), `weights?`, `top_n` | ranked rows: score, tier, pillar breakdown, confidence |
| `compare_airports` | `codes[]`, `metrics[]` | side-by-side metric table + verdict per metric |
| `airport_profile` | `code` | full KPI sheet: traffic, capacity, delays, constraints, forecast |
| `flight_mix` | `code`, `dimension` (haul/region/carrier/aircraft), `long_haul_nmi?` | distribution with counts, shares, denominators |
| `unmet_demand` | `code` | spill estimate, slot level, upgauge signal, catchment gap, narrative drivers |
| `explain_score` | `code`, `profile` | per-pillar inputs → normalised value → weight → contribution |
| `sensitivity_analysis` | `codes[]`, `profile`, `n_draws` | rank stability bands under weight perturbation |

**Design notes worth defending:**
- Every tool returns `assumptions{}`, `data_vintage{}` and `confidence` alongside data. Provenance travels *with* the number, so the model can't narrate a figure without its caveat in context.
- Tools return **denominators, not just percentages**. "12% of flights" is unfalsifiable; "142 of 1,183 departures" is checkable.
- `explain_score` exists purely so "why?" is a **tool call**, not a re-derivation. Follow-ups are where agents hallucinate; give reasoning its own retrievable surface.
- Schemas come from Pydantic models via `model_json_schema()` — one definition serving validation *and* the LLM function schema.

## System prompt (skeleton)

```
You are an airport investment analyst assistant for a firm that invests in US
airport modernization. You help analysts find airports where added flight and
passenger capacity would be most profitable.

RULES — these are absolute:
1. Never state a number that did not come from a tool result. No estimating,
   no arithmetic, no recalling figures from training data.
2. Always name the data vintage when you give figures.
3. Always surface the assumptions in the tool result that materially affect
   the answer (e.g. the long-haul distance threshold).
4. If a question is ambiguous in a way that changes the answer, ask ONE
   clarifying question. Otherwise state your assumption and proceed.
5. Distinguish measurement from inference. "SFO's load factor is 87.2%" is a
   measurement. "SFO likely turns away demand" is an inference — label it.
6. Say what you do not know. Missing data is a finding, not something to fill in.

SCOPE: US commercial-service airports. Not international airports, not general
aviation, not airline profitability, not stock recommendations. Say so plainly
when asked for something out of scope, then offer the nearest thing you can do.

METHOD: capacity thresholds follow FAA AC 150/5060-5 (plan at 60% of Annual
Service Volume, build at 80%). Lead with the tier; the composite score ranks
within it.

STYLE: analyst-to-analyst. Lead with the answer, then the evidence, then the
caveats. No preamble. Answers spoken aloud must work as speech — see the
voice mode instruction when it is active.
```

## The loop

```python
async def run(user_msg, history, max_hops=5):
    history.append({"role": "user", "content": user_msg})
    for hop in range(max_hops):
        resp = await llm.chat(messages=history, tools=TOOL_SCHEMAS)
        if not resp.tool_calls:
            history.append(resp.message)
            return resp.text
        history.append(resp.message)
        for call in resp.tool_calls:            # run in parallel with asyncio.gather
            try:
                args = TOOL_MODELS[call.name].model_validate_json(call.arguments)
                result = await TOOLS[call.name](args)
            except ValidationError as e:
                result = {"error": "invalid arguments", "detail": str(e)}
            history.append({"role": "tool", "tool_call_id": call.id,
                            "content": json.dumps(result)})
            yield {"type": "tool_trace", "name": call.name, "args": args, "result": result}
    return await llm.chat(messages=history + [FINALIZE_HINT])
```

Stream three event types over SSE so the UI can show work as it happens:
`{"type":"tool_trace"}` → `{"type":"token"}` → `{"type":"done", "evidence": {...}}`

## Conversational follow-up

The brief explicitly requires follow-ups. Three things make them work:

1. **Full message history**, including tool results. Cheap at this scale; don't over-engineer memory.
2. **A small explicit `ConversationState`** carried alongside — `last_airports[]`, `last_profile`, `last_weights`, `last_region`. This is what makes *"what about the second one?"*, *"now weight growth higher"*, and *"why?"* resolve correctly. Pronoun resolution via a state object beats hoping the model reconstructs it from transcript.
3. **A referent-resolution note in the prompt:** "'it', 'that one', 'the second' refer to `ConversationState.last_airports` in order."

Rehearse this exact chain — it's the demo that proves conversational depth:
```
"Which New England airports are candidates for terminal expansion?"
→ "Why is BDL ahead of PVD?"                      (explain_score)
→ "What if I care more about growth than congestion?"  (rank_airports w/ new weights)
→ "Is that ranking stable?"                       (sensitivity_analysis)
→ "Compare the top two on delays."                (compare_airports)
```

## Handling ambiguity — the behaviour they're actually grading

| Input | Right behaviour |
|---|---|
| "LA airport" | Ask once: LAX, BUR, LGB or ONT? (Or assume LAX, *say so*, and offer the others.) |
| "New England" | Assume ME/NH/VT/MA/RI/CT, state it, proceed. Don't ask — there's a standard answer. |
| "long haul" | Assume ≥2,500 nmi, **state that no ICAO/IATA standard exists**, offer to change it. |
| "best airport to invest in" | Ask what they optimise for, or run the default profile and name the weights. |
| "Will BOS stock go up?" | Out of scope, say so in one sentence, offer the capacity analysis instead. |

**Ask at most one clarifying question, and only when the answer genuinely changes.** An agent that interrogates the user is a bad agent; so is one that silently guesses on something material. The line between those is what "80% resolve rate" is made of.

## Anti-hallucination checklist
- [ ] System prompt forbids un-sourced numbers
- [ ] All numbers come from tool JSON
- [ ] Tools return denominators alongside ratios
- [ ] Numeric guard scans the final text against tool outputs
- [ ] Missing data returns `null` + a reason, never a plausible-looking value
- [ ] Tool errors are surfaced to the user, not swallowed
- [ ] `explain_score` makes "why" retrievable instead of re-derived
