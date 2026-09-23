"""Vercel entry point for the Version 2 FastAPI application.

The application remains under ``backend/app`` for local development.  Vercel
invokes this module as an ASGI function, so the backend directory is added to
the import path without changing the local ``uvicorn app.main:app`` command.
"""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import parse_qs


BACKEND_ROOT = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app as fastapi_app  # noqa: E402  (path setup must run first)


class VercelRewriteAdapter:
    """Restore the original route after Vercel's internal Python rewrite."""

    def __init__(self, application):
        self.application = application

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http":
            query = parse_qs(scope.get("query_string", b"").decode("utf-8"))
            route = query.get("route", [""])[0]
            if route:
                scope = dict(scope)
                scope["path"] = route
                scope["raw_path"] = route.encode("utf-8")
        await self.application(scope, receive, send)


app = VercelRewriteAdapter(fastapi_app)


__all__ = ["app"]
