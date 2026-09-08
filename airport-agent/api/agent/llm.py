"""Model construction via LangChain, so any provider works from one .env line.

Everything about *which* model runs lives in `LLM=provider:model`. LangChain's
`init_chat_model` turns that into a chat model with a uniform tool-calling
interface, which is the real reason for the dependency: normalising tool calls
across providers is fiddly and every provider shapes them differently. The
hand-written adapters this replaces had a live bug of exactly that kind, silently
dropping tool calls from Gemini conversation history.

Imports are deliberately version-tolerant. `init_chat_model` has moved between
LangChain releases and this code could not be executed in the environment where
it was written, so it tries the known locations rather than betting on one.
"""
from __future__ import annotations

import functools

from .. import config


def _import_init_chat_model():
    """Find init_chat_model wherever this LangChain version keeps it."""
    candidates = (
        ("langchain.chat_models", "init_chat_model"),
        ("langchain_core.language_models", "init_chat_model"),
        ("langchain.chat_models.base", "init_chat_model"),
        ("langchain_core.language_models.chat_models", "init_chat_model"),
    )
    errors = []
    for module_name, attr in candidates:
        try:
            module = __import__(module_name, fromlist=[attr])
            fn = getattr(module, attr, None)
            if fn is not None:
                return fn
        except Exception as exc:                       # noqa: BLE001
            errors.append(f"{module_name}: {exc}")
    raise ImportError(
        "Could not find init_chat_model in this LangChain install. Tried:\n  "
        + "\n  ".join(f"{m}.{a}" for m, a in candidates)
        + ("\nImport errors:\n  " + "\n  ".join(errors) if errors else "")
    )


@functools.lru_cache(maxsize=1)
def llm_available() -> bool:
    """Is the LangChain stack importable at all?

    Everything keys off this: with LangChain absent the app still runs, still
    serves, and still answers through the keyless planner.
    """
    try:
        _import_init_chat_model()
        import langchain_core.messages  # noqa: F401
        return True
    except Exception:                                  # noqa: BLE001
        return False


def missing_dependency_hint() -> str:
    spec = config.llm_spec()
    provider = spec.split(":")[0] if spec else "google_genai"
    package = {
        "google_genai": "langchain-google-genai",
        "openai": "langchain-openai",
        "groq": "langchain-groq",
        "anthropic": "langchain-anthropic",
        "ollama": "langchain-ollama",
    }.get(provider, f"langchain-{provider}")
    import sys
    # Naming the interpreter matters: "LangChain is not installed" is baffling
    # when it IS installed, just not for the python that is running.
    return (f"LangChain is not importable by this interpreter, so the model path "
            f"is unavailable.\n"
            f"  interpreter: {sys.executable}\n"
            f"  fix: {sys.executable} -m pip install -r requirements.txt\n"
            f"       (or: pip install langchain {package})\n"
            f"The deterministic analytics and the keyless planner work without it.")


def build_model(spec: str | None = None, temperature: float | None = None):
    """Return a LangChain chat model for the configured spec.

    Raises RuntimeError with something actionable rather than a traceback: a
    missing package and a missing API key are the two likely failures and they
    need different fixes.
    """
    spec = (spec or config.llm_spec()).strip()
    if not spec:
        raise RuntimeError("No model configured. Set LLM=provider:model in .env")

    try:
        init_chat_model = _import_init_chat_model()
    except ImportError as exc:
        # A missing package and a missing key need different fixes, so say which.
        raise RuntimeError(missing_dependency_hint()) from exc

    temp = config.LLM_TEMPERATURE if temperature is None else temperature
    try:
        return init_chat_model(spec, temperature=temp)
    except Exception as exc:                           # noqa: BLE001
        raise RuntimeError(
            f"Could not start {spec!r}: {exc}\n"
            f"Check the provider package is installed and its API key is set "
            f"in .env (GOOGLE_API_KEY, OPENAI_API_KEY, GROQ_API_KEY, ...)."
        ) from exc


def describe() -> str:
    """What to print at startup and report through /meta."""
    spec = config.llm_spec()
    if not spec:
        return "built-in planner (no model configured)"
    if not llm_available():
        return f"{spec} (LangChain not installed - using built-in planner)"
    return spec
