"""The agent loop.

Deliberately hand-written and small. In a project where the agent design is
the thing being evaluated, hiding the loop inside a framework would hide
exactly what is being asked for. It is also the piece that must be explainable
line by line.

Emits a stream of events so the UI can show the work as it happens:
    {"type": "tool_trace", ...}   a tool ran, with args, timing and result
    {"type": "token", ...}        a chunk of the answer
    {"type": "done", ...}         final payload: evidence, speech text, state
"""
from __future__ import annotations

import json
import re
import time
from typing import Iterator

from .. import config
from . import llm, providers, render, schemas
from .prompts import system_prompt
from .tools import TOOLS

MAX_RESULT_CHARS = 14_000

# Human-readable progress steps shown while a tool runs.
#
# The UI shows these instead of "Calling tool... Parsing JSON..." -- the user
# should feel that an expert is thinking, not that they are watching a stack
# trace. Each phrase describes work the function ACTUALLY does, so this is
# plain language, not theatre. The raw trace is still emitted alongside and
# stays available behind a details toggle, because "deterministic scoring, not
# just LLM output" has to remain demonstrable.
STEP_PLANS: dict[str, list[str]] = {
    "list_airports": [
        "Resolving the region",
        "Finding commercial-service airports",
    ],
    "rank_airports": [
        "Pulling traffic and capacity for the national cohort",
        "Scoring saturation, unmet demand and growth",
        "Applying feasibility and monetization",
        "Ranking and assigning FAA capacity tiers",
    ],
    "airport_profile": [
        "Pulling traffic and capacity data",
        "Reading runway geometry",
        "Checking constraints and slot status",
    ],
    "flight_mix": [
        "Loading the route network",
        "Measuring great-circle distances",
        "Splitting short, medium and long haul",
    ],
    "unmet_demand": [
        "Analysing load factors",
        "Estimating spill against capacity",
        "Checking slot controls and legal caps",
        "Reviewing runway and weather constraints",
    ],
    "compare_airports": [
        "Pulling both airports' traffic and delays",
        "Comparing congestion metrics",
        "Checking curfews and capacity agreements",
    ],
    "explain_score": [
        "Recomputing the score",
        "Attributing each pillar's contribution",
    ],
    "capital_programmes": [
        "Searching for announced plans",
        "Reading third-party reports",
        "Separating announcements from delivered capacity",
    ],
    "sensitivity_analysis": [
        "Resampling the pillar weights",
        "Re-ranking under each draw",
        "Measuring how far each airport moves",
    ],
}

DEFAULT_STEPS = ["Working through the data"]


def _trim(obj: dict) -> str:
    """Serialise a tool result, trimming if it would blow the context budget."""
    s = json.dumps(obj, default=str)
    if len(s) <= MAX_RESULT_CHARS:
        return s
    if isinstance(obj, dict) and isinstance(obj.get("results"), list):
        clipped = dict(obj)
        clipped["results"] = obj["results"][:8]
        clipped["_note"] = "results truncated for context budget"
        s = json.dumps(clipped, default=str)
    return s[:MAX_RESULT_CHARS]


def _stream_blocks(text: str):
    """Split an answer into markdown blocks so the UI can reveal it gradually.

    The client types out prose a word at a time and drops tables in whole
    (a half-drawn table looks broken). Splitting server-side keeps block
    boundaries intact and means the same progressive rendering works whether
    the text came from a language model or the deterministic renderer.
    """
    if not text:
        return
    buf: list[str] = []
    in_table = False
    for line in text.split("\n"):
        is_table_row = line.lstrip().startswith("|")
        if is_table_row and not in_table:
            if buf:
                yield "\n".join(buf) + "\n\n"
                buf = []
            in_table = True
        elif in_table and not is_table_row:
            yield "\n".join(buf) + "\n\n"
            buf = []
            in_table = False
        buf.append(line)
        if not in_table and line.strip() == "" and buf:
            block = "\n".join(buf).strip()
            if block:
                yield block + "\n\n"
            buf = []
    if buf:
        block = "\n".join(buf).strip()
        if block:
            yield block + ("\n\n" if not in_table else "\n")


