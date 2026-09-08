"""JSON-Schema tool definitions shared by every provider.

One definition drives both the LLM function schema and our own argument
validation, so the two cannot drift apart.
"""
from __future__ import annotations

PROFILE_ENUM = ["investment", "terminal", "congestion", "airfield"]

TOOL_SCHEMAS = [
    {
        "name": "list_airports",
        "description": (
            "Find candidate US commercial airports by region (e.g. 'New England'), "
            "metro area (e.g. 'Los Angeles'), US state codes, or explicit airport "
            "codes. Use this first when the user names a place rather than an airport."),
        "parameters": {
            "type": "object",
            "properties": {
                "region": {"type": "string", "description":
                    "A US region in the user's own words: compass groupings "
                    "('the east', 'the west', 'the south'), Census regions "
                    "('Northeast', 'Midwest'), or colloquial ones ('Gulf Coast', "
                    "'Great Lakes', 'New England'). The server resolves it and "
                    "reports what it assumed. For a single state use `states`."},
                "metro": {"type": "string", "description": "Metro area, e.g. 'Los Angeles', 'Bay Area'"},
                "states": {"type": "array", "items": {"type": "string"}, "description": "Two-letter US state codes"},
                "codes": {"type": "array", "items": {"type": "string"}, "description": "IATA airport codes"},
                "hub_class": {"type": "string", "enum": ["L", "M", "S"]},
                "limit": {"type": "integer", "default": 40},
            },
        },
    },
    {
        "name": "rank_airports",
        "description": (
            "Rank airports by investment attractiveness using deterministic scoring. "
            "Choose the profile to match the question: 'terminal' for terminal or "
            "gate expansion, 'congestion' for how busy/delayed, 'airfield' for runway "
            "capacity, 'investment' for general investment ranking. Returns scores, "
            "FAA capacity tiers, pillar breakdowns and confidence."),
        "parameters": {
            "type": "object",
            "properties": {
                "region": {"type": "string"},
                "metro": {"type": "string"},
                "states": {"type": "array", "items": {"type": "string"}},
                "codes": {"type": "array", "items": {"type": "string"}},
                "profile": {"type": "string", "enum": PROFILE_ENUM, "default": "investment"},
                "weights": {"type": "object", "description":
                            "Optional pillar weight overrides: saturation, unmet_demand, growth, feasibility, monetization"},
                "hub_class": {"type": "string", "enum": ["L", "M", "S"]},
                "top_n": {"type": "integer", "default": 10},
            },
        },
    },
    {
        "name": "airport_profile",
        "description": "Full KPI sheet for one airport: traffic, capacity, delays, growth, constraints.",
        "parameters": {
            "type": "object",
            "properties": {"code": {"type": "string", "description": "IATA code or airport/city name"}},
            "required": ["code"],
        },
    },
    {
        "name": "flight_mix",
        "description": (
            "Distribution of departures for one airport. dimension='haul' gives "
            "short/medium/long-haul shares (use for long-haul percentage questions), "
            "'international' gives the domestic/international split, 'destination' "
            "gives the top destinations."),
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "dimension": {"type": "string", "enum": ["haul", "international", "destination"], "default": "haul"},
                "long_haul_nmi": {"type": "number", "description": "Override the long-haul threshold in nautical miles"},
            },
            "required": ["code"],
        },
    },
    {
        "name": "unmet_demand",
        "description": (
            "Estimate suppressed/unmet demand at one airport and explain the drivers "
            "(slot controls, spill, upgauging, runway geometry, legal caps). Use for "
            "any 'unmet demand' or 'why is it constrained' question."),
        "parameters": {
            "type": "object",
            "properties": {"code": {"type": "string"}},
            "required": ["code"],
        },
    },
    {
        "name": "compare_airports",
        "description": "Compare two or more airports side by side on congestion and capacity metrics.",
        "parameters": {
            "type": "object",
            "properties": {
                "codes": {"type": "array", "items": {"type": "string"}, "minItems": 2},
                "metrics": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["codes"],
        },
    },
    {
        "name": "explain_score",
        "description": (
            "Break down why an airport scored what it did: per-pillar values, weights, "
            "which pillars drag the score down. Use for any 'why' follow-up."),
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "profile": {"type": "string", "enum": PROFILE_ENUM, "default": "investment"},
            },
            "required": ["code"],
        },
    },
    {
        "name": "capital_programmes",
        "description": (
            "Announced expansion plans, terminal programmes and master plans for one "
            "airport, reported by third parties on the web. QUALITATIVE CONTEXT ONLY: "
            "it contains no figures you may quote as data and is never an input to any "
            "score or ranking. Use it when the user asks what an airport has announced, "
            "is planning, or has promised to build."),
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "max_results": {"type": "integer", "default": 5},
            },
            "required": ["code"],
        },
    },
    {
        "name": "web_research",
        "description": (
            "Search the web for something the loaded datasets cannot answer: funding, "
            "legislation, ownership, litigation, recent news, anything qualitative about "
            "a US airport or its expansion. QUALITATIVE CONTEXT ONLY: never quote a "
            "figure from it as data, and it is never an input to any score or ranking. "
            "Always prefer the local tools for traffic, capacity, delays or scoring -- "
            "use this only for what they genuinely do not hold."),
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string",
                             "description": "What to find out, in plain words."},
                "code": {"type": "string",
                         "description": "Optional airport code, to scope the search."},
                "max_results": {"type": "integer", "default": 5},
            },
            "required": ["question"],
        },
    },
    {
        "name": "sensitivity_analysis",
        "description": (
            "Test how stable a ranking is when the pillar weights change. Use when the "
            "user asks whether a ranking is robust, reliable or sensitive to assumptions."),
        "parameters": {
            "type": "object",
            "properties": {
                "codes": {"type": "array", "items": {"type": "string"}},
                "region": {"type": "string"},
                "profile": {"type": "string", "enum": PROFILE_ENUM, "default": "investment"},
                "n_draws": {"type": "integer", "default": 400},
            },
        },
    },
]

