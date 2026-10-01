import asyncio
import json
from types import SimpleNamespace

from app.models import Action, DocumentRequirement, LabeledFact, NoticeData, ReviewState
from app.services.coverage_repair import RepairDetail, RepairResponse, repair_coverage
from app.services.grounded_wording import correct_grounded_wording
from app.services.semantic import OpenAISemanticProvider, normalize_notice
from app.services.text import simplified_text


def test_leave_participation_retains_both_distinct_funding_exclusions() -> None:
    source = "휴학생도 참여는 가능하나 연구비 및 활동비 지원 대상에서는 제외"
    broad = "Leave students can participate but are excluded from funding support."
    expected = "Students on leave may participate, but are excluded from both research funding and activity allowance support."

    assert correct_grounded_wording(broad, source) == expected
    assert correct_grounded_wording(expected, source) == expected
    assert correct_grounded_wording("Eligibility", source) == "Eligibility"
    assert correct_grounded_wording(broad, source.replace("및 활동비 ", "")) != expected
    assert correct_grounded_wording(broad, "휴학생 참여 불가") == "Students on leave can participate but are excluded from funding support."


def test_enrolled_status_is_restored_only_for_the_complete_cited_eligibility_clause() -> None:
    english = "Undergraduate students in the second semester of the 2026 academic year."
    source = "모집 대상: 2026학년도 2학기 학부 재학생"
    expected = "Undergraduate students enrolled in the second semester of the 2026 academic year."

    assert correct_grounded_wording(english, source) == expected
    assert correct_grounded_wording(expected, source) == expected
    assert correct_grounded_wording("Eligibility", source) == "Eligibility"
    assert correct_grounded_wording(english, source.replace("재학생", "신입생")) == english
    assert correct_grounded_wording(english, source + " 중 연구 경험자") == english
    assert correct_grounded_wording(english, "2027학년도 1학기 학부 재학생") == (
        "Undergraduate students enrolled in the first semester of the 2027 academic year."
    )


def test_spending_verbs_keep_their_source_scope_and_card_payment_covers_all_expenses() -> None:
    source = "연구비는 기자재 구입 및 대여, 재료비, 도서 구입 및 인쇄비로 사용 가능"
    english = "Research expenses can be used to purchase and rent equipment, materials, books, and printing costs."
    expected = "Research expenses may cover equipment purchase or rental, material costs, book purchases, and printing costs."

    assert correct_grounded_wording(english, source) == expected
    assert correct_grounded_wording(expected, source) == expected
    assert correct_grounded_wording("Spending", source) == "Spending"
    assert correct_grounded_wording(english, source.replace("대여, ", "")) == english
    assert correct_grounded_wording(english, source + ", 식비 제외") == english


def test_research_card_rule_does_not_sound_optional_or_describe_grant_disbursement() -> None:
    source = "연구비는 융합교육원에 방문하여 카드결제"
    incorrect = "Research funds can be paid by card payment after visiting the Convergence Education Center."

    assert correct_grounded_wording(incorrect, source) == (
        "Research expenses must be paid by card at the Convergence Education Center, requiring an in-person visit."
    )
    assert correct_grounded_wording(incorrect, "연구비 최대 20만원 지급") == incorrect
    assert correct_grounded_wording(incorrect, "연구비 납부: 융합교육원 방문하여 카드결제") == incorrect


def test_observed_funding_processed_wording_becomes_the_exact_source_payment_procedure() -> None:
    source = "연구비는 융합교육원에 방문하여 카드결제"
    incorrect = "Research funding must be processed in person at the Convergence Education Center with card payment."

    assert correct_grounded_wording(incorrect, source) == (
        "Research expenses must be paid by card at the Convergence Education Center, requiring an in-person visit."
    )
    assert correct_grounded_wording(incorrect, "연구비는 현장 카드결제로 지급") == incorrect
    notice = NoticeData(financial_support=[LabeledFact(text=incorrect, source_evidence=source)])
    assert normalize_notice(notice).financial_support[0].text.startswith("Research expenses must be paid by card")


def test_same_or_similar_on_campus_scope_is_recovered_only_from_exact_source_condition() -> None:
    source = "교내 타 프로그램에서 동일하거나 유사한 연구 주제로 지원을 받는 학생 및 팀은 참여 제한"
    english = "Students and teams supported for similar research topics in other programs are restricted from participation."
    expected = "Students and teams receiving support from other on-campus programs for the same or similar research topics are restricted from participation."

    assert correct_grounded_wording(english, source) == expected
    assert correct_grounded_wording(english.replace("other programs", "other university programs"), source) == expected
    assert correct_grounded_wording(expected, source) == expected
    assert correct_grounded_wording(english, source.replace("교내", "교외")) == english
    assert correct_grounded_wording(english, "교내 타 프로그램에 참여") == english


