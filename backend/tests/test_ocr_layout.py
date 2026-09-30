from __future__ import annotations

import asyncio
import json
from collections import Counter
from pathlib import Path

import pytest
from pytest import MonkeyPatch

from app import main
from app.models import BoundingBox, ClientOcrPage, ClientOcrRequest, OcrSpan
from app.services.ocr_layout import format_ocr_layout, reorder_ocr_page_columns


FIXTURE = Path(__file__).parent / "fixtures" / "sogang_research_2026_browser_ocr.json"


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


def _poster_page() -> ClientOcrPage:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    width = fixture["image"]["width"]
    height = fixture["image"]["height"]
    spans = []
    for item in fixture["items"]:
        left, top, right, bottom = item["box"]
        spans.append(OcrSpan.model_validate({
            "text": item["text"],
            "box": {
                "x": left / width,
                "y": top / height,
                "width": (right - left) / width,
                "height": (bottom - top) / height,
            },
        }))
    return ClientOcrPage(text="\n".join(item["text"] for item in fixture["items"]), spans=spans)


def test_poster_columns_are_read_as_sections_without_losing_lines() -> None:
    page = _poster_page()

    ordered = reorder_ocr_page_columns(page)
    lines = [line for line in ordered.text.splitlines() if line.strip()]

    assert Counter(lines) == Counter(page.text.splitlines())
    assert len(ordered.spans) == len(page.spans) == 47
    assert lines.index("비교과통합관리시스템(S Pus)로 제출") < lines.index("모집 대상")
    assert lines.index("모집 대상") < lines.index("지원 금액") < lines.index("연구 주제")
    assert lines.index("장학금 형태로 지급") < lines.index("1.융합교육원 제시 주제(지정 주제)")
    assert lines.index("2.학생 자율 선정 주제") < lines.index("문의:융합교육혁신팀(02.710.25n0 |convedu@sogang.ac.kr)")
    assert [span.text for span in ordered.spans] == lines
    assert "\n\n연구 주제" in ordered.text
    layout_lines = format_ocr_layout([ordered]).splitlines()
    assert next(i for i, line in enumerate(layout_lines) if line.endswith(" 지원 금액")) < next(
        i for i, line in enumerate(layout_lines) if line.endswith(" 연구 주제")
    )


def test_missing_positions_do_not_change_ocr_order() -> None:
    page = _poster_page()
    partial = ClientOcrPage(text=page.text, spans=page.spans[:-1])

    assert reorder_ocr_page_columns(partial) is partial


def test_short_two_column_table_is_left_in_row_order() -> None:
    spans = [
        OcrSpan.model_validate({"text": text, "box": {"x": x, "y": y, "width": 0.1, "height": 0.02}})
        for text, x, y in (
            ("Qualifications", 0.2, 0.1),
            ("A", 0.2, 0.3), ("1", 0.7, 0.3),
            ("B", 0.2, 0.5), ("2", 0.7, 0.5),
            ("C", 0.2, 0.7), ("3", 0.7, 0.7),
        )
    ]
    page = ClientOcrPage(text="\n".join(span.text for span in spans), spans=spans)

    assert reorder_ocr_page_columns(page) is page


def test_client_ocr_sends_column_order_to_translation(monkeypatch: MonkeyPatch) -> None:
    page = _poster_page()
    observed: dict[str, str] = {}

    async def capture(request, *, layout_context):
        observed["text"] = request.text
        observed["layout"] = layout_context
        raise RuntimeError("captured")

    monkeypatch.setattr(main, "_run_text_pipeline", capture)
    request = ClientOcrRequest(pages=[page], target_language="en", provider="openai", ocr_latency_ms=0)

    with pytest.raises(RuntimeError, match="captured"):
        asyncio.run(main.analyze_client_ocr(request))

    source_lines = observed["text"].splitlines()
    assert source_lines.index("지원 금액") < source_lines.index("연구 주제")
    layout_lines = observed["layout"].splitlines()
    assert next(i for i, line in enumerate(layout_lines) if line.endswith(" 지원 금액")) < next(
        i for i, line in enumerate(layout_lines) if line.endswith(" 연구 주제")
    )
