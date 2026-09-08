#!/usr/bin/env python3
"""Ask the agent from the terminal. No server, no browser, no key needed.

    python3 ask.py "What is the unmet flight demand in SFO airport and why?"
    python3 ask.py --demo          # run all four sample questions
    python3 ask.py                 # interactive; keeps conversation state
"""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from api.agent.loop import run
from api import db

DEMO = [
    "Which airports in New England are strong candidates for terminal expansion?",
    "Compare LA and Santa Ana airport congestion levels.",
    "What is the percentage of long haul flights out of Anchorage airport?",
    "What is the unmet flight demand in SFO airport and why?",
]

DIM, BOLD, CYAN, YELLOW, RESET = "\033[2m", "\033[1m", "\033[36m", "\033[33m", "\033[0m"


def ask(question: str, state: dict) -> dict:
    print(f"\n{BOLD}▸ {question}{RESET}")
    for ev in run(question, state=state):
        if ev["type"] == "tool_trace":
            flag = "" if ev["ok"] else " [FAILED]"
            print(f"{CYAN}  ⚙ {ev['name']}({ev['args']}) {ev['ms']}ms{flag}{RESET}")
            print(f"{DIM}    → {ev['summary']}{RESET}")
        elif ev["type"] == "done":
            print()
            print(ev["text"])
            if ev.get("unverified_numbers"):
                print(f"{YELLOW}  ⚠ numbers not found in any tool output: "
                      f"{ev['unverified_numbers']}{RESET}")
            state = ev.get("state", state)
    return state


def main() -> None:
    try:
        meta = db.meta()
    except FileNotFoundError as exc:
        raise SystemExit(f"{exc}")

    from api.agent.llm import describe
    print(f"{DIM}provider: {describe()} | data: {meta.get('data_mode')} "
          f"({meta.get('n_airports')} airports, window {meta.get('window_year')}){RESET}")
    if meta.get("data_mode") == "synthetic":
        print(f"{YELLOW}traffic volumes are SYNTHETIC (structure/geometry are real){RESET}")

    args = [a for a in sys.argv[1:] if a != "--demo"]
    state: dict = {}

    if "--demo" in sys.argv:
        for q in DEMO:
            state = ask(q, state)
            print(f"\n{DIM}{'─' * 72}{RESET}")
        return
    if args:
        ask(" ".join(args), state)
        return

    print(f"{DIM}Interactive. Ctrl-C or 'quit' to exit. Follow-ups keep context.{RESET}")
    while True:
        try:
            q = input(f"\n{BOLD}you ›{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye")
            return
        if q.lower() in {"quit", "exit", "q"}:
            return
        if q:
            state = ask(q, state)


if __name__ == "__main__":
    main()
