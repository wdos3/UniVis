from __future__ import annotations

import hmac
import logging
import os

from dotenv import load_dotenv
from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from pydantic import BaseModel, Field

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:  # Optional for deployments that only accept JPG/PNG.
    pass

from app.services.ocr import OcrError, PaddleOcrProvider


load_dotenv()

MAX_PAGE_BYTES = 15 * 1024 * 1024
MAX_TOTAL_BYTES = 50 * 1024 * 1024
MAX_PAGES = 12


class OcrResponse(BaseModel):
    text: str
    page_texts: list[str]
    provider: str
    status: str
    warnings: list[str] = Field(default_factory=list)


app = FastAPI(title="UniVis PaddleOCR Service", version="1.0.0")
logger = logging.getLogger("univis.ocr")


def _configured_token() -> str:
    return os.getenv("PADDLEOCR_SERVICE_TOKEN", "").strip()


def _check_token(provided_token: str | None) -> None:
    expected_token = _configured_token()
    if expected_token and not hmac.compare_digest(provided_token or "", expected_token):
        raise HTTPException(status_code=401, detail="Invalid OCR service token.")


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "service": "paddleocr",
        "provider": "paddleocr-ppocrv5-korean-local",
        "auth_required": bool(_configured_token()),
    }


@app.post("/ocr", response_model=OcrResponse)
async def ocr(
    files: list[UploadFile] = File(...),
    x_ocr_service_token: str | None = Header(default=None),
) -> OcrResponse:
    _check_token(x_ocr_service_token)
    if not files:
        raise HTTPException(status_code=422, detail="Add at least one notice image.")
    if len(files) > MAX_PAGES:
        raise HTTPException(status_code=413, detail=f"A notice can contain at most {MAX_PAGES} image pages.")

    image_bytes: list[bytes] = []
    total_size = 0
    for file in files:
        data = await file.read(MAX_PAGE_BYTES + 1)
        if len(data) > MAX_PAGE_BYTES:
            raise HTTPException(status_code=413, detail="Images exceed the 15 MB per-page prototype limit.")
        total_size += len(data)
        if total_size > MAX_TOTAL_BYTES:
            raise HTTPException(status_code=413, detail="Images exceed the 50 MB total prototype limit.")
        image_bytes.append(data)

    try:
        result = await PaddleOcrProvider().extract_bytes(image_bytes)
    except OcrError as exc:
        logger.warning("ocr_request_failed reason=%s", str(exc))
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("ocr_request_failed_unexpected")
        raise HTTPException(status_code=502, detail="PaddleOCR could not complete the recognition request.") from exc

    return OcrResponse(
        text=result.text,
        page_texts=result.page_texts,
        provider=result.provider,
        status=result.status,
        warnings=result.warnings,
    )
