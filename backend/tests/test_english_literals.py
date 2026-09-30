from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.models import NoticeData
from app.services.coverage_repair import CoverageRepairError, RepairDetail, RepairResponse, repair_coverage
from app.services.english_literals import missing_english_literals, missing_source_values


@pytest.mark.parametrize(("source", "english", "expected"), [
    ("연구비: 1인당 최대 20만원", "Research funding of up to KRW 200,000 per person.", []),
    ("연구비: 1인당 최대 20만원", "Research funding for AI projects.", ["KRW 200,000"]),
    ("2026년 9월 20일 신청 마감", "Applications close Sept. 20, 2026.", []),
    ("2026년 9월 20일 신청 마감", "Applications close Sept. 21, 2026.", ["2026-09-20"]),
    ("TOEIC 800 이상", "A TOEIC score of at least 800.", []),
    ("TOEIC 800 이상", "An English score of 800.", ["TOEIC"]),
    ("AI Wearable Device 연구", "Research an AI wearable device.", []),
    ("AI Wearable Device 연구", "Research an AI instrument.", ["Wearable", "Device"]),
    ("2~5명의 학부생", "A team of 2 to 5 undergraduates.", []),
])
def test_source_value_guard(source: str, english: str, expected: list[str]) -> None:
    assert missing_source_values(source, english) == expected


def test_preserves_the_posters_exact_mvp_expansion() -> None:
    source = "AI Wearable Device의 AIX 발굴과 MVP(Minimum Value Prototyping)"

    assert missing_english_literals(
        source, "Explore an AI Wearable Device and make an MVP (Minimum Viable Prototyping)."
    ) == ["Minimum Value Prototyping"]
    assert missing_english_literals(
        source, "Explore an AI Wearable Device and make an MVP: Minimum Value Prototyping."
    ) == []


def test_case_spacing_and_punctuation_variants_are_allowed() -> None:
    source = '"AI is Everywhere"의 모토에 맞는 AI 기능 개발'

    assert missing_english_literals(source, "Develop AI features for the AI-is-everywhere motto.") == []
    assert missing_english_literals(source, "Develop AI features for an AI everywhere motto.") == [
        "AI is Everywhere"
    ]


def test_only_multiword_literals_are_checked() -> None:
    assert missing_english_literals("AI 원천기술 연구개발", "Research foundational technology.") == []
    assert missing_english_literals("AI Wearable Device의 연구개발", "Research AI wearable devices.") == []


def test_parenthesized_literal_can_span_adjacent_ocr_lines() -> None:
    source = "MVP(Minimum Value\nPrototyping)의 개발"

    assert missing_english_literals(source, "Develop an MVP through Minimum Viable Prototyping.") == [
        "Minimum Value Prototyping"
    ]
    assert missing_english_literals(source, "Develop an MVP through minimum-value prototyping.") == []


def _repair(source: str, details: list[RepairDetail]):
    parsed = RepairResponse(
        represented_unit_ids=[], details=details, decorative=[], unresolved_unit_ids=[],
    )

    class Responses:
        async def parse(self, **kwargs):
            return SimpleNamespace(output_parsed=parsed, usage=None)

    return asyncio.run(repair_coverage(
        NoticeData(), source, client=SimpleNamespace(responses=Responses()),
    ))


def _detail(ids: list[str], text: str) -> RepairDetail:
    return RepairDetail(unit_ids=ids, text=text, category="research_topic", certain=True)


def test_required_repair_detail_cannot_change_a_literal_english_phrase() -> None:
    source = "MVP(Minimum Value Prototyping)의 개발"

    with pytest.raises(CoverageRepairError, match="literal English source wording"):
        _repair(source, [_detail(["P001-L0001"], "Develop an MVP using Minimum Viable Prototyping.")])

    result = _repair(source, [_detail(["P001-L0001"], "Develop an MVP using Minimum Value Prototyping.")])
    assert result.notice.key_details[0].text.endswith("Minimum Value Prototyping.")


def test_split_ocr_literal_is_checked_against_final_digest() -> None:
    source = "MVP(Minimum Value\nPrototyping)의 개발"
    separate_details = [
        _detail(["P001-L0001"], "Develop an MVP through Minimum Viable research."),
        _detail(["P001-L0002"], "Build a prototype."),
    ]

    with pytest.raises(CoverageRepairError, match="Page 1 still alters or omits literal English"):
        _repair(source, separate_details)

    result = _repair(source, [_detail(
        ["P001-L0001", "P001-L0002"],
        "Develop an MVP (Minimum Value Prototyping).",
    )])
    assert result.repaired_unit_count == 2
