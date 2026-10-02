from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.models import Deadline, LabeledFact, NoticeData
from app.services.coverage_repair import CoverageProviderError, RepairDetail, RepairResponse, repair_coverage
from app.services.english_literals import missing_english_literals, missing_source_conditions, missing_source_values, missing_spending_rules, unsupported_currency_amounts, unsupported_source_dates
from app.services.text import simplified_text


@pytest.mark.parametrize("source", ["행정실에 방문하여 카드결제", "교육원 방문 후 카드 결제 진행"])
def test_prescribed_payment_procedure_cannot_be_softened_to_optional(source):
    assert "prescribed in-person card-payment procedure" in missing_spending_rules(
        source, "Participants can visit the office and pay by card.",
    )
    assert missing_spending_rules(source, "Visit the office and pay by card.") == []


def test_source_optional_card_procedure_remains_optional():
    assert missing_spending_rules("교육원 방문 후 카드 결제 가능", "Participants may visit and pay by card.") == []


@pytest.mark.parametrize("english", ["Win KRW 5,000.", "Win 5,000 won.", "Win 5,000 KRW."])
def test_amount_elsewhere_cannot_be_invented_from_a_heading_quote(english):
    assert unsupported_currency_amounts("만족도 조사", english) == ["KRW 5,000"]
    assert unsupported_currency_amounts("상품권 5천원 증정", english) == []


def test_quoted_currency_amount_preserves_decimal_and_large_korean_units():
    assert unsupported_currency_amounts("예산 1.5억원", "Budget: KRW 150,000,000.") == []
    assert unsupported_currency_amounts("지원금 KRW 20,000", "Funding: 20,000 won.") == []


@pytest.mark.parametrize(("english", "expected"), [
    ("Deadline: 2029-10-15.", ["2029-10-15"]),
    ("Applications close October 15, 2029 at 18:00.", ["2029-10-15"]),
    ("Apply by 15th of October 2029.", ["2029-10-15"]),
    ("Applications close October 17, 2028.", ["2028-10-17"]),
    ("Deadline: 10/15.", ["10-15"]),
    ("Deadline: 2029-10-17 at 18:00.", []),
    ("Applications close Oct. 17, 2029 at 18:00.", []),
    ("Applications close 17 October 2029 at 18:00.", []),
    ("Apply by October 17.", []),
    ("Application instructions are provided below.", []),
])
def test_explicit_english_calendar_dates_must_match_the_field_quote(english, expected):
    assert unsupported_source_dates("접수 마감: 2029.10.17 18:00", english) == expected


@pytest.mark.parametrize("english", [
    "Applications open on November 3, 2029.",
    "Applications close on November 28, 2029.",
    "Opening date: 2029-11-03.",
    "Closing date: 2029-11-28.",
    "Apply November 3 through November 28, 2029.",
])
def test_valid_single_range_endpoint_is_not_a_date_contradiction(english):
    assert unsupported_source_dates("접수기간: 2029.11.03(토)~11.28(수)18:00", english) == []


@pytest.mark.parametrize("source", ["접수 마감: 10.17", "10.17(수)", "10월 17일 마감"])
def test_abbreviated_source_date_allows_an_english_year_from_context(source):
    assert unsupported_source_dates(source, "Applications close October 17, 2029.") == []
    assert unsupported_source_dates(source, "Applications close Oct. 15, 2029.") == ["2029-10-15"]


@pytest.mark.parametrize("source", [
    "Deadline: October 17, 2029.", "Deadline: 2029-10/17.", "Deadline: 2029/10/17.",
])
def test_calendar_context_cannot_weaken_an_explicit_source_year(source):
    assert unsupported_source_dates(source, "Deadline: October 17, 2028.") == ["2028-10-17"]
    assert unsupported_source_dates(source, "Deadline: October 17, 2029.") == []


@pytest.mark.parametrize("source", [
    "접수 마감 2029.10.17\nPython 3.12 지원",
    "접수 마감 2029.10.17 Python 3.12 지원",
    "Python 3.12 지원; 접수 마감 2029.10.17",
])
@pytest.mark.parametrize("english", [
    "Deadline: October 17, 2029. Python 3.12 is supported.",
    "Python 3.12 is supported; deadline: October 17, 2029.",
    "Deadline: 10/17. Python versions 3.12 through 3.13 are supported.",
])
def test_calendar_context_does_not_spread_to_software_decimals(source, english):
    assert unsupported_source_dates(source, english) == []


@pytest.mark.parametrize("source", [
    "접수 마감 2029.10.17 Python 3.12 지원",
    "면접 10.17(수) Python 3.12 지원",
])
def test_software_decimal_near_a_source_date_cannot_support_a_changed_deadline(source):
    assert unsupported_source_dates(source, "Deadline: March 12, 2029.") == ["2029-03-12"]
    assert unsupported_source_dates(source, "Deadline: 3/12.") == ["03-12"]


