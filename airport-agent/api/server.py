"""Stdlib HTTP server: SSE chat + deterministic REST endpoints + static web UI.

http.server rather than FastAPI so the whole backend runs with no pip install.
ThreadingHTTPServer gives enough concurrency for a single-user analyst tool.

The deterministic endpoints (/rank, /compare, /airport, /explain, /sensitivity)
exist separately from /chat on purpose: the analytics are the product, chat is
one interface onto them. They also keep the system demonstrable if the LLM key
is missing or the provider is down.

    python3 -m api.server
"""
from __future__ import annotations

import json
import mimetypes
import sys
import os
import traceback
import urllib.error
import urllib.parse
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from . import config, db
from .agent import tools as T
from .agent.loop import run as run_agent
from .scoring.profiles import PROFILES


def _http_post_bytes(url: str, payload: dict, headers: dict, timeout: int = 45) -> bytes:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _json_default(o):
    try:
        return float(o)
    except Exception:                                    # noqa: BLE001
        return str(o)


class _HeadOnlyWriter:
    """Lets the response headers through and swallows the body after them.

    HEAD must answer with GET's status and headers but no body. Wrapping wfile
    is what lets do_HEAD reuse do_GET's routing table verbatim instead of
    growing a second one that can drift out of step with it.
    """

    def __init__(self, wfile):
        self._wfile = wfile
        self.body_started = False

    def write(self, data):
        if self.body_started:
            return len(data)
        return self._wfile.write(data)

    def flush(self):
        return self._wfile.flush()