_NUM_RE = re.compile(r"\d[\d,]*\.?\d*")


def numeric_guard(text: str, tool_outputs: list[str],
                  external_outputs: list[str] | None = None) -> tuple[list[str], list[str]]:
    """Classify every figure in the answer by where it came from.

    Returns (unverified, externally_sourced). The distinction matters once web
    retrieval exists: a figure from a press release IS traceable, but to a
    publisher rather than to our own deterministic code, and folding it in with
    tool output would make the guard certify exactly what it exists to catch.
    """
    """Flag numbers in the answer that appear in no tool output.

    A cheap backstop for the core invariant: the model narrates numbers, it
    does not invent them. Small integers and years are ignored because they
    are usually ordinals or dates rather than claims about data.
    """
    haystack = " ".join(tool_outputs)
    # Compare against a comma-free copy too: the answer may write "2,600"
    # where the tool wrote "2600", or vice versa. Digit grouping is a
    # formatting choice, not a different number.
    bare_haystack = haystack.replace(",", "")
    ext = " ".join(external_outputs or [])
    bare_ext = ext.replace(",", "")
    suspicious, external = [], []
    for raw in _NUM_RE.findall(text or ""):
        token = raw.rstrip(".,")            # trailing punctuation is not part of the number
        clean = token.replace(",", "")
        if not clean:
            continue
        try:
            val = float(clean)
        except ValueError:
            continue
        if val < 100 or 1900 <= val <= 2100:
            continue
        if clean in bare_haystack or token in haystack:
            continue
        # tolerate rounding of a value that IS present
        rounded = {f"{val:.0f}", f"{val:.1f}", f"{val:.2f}"}
        if any(r in bare_haystack for r in rounded):
            continue
        if clean in bare_ext or token in ext:
            external.append(token)      # real, but the publisher's claim, not ours
            continue
        suspicious.append(token)
    return suspicious, external


