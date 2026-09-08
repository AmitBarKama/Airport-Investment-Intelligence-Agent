"""Configuration. Every assumption in the system is a setting, and every
setting is echoed back through /meta so the user can see what was assumed."""
from __future__ import annotations

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _load_dotenv(path: str) -> None:
    """Read a .env file into the process environment.

    Hand-rolled because the backend carries no third-party dependencies. Real
    exported variables always win, via setdefault, so `FOO=bar make serve` still
    overrides the file.

    This exists because nothing read .env before: the file looked like
    configuration but was silently ignored, so a correctly written key produced
    a server that still reported "no API key".
    """
    try:
        with open(path, encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key, value = key.strip(), value.strip()
                if value[:1] == value[-1:] and value[:1] in ("'", '"'):
                    value = value[1:-1]
                if key:
                    os.environ.setdefault(key, value)
    except FileNotFoundError:
        pass
    except OSError:
        pass                      # unreadable .env must never stop the server


_load_dotenv(os.path.join(ROOT, ".env"))

DB_PATH = os.environ.get("AIRPORT_DB", os.path.join(ROOT, "data", "airports.db"))
RAW_DIR = os.path.join(ROOT, "data", "raw")
CURATED_DIR = os.path.join(ROOT, "etl", "curated")
WEB_DIR = os.path.join(ROOT, "web")

# Vercel sets VERCEL=1 in build and runtime environments. The only thing
# that turns on is cache headers: on a serverless deploy every static byte
# costs a function invocation, so revalidating them per page load is wrong.
IS_DEPLOYED = bool(os.environ.get("VERCEL"))

# ---------------------------------------------------------------- assumptions
# There is NO international standard for what counts as a long-haul flight.
# Industry usage spans roughly 2,200-2,600 nmi; ICAO and IATA both define by
# flight time instead, and disagree with each other. So this is a disclosed,
# configurable assumption rather than a fact.
LONG_HAUL_NMI = float(os.environ.get("LONG_HAUL_NMI", 2500))
SHORT_HAUL_NMI = float(os.environ.get("SHORT_HAUL_NMI", 800))

NEW_ENGLAND_STATES = ["ME", "NH", "VT", "MA", "RI", "CT"]

# Every US state by name. Their absence is why "airports in florida" used to
# fuzzy-match an airport NAME and return one small field in Fort Myers.
US_STATES: dict[str, str] = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE",
    "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ",
    "new mexico": "NM", "new york": "NY", "north carolina": "NC",
    "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR",
    "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
    "district of columbia": "DC", "washington dc": "DC", "washington d.c.": "DC",
    "puerto rico": "PR",
}

# Compass and coastal groupings. These are the phrases people actually use
# ("the east", "out west", "down south") and their absence meant the geography
# was silently dropped and the question answered nationally instead.
_EAST = ["ME", "NH", "VT", "MA", "RI", "CT", "NY", "NJ", "PA", "DE", "MD", "DC",
         "VA", "WV", "NC", "SC", "GA", "FL"]
_WEST = ["CA", "OR", "WA", "NV", "AZ", "ID", "UT", "MT", "WY", "CO", "NM", "AK", "HI"]
_SOUTH = ["TX", "OK", "AR", "LA", "MS", "AL", "TN", "KY", "GA", "FL", "SC", "NC", "VA", "WV"]
_NORTH = ["WA", "ID", "MT", "ND", "MN", "WI", "MI", "NY", "VT", "NH", "ME"]

