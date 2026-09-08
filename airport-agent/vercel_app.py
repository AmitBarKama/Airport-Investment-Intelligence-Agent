"""Vercel entrypoint.

Vercel's Python runtime drives a top-level `handler` that subclasses
BaseHTTPRequestHandler, and api.server.Handler already is one -- so the whole
app (REST analytics, SSE chat, static web UI) deploys with no second server
implementation to keep in sync. `python3 -m api.server` locally and the
deployed function run the same code down to the routing table.

It is subclassed rather than aliased because the build finds the entrypoint by
*parsing* this file, not by importing it. `from api.server import Handler as
handler` binds the name at runtime but leaves nothing in the source for the
parser to see, and the build fails with "Could not find a top-level handler".
A class statement is visible to both.

The one behavioural difference is streaming: a serverless response is
delivered whole, so /chat's SSE frames arrive in a single chunk at the end.
The browser parses them identically -- it buffers and splits on the frame
separator either way -- so the answer is unchanged; only the live "thinking"
ticker is lost.
"""
from __future__ import annotations

import os
import sys

# The function is invoked with an unspecified cwd; make the package importable
# by path rather than by luck.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from api.server import Handler as _Handler   # noqa: E402  (must follow sys.path)


class handler(_Handler):        # noqa: N801  the runtime requires this name
    """The deployed app: api.server.Handler, under the name Vercel looks for."""


__all__ = ["handler"]