def run(user_message: str, history: list[dict] | None = None,
        state: dict | None = None, voice: bool = False,
        max_hops: int | None = None) -> Iterator[dict]:
    """Run one turn. Yields events; the last is always type 'done'."""
    history = list(history or [])
    state = dict(state or {})
    max_hops = max_hops or config.MAX_AGENT_HOPS

    # LangChain/LangGraph when a model is configured and importable; the
    # keyless planner otherwise. The event contract below is identical either
    # way, which is what lets the frontend stay untouched.
    if llm.llm_available() and config.llm_spec():
        try:
            yield from _run_graph(user_message, history, state, voice, max_hops)
            return
        except Exception as exc:                          # noqa: BLE001
            # Deliberately broad. The first version caught RuntimeError only,
            # which build_model raises -- but a provider/network failure raises
            # its own type (httpx.ConnectError on a DNS blip, for one), escaped
            # this handler entirely and killed the stream instead of degrading.
            msg = (f"The model is configured but could not run: "
                   f"{type(exc).__name__}: {exc}\n\n"
                   f"Falling back to the built-in planner for this turn.")
            yield {"type": "token", "t": msg}

    provider = providers.get_provider()
    if isinstance(provider, providers.RuleBasedProvider):
        provider.state = state
        provider.history = history

    messages = history + [{"role": "user", "content": user_message}]
    system = system_prompt(voice=voice, state=state)

    evidence: dict | None = None
    evidence_tool: str | None = None
    tool_payloads: list[str] = []
    external_payloads: list[str] = []      # web findings: cited, but not ours
    traces: list[dict] = []

    for hop in range(max_hops):
        try:
            resp = provider.chat(system, messages)
        except RuntimeError as exc:
            msg = (f"The language model call failed ({exc}). The deterministic "
                   f"analytics are unaffected — you can still use the ranking "
                   f"endpoints directly.")
            yield {"type": "token", "t": msg}
            yield {"type": "done", "text": msg, "speech_text": msg,
                   "evidence": evidence, "state": state, "traces": traces,
                   "error": str(exc)}
            return

        if not resp.tool_calls:
            text = resp.text or ""
            turn_offers = render.offers(evidence_tool, evidence)
            followup = render.offer_sentence(turn_offers)
            if not text and evidence is not None:
                # Non-conversational provider: narrate deterministically.
                text, speech = render.render(evidence_tool, evidence)
            else:
                speech = text
            # A figure quoted from an earlier turn came from a tool then, so it
            # is still traceable. Without this every legitimate recall is flagged.
            flagged, externally_sourced = numeric_guard(
                text, tool_payloads + list(state.get("numbers_seen") or []),
                external_payloads)
            state = _close_turn(state, user_message, text, tool_payloads)
            # What we just offered, so an answer of "yes" has something to run.
            state["last_offers"] = turn_offers
            for chunk in _stream_blocks(text):
                yield {"type": "token", "t": chunk}
            yield {"type": "done", "text": text, "speech_text": speech,
                   "evidence": evidence, "evidence_tool": evidence_tool,
                   "state": state, "traces": traces,
                   "unverified_numbers": flagged,
                   "externally_sourced_numbers": externally_sourced,
                   "sources": (evidence or {}).get("sources", []),
                   "followup": followup,
                   "provider": provider.name}
            return

        messages.append({
            "role": "assistant", "content": resp.text or "",
            "tool_calls": [{"id": c.id, "name": c.name, "arguments": c.arguments}
                           for c in resp.tool_calls],
        })

        for call in resp.tool_calls:
            args, issues = schemas.validate_args(call.name, call.arguments)
            yield {"type": "progress",
                   "tool": call.name,
                   "reason": getattr(call, "reason", ""),
                   "steps": STEP_PLANS.get(call.name, DEFAULT_STEPS)}
            started = time.time()
            if call.name not in TOOLS:
                result = {"error": f"unknown tool {call.name!r}",
                          "available": sorted(TOOLS)}
            elif any(i.startswith("missing required") for i in issues):
                result = {"error": "invalid arguments", "issues": issues}
            else:
                try:
                    result = TOOLS[call.name](**args)
                except TypeError as exc:
                    result = {"error": f"bad arguments: {exc}"}
                except Exception as exc:                     # noqa: BLE001
                    result = {"error": f"tool failed: {exc}"}
            elapsed_ms = int((time.time() - started) * 1000)

            payload = _trim(result)
            if result.get("evidence_class") == "third_party_reported":
                external_payloads.append(payload)
            else:
                tool_payloads.append(payload)
            if not result.get("error"):
                evidence, evidence_tool = result, call.name
                state = _update_state(state, call.name, args, result)

            trace = {"name": call.name, "args": args, "ms": elapsed_ms,
                     "issues": issues, "ok": not result.get("error"),
                     "reason": getattr(call, "reason", "") or "chosen by the model",
                     "rows": _result_size(result),
                     "sources": [s["label"] for s in (result.get("sources") or [])],
                     "summary": _summarise(call.name, result)}
            traces.append(trace)
            yield {"type": "tool_trace", **trace}

            messages.append({"role": "tool", "tool_call_id": call.id,
                             "name": call.name, "content": payload})

    # Ran out of hops: answer with what we have rather than failing.
    text, speech = (render.render(evidence_tool, evidence) if evidence
                    else ("I could not complete that within the tool budget.",) * 2)
    for chunk in _stream_blocks(text):
        yield {"type": "token", "t": chunk}
    yield {"type": "done", "text": text, "speech_text": speech,
           "evidence": evidence, "evidence_tool": evidence_tool,
           "state": state, "traces": traces, "truncated": True,
           "sources": (evidence or {}).get("sources", []),
           "followup": render.followup(evidence_tool, evidence),
           "provider": provider.name}


def _result_size(result: dict) -> int | None:
    """How many records the tool actually returned, for the developer panel."""
    for key in ("results", "airports", "drivers", "contributions"):
        v = result.get(key)
        if isinstance(v, list):
            return len(v)
    return None


