from __future__ import annotations

import asyncio
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, Sequence

import httpx

from app.services.images.models import PreparedImage
from app.services.images.paddle_ocr import PROVIDER_NAME, extract_korean_text


class OcrError(RuntimeError):
    pass


@dataclass(frozen=True)
class OcrResult:
    text: str
    page_texts: list[str]
    provider: str
    status: str
    warnings: list[str] = field(default_factory=list)


class OcrProvider(ABC):
    name: str

    @abstractmethod
    async def extract(self, images: list[PreparedImage]) -> OcrResult:
        """Recover text from ordered notice pages."""


class PaddleOcrProvider(OcrProvider):
    name = PROVIDER_NAME

    def __init__(self, extractor=extract_korean_text) -> None:
        self.extractor = extractor

    async def extract(self, images: list[PreparedImage]) -> OcrResult:
        if not images:
            raise OcrError("Add at least one notice image.")

        return await self.extract_bytes([image.original_bytes for image in images])

    async def extract_bytes(self, image_bytes: Sequence[bytes]) -> OcrResult:
        if not image_bytes:
            raise OcrError("Add at least one notice image.")

        page_texts: list[str] = []
        warnings: list[str] = []
        try:
            for index, data in enumerate(image_bytes, start=1):
                text, low_confidence = await asyncio.to_thread(self.extractor, data)
                page_texts.append(text.strip())
                if low_confidence:
                    warnings.append(f"PaddleOCR marked {low_confidence} line(s) on page {index} as low-confidence.")
        except (ImportError, ModuleNotFoundError) as exc:
            raise OcrError("Local PaddleOCR is not installed. Run the Version 2 dependency installation and try again.") from exc
        except Exception as exc:
            raise OcrError(
                "Local PaddleOCR could not read this notice. On its first run, it must download the Korean model files; check the connection and try again."
            ) from exc

        missing_pages = [str(index) for index, text in enumerate(page_texts, start=1) if not text]
        if len(missing_pages) == len(page_texts):
            raise OcrError("Local OCR could not recover readable text. Retake the photo closer, brighter, and straight-on.")
        if missing_pages:
            warnings.append(f"Local OCR recovered no text from page(s): {', '.join(missing_pages)}.")
        text = "\n\n".join(f"[Page {index}]\n{page_text}" for index, page_text in enumerate(page_texts, start=1))
        return OcrResult(
            text=text,
            page_texts=page_texts,
            provider=self.name,
            status="partial" if missing_pages else "available",
            warnings=warnings,
        )


REMOTE_PROVIDER_NAME = "paddleocr-ppocrv5-korean-container"


class RemotePaddleOcrProvider(OcrProvider):
    """Call the dedicated PaddleOCR container without loading Paddle locally."""

    name = REMOTE_PROVIDER_NAME

    def __init__(
        self,
        service_url: str,
        token: str = "",
        timeout_seconds: float = 90,
        client_factory: Callable[..., httpx.AsyncClient] = httpx.AsyncClient,
    ) -> None:
        self.service_url = service_url.rstrip("/")
        self.token = token
        self.timeout_seconds = timeout_seconds
        self.client_factory = client_factory

    async def extract(self, images: list[PreparedImage]) -> OcrResult:
        if not images:
            raise OcrError("Add at least one notice image.")

        files = [
            (
                "files",
                (image.page.filename, image.original_bytes, image.page.media_type),
            )
            for image in images
        ]
        headers = {"X-OCR-Service-Token": self.token} if self.token else {}
        try:
            async with self.client_factory(timeout=self.timeout_seconds) as client:
                response = await client.post(f"{self.service_url}/ocr", files=files, headers=headers)
                response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise OcrError("The PaddleOCR container timed out while reading this notice.") from exc
        except httpx.HTTPStatusError as exc:
            detail = _remote_error_detail(exc.response)
            raise OcrError(f"The PaddleOCR container rejected the notice: {detail}") from exc
        except httpx.HTTPError as exc:
            raise OcrError("The PaddleOCR container could not be reached. Check PADDLEOCR_SERVICE_URL and its network access.") from exc

        try:
            payload = response.json()
            page_texts = [str(text).strip() for text in payload["page_texts"]]
            text = str(payload["text"]).strip()
            status = str(payload.get("status", "available"))
            warnings = [str(warning) for warning in payload.get("warnings", [])]
        except (KeyError, TypeError, ValueError) as exc:
            raise OcrError("The PaddleOCR container returned an invalid OCR response.") from exc

        if not page_texts or len(page_texts) != len(images):
            raise OcrError("The PaddleOCR container returned an incomplete OCR response.")
        if not text:
            raise OcrError("The PaddleOCR container recovered no readable text from this notice.")
        return OcrResult(text=text, page_texts=page_texts, provider=self.name, status=status, warnings=warnings)


def _remote_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
        detail = payload.get("detail") if isinstance(payload, dict) else None
    except (ValueError, TypeError):
        detail = None
    return str(detail or f"HTTP {response.status_code}")


def choose_ocr_provider() -> OcrProvider:
    service_url = os.getenv("PADDLEOCR_SERVICE_URL", "").strip()
    if not service_url:
        return PaddleOcrProvider()
    try:
        timeout_seconds = max(5.0, float(os.getenv("PADDLEOCR_SERVICE_TIMEOUT_SECONDS", "90")))
    except ValueError:
        timeout_seconds = 90.0
    return RemotePaddleOcrProvider(
        service_url=service_url,
        token=os.getenv("PADDLEOCR_SERVICE_TOKEN", ""),
        timeout_seconds=timeout_seconds,
    )
