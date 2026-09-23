from __future__ import annotations

import asyncio
import httpx
import pytest

from app.models import SourcePage
from app.services.images.models import PreparedImage
from app.services.ocr import PaddleOcrProvider, RemotePaddleOcrProvider, choose_ocr_provider


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


def test_remote_paddle_provider_posts_ordered_pages_to_container() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["token"] = request.headers.get("x-ocr-service-token")
        seen["body"] = request.content
        return httpx.Response(
            200,
            json={
                "text": "[Page 1]\n지원 기간",
                "page_texts": ["지원 기간"],
                "provider": "paddleocr-ppocrv5-korean-local",
                "status": "available",
                "warnings": [],
            },
        )

    transport = httpx.MockTransport(handler)

    def client_factory(**kwargs):
        return httpx.AsyncClient(transport=transport, **kwargs)

    result = asyncio.run(
        RemotePaddleOcrProvider(
            "http://ocr:8000/",
            token="test-token",
            client_factory=client_factory,
        ).extract([_prepared_image()])
    )

    assert result.provider == "paddleocr-ppocrv5-korean-container"
    assert result.page_texts == ["지원 기간"]
    assert seen["url"] == "http://ocr:8000/ocr"
    assert seen["token"] == "test-token"
    assert b"notice.jpg" in seen["body"]


def test_ocr_provider_selection_uses_container_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PADDLEOCR_SERVICE_URL", "https://ocr.example.test")
    monkeypatch.setenv("PADDLEOCR_SERVICE_TOKEN", "secret")
    monkeypatch.setenv("PADDLEOCR_SERVICE_TIMEOUT_SECONDS", "12")

    provider = choose_ocr_provider()

    assert isinstance(provider, RemotePaddleOcrProvider)
    assert provider.service_url == "https://ocr.example.test"
    assert provider.token == "secret"
    assert provider.timeout_seconds == 12