def _run_graph(user_message, history, state, voice, max_hops):
    """Drive the LangGraph agent, emitting the same SSE events as the keyless path."""
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
    from .graph import build_graph

    graph, system_text, _G = build_graph(state, voice=voice)

    messages = [SystemMessage(content=system_text)]
    for m in (history or []):
        role = m.get("role")
        if role == "user":
            messages.append(HumanMessage(content=m.get("content") or ""))
        elif role == "assistant":
            messages.append(AIMessage(content=m.get("content") or ""))
    messages.append(HumanMessage(content=user_message))

    traces, payloads, external = [], [], []
    final_text = ""
    seen_traces = 0
    # The answer's prose comes from the model; its evidence panel, source pills
    # and follow-up offer come from the tool result, exactly as on the keyless
    # path. Tracked here because the tools node pops `result` off each trace.
    evidence, evidence_tool = None, None

    for update in graph.stream(
            {"messages": messages, "hops": 0,
             "traces": [], "payloads": [], "external": []},
            stream_mode="updates"):
        for node, delta in (update or {}).items():
            if not isinstance(delta, dict):
                continue
            if node == "agent":
                msgs = delta.get("messages") or []
                last = msgs[-1] if msgs else None
                calls = getattr(last, "tool_calls", None) or []
                # Announce the work before it happens, so the interface can show
                # readable progress rather than a spinner.
                for call in calls:
                    yield {"type": "progress", "tool": call.get("name"),
                           "reason": "",
                           "steps": STEP_PLANS.get(call.get("name"), DEFAULT_STEPS)}
                if last is not None and not calls:
                    final_text = _message_text(last) or final_text
            elif node == "tools":
                for t in (delta.get("traces") or []):
                    result = t.pop("result", None)
                    traces.append(t)
                    yield {"type": "tool_trace", **t}
                    if isinstance(result, dict) and not result.get("error"):
                        evidence, evidence_tool = result, t["name"]
                        nonlocal_state = _update_state(state, t["name"], t["args"], result)
                        state.clear(); state.update(nonlocal_state)
                payloads.extend(delta.get("payloads") or [])
                external.extend(delta.get("external") or [])
                seen_traces = len(traces)

    turn_offers = render.offers(evidence_tool, evidence)
    followup = render.offer_sentence(turn_offers)
    if not final_text and evidence is not None:
        # Hop budget spent without a closing message. Narrate the evidence we
        # do have rather than returning a blank answer, which is what this path
        # used to do while the keyless one said so plainly.
        final_text, speech = render.render(evidence_tool, evidence)
    else:
        speech = final_text

    flagged, externally_sourced = numeric_guard(
        final_text, payloads + list(state.get("numbers_seen") or []), external)
    state_out = _close_turn(state, user_message, final_text, payloads)
    state_out["last_offers"] = turn_offers

    for chunk in _stream_blocks(final_text):
        yield {"type": "token", "t": chunk}
    yield {"type": "done", "text": final_text, "speech_text": speech,
           "evidence": evidence, "evidence_tool": evidence_tool,
           "state": state_out, "traces": traces,
           "unverified_numbers": flagged,
           "externally_sourced_numbers": externally_sourced,
           "sources": (evidence or {}).get("sources", []),
           "followup": followup,
           "provider": llm.describe()}


def _message_text(message) -> str:
    """LangChain message content can be a string or a list of content blocks."""
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "".join(parts)
    return str(content or "")


def _summarise(tool: str, result: dict) -> str:
    if result.get("error"):
        return f"error: {result['error']}"
    if tool in ("rank_airports",):
        rows = result.get("results", [])
        return (f"{len(rows)} ranked; top "
                f"{', '.join(r['code'] for r in rows[:3])}") if rows else "no results"
    if tool == "list_airports":
        return f"{result.get('count', 0)} airports"
    if tool == "flight_mix":
        h = result.get("headline", {})
        return h.get("stated_as") or "mix computed"
    if tool == "unmet_demand":
        sp = result.get("spill", {})
        return (f"spill {sp.get('spill_rate')}, "
                f"{len(result.get('drivers', []))} drivers")
    if tool == "compare_airports":
        return " vs ".join(a["code"] for a in result.get("airports", []))
    if tool == "explain_score":
        return f"score {result.get('score')}, rank {result.get('rank_national')}"
    if tool == "sensitivity_analysis":
        return result.get("headline") or "stability computed"
    if tool == "airport_profile":
        return f"{result.get('code')} profile"
    return "ok"


