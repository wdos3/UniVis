from __future__ import annotations

import io
import os
import platform
import re
from functools import lru_cache
from threading import Lock
from typing import Any

import numpy as np
from PIL import Image, ImageOps


DETECTION_MODEL = "PP-OCRv5_mobile_det"
KOREAN_RECOGNITION_MODEL = "korean_PP-OCRv5_mobile_rec"
PROVIDER_NAME = "paddleocr-ppocrv5-korean-local"

_engine_lock = Lock()
_inference_lock = Lock()


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@lru_cache(maxsize=1)
def get_paddle_engine() -> Any:
    """Create the local Korean OCR engine once; model weights are cached by PaddleOCR."""
    with _engine_lock:
        os.environ.setdefault("PADDLE_PDX_MODEL_SOURCE", "BOS")
        os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
        from paddleocr import PaddleOCR

        cpu_threads = max(1, int(os.getenv("PADDLEOCR_CPU_THREADS", str(min(8, os.cpu_count() or 1)))))
        enable_mkldnn = _env_bool("PADDLEOCR_ENABLE_MKLDNN", platform.system() != "Windows")
        return PaddleOCR(
            text_detection_model_name=DETECTION_MODEL,
            text_recognition_model_name=KOREAN_RECOGNITION_MODEL,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            device="cpu",
            cpu_threads=cpu_threads,
            enable_mkldnn=enable_mkldnn,
            text_rec_score_thresh=0.25,
        )


def _result_payload(result: Any) -> dict[str, Any]:
    payload = result.json
    if callable(payload):
        payload = payload()
    if not isinstance(payload, dict):
        return {}
    nested = payload.get("res", payload)
    return nested if isinstance(nested, dict) else {}


def _useful_line(text: str) -> bool:
    hangul_count = len(re.findall(r"[가-힣]", text))
    exact_value = bool(re.search(r"(?:\d{4}|\d{2,4}[.\-/]\d|@|https?://|\d{2,4}-\d{3,4}-\d{4})", text))
    return hangul_count >= 2 or exact_value


def _recognize(engine: Any, image: Image.Image, *, box_threshold: float) -> tuple[list[str], int]:
    results = engine.predict(
        np.asarray(image),
        text_det_thresh=0.2,
        text_det_box_thresh=box_threshold,
    )
    lines: list[str] = []
    low_confidence = 0
    for result in results:
        payload = _result_payload(result)
        texts = payload.get("rec_texts", [])
        scores = payload.get("rec_scores", [])
        for index, raw_text in enumerate(texts):
            text = re.sub(r"\s+", " ", str(raw_text)).strip()
            if not text or not _useful_line(text):
                continue
            score = float(scores[index]) if index < len(scores) else 0.0
            if score < 0.70:
                low_confidence += 1
            lines.append(text)
    return lines, low_confidence


def extract_korean_text(image_bytes: bytes) -> tuple[str, int]:
    """Run a full-page pass plus a high-resolution footer pass for small contact text."""
    with Image.open(io.BytesIO(image_bytes)) as source:
        original = ImageOps.exif_transpose(source).convert("RGB")

    full_page = original.copy()
    full_page.thumbnail((2400, 2400), Image.Resampling.LANCZOS)

    width, height = original.size
    footer = original.crop((0, int(height * 0.84), width, height))
    footer = ImageOps.autocontrast(footer, cutoff=1)
    footer.thumbnail((2800, 2800), Image.Resampling.LANCZOS)

    engine = get_paddle_engine()
    with _inference_lock:
        full_lines, full_low_confidence = _recognize(engine, full_page, box_threshold=0.35)
        footer_lines, footer_low_confidence = _recognize(engine, footer, box_threshold=0.25)

    seen: set[str] = set()

    def unique(lines: list[str]) -> list[str]:
        result: list[str] = []
        for line in lines:
            key = re.sub(r"\W+", "", line).casefold()
            if key and key not in seen:
                seen.add(key)
                result.append(line)
        return result

    full_lines = unique(full_lines)
    footer_lines = unique(footer_lines)
    sections = []
    if full_lines:
        sections.append("[Full-page OCR]\n" + "\n".join(full_lines))
    if footer_lines:
        sections.append("[Footer detail OCR — may overlap full page]\n" + "\n".join(footer_lines))
    return "\n\n".join(sections), full_low_confidence + footer_low_confidence
