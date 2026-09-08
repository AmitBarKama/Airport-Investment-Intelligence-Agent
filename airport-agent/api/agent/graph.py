"""The agent loop, as a LangGraph state machine.

Two nodes: `agent` calls the model, `tools` executes whatever it asked for, and
a conditional edge sends control back until the model stops calling tools or a
hard hop cap is reached.

What matters here is what the graph carries alongside the messages, because
these are the properties the product is built on and a stock agent executor
would not preserve them:

  * `progress` and `tool_trace` events, so the interface can show human-readable
    steps and developer mode can show which tool ran and why;
  * separation of deterministic tool output from third-party web content, so the
    numeric guard can tell "we computed this" from "a publisher claimed this";
  * a hard hop cap;
  * the conversation memory block injected into the system prompt.

Tools are bound as raw OpenAI-format schemas via `bind_tools` and executed here,
rather than wrapped as StructuredTools. That keeps the LangChain surface small
(this module could not be executed in the environment where it was written) and
keeps argument validation in our own `schemas.validate_args`.
"""
from __future__ import annotations

import json
import operator
import time
from typing import Annotated, Any, TypedDict

from .. import config
from . import schemas
from .llm import build_model
from .prompts import system_prompt
from .tools import TOOLS


def _import_graph_bits():
    """Import LangGraph and the message classes, tolerating layout changes."""
    try:
        return _do_import_graph_bits()
    except ImportError as exc:
        from .llm import missing_dependency_hint
        raise RuntimeError(missing_dependency_hint()) from exc


def _do_import_graph_bits():
    from langgraph.graph import END, START, StateGraph
    from langgraph.graph.message import add_messages
    from langchain_core.messages import (AIMessage, HumanMessage, SystemMessage,
                                         ToolMessage)
    return {"END": END, "START": START, "StateGraph": StateGraph,
            "add_messages": add_messages, "AIMessage": AIMessage,
            "HumanMessage": HumanMessage, "SystemMessage": SystemMessage,
            "ToolMessage": ToolMessage}


MAX_RESULT_CHARS = 14_000


def _trim(obj: Any) -> str:
    s = json.dumps(obj, default=str)
    if len(s) <= MAX_RESULT_CHARS:
        return s
    if isinstance(obj, dict) and isinstance(obj.get("results"), list):
        clipped = dict(obj)
        clipped["results"] = obj["results"][:8]
        clipped["_note"] = "results truncated for context budget"
        s = json.dumps(clipped, default=str)
    return s[:MAX_RESULT_CHARS]


def build_graph(state_memory: dict | None, voice: bool = False):
    """Compile the agent graph. Returns (graph, system_prompt_text)."""
    G = _import_graph_bits()
    model = build_model().bind_tools(schemas.openai_style())
    system_text = system_prompt(voice=voice, state=state_memory or {})
    max_hops = config.MAX_AGENT_HOPS

    # Functional form on purpose. `from __future__ import annotations` turns
    # class-body annotations into strings, and LangGraph resolves those strings
    # against this module's globals - where the local `G` does not exist, so a
    # class-bodied AgentState raises NameError: name 'G' is not defined on the
    # first LLM turn. Passing the types in a dict keeps them as real objects,
    # so there is nothing left to re-evaluate.
    AgentState = TypedDict("AgentState", {
        "messages": Annotated[list, G["add_messages"]],
        "hops": int,
        "traces": Annotated[list, operator.add],
        "payloads": Annotated[list, operator.add],
        "external": Annotated[list, operator.add],
    })

    # `state` is deliberately unannotated on these three. LangGraph calls
    # get_type_hints() on every node and branch callable, and the future
    # annotations import means it would resolve the string "AgentState"
    # against module globals, where this function-local class is invisible.
    # The schema is already declared once, on StateGraph(AgentState) below.
    def agent_node(state) -> dict:
        return {"messages": [model.invoke(state["messages"])]}

    def tools_node(state) -> dict:
        last = state["messages"][-1]
        out_messages, traces, payloads, external = [], [], [], []

        for call in getattr(last, "tool_calls", []) or []:
            name = call.get("name", "")
            raw_args = call.get("args") or {}
            args, issues = schemas.validate_args(name, raw_args)
            started = time.time()

            if name not in TOOLS:
                result = {"error": f"unknown tool {name!r}", "available": sorted(TOOLS)}
            elif any(i.startswith("missing required") for i in issues):
                result = {"error": "invalid arguments", "issues": issues}
            else:
                try:
                    result = TOOLS[name](**args)
                except TypeError as exc:
                    result = {"error": f"bad arguments: {exc}"}
                except Exception as exc:                      # noqa: BLE001
                    result = {"error": f"tool failed: {exc}"}

            payload = _trim(result)
            # Web findings are cited, but they are the publisher's claim rather
            # than something we computed. Keeping them apart is what lets the
            # numeric guard classify a figure instead of blessing it.
            if isinstance(result, dict) and result.get("evidence_class") == "third_party_reported":
                external.append(payload)
            else:
                payloads.append(payload)

            traces.append({
                "name": name,
                "args": args,
                "ms": int((time.time() - started) * 1000),
                "issues": issues,
                "ok": not (isinstance(result, dict) and result.get("error")),
                "reason": "chosen by the model",
                "rows": _result_size(result),
                "sources": [s["label"] for s in (result.get("sources") or [])]
                           if isinstance(result, dict) else [],
                "summary": _summarise(name, result),
                "result": result,
            })
            out_messages.append(G["ToolMessage"](
                content=payload, tool_call_id=call.get("id") or name, name=name))

        return {"messages": out_messages, "hops": state.get("hops", 0) + 1,
                "traces": traces, "payloads": payloads, "external": external}

    def should_continue(state) -> str:
        last = state["messages"][-1]
        if getattr(last, "tool_calls", None) and state.get("hops", 0) < max_hops:
            return "tools"
        return G["END"]

    builder = G["StateGraph"](AgentState)
    builder.add_node("agent", agent_node)
    builder.add_node("tools", tools_node)
    builder.add_edge(G["START"], "agent")
    builder.add_conditional_edges("agent", should_continue,
                                  {"tools": "tools", G["END"]: G["END"]})
    builder.add_edge("tools", "agent")
    return builder.compile(), system_text, G


def _result_size(result: Any) -> int | None:
    if not isinstance(result, dict):
        return None
    for key in ("results", "airports", "drivers", "contributions", "findings"):
        v = result.get(key)
        if isinstance(v, list):
            return len(v)
    return None


def _summarise(tool: str, result: Any) -> str:
    from .loop import _summarise as base
    return base(tool, result if isinstance(result, dict) else {})
