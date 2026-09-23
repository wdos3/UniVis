"""Vercel entry point for the Version 2 FastAPI application.

The application remains under ``backend/app`` for local development.  Vercel
invokes this module as an ASGI function, so the backend directory is added to
the import path without changing the local ``uvicorn app.main:app`` command.
"""

from __future__ import annotations

import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app  # noqa: E402  (path setup must run first)


__all__ = ["app"]
