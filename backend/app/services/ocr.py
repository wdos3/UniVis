from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

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
        """Recover text locally from ordered notice pages."""


class PaddleOcrProvider(OcrProvider):
    name = PROVIDER_NAME

    def __init__(self, extractor=extract_korean_text) -> None:
        self.extractor = extractor

    async def extract(self, images: list[PreparedImage]) -> OcrResult:
        if not images:
            raise OcrError("Add at least one notice image.")

        page_texts: list[str] = []
        warnings: list[str] = []
        try:
            for index, image in enumerate(images, start=1):
                text, low_confidence = await asyncio.to_thread(self.extractor, image.original_bytes)
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