class Handler(SimpleHTTPRequestHandler):
    server_version = "AirportAgent/1.0"

    def log_message(self, fmt, *args):                   # quieter console
        if "/health" not in (args[0] if args else ""):
            super().log_message(fmt, *args)

    # ---------------------------------------------------------------- helpers
    def _send_json(self, obj, status=200):
        body = json.dumps(obj, default=_json_default).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode())
        except json.JSONDecodeError:
            return {}

    def _query(self) -> dict:
        parsed = urllib.parse.urlparse(self.path)
        return {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}

    # ------------------------------------------------------------------- GET
    def do_GET(self):                                    # noqa: N802
        path = urllib.parse.urlparse(self.path).path
        try:
            if path == "/health":
                return self._send_json({"ok": True})
            if path == "/meta":
                m = db.meta()
                return self._send_json({
                    "data": m,
                    "assumptions": config.assumption_registry(),
                    "profiles": {k: {"label": v["label"],
                                     "description": v["description"],
                                     "weights": v["weights"]}
                                 for k, v in PROFILES.items()},
                    "provider": _provider_name(),
                    "tts": config.tts_provider(),
                    "search": config.search_provider(),
                })
            if path == "/airports":
                q = self._query()
                return self._send_json(T.list_airports(
                    region=q.get("region"), metro=q.get("metro"),
                    states=q["states"].split(",") if q.get("states") else None,
                    hub_class=q.get("hub_class"),
                    limit=int(q.get("limit", 50))))
            if path.startswith("/airport/"):
                return self._send_json(T.airport_profile(path.split("/")[-1]))
            if path.startswith("/explain/"):
                q = self._query()
                return self._send_json(T.explain_score(
                    path.split("/")[-1], profile=q.get("profile", "investment")))
            if path.startswith("/mix/"):
                q = self._query()
                return self._send_json(T.flight_mix(
                    path.split("/")[-1], dimension=q.get("dimension", "haul"),
                    long_haul_nmi=float(q["long_haul_nmi"]) if q.get("long_haul_nmi") else None))
            if path.startswith("/unmet/"):
                return self._send_json(T.unmet_demand(path.split("/")[-1]))
            return self._serve_static(path)
        except FileNotFoundError as exc:
            self._send_json({"error": str(exc)}, 503)
        except Exception as exc:                          # noqa: BLE001
            traceback.print_exc()
            self._send_json({"error": str(exc)}, 500)

    # ------------------------------------------------------------------ HEAD
    def do_HEAD(self):                                   # noqa: N802
        """Answer HEAD from the same routing table as GET.

        SimpleHTTPRequestHandler's inherited do_HEAD serves the process's
        working directory, which is the project root and not web/. It therefore
        answered for files that are not the site at all -- the Python sources
        next to it -- knew none of the routes above, and raised a traceback on
        anything it could not find. Running GET with the body swallowed gives
        HEAD the right answer for every route by construction.
        """
        real, self.wfile = self.wfile, _HeadOnlyWriter(self.wfile)
        try:
            self.do_GET()
        finally:
            self.wfile = real

    def end_headers(self):
        super().end_headers()
        if isinstance(self.wfile, _HeadOnlyWriter):
            self.wfile.body_started = True

    # ------------------------------------------------------------------ POST
    def do_POST(self):                                   # noqa: N802
        path = urllib.parse.urlparse(self.path).path
        try:
            body = self._body()
            if path == "/rank":
                return self._send_json(T.rank_airports(**body))
            if path == "/compare":
                return self._send_json(T.compare_airports(**body))
            if path == "/sensitivity":
                return self._send_json(T.sensitivity_analysis(**body))
            if path == "/chat":
                return self._chat(body)
            if path == "/speak":
                return self._speak(body)
            self._send_json({"error": "not found"}, 404)
        except TypeError as exc:
            self._send_json({"error": f"bad arguments: {exc}"}, 400)
        except Exception as exc:                          # noqa: BLE001
            traceback.print_exc()
            self._send_json({"error": str(exc)}, 500)

    def do_OPTIONS(self):                                # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.end_headers()

    # ------------------------------------------------------------------- SSE
    def _chat(self, body: dict):
        # An SSE body has no Content-Length, so the response MUST be delimited
        # some other way. Advertising keep-alive without chunked encoding
        # leaves the client unable to tell where the body ends: Chrome then
        # withholds the stream entirely and the answer never appears. Closing
        # the connection makes EOF the delimiter, which is what an SSE stream
        # of unknown length needs here.
        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")   # defeat proxy buffering
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        def emit(event: str, payload: dict):
            chunk = (f"event: {event}\n"
                     f"data: {json.dumps(payload, default=_json_default)}\n\n")
            self.wfile.write(chunk.encode())
            self.wfile.flush()

        try:
            for ev in run_agent(
                body.get("message", ""),
                history=body.get("history"),
                state=body.get("state"),
                voice=bool(body.get("voice")),
            ):
                emit(ev.pop("type"), ev)
        except BrokenPipeError:
            pass
        except Exception as exc:                          # noqa: BLE001
            traceback.print_exc()
            try:
                emit("done", {"text": f"Server error: {exc}", "error": str(exc)})
            except Exception:                             # noqa: BLE001
                pass

    # ------------------------------------------------------------------ tts
    def _speak(self, body: dict):
        """Neural text-to-speech, proxied so the API key never reaches the browser.

        Falls back with a 501 when no key is configured, which the client reads
        as "use the built-in browser voice instead".
        """
        text = (body.get("text") or "").strip()[:2000]
        gender = "male" if body.get("gender") == "male" else "female"
        if not text:
            return self._send_json({"error": "no text"}, 400)

        provider = config.tts_provider()
        if provider == "browser":
            return self._send_json(
                {"error": "no neural voice configured",
                 "hint": "set ELEVENLABS_API_KEY or OPENAI_API_KEY"}, 501)

        try:
            if provider == "elevenlabs":
                voice = (config.ELEVENLABS_VOICE_MALE if gender == "male"
                         else config.ELEVENLABS_VOICE_FEMALE)
                audio = _http_post_bytes(
                    f"https://api.elevenlabs.io/v1/text-to-speech/{voice}",
                    {"text": text, "model_id": config.ELEVENLABS_MODEL,
                     "voice_settings": {"stability": 0.45, "similarity_boost": 0.75,
                                        "style": 0.15, "use_speaker_boost": True}},
                    {"xi-api-key": config.ELEVENLABS_API_KEY, "Accept": "audio/mpeg"})
            else:
                voice = (config.OPENAI_VOICE_MALE if gender == "male"
                         else config.OPENAI_VOICE_FEMALE)
                audio = _http_post_bytes(
                    "https://api.openai.com/v1/audio/speech",
                    {"model": config.OPENAI_TTS_MODEL, "voice": voice,
                     "input": text, "response_format": "mp3"},
                    {"Authorization": f"Bearer {config.OPENAI_API_KEY}"})
        except Exception as exc:                          # noqa: BLE001
            return self._send_json({"error": f"tts failed: {exc}"}, 502)

        self.send_response(200)
        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("Content-Length", str(len(audio)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(audio)

    # ---------------------------------------------------------------- static
    def _serve_static(self, path: str):
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        full = os.path.normpath(os.path.join(config.WEB_DIR, rel))
        if not full.startswith(os.path.normpath(config.WEB_DIR)):
            return self._send_json({"error": "forbidden"}, 403)
        if not os.path.isfile(full):
            return self._send_json({"error": "not found"}, 404)
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        with open(full, "rb") as fh:
            data = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        # A dev server that serves stale JS is a debugging trap: the code on
        # disk and the code in the browser disagree, and nothing says so.
        # A deployed build is immutable, and there every asset byte is served
        # by a function invocation, so the same default would bill ~800 KB of
        # orb and script through the runtime on every single page load.
        self.send_header("Cache-Control",
                         "public, max-age=3600" if config.IS_DEPLOYED
                         else "no-cache, must-revalidate")
        self.end_headers()
        self.wfile.write(data)


def _provider_name() -> str:
    """What is actually answering: the configured model, or the keyless planner."""
    try:
        from .agent import llm
        return llm.describe()
    except Exception:                                     # noqa: BLE001
        return "unavailable"


def _warn_if_model_unusable() -> None:
    """Shout when a model is configured but cannot run.

    This used to be a parenthetical on the provider line -- "(LangChain not
    installed - using built-in planner)" -- which reads as a note and was
    missed for an entire session while every answer came from the keyword
    planner. Asking for a model and silently not getting one is a fault.
    """
    from .agent import llm
    if not config.llm_spec() or llm.llm_available():
        return
    bar = "  " + "!" * 68
    print()
    print(bar)
    print("  MODEL CONFIGURED BUT NOT USABLE - answering with the keyword planner.")
    print(f"  LLM={config.llm_spec()} is set, but LangChain cannot be imported by")
    print(f"  the interpreter running this server:")
    print(f"      {sys.executable}")
    print("  Install the dependencies for that interpreter, then restart:")
    print("      make install && make serve")
    print(bar)
    print()


def main():
    try:
        meta = db.meta()
    except FileNotFoundError as exc:
        raise SystemExit(f"{exc}")
    srv = ThreadingHTTPServer(("127.0.0.1", config.PORT), Handler)
    print(f"Airport Investment Intelligence Agent")
    print(f"  http://127.0.0.1:{config.PORT}")
    print(f"  data mode : {meta.get('data_mode')}  ({meta.get('n_airports')} airports)")
    print(f"  provider  : {_provider_name()}")
    _warn_if_model_unusable()
    if meta.get("data_mode") == "synthetic":
        print("  WARNING   : traffic volumes are SYNTHETIC (structure is real)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