@pytest.mark.parametrize(("source", "english"), [
    ("접수 마감 2029.10.17 Python 3.12 지원", "Deadline: October 17, 2029. Python 3.12 is supported."),
    ("면접 10.17(수) Python 3.12 지원", "Interview: October 17. Python 3.12 is supported."),
    ("3.02~3.24(화) Python 3.12 지원", "March 2 through March 24. Python 3.12 is supported."),
    ("접수기간 2029.10.17~10.20 Python 3.12 지원", "Applications: October 17 through October 20, 2029."),
])
def test_source_value_guard_does_not_require_software_decimals_as_extra_dates(source, english):
    assert missing_source_values(source, english) == []


@pytest.mark.parametrize("english", [
    "Dates: 10/17 through 10/20. Python 3.12 is supported.",
    "Date range: 2029-10-17~10/20. Python 3.12 is supported.",
    "October 17, 2029–10/20. Python 3.12 is supported.",
    "Dates: 10/17-10/20. Python 3.12 is supported.",
])
def test_explicit_range_links_preserve_abbreviated_endpoints_with_other_decimal_values(english):
    source = "접수기간 2029.10.17~2029.10.20 Python 3.12 지원"
    assert unsupported_source_dates(source, english) == []
    assert unsupported_source_dates(source, english.replace("10/20", "10/21")) == ["10-21"]


@pytest.mark.parametrize("english", ["September 20, 2029.", "Sep. 20, 2029.", "Sept. 20, 2029."])
def test_spelled_month_and_its_common_abbreviations_are_equivalent(english):
    assert unsupported_source_dates("2029년 9월 20일 신청 마감", english) == []


@pytest.mark.parametrize(("source", "english"), [
    ("제품 가격: 3.20만원", "The product costs KRW 32,000 on October 15, 2029."),
    ("프로그램 버전 3.20~3.25", "Release date: March 22."),
    ("연구 값 9.30", "Results published September 29, 2029."),
    ("신청 마감", "Deadline: 2029-10-15."),
    ("2029.10.17 신청 마감", "Software version 3.20 is supported."),
    ("2029.10.17 신청 마감", "Applicants must obtain a rating of 3.20."),
])
def test_date_contradiction_guard_requires_actual_calendar_evidence(source, english):
    assert unsupported_source_dates(source, english) == []


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
    ("접수기간: 2029.11.03(토)~11.28(수)18:00", "Applications close on November 3, 2029 at 18:00.", ["11-28"]),
    ("접수기간: 2029.11.03(토)~11.28(수)18:00", "Apply from November 3 through November 28, 2029, closing at 18:00.", []),
    ("3.02(월)~3.24(화)", "Applications open on March 2.", ["03-24"]),
    ("3.02(월)~3.24(화)", "March 2 through March 24.", []),
    ("4/05 ~ 4/22", "April 5 through April 22.", []),
    ("4/05 ~ 4/22", "April 5.", ["04-22"]),
    ("면접 11.20(금)", "The interview is November 21.", ["11-20"]),
    ("납부 마감: 4.15", "Payment closes April 16.", ["04-15"]),
    ("제품 가격: 3.20만원", "The product costs KRW 32,000.", []),
    ("프로그램 버전 3.20~3.25", "Software versions are listed.", []),
    ("연구 값 9.30", "Research values are listed.", []),
])
def test_abbreviated_dates_preserve_each_endpoint_without_inventing_calendar_context(
    source: str, english: str, expected: list[str],
) -> None:
    assert missing_source_values(source, english) == expected


@pytest.mark.parametrize("allow_partial", [False, True])
def test_audited_abbreviated_range_supersedes_a_primary_that_ends_at_the_start_date(allow_partial: bool) -> None:
    source = "접수기간: 2029.11.03(토)~11.28(수)18:00"
    notice = NoticeData(deadlines=[Deadline(
        date="2029-11-03", time="18:00", description="Application period ends.",
        source_evidence=source, source_page=1,
    )])
    correct = "Apply from November 3 through November 28, 2029, closing at 18:00."
    parsed = RepairResponse(
        represented_unit_ids=[], details=[RepairDetail(
            unit_ids=["P001-L0001"], text=correct, category="schedule", certain=True,
        )], decorative=[], unresolved_unit_ids=[],
    )

    class Responses:
        async def parse(self, **kwargs):
            return SimpleNamespace(output_parsed=parsed, usage=None)

    result = asyncio.run(repair_coverage(
        notice, source, client=SimpleNamespace(responses=Responses()), allow_partial=allow_partial,
    ))

    assert result.notice.deadlines == []
    assert correct in simplified_text(result.notice)
    assert "Application period ends." not in simplified_text(result.notice)
    assert result.has_verification_gaps is False


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
    ("프로그램 내 중복 참여 불허", "Duplicate participation is possible.", ["duplicate participation within the same program", "not allowed"]),
    ("프로그램 내 중복 참여 불허", "No duplicate participation within this program is permitted.", []),
    ("프로그램 내 중복참여 불허", "Participation in multiple programs is not allowed.", ["duplicate participation within the same program"]),
    ("이 프로그램 내 중복 신청 불허", "Duplicate applications for this program are not permitted.", []),
    ("활동비 지원 대상에서는 제외", "Eligible for activity support.", ["exclusion from support"]),
    ("활동비 지원 대상에서는 제외", "Not eligible for activity support.", []),
])
def test_narrow_conditions_guard(source: str, english: str, expected: list[str]) -> None:
    assert missing_source_conditions(source, english) == expected


