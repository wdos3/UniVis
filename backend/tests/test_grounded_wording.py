import asyncio
import json
from types import SimpleNamespace

from app.models import Action, DocumentRequirement, LabeledFact, NoticeData, ReviewState
from app.services.coverage_repair import RepairDetail, RepairResponse, repair_coverage
from app.services.grounded_wording import correct_grounded_wording
from app.services.semantic import OpenAISemanticProvider, normalize_notice
from app.services.text import simplified_text


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

    assert normalized.audience[0].text == "Students on leave may participate."
    assert normalized.actions[0].action == (
        "Submit through the Extracurricular Integrated Management System (S Plus)."
    )
    assert normalized.financial_support[0].text == "Research funding: up to KRW 200,000 per person."
    assert normalized.financial_support[1].text == (
        "Research-funded purchases must be paid for at the Convergence Education Center by card."
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
        "Research-funded purchases are paid for by visiting the Convergence Education Center "
        "and using card payment."
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
        ("Research fees must be paid at the Convergence Education Center by card.", "funding"),
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
        "Research-funded purchases must be paid for at the Convergence Education Center by card.",
    ]
    assert [item.source_evidence for item in result.notice.key_details + result.notice.financial_support] == lines