def test_complete_duplicate_support_clause_recovers_receiving_support_without_rewriting_labels() -> None:
    source = "교내 타 프로그램에서 동일하거나 유사한 연구 주제로 지원을 받는 학생 및 팀은 참여 제한"
    wrong = "Students and teams applying for similar research topics in other programs are restricted from participation."
    expected = "Students and teams receiving support from other on-campus programs for the same or similar research topics are restricted from participation."
    notice = NoticeData(warnings=[LabeledFact(text=wrong, label="Restriction", source_evidence=source)])

    normalized = normalize_notice(notice)

    assert normalized.warnings[0].text == expected
    assert normalized.warnings[0].label == "Restriction"
    assert correct_grounded_wording(wrong, source.replace("지원을 받는", "지원을 신청하는")) != expected
    assert correct_grounded_wording(wrong, source + "\n다른 안내") != expected
    assert correct_grounded_wording(expected, source) == expected


def test_comparison_and_integrated_system_name_requires_cited_korean_name() -> None:
    english = "Submit via the Comparison and Integrated Management System (S Plus)."
    assert correct_grounded_wording(english, "비교과통합관리시스템(S Plus)로 제출") == (
        "Submit via the Extracurricular Integrated Management System (S Plus)."
    )
    assert correct_grounded_wording(english, "온라인 시스템으로 제출") == english


def test_primary_output_corrects_mistranslations_only_with_cited_korean_evidence() -> None:
    leave_evidence = "휴학생도 참여는 가능하나 연구비 및 활동비 지원 대상에서는 제외"
    system_evidence = "지원서, 연구계획서를 비교과통합관리시스템(S Plus)로 제출"
    support_evidence = "연구비: 1인당 최대 20만원"
    card_evidence = "연구비 사용: 융합교육원에 방문하여 카드결제"
    notice = NoticeData(
        audience=[LabeledFact(text="Leaving students may participate.", source_evidence=leave_evidence)],
        actions=[Action(
            step=1,
            action="Submit through the Comparative Integrated Management System (S Plus).",
            source_evidence=system_evidence,
        )],
        financial_support=[
            LabeledFact(text="Research fee: up to KRW 200,000 per person.", source_evidence=support_evidence),
            LabeledFact(
                text="Research fees must be paid at the Convergence Education Center by card.",
                source_evidence=card_evidence,
            ),
        ],
    )

    normalized = normalize_notice(notice)

    assert normalized.audience[0].text == (
        "Students on leave may participate, but are excluded from both research funding and activity allowance support."
    )
    assert normalized.actions[0].action == (
        "Submit through the Extracurricular Integrated Management System (S Plus)."
    )
    assert normalized.financial_support[0].text == "Research funding: up to KRW 200,000 per person."
    assert normalized.financial_support[1].text == (
        "Research expenses must be paid by card at the Convergence Education Center, requiring an in-person visit."
    )
    for item, evidence in (
        (normalized.audience[0], leave_evidence),
        (normalized.actions[0], system_evidence),
        (normalized.financial_support[0], support_evidence),
        (normalized.financial_support[1], card_evidence),
    ):
        assert item.source_evidence == evidence
        assert item.state == ReviewState.NEEDS_REVIEW


def test_absent_or_payable_evidence_does_not_trigger_funding_rewrite() -> None:
    phrase = "Research fee must be paid by card."
    assert correct_grounded_wording(phrase, "") == phrase
    assert correct_grounded_wording(phrase, "연구비 20만원 납부, 카드결제") == phrase
    assert correct_grounded_wording("Leaving students may apply.", "재학생 지원 가능") == (
        "Leaving students may apply."
    )
    assert correct_grounded_wording(
        "Use the Comparative Integrated Management System.", "비교과 프로그램 신청"
    ) == "Use the Comparative Integrated Management System."


def test_activity_allowance_is_not_called_a_fee_when_awarded() -> None:
    assert correct_grounded_wording("Activity fee: KRW 200,000 per person", "활동비: 1인당 20만원") == (
        "Activity allowance: KRW 200,000 per person"
    )


def test_unstated_acronym_expansion_is_removed_from_cited_detail() -> None:
    evidence = "AI Wearable Device의 AIX 발굴과 MVP(Minimum Value Prototyping)"
    notice = NoticeData(
        key_details=[LabeledFact(
            text="Discover AIX (AI Experience) for AI Wearable Devices.",
            source_evidence=evidence,
        )],
        summary="Research and activity fees support this project.",
    )

    normalized = normalize_notice(notice, source_text=evidence + "\n연구비 및 활동비 지원")

    assert normalized.key_details[0].text == "Discover AIX for AI Wearable Devices."
    assert normalized.key_details[0].state == ReviewState.NEEDS_REVIEW
    assert normalized.summary == "Research funding and activity allowances support this project."
    assert correct_grounded_wording("AIX (AI Experience)", "AIX (AI Experience) 연구") == (
        "AIX (AI Experience)"
    )


def test_placeholder_key_detail_label_is_not_displayed_as_a_section_header() -> None:
    notice = NoticeData(key_details=[LabeledFact(
        label="key_details", text="Students may choose their own research topic.",
        source_evidence="학생 자율선정 주제",
    )])

    normalized = normalize_notice(notice)

    assert normalized.key_details[0].label == "Other key details"
    assert "key_details" not in simplified_text(normalized)