@pytest.mark.parametrize(("source", "incomplete", "complete", "order"), [
    (
        "보조금은 2차에 걸쳐 지급하며 확인서를 제출한 사람에 한하여 2차 보조금 지급",
        "The subsidy is paid in two installments, contingent on filing confirmation.",
        "The subsidy is paid in two installments; only people filing confirmation receive the second installment.",
        2,
    ),
    (
        "1차 장학금 15만원, 2차 장학금 25만원은 승인 후 지급",
        "Scholarship payments of KRW 150,000 and KRW 250,000 require approval.",
        "The first scholarship payment is KRW 150,000; the second payment of KRW 250,000 is paid after approval.",
        2,
    ),
    (
        "자료 검증 후 3회차 지급",
        "Three payments are made following document verification.",
        "Payment number 3 is made after document verification.",
        3,
    ),
    (
        "1번째 지급은 신청서를 확인한 경우에만 가능",
        "All payments require application verification.",
        "The 1st disbursement is made only after verifying the application.",
        1,
    ),
])
def test_payment_prerequisite_retains_its_specific_installment(
    source: str, incomplete: str, complete: str, order: int,
) -> None:
    assert missing_source_conditions(source, incomplete) == [f"condition applying to installment {order}"]
    assert missing_source_conditions(source, complete) == []


@pytest.mark.parametrize("source", [
    "보조금은 3차에 걸쳐 지급", "2차 지원금 지급 조건 없음", "확인서를 제출한 경우에만 참여 가능",
])
def test_payment_scope_guard_does_not_create_an_installment_condition(source: str) -> None:
    assert missing_source_conditions(source, "The notice describes its support.") == []


@pytest.mark.parametrize("allow_partial", [False, True])
def test_complete_specific_installment_repair_removes_a_primary_conditioning_every_payment(allow_partial: bool) -> None:
    source = "보조금은 3차에 걸쳐 지급하며 주소를 검증한 경우에만 3차 보조금 지급"
    incomplete = "The housing subsidy is paid in three installments after address verification."
    complete = "The subsidy is paid in three installments; only the third installment requires address verification."
    notice = NoticeData(financial_support=[LabeledFact(
        text=incomplete, source_evidence=source, source_page=1,
    )])
    parsed = RepairResponse(
        represented_unit_ids=[], details=[RepairDetail(
            unit_ids=["P001-L0001"], text=complete, category="funding", certain=True,
        )], decorative=[], unresolved_unit_ids=[],
    )

    class Responses:
        async def parse(self, **kwargs):
            return SimpleNamespace(output_parsed=parsed, usage=None)

    result = asyncio.run(repair_coverage(
        notice, source, client=SimpleNamespace(responses=Responses()), allow_partial=allow_partial,
    ))

    assert [item.text for item in result.notice.financial_support] == [complete]
    assert incomplete not in simplified_text(result.notice)
    assert result.has_verification_gaps is False


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


def test_split_parenthetical_source_requires_a_complete_group() -> None:
    source = "MVP(Minimum Value\nPrototyping)의 개발"
    separate_details = [
        _detail(["P001-L0001"], "Develop an MVP through Minimum Viable research."),
        _detail(["P001-L0002"], "Build a prototype."),
    ]

    with pytest.raises(CoverageProviderError, match="open source parenthetical"):
        _repair(source, separate_details)

    result = _repair(source, [_detail(
        ["P001-L0001", "P001-L0002"],
        "Develop an MVP (Minimum Value Prototyping).",
    )])
    assert result.repaired_unit_count == 2


def test_split_quoted_literal_is_checked_against_final_digest() -> None:
    source = '"Safety\nFirst" 교육'
    separate_details = [
        _detail(["P001-L0001"], "Safety training."),
        _detail(["P001-L0002"], "Priority guidance."),
    ]

    with pytest.raises(CoverageProviderError, match="Page 1 still alters or omits literal English"):
        _repair(source, separate_details)

    result = _repair(source, [_detail(
        ["P001-L0001", "P001-L0002"], 'Attend "Safety First" training.',
    )])
    assert result.repaired_unit_count == 2
