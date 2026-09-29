from __future__ import annotations

from app.models import ClientOcrPage


def format_ocr_layout(pages: list[ClientOcrPage]) -> str:
    """Give the semantic step OCR positions without sending photo pixels."""
    formatted: list[str] = []
    for page_number, page in enumerate(pages, start=1):
        if not page.spans:
            continue
        formatted.append(f"[Page {page_number}; x,y are centers on a 0-1000 page grid]")
        for span in page.spans:
            center_x = round((span.box.x + span.box.width / 2) * 1000)
            center_y = round((span.box.y + span.box.height / 2) * 1000)
            formatted.append(f"({center_x:03d},{center_y:03d}) {span.text}")
    return "\n".join(formatted)