REGIONS: dict[str, list[str]] = {
    "new england": NEW_ENGLAND_STATES,
    "east": _EAST,
    "east coast": _EAST,
    "the east": _EAST,
    "eastern": _EAST,
    "west": _WEST,
    "the west": _WEST,
    "western": _WEST,
    "south": _SOUTH,
    "the south": _SOUTH,
    "southern": _SOUTH,
    "deep south": ["MS", "AL", "GA", "LA", "SC"],
    "north": _NORTH,
    "the north": _NORTH,
    "northern": _NORTH,
    "gulf coast": ["TX", "LA", "MS", "AL", "FL"],
    "great lakes": ["MN", "WI", "IL", "IN", "MI", "OH", "PA", "NY"],
    "plains": ["ND", "SD", "NE", "KS", "OK", "IA", "MO"],
    "rockies": ["CO", "UT", "WY", "MT", "ID", "NM"],
    "sun belt": ["CA", "AZ", "NM", "TX", "LA", "MS", "AL", "GA", "FL", "SC", "NV"],
    "continental us": [v for v in sorted(set(US_STATES.values()))
                       if v not in ("AK", "HI", "PR")],
    "northeast": NEW_ENGLAND_STATES + ["NY", "NJ", "PA"],
    "mid-atlantic": ["NY", "NJ", "PA", "DE", "MD", "DC", "VA", "WV"],
    "southeast": ["NC", "SC", "GA", "FL", "AL", "MS", "TN", "KY"],
    "midwest": ["OH", "MI", "IN", "IL", "WI", "MN", "IA", "MO", "ND", "SD", "NE", "KS"],
    "southwest": ["TX", "OK", "NM", "AZ"],
    "mountain": ["CO", "UT", "NV", "ID", "MT", "WY"],
    "west coast": ["CA", "OR", "WA"],
    "california": ["CA"],
    "pacific northwest": ["WA", "OR"],
    "alaska": ["AK"],
    "hawaii": ["HI"],
}

# Short forms people actually say, especially out loud. "Compare LA and Santa
# Ana" is one of the sample questions, so "LA" has to resolve.
METRO_ALIASES: dict[str, str] = {
    "la": "los angeles", "l.a.": "los angeles", "socal": "los angeles",
    "nyc": "new york", "ny": "new york", "sf": "san francisco",
    "the bay": "bay area", "dc": "washington", "chi": "chicago",
    "dfw": "dallas", "orange county": "los angeles",
}

# Metro areas where "the LA airport" style questions are genuinely ambiguous.
METRO_GROUPS: dict[str, list[str]] = {
    "los angeles": ["LAX", "BUR", "LGB", "ONT", "SNA"],
    "new york": ["JFK", "LGA", "EWR", "HPN", "ISP"],
    "bay area": ["SFO", "OAK", "SJC"],
    "san francisco": ["SFO", "OAK", "SJC"],
    "chicago": ["ORD", "MDW"],
    "washington": ["DCA", "IAD", "BWI"],
    "boston": ["BOS", "MHT", "PVD"],
    "dallas": ["DFW", "DAL"],
    "houston": ["IAH", "HOU"],
    "miami": ["MIA", "FLL", "PBI"],
}

DEFAULT_WEIGHTS = json.loads(os.environ.get("SCORE_WEIGHTS", "{}") or "{}")

# ------------------------------------------------------------------- provider
# One line chooses the model, in LangChain's own "provider:model" form:
#
#   LLM=google_genai:gemini-3.5-flash-lite
#   LLM=openai:gpt-4o-mini
#   LLM=groq:llama-3.3-70b-versatile
#   LLM=anthropic:claude-sonnet-4-6
#   LLM=ollama:llama3
#
# Each provider reads its own conventional key variable (GOOGLE_API_KEY,
# OPENAI_API_KEY, GROQ_API_KEY, ANTHROPIC_API_KEY...), so switching models
# touches nothing else.
LLM = os.environ.get("LLM", "")
LLM_TEMPERATURE = float(os.environ.get("LLM_TEMPERATURE", "0.2"))

# Deprecated split form, still honoured so older .env files keep working.
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "auto")
LLM_MODEL = os.environ.get("LLM_MODEL", "")

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "") or GEMINI_API_KEY
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

# LangChain's Google integration looks for GOOGLE_API_KEY. Accept the older
# GEMINI_API_KEY spelling too rather than making people rename a working key.
if GOOGLE_API_KEY:
    os.environ.setdefault("GOOGLE_API_KEY", GOOGLE_API_KEY)

_PROVIDER_ALIASES = {
    "gemini": "google_genai", "google": "google_genai",
    "groq": "groq", "openai": "openai", "anthropic": "anthropic",
    "openrouter": "openai",          # OpenAI-compatible endpoint
    "ollama": "ollama",
}

