from __future__ import annotations

import io
import os
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageEnhance, ImageFilter, ImageOps, UnidentifiedImageError

from app.models import SourcePage
from app.services.images.models import PreparedImage
from app.services.images.qr import detect_qr_codes
from app.services.images.quality import inspect_quality

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:  # Optional at runtime; the upload error explains unsupported HEIC.
    pass


class ImageProcessingError(ValueError):
    pass


def upload_root() -> Path:
    if os.getenv("VERCEL") == "1":
        path = Path("/tmp/visnotice-v2") / "uploads"
    else:
        path = Path(__file__).resolve().parents[4] / "data" / "uploads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_suffix(filename: str, media_type: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}:
        return suffix
    return {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/heic": ".heic", "image/heif": ".heif"}.get(media_type, ".bin")


def prepare_image(data: bytes, filename: str, media_type: str, analysis_id: str, page_number: int) -> PreparedImage:
    try:
        with Image.open(io.BytesIO(data)) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ImageProcessingError(f"{filename} is not a readable image.") from exc

    if image.width < 40 or image.height < 40:
        raise ImageProcessingError(f"{filename} is too small to process.")

    issues = inspect_quality(image)
    qr_codes = detect_qr_codes(image, page_number)
    original_width, original_height = image.size

    processed = image.copy()
    processed.thumbnail((2400, 2400), Image.Resampling.LANCZOS)
    processed = ImageOps.autocontrast(processed, cutoff=1)
    processed = ImageEnhance.Contrast(processed).enhance(1.06)
    processed = processed.filter(ImageFilter.UnsharpMask(radius=1.1, percent=65, threshold=3))

    processed_buffer = io.BytesIO()
    processed.save(processed_buffer, format="JPEG", quality=90, optimize=True)
    processed_bytes = processed_buffer.getvalue()
    page_id = f"page-{page_number:03d}-{uuid4().hex[:8]}"
    directory = upload_root() / analysis_id
    directory.mkdir(parents=True, exist_ok=True)
    original_name = f"{page_id}-original{_safe_suffix(filename, media_type)}"
    processed_name = f"{page_id}-processed.jpg"
    (directory / original_name).write_bytes(data)
    (directory / processed_name).write_bytes(processed_bytes)

    page = SourcePage(
        id=page_id,
        page_number=page_number,
        filename=filename,
        media_type=media_type,
        original_url=f"/uploads/{analysis_id}/{original_name}",
        processed_url=f"/uploads/{analysis_id}/{processed_name}",
        width=original_width,
        height=original_height,
        readable=not any(issue.severity == "blocking" for issue in issues),
        quality_issues=issues,
        qr_codes=qr_codes,
    )
    return PreparedImage(page=page, original_bytes=data, processed_bytes=processed_bytes)
