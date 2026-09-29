from __future__ import annotations

from app.models import BoundingBox, ClientOcrPage, OcrSpan
from app.services.ocr_layout import format_ocr_layout


def test_layout_preserves_score_header_alignment_without_photo_data() -> None:
    page = ClientOcrPage(
        text="TOEIC\nTEPS\n800 이상\n309 이상",
        spans=[
            OcrSpan(text="TOEIC", box=BoundingBox(x=0.50, y=0.55, width=0.10, height=0.02)),
            OcrSpan(text="TEPS", box=BoundingBox(x=0.60, y=0.55, width=0.10, height=0.02)),
            OcrSpan(text="800 이상", box=BoundingBox(x=0.50, y=0.58, width=0.10, height=0.02)),
            OcrSpan(text="309 이상", box=BoundingBox(x=0.60, y=0.58, width=0.10, height=0.02)),
        ],
    )

    assert format_ocr_layout([page]) == (
        "[Page 1; x,y are centers on a 0-1000 page grid]\n"
        "(550,560) TOEIC\n"
        "(650,560) TEPS\n"
        "(550,590) 800 이상\n"
        "(650,590) 309 이상"
    )
