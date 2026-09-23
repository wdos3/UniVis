from __future__ import annotations

from dataclasses import dataclass

from app.models import SourcePage


@dataclass(frozen=True)
class PreparedImage:
    page: SourcePage
    original_bytes: bytes
    processed_bytes: bytes