def test_cited_privacy_consent_is_named_fully_in_documents_actions_and_details() -> None:
    evidence = "지원서, 연구계획서, 개인정보 수집 및 이용 동의서를 제출"
    notice = NoticeData(
        actions=[Action(
            step=1, action="Submit the required documents.", required_items=["Consent form"],
            source_evidence=evidence,
        )],
        required_documents=[DocumentRequirement(name="Personal information consent form", source_evidence=evidence)],
        key_details=[LabeledFact(text="Bring the consent form.", source_evidence=evidence)],
    )

    normalized = normalize_notice(notice)

    assert normalized.actions[0].required_items == ["Personal information collection and use consent form"]
    assert normalized.required_documents[0].name == "Personal information collection and use consent form"
    assert normalized.key_details[0].text == "Bring the personal information collection and use consent form."
    for item in (normalized.actions[0], normalized.required_documents[0], normalized.key_details[0]):
        assert item.source_evidence == evidence
        assert item.state == ReviewState.NEEDS_REVIEW
    assert correct_grounded_wording("Consent form", "일반 동의서 제출") == "Consent form"
    complete = "Personal information collection and use consent form"
    assert correct_grounded_wording(complete, evidence) == complete


def test_audit_added_consent_bullet_uses_specific_cited_name() -> None:
    source = "개인정보 수집 및 이용 동의서를 제출"
    parsed = RepairResponse(
        represented_unit_ids=[],
        details=[RepairDetail(
            unit_ids=["P001-L0001"], text="Submit a consent form.", category="application", certain=True,
        )], decorative=[], unresolved_unit_ids=[],
    )

    class Responses:
        async def parse(self, **kwargs):
            return SimpleNamespace(output_parsed=parsed, usage=None)

    result = asyncio.run(repair_coverage(
        NoticeData(), source, client=SimpleNamespace(responses=Responses()),
    ))

    assert result.notice.key_details[0].text == "Submit a personal information collection and use consent form."
    assert result.notice.key_details[0].source_evidence == source


def test_observed_are_paid_card_wording_is_recast_as_a_purchase_procedure() -> None:
    observed = (
        "Research fees are paid by visiting the Convergence Education Center "
        "and using card payment."
    )
    evidence = "연구비 사용: 융합교육원에 방문하여 카드결제"

    assert correct_grounded_wording(observed, evidence) == (
        "Research expenses must be paid by card at the Convergence Education Center, requiring an in-person visit."
    )


def test_wording_is_rechecked_after_korean_field_translation() -> None:
    original = NoticeData(audience=[LabeledFact(
        text="휴학생도 참여 가능", source_evidence="휴학생도 참여 가능",
    )])

    class Responses:
        def __init__(self) -> None:
            self.calls = 0

        async def parse(self, *, text_format, input, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return SimpleNamespace(output_parsed=original, usage=None)
            payload = json.loads(input[1]["content"])
            return SimpleNamespace(output_parsed=text_format.model_validate({
                "repairs": [{"id": item["id"], "english": "Leaving students may participate."} for item in payload],
            }), usage=None)

    responses = Responses()
    result = asyncio.run(OpenAISemanticProvider(client=SimpleNamespace(responses=responses)).analyze(
        "휴학생도 참여 가능", "Leaving students may participate.", "en",
    ))

    assert responses.calls == 2
    assert result.notice.audience[0].text == "Students on leave may participate."
    assert result.notice.audience[0].source_evidence == "휴학생도 참여 가능"


def test_post_audit_details_receive_the_same_evidence_gated_corrections() -> None:
    lines = [
        "휴학생도 참여 가능",
        "지원서는 비교과통합관리시스템(S Plus)로 제출",
        "연구비: 1인당 최대 20만원",
        "연구비 사용: 융합교육원 방문하여 카드결제",
    ]
    detail_texts = [
        ("Leaving students may participate.", "eligibility"),
        ("Submit through the Comparative Integrated Management System (S Plus).", "application"),
        ("Research fee: up to KRW 200,000 per person.", "funding"),
        ("Research fees must be paid at the Convergence Education Center by card during an in-person visit.", "funding"),
    ]
    parsed = RepairResponse(
        represented_unit_ids=[],
        details=[RepairDetail(
            unit_ids=[f"P001-L{index:04d}"], text=text, category=category, certain=True,
        ) for index, (text, category) in enumerate(detail_texts, 1)],
        decorative=[], unresolved_unit_ids=[],
    )

    class Responses:
        async def parse(self, **kwargs):
            return SimpleNamespace(output_parsed=parsed, usage=None)

    result = asyncio.run(repair_coverage(
        NoticeData(), "\n".join(lines), client=SimpleNamespace(responses=Responses()),
    ))

    assert [item.text for item in result.notice.key_details] == [
        "Students on leave may participate.",
        "Submit through the Extracurricular Integrated Management System (S Plus).",
    ]
    assert [item.text for item in result.notice.financial_support] == [
        "Research funding: up to KRW 200,000 per person.",
        "Research expenses must be paid by card at the Convergence Education Center, requiring an in-person visit.",
    ]
    assert [item.source_evidence for item in result.notice.key_details + result.notice.financial_support] == lines