TOOLS_BY_NAME = {t["name"]: t for t in TOOL_SCHEMAS}


def openai_style() -> list[dict]:
    """Groq / OpenRouter / OpenAI-compatible function schema."""
    return [{"type": "function", "function": t} for t in TOOL_SCHEMAS]


def anthropic_style() -> list[dict]:
    return [{"name": t["name"], "description": t["description"],
             "input_schema": t["parameters"]} for t in TOOL_SCHEMAS]


def gemini_style() -> list[dict]:
    def clean(schema: dict) -> dict:
        out = {}
        for k, v in schema.items():
            if k == "default":
                continue
            out[k] = clean(v) if isinstance(v, dict) else v
        return out
    return [{"function_declarations": [
        {"name": t["name"], "description": t["description"],
         "parameters": clean(t["parameters"])} for t in TOOL_SCHEMAS]}]


def validate_args(name: str, args: dict) -> tuple[dict, list[str]]:
    """Light validation: drop unknown keys, coerce obvious types, report issues.

    Deliberately permissive -- a small model that passes a string where an
    array belongs should be corrected, not failed, because failing costs a
    whole extra round trip.
    """
    spec = TOOLS_BY_NAME.get(name)
    if not spec:
        return {}, [f"unknown tool {name!r}"]
    props = spec["parameters"].get("properties", {})
    required = spec["parameters"].get("required", [])
    clean, issues = {}, []
    for k, v in (args or {}).items():
        if k not in props:
            issues.append(f"ignored unknown argument {k!r}")
            continue
        want = props[k].get("type")
        if want == "array" and isinstance(v, str):
            v = [s.strip() for s in v.replace(";", ",").split(",") if s.strip()]
        elif want == "integer" and isinstance(v, str) and v.strip().lstrip("-").isdigit():
            v = int(v)
        elif want == "number" and isinstance(v, str):
            try:
                v = float(v)
            except ValueError:
                issues.append(f"{k!r} is not a number")
                continue
        clean[k] = v
    for r in required:
        if r not in clean:
            issues.append(f"missing required argument {r!r}")
    return clean, issues
