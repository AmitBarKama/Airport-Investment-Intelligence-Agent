#!/usr/bin/env python3
"""One live round trip through the configured model. Run: make check-llm

Exists because the LangChain integration could not be executed in the
environment where it was written. This is the smallest thing that proves the
model, the key and tool calling all work together.
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from api import config                                   # noqa: E402
from api.agent import llm                                # noqa: E402

spec = config.llm_spec()
print(f"  configured : {spec or '(nothing set — check LLM= in .env)'}")
print(f"  langchain  : {'installed' if llm.llm_available() else 'NOT installed'}")
if not spec:
    raise SystemExit("  Set LLM=provider:model in .env")
if not llm.llm_available():
    raise SystemExit("\n" + llm.missing_dependency_hint())

try:
    model = llm.build_model()
except RuntimeError as exc:
    raise SystemExit(f"\n{exc}")

from api.agent import schemas                            # noqa: E402
bound = model.bind_tools(schemas.openai_style())

t0 = time.time()
try:
    reply = bound.invoke(
        "Which airports in New England are strong candidates for terminal expansion?")
except Exception as exc:                                  # noqa: BLE001
    raise SystemExit(f"  live call FAILED: {type(exc).__name__}: {exc}")

ms = int((time.time() - t0) * 1000)
calls = getattr(reply, "tool_calls", None) or []
print(f"  round trip : {ms} ms")
if calls:
    print(f"  tool call  : {calls[0].get('name')}({calls[0].get('args')})")
    print("\n  Working. Tool calling is live; start the server with: make serve")
else:
    text = getattr(reply, "content", "")
    print(f"  reply      : {str(text)[:120]}")
    print("\n  The model answered but did not call a tool. It is reachable; if this "
          "persists, the model may be weak at tool use — try a larger one.")
usage = getattr(reply, "usage_metadata", None)
if usage:
    print(f"  tokens     : {usage}")