def _update_state(state: dict, tool: str, args: dict, result: dict) -> dict:
    """Record what this tool call established.

    The old version kept five keys and overwrote `last_airports` wholesale on
    every call, so a ranking's order was destroyed by the next comparison and
    "the first one" became unresolvable. Now a ranking is preserved separately
    from the most-recently-discussed airports, and each turn is appended to a
    bounded log so the conversation can be recalled rather than re-run.
    """
    s = dict(state)
    s.setdefault("v", 2)

    if tool in ("rank_airports", "list_airports"):
        rows = result.get("results") or result.get("airports") or []
        codes = [r["code"] for r in rows][:12]
        if tool == "rank_airports" and codes:
            # The ordered result of a RANKING. "The first one" means this,
            # and it must survive later comparisons.
            s["last_ranking"] = codes
            s["last_ranking_label"] = (result.get("filters_applied") or {}).get("region") \
                or (result.get("filters_applied") or {}).get("metro") or "nationally"
        s["last_airports"] = codes
        if result.get("profile"):
            s["last_profile"] = result["profile"]
        if result.get("weights"):
            s["last_weights"] = result["weights"]
        f = result.get("filters_applied") or {}
        if f.get("region"):
            s["last_region"] = f["region"]
        if f.get("metro"):
            s["last_metro"] = f["metro"]
    elif tool in ("airport_profile", "unmet_demand", "flight_mix", "explain_score"):
        code = result.get("code")
        if code:
            s["last_airports"] = [code] + [c for c in s.get("last_airports", []) if c != code]
    elif tool == "compare_airports":
        s["last_airports"] = [a["code"] for a in result.get("airports", [])]

    # Sticky user choices. "Use 2,200 nautical miles" used to evaporate.
    prefs = dict(s.get("prefs") or {})
    if args.get("long_haul_nmi"):
        prefs["long_haul_nmi"] = args["long_haul_nmi"]
    if args.get("weights"):
        prefs["weights"] = args["weights"]
    if prefs:
        s["prefs"] = prefs

    # Every airport mentioned anywhere in the conversation.
    seen = list(s.get("mentioned_airports") or [])
    for c in (s.get("last_airports") or []):
        if c not in seen:
            seen.append(c)
    s["mentioned_airports"] = seen[-40:]

    s["_pending"] = {"tool": tool, "args": args,
                     "summary": _summarise(tool, result),
                     "codes": (s.get("last_airports") or [])[:8]}
    return s


def _close_turn(state: dict, question: str, answer: str,
                payloads: list[str]) -> dict:
    """Append the finished turn to the conversation log.

    Bounded deliberately: this rides in the SSE payload and in localStorage, so
    it must stay a summary and never become a transcript.
    """
    s = dict(state)
    rec = s.pop("_pending", None) or {}
    turns = list(s.get("turns") or [])
    turns.append({
        "n": len(turns) + 1,
        "q": (question or "")[:200],
        "tool": rec.get("tool"),
        "args": rec.get("args"),
        "summary": (rec.get("summary") or "")[:200],
        "codes": rec.get("codes") or [],
        "answer_head": " ".join((answer or "").split())[:180],
    })
    s["turns"] = turns[-8:]

    # Numbers already established in this conversation, so the guard does not
    # flag a figure the agent legitimately quotes from an earlier answer.
    nums = list(s.get("numbers_seen") or [])
    for payload in payloads:
        nums.extend(_NUM_RE.findall(payload))
    seen, deduped = set(), []
    for n in nums:
        if n not in seen:
            seen.add(n); deduped.append(n)
    s["numbers_seen"] = deduped[-400:]
    return s
