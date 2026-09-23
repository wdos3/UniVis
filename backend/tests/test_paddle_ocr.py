from __future__ import annotations

import asyncio

from app.models import SourcePage
from app.services.images.models import PreparedImage
from app.services.ocr import PaddleOcrProvider


def _prepared_image() -> PreparedImage:
    page = SourcePage(
        id="page-001-test",
        page_number=1,
        filename="notice.jpg",
        media_type="image/jpeg",
        original_url="/uploads/test/original.jpg",
        processed_url="/uploads/test/processed.jpg",
        width=1200,
        height=1800,
    )
    return PreparedImage(page=page, original_bytes=b"image-bytes", processed_bytes=b"processed-bytes")


def test_paddle_provider_uses_local_extractor_and_reports_uncertain_lines() -> None:
    def extractor(image_bytes: bytes) -> tuple[str, int]:
        assert image_bytes == b"image-bytes"
        return "지원 기간\n2026.09.07~2026.10.05", 2

    result = asyncio.run(PaddleOcrProvider(extractor=extractor).extract([_prepared_image()]))

    assert result.provider == "paddleocr-ppocrv5-korean-local"
    assert result.status == "available"
    assert "2026.10.05" in result.text
    assert result.page_texts == ["지원 기간\n2026.09.07~2026.10.05"]
    assert result.warnings == ["PaddleOCR marked 2 line(s) on page 1 as low-confidence."]