_DEFAULT_MODELS = {
    "google_genai": "gemini-3.5-flash-lite",
    "groq": "llama-3.3-70b-versatile",
    "openai": "gpt-4o-mini",
    "anthropic": "claude-sonnet-4-6",
    "ollama": "llama3",
}


def llm_spec() -> str:
    """The configured model as "provider:model", or "" when none is set."""
    if LLM.strip():
        spec = LLM.strip()
        if ":" not in spec:
            return spec
        prov, _, model = spec.partition(":")
        prov = _PROVIDER_ALIASES.get(prov.lower().strip(), prov.lower().strip())
        return f"{prov}:{model.strip() or _DEFAULT_MODELS.get(prov, '')}"

    # Fall back to the deprecated split form.
    choice = (LLM_PROVIDER or "").lower().strip()
    if choice in ("", "auto"):
        for env_key, prov in (("GOOGLE_API_KEY", "google_genai"),
                              ("GROQ_API_KEY", "groq"),
                              ("OPENAI_API_KEY", "openai"),
                              ("ANTHROPIC_API_KEY", "anthropic")):
            if os.environ.get(env_key):
                choice = prov
                break
        else:
            return ""            # nothing configured: the keyless planner runs
    if not choice or choice in ("rule", "auto"):
        return ""
    prov = _PROVIDER_ALIASES.get(choice, choice)
    return f"{prov}:{LLM_MODEL.strip() or _DEFAULT_MODELS.get(prov, '')}"

# ── Speech synthesis ────────────────────────────────────────────────────────
# The browser's built-in voices are free and need no key, but they are the
# reason synthetic speech still sounds synthetic. Setting either key below
# switches the app to a neural voice, which is the actual fix.
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_FEMALE = os.environ.get("ELEVENLABS_VOICE_FEMALE", "EXAVITQu4vr4xnSDxMaL")  # Sarah
ELEVENLABS_VOICE_MALE = os.environ.get("ELEVENLABS_VOICE_MALE", "onwK4e9ZLuTAKqWW03F9")      # Daniel
ELEVENLABS_MODEL = os.environ.get("ELEVENLABS_MODEL", "eleven_turbo_v2_5")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_TTS_MODEL = os.environ.get("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
OPENAI_VOICE_FEMALE = os.environ.get("OPENAI_VOICE_FEMALE", "shimmer")
OPENAI_VOICE_MALE = os.environ.get("OPENAI_VOICE_MALE", "onyx")


def tts_provider() -> str:
    if ELEVENLABS_API_KEY:
        return "elevenlabs"
    if OPENAI_API_KEY:
        return "openai"
    return "browser"


# ── Web retrieval (optional) ────────────────────────────────────────────────
# Used only for announced capital programmes: qualitative context, never an
# input to any score. Without a key the tool reports itself unavailable and the
# agent falls back to the curated constraints file.
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")
BRAVE_API_KEY = os.environ.get("BRAVE_API_KEY", "")


def search_provider() -> str:
    if TAVILY_API_KEY:
        return "tavily"
    if BRAVE_API_KEY:
        return "brave"
    return "none"


MAX_AGENT_HOPS = int(os.environ.get("MAX_AGENT_HOPS", 5))
PORT = int(os.environ.get("PORT", 8000))


def assumption_registry() -> dict:
    """The assumptions bundle attached to every substantive answer."""
    return {
        "long_haul_threshold_nmi": LONG_HAUL_NMI,
        "long_haul_note": (
            "No ICAO/IATA standard exists for 'long haul'. Industry usage spans "
            "roughly 2,200-2,600 nmi; ICAO and IATA both define by flight time "
            "and disagree. This threshold is configurable."
        ),
        "short_haul_threshold_nmi": SHORT_HAUL_NMI,
        "new_england_states": NEW_ENGLAND_STATES,
        "ops_estimate": "Annual operations approximated as 2 x departures performed.",
        "capacity_thresholds": (
            "Tiers follow FAA AC 150/5060-5: plan additional capacity at 60% of "
            "Annual Service Volume, build at 80%."
        ),
        "scope": (
            "US commercial-service airports only. Not general aviation, not "
            "non-US airports, not airline or equity analysis."
        ),
    }
