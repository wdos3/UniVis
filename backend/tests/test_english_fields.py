from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.models import Action, Contact, Deadline, LabeledFact, NoticeData, ReviewState, SourceFact
from app.services.semantic import OpenAISemanticProvider, SemanticError, normalize_notice, repair_english_fields
from app.services.text import appears_korean


def test_semantic_provider_repairs_korean_display_fields_without_changing_evidence() -> None:
    original = NoticeData(
        target_language="ko",  # Model output must not override the caller's English request.
        title="창의융합 자유연구 참가자 모집",
        summary="학부생 연구 참여 안내",
        audience=[LabeledFact(text="2026학년도 2학기 학부 재학생", source_evidence="2026학년도 2학기 학부 재학생")],
        actions=[Action(step=1, action="지원서 제출", required_items=["연구계획서"], source_evidence="지원서, 연구계획서 제출")],
        source_facts=[SourceFact(id="F001", kind="eligibility", source_text="2026학년도 2학기 학부 재학생")],
    )
    replacements = {
        "창의융합 자유연구 참가자 모집": "Creative Convergence Independent Research Recruitment",
        "학부생 연구 참여 안내": "Undergraduate research participation notice",
        "2026학년도 2학기 학부 재학생": "Undergraduates enrolled in the second semester of academic year 2026",
        "지원서 제출": "Submit the application form",
        "연구계획서": "Research plan",
    }

    class FakeResponses:
        def __init__(self) -> None:
            self.calls = 0

        async def parse(self, *, text_format, input, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return SimpleNamespace(output_parsed=original, usage=SimpleNamespace(input_tokens=100, output_tokens=200, total_tokens=300))
            import json

            payload = json.loads(input[1]["content"])
            repairs = [{"id": item["id"], "english": replacements[item["text"]]} for item in payload]
            return SimpleNamespace(
                output_parsed=text_format.model_validate({"repairs": repairs}),
                usage=SimpleNamespace(input_tokens=20, output_tokens=30, total_tokens=50),
            )

    responses = FakeResponses()
    result = asyncio.run(OpenAISemanticProvider(client=SimpleNamespace(responses=responses)).analyze("지원 안내", "Apply", "en"))

    assert responses.calls == 2
    assert result.requests == 2
    assert result.notice.target_language == "en"
    assert (result.input_tokens, result.output_tokens, result.total_tokens) == (120, 230, 350)
    assert result.notice.audience[0].text == replacements["2026학년도 2학기 학부 재학생"]
    assert result.notice.actions[0].required_items == ["Research plan"]
    assert result.notice.audience[0].state == ReviewState.NEEDS_REVIEW
    assert result.notice.audience[0].source_evidence == "2026학년도 2학기 학부 재학생"
    assert result.notice.source_facts[0].source_text == "2026학년도 2학기 학부 재학생"
    assert not any(appears_korean(item) for item in result.notice.unverified_items)


def test_english_repair_rejects_partial_or_untranslated_model_result() -> None:
    notice = NoticeData(title="연구 참가자 모집", summary="지원 안내")

    class FakeResponses:
        async def parse(self, *, text_format, input, **kwargs):
            return SimpleNamespace(output_parsed=text_format.model_validate({
                "repairs": [{"id": "T001", "english": "Research recruitment"}],
            }))

    with pytest.raises(SemanticError, match="incomplete English summary"):
        asyncio.run(repair_english_fields(notice, SimpleNamespace(responses=FakeResponses()), "gpt-4o-mini"))
    assert notice.title == "연구 참가자 모집"
    assert notice.summary == "지원 안내"


def test_english_repair_makes_no_api_call_when_output_is_already_english() -> None:
    notice = NoticeData(title="Undergraduate research notice")

    class FailingResponses:
        async def parse(self, **kwargs):
            raise AssertionError("No repair request should be needed")

    metrics = asyncio.run(repair_english_fields(notice, SimpleNamespace(responses=FailingResponses()), "gpt-4o-mini"))
    assert metrics.requests == 0


def test_english_repair_includes_fact_labels_and_financial_support() -> None:
    notice = NoticeData(financial_support=[LabeledFact(
        label="지원 금액", text="연구비: 1인당 최대 20만원", source_evidence="연구비: 1인당 최대 20만원",
    )])

    class FakeResponses:
        async def parse(self, *, text_format, input, **kwargs):
            import json

            payload = json.loads(input[1]["content"])
            translations = {
                "지원 금액": "Support amount",
                "연구비: 1인당 최대 20만원": "Research funding: up to KRW 200,000 per person",
            }
            return SimpleNamespace(output_parsed=text_format.model_validate({
                "repairs": [{"id": item["id"], "english": translations[item["text"]]} for item in payload],
            }))

    metrics = asyncio.run(repair_english_fields(notice, SimpleNamespace(responses=FakeResponses()), "gpt-4o-mini"))
    assert metrics.requests == 1
    assert notice.financial_support[0].label == "Support amount"
    assert notice.financial_support[0].text == "Research funding: up to KRW 200,000 per person"
    assert notice.financial_support[0].source_evidence == "연구비: 1인당 최대 20만원"


def test_semantic_cleanup_separates_awards_from_payments_owed() -> None:
    notice = NoticeData(fees=[
        LabeledFact(text="Research fee: up to KRW 200,000 per person", source_evidence="연구비: 1인당 최대 20만원"),
        LabeledFact(text="Activity fee: KRW 200,000 per person", source_evidence="활동비: 1인당 20만원"),
        LabeledFact(text="Application fee: KRW 20,000", source_evidence="참가비 2만원 납부"),
    ])

    normalized = normalize_notice(notice)

    assert [item.text for item in normalized.financial_support] == [
        "Research funding: up to KRW 200,000 per person",
        "Activity allowance: KRW 200,000 per person",
    ]
    assert [item.text for item in normalized.fees] == ["Application fee: KRW 20,000"]


def test_research_grant_remains_support_when_evidence_also_mentions_card_payment() -> None:
    notice = NoticeData(fees=[LabeledFact(
        text="Research fee: up to KRW 200,000 per person",
        source_evidence="연구비: 1인당 최대 20만원\n융합교육원에 방문하여 카드결제",
    )])

    normalized = normalize_notice(notice)

    assert normalized.fees == []
    assert normalized.financial_support[0].text == "Research funding: up to KRW 200,000 per person"


def test_combined_research_and_activity_grants_are_not_labeled_as_fees() -> None:
    notice = NoticeData(fees=[LabeledFact(
        text="Research fee: KRW 200,000; Activity fee: KRW 200,000",
        source_evidence="연구비 1인당 20만원; 활동비 1인당 20만원",
    )])

    normalized = normalize_notice(notice)

    assert normalized.fees == []
    assert normalized.financial_support[0].text == (
        "Research funding: KRW 200,000; Activity allowance: KRW 200,000"
    )


def test_ocr_damaged_phone_is_not_presented_as_a_valid_contact_number() -> None:
    notice = NoticeData(contacts=[Contact(
        name="Convergence Education Innovation Team",
        phone="02.710.25n0",
        source_evidence="문의:융합교육혁신팀(02.710.25n0 |convedu@sogang.ac.kr)",
    )])

    normalized = normalize_notice(notice)

    assert normalized.contacts[0].phone == ""
    assert "Phone number does not match the cited source text" in normalized.contacts[0].details
    assert normalized.contacts[0].state == ReviewState.NEEDS_REVIEW


def test_guessed_phone_is_cleared_when_ocr_digits_are_damaged() -> None:
    notice = NoticeData(contacts=[Contact(
        phone="02-710-2500",
        source_evidence="문의: 융합교육혁신팀(02.710.25n0 | convedu@sogang.ac.kr)",
    )])

    contact = normalize_notice(notice).contacts[0]

    assert contact.phone == ""
    assert contact.state == ReviewState.NEEDS_REVIEW
    assert "02-710-2500" not in contact.details


def test_phone_separator_change_preserves_supported_source_number() -> None:
    notice = NoticeData(contacts=[Contact(
        phone="02-710-2500",
        source_evidence="문의: 융합교육혁신팀(02.710.2500 | convedu@sogang.ac.kr)",
    )])

    contact = normalize_notice(notice).contacts[0]

    assert contact.phone == "02-710-2500"
    assert contact.state == ReviewState.VERIFIED
    assert contact.details == ""


def test_invented_deadline_time_is_cleared_without_changing_date() -> None:
    notice = NoticeData(deadlines=[Deadline(
        date="2026.09.20", time="23:59", description="Application deadline",
        source_evidence="신청 기간 | 2026.08.24(월) ~ 2026.09.20(일)",
    )])

    deadline = normalize_notice(notice).deadlines[0]

    assert deadline.date == "2026.09.20"
    assert deadline.time == ""
    assert deadline.state == ReviewState.NEEDS_REVIEW


@pytest.mark.parametrize(
    ("source_evidence", "output_time"),
    [
        ("접수기간 2026.09.30(수) 18:00", "18:00"),
        ("접수기간 2026.09.30(수) 18:00", "6:00 PM"),
        ("접수기간 2026.09.30(수) 오후 6시", "18:00"),
    ],
)
def test_deadline_time_remains_when_explicitly_supported(source_evidence: str, output_time: str) -> None:
    notice = NoticeData(deadlines=[Deadline(
        date="2026.09.30", time=output_time, source_evidence=source_evidence,
    )])

    deadline = normalize_notice(notice).deadlines[0]

    assert deadline.time == output_time
    assert deadline.state == ReviewState.VERIFIED


def test_single_korean_word_in_long_english_field_is_repaired() -> None:
    mixed = "Undergraduate students may apply and receive research support; 휴학생 are excluded from payment."
    notice = NoticeData(key_details=[LabeledFact(text=mixed, source_evidence="휴학생은 지원 대상 제외")])

    class FakeResponses:
        async def parse(self, *, text_format, input, **kwargs):
            import json

            payload = json.loads(input[1]["content"])
            assert [item["text"] for item in payload] == [mixed]
            return SimpleNamespace(output_parsed=text_format.model_validate({"repairs": [{
                "id": payload[0]["id"],
                "english": "Undergraduate students may apply and receive research support; students on leave are excluded from payment.",
            }]}))

    normalized = normalize_notice(notice)
    assert normalized.key_details[0].state == ReviewState.NEEDS_REVIEW
    asyncio.run(repair_english_fields(notice, SimpleNamespace(responses=FakeResponses()), "gpt-4o-mini"))
    assert "students on leave" in notice.key_details[0].text


def test_english_repair_rejects_even_one_remaining_korean_word() -> None:
    notice = NoticeData(key_details=[LabeledFact(text="지원 자격")])

    class FakeResponses:
        async def parse(self, *, text_format, input, **kwargs):
            return SimpleNamespace(output_parsed=text_format.model_validate({"repairs": [{
                "id": "T001", "english": "Eligibility details for undergraduate students: 지원 자격",
            }]}))

    with pytest.raises(SemanticError, match="untranslated or mismatched"):
        asyncio.run(repair_english_fields(notice, SimpleNamespace(responses=FakeResponses()), "gpt-4o-mini"))
    assert notice.key_details[0].text == "지원 자격"
