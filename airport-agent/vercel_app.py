"""Vercel entrypoint.

Vercel's Python runtime looks for a module-level `handler` that subclasses
BaseHTTPRequestHandler and drives it once per request. api.server.Handler is
already exactly that, so the whole app -- the REST analytics endpoints, the
SSE chat and the static web UI -- deploys with no second implementation to
keep in sync. `python3 -m api.server` locally and the deployed function run
the same code down to the routing table.

The one behavioural difference is streaming: a serverless response is
delivered whole, so /chat's SSE frames arrive in a single chunk at the end
rather than progressively. The browser parses them identically -- it buffers
and splits on the frame separator either way -- so the answer is unchanged;
only the live "thinking" ticker is lost.
"""
from __future__ import annotations

import os
import sys

# The function is invoked with an unspecified cwd; make the package importable
# by path rather than by luck.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from api.server import Handler as handler   # noqa: E402  (must follow sys.path)

__all__ = ["handler"]
