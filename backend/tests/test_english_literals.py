from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.models import NoticeData
from app.services.coverage_repair import CoverageProviderError, RepairDetail, RepairResponse, repair_coverage
from app.services.english_literals import missing_english_literals, missing_source_conditions, missing_source_values


@pytest.mark.parametrize("wording", ["receiving research supervision", "receiving research guidance"])
def test_source_supervision_condition_cannot_be_reduced_to_course_enrollment(wording: str) -> None:
    source = "연구 관련 과목을 수강하며 연구지도를 받는 학부생"
    assert missing_source_conditions(source, "Undergraduate students taking research courses.") == [
        "receiving research supervision"
    ]
    assert missing_source_conditions(source, f"Undergraduate students taking research courses and {wording}.") == []


@pytest.mark.parametrize(("source", "english", "expected"), [
    ("연구비: 1인당 최대 20만원", "Research funding of up to KRW 200,000 per person.", []),
    ("연구비: 1인당 최대 20만원", "Research funding for AI projects.", ["KRW 200,000"]),
    ("2026년 9월 20일 신청 마감", "Applications close Sept. 20, 2026.", []),
    ("2026년 9월 20일 신청 마감", "Applications close Sept. 21, 2026.", ["2026-09-20"]),
    ("신청 기간: 2026.08.24(월) ~ 2026.09.20(일)", "Application Period: 2026.08.24 (Monday) ~ 2026.09.20 (Sunday)", []),
    ("신청 기간: 2026.08.24(월) ~ 2026.09.20(일)", "Application Period: 2027.08.24 (Monday) ~ 2027.09.20 (Sunday)", ["2026-08-24", "2026-09-20"]),
    ("TOEIC 800 이상", "A TOEIC score of at least 800.", []),
    ("TOEIC 800 이상", "An English score of 800.", ["TOEIC"]),
    ("AI Wearable Device 연구", "Research an AI wearable device.", []),
    ("AI Wearable Device 연구", "Research an AI instrument.", ["Wearable", "Device"]),
    ("2~5명의 학부생", "A team of 2 to 5 undergraduates.", []),
    ("문의 02.710.2500", "Call 02-710-2500.", []),
    ("문의 02.710.2500", "Call 02-710-2501.", ["phone 02.710.2500"]),
    ("문의 convedu@sogang.ac.kr", "Email convedu@sogang.ac.kr.", []),
    ("문의 convedu@sogang.ac.kr", "Contact the team.", ["email convedu@sogang.ac.kr"]),
])
def test_source_value_guard(source: str, english: str, expected: list[str]) -> None:
    assert missing_source_values(source, english) == expected


@pytest.mark.parametrize(("source", "english", "expected"), [
    ("교내 타 프로그램에서 동일하거나 유사한 연구 주제로 지원을 받는 학생 및 팀은 참여 제한",
     "Students supported for similar topics in other programs are restricted from participation.",
     ["on-campus scope", "same topic"]),
    ("교내 타 프로그램에서 동일하거나 유사한 연구 주제로 지원을 받는 학생 및 팀은 참여 제한",
     "Students supported for the same or similar research topic by other on-campus programs are restricted from participation.", []),
    ("교내 타 프로그램에서 동일하거나 유사한 연구 주제로 지원을 받는 학생 및 팀은 참여 제한",
     "Students and teams with the same or similar research topics in other on-campus programs are restricted from participation.",
     ["receiving support qualification"]),
    ("연구 주제로 지원을 받는 학생 및 팀은 참여 제한",
     "Students and teams with these research topics are restricted. Research funding is available.",
     ["receiving support qualification"]),
    ("연구 주제로 지원을 받는 학생 및 팀은 참여 제한",
     "Students and teams receiving financial support for these research topics are restricted.", []),
    ("연구 주제로 지원을 받는 학생 및 팀은 참여 제한",
     "Students and teams that obtain research funding for these topics are restricted.", []),
    ("연구 주제로 지원을 받는 학생 및 팀은 참여 제한",
     "Students and teams funded for these research topics are restricted.", []),
    ("연구 주제로 참가하는 학생 및 팀은 참여 제한",
     "Students and teams with these research topics are restricted.", []),
    ("연구비: 1인당 최대 20만원", "Research funding: KRW 200,000 per team.", ["maximum limit", "per-person amount"]),
    ("연구비: 1인당 최대 20만원", "Research funding: up to KRW 200,000 for each participant.", []),
    ("장학금 형태로 지급", "Paid as an allowance.", ["scholarship payment"]),
    ("장학금 형태로 지급", "Paid as a scholarship.", []),
    ("프로그램 내 중복 참여 불허", "Duplicate participation is possible.", ["not allowed"]),
    ("프로그램 내 중복 참여 불허", "No duplicate participation is permitted.", []),
    ("활동비 지원 대상에서는 제외", "Eligible for activity support.", ["exclusion from support"]),
    ("활동비 지원 대상에서는 제외", "Not eligible for activity support.", []),
])
def test_narrow_conditions_guard(source: str, english: str, expected: list[str]) -> None:
    assert missing_source_conditions(source, english) == expected


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

    with pytest.raises(CoverageProviderError, match="literal English source wording"):
        _repair(source, [_detail(["P001-L0001"], "Develop an MVP using Minimum Viable Prototyping.")])

    result = _repair(source, [_detail(["P001-L0001"], "Develop an MVP using Minimum Value Prototyping.")])
    assert result.notice.key_details[0].text.endswith("Minimum Value Prototyping.")


def test_split_ocr_literal_is_checked_against_final_digest() -> None:
    source = "MVP(Minimum Value\nPrototyping)의 개발"
    separate_details = [
        _detail(["P001-L0001"], "Develop an MVP through Minimum Viable research."),
        _detail(["P001-L0002"], "Build a prototype."),
    ]

    with pytest.raises(CoverageProviderError, match="Page 1 still alters or omits literal English"):
        _repair(source, separate_details)

    result = _repair(source, [_detail(
        ["P001-L0001", "P001-L0002"],
        "Develop an MVP (Minimum Value Prototyping).",
    )])
    assert result.repaired_unit_count == 2
