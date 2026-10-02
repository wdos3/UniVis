import asyncio
import json
from types import SimpleNamespace

import pytest

from app.models import Action, DocumentRequirement, LabeledFact, NoticeData, ReviewState
from app.services import english_review
from app.services.coverage_repair import RepairDetail, RepairResponse, repair_coverage
from app.services.english_verification import EnglishSupportDecision, EnglishSupportResult
from app.services.grounded_wording import correct_grounded_wording
from app.services.semantic import OpenAISemanticProvider, normalize_notice
from app.services.text import simplified_text



def test_fundamental_ai_technology_keeps_the_cited_research_topic() -> None:
    english = "Designated topic 3: Research and development of original AI technology."
    source = "지정 주제 3: AI 원천 기술 연구 개발"

    assert correct_grounded_wording(english, source) == (
        "Designated topic 3: Research and development of core AI technologies."
    )
    assert correct_grounded_wording("Original AI technology research and development.", source) == (
        "Core AI technologies research and development."
    )
    assert correct_grounded_wording(english, "AI 응용 기술 연구 개발") == english










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
        "Students on leave may participate."
    )
    assert normalized.actions[0].action == (
        "Submit through the Extracurricular Integrated Management System (S Plus)."
    )
    assert normalized.financial_support[0].text == "Research funding: up to KRW 200,000 per person."
    assert normalized.financial_support[1].text == (
        "Research expenses must be paid at the Convergence Education Center by card."
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


def test_local_glossary_does_not_replace_acronyms_or_their_expansions() -> None:
    evidence = "AI Wearable Device의 AIX 발굴과 MVP(Minimum Value Prototyping)"
    notice = NoticeData(
        key_details=[LabeledFact(
            text="Discover AIX (AI Experience) for AI Wearable Devices.",
            source_evidence=evidence,
        )],
        summary="Research and activity fees support this project.",
    )

    normalized = normalize_notice(notice, source_text=evidence + "\n연구비 및 활동비 지원")

    assert normalized.key_details[0].text == "Discover AIX (AI Experience) for AI Wearable Devices."
    assert normalized.summary == "Research funding and activity allowances support this project."
    assert correct_grounded_wording("AIX (AI Experience)", "AIX (AI Experience) 연구") == (
        "AIX (AI Experience)"
    )


@pytest.mark.parametrize(("source", "english", "expected"), [
    (
        "MVP(Minimum Value\nPrototyping) 제작",
        "Develop an MVP for the selected research topic.",
        "Develop an MVP (Minimum Value Prototyping) for the selected research topic.",
    ),
    (
        "HSS (Housing Support Scheme) 신청",
        "Apply to HSS by the deadline.",
        "Apply to HSS (Housing Support Scheme) by the deadline.",
    ),
    (
        "HSS \n  (Housing Support Scheme) 신청",
        "Apply to HSS by the deadline.",
        "Apply to HSS (Housing Support Scheme) by the deadline.",
    ),
    (
        "HSS(Housing Support Scheme), HSS (Housing   Support\nScheme)",
        "HSS applicants may contact the HSS office.",
        "HSS (Housing Support Scheme) applicants may contact the HSS (Housing Support Scheme) office.",
    ),
    (
        "QOL(Quality of Life) 안내",
        "Apply for the QOL program.",
        "Apply for the QOL (Quality of Life) program.",
    ),
])
def test_acronym_restoration_copies_only_the_explicit_quoted_english_expansion(source, english, expected) -> None:
    assert correct_grounded_wording(english, source) == expected
    assert correct_grounded_wording(expected, source) == expected


@pytest.mark.parametrize(("source", "english"), [
    ("MVP 제작", "Develop an MVP."),
    ("MVP(Minimum Value Prototyping)", "Develop a prototype."),
    ("MVP(Minimum Value Prototyping)", "Develop an MVP (Minimum Viable"),
    ("MVP(Minimum Value Prototyping)", "Develop an MVP — (Minimum Viable Product)."),
    ("MVP(Minimum Value Prototyping)", "Develop an MVP [Minimum Viable Product]."),
    ("MVP(Minimum Value Prototyping)", "Develop an MVP through Minimum Viable Prototyping."),
    ("MVP(Minimum Value Prototyping)", "Develop an MVP through Minimum Viable Product."),
    ("MVP(Minimum Value Prototyping)", "Develop an MVP through minimum viable product."),
    ("MVP(Minimum Value Prototyping)", "Develop an MVP through Minimum Value Prototyping."),
    ("MVP(Minimum Value Prototyping)", "MVP development uses value prototyping."),
    ("MVP(Minimum Value Prototyping)", "Prototyping is part of MVP development."),
    ("HSS(Housing Support Scheme)", "Apply to HSS through the Housing Subsidy Scheme."),
    ("HSS(Housing Support Scheme)", "The Housing Support Scheme accepts HSS applications."),
    ("HSS(Housing Support Scheme)", "Apply to HSS to receive housing assistance."),
    ("HSS(Housing Support Scheme)", "Apply to HSS (optional)."),
    ("HSS(Housing Support Scheme)", "Apply to HSS (for enrolled students)."),
    ("HSS(Housing Support Scheme)", "Apply to HSS (for Housing Support)."),
    ("HSS(Housing Support Scheme)", "Apply to HSS (minimum score 80)."),
    ("HSS(Housing Support Scheme)", "Apply to HSS (Housing Support is required)."),
    ("HSS(Housing Support Scheme)", "Apply to HSS (Housing Support only)."),
    ("HSS(Housing Support Scheme)", "Apply to HSS (Housing Support is not available)."),
    ("MVP(Minimum Value Prototyping)", "Develop an MVP (Minimum Viable Product) through Minimum Viable Prototyping."),
    ("MVP(Minimum Value Prototyping)", "Prototyping is part of MVP (Minimum Viable Product) development."),
    ("MVP(Minimum Value Prototyping)", "Develop an MVP (Minimum (Viable) Product)."),
    ("MVP(Minimum Value Prototyping)", "Develop MVPs or an AMVP."),
    ("MVP(Minimum Value Prototyping)", "Develop an mvp."),
    ("MVP(Minimum Value Prototyping)", "Develop an MVP2."),
    ("MVP(Minimum Value Prototyping", "Develop an MVP."),
    ("MVP((Minimum Value Prototyping)", "Develop an MVP."),
    ("MVP(Minimum Value (Prototyping))", "Develop an MVP."),
    ("MVP(최소 가치 프로토타이핑)", "Develop an MVP."),
    ("MVP(Minimum Value 프로토타이핑)", "Develop an MVP."),
    ("MVP()", "Develop an MVP."),
    ("MVP(2026)", "Develop an MVP."),
    ("HSS\n\n(Housing Support Scheme)", "Apply to HSS."),
    ("HSS\n다른 사업\n(Housing Support Scheme)", "Apply to HSS."),
    ("MVP(Minimum Value Prototyping), MVP(Minimum Viable Product)", "Develop an MVP."),
    ("MVP(Minimum Value Prototyping), MVP(최소 가치 프로토타이핑)", "Develop an MVP."),
    ("MVP(Minimum Value Prototyping), MVP(Minimum Viable", "Develop an MVP."),
])
def test_acronym_restoration_preserves_missing_conflicting_ambiguous_and_unreadable_expansions(source, english) -> None:
    assert correct_grounded_wording(english, source) == english


@pytest.mark.parametrize(("source", "english", "expected"), [
    (
        "MVP(Minimum Value\nPrototyping) 제작",
        "Develop an MVP (Minimum Viable Product Prototyping) for the selected topic.",
        "Develop an MVP (Minimum Value Prototyping) for the selected topic.",
    ),
    (
        "MVP(Minimum Value Prototyping) 제작",
        "Develop an MVP(Minimum Viable Product).",
        "Develop an MVP(Minimum Value Prototyping).",
    ),
    (
        "HSS(Housing Support Scheme) 신청",
        "Apply to HSS (Housing Allowance Scheme) by the deadline.",
        "Apply to HSS (Housing Support Scheme) by the deadline.",
    ),
    (
        "HSS(Health Safety Standard) 안내",
        "HSS (Housing Support Scheme) applies to applicants.",
        "HSS (Health Safety Standard) applies to applicants.",
    ),
    (
        "MVP(Minimum Value Prototyping) 제작",
        "Develop an MVP (Minimum Viable Product) and another MVP.",
        "Develop an MVP (Minimum Value Prototyping) and another MVP (Minimum Value Prototyping).",
    ),
])
def test_complete_attached_expansions_use_only_the_unique_literal_in_the_field_quote(source, english, expected) -> None:
    assert correct_grounded_wording(english, source) == expected
    assert correct_grounded_wording(expected, source) == expected
    assert correct_grounded_wording(english, "사업 안내") == english


@pytest.mark.parametrize("english", [
    "Develop an MVP (Minimum Value Prototyping).",
    "Develop an MVP (minimum value prototyping).",
    "Develop an MVP(Minimum   Value Prototyping).",
])
def test_already_correct_attached_expansions_preserve_existing_english_spacing_and_case(english) -> None:
    assert correct_grounded_wording(english, "MVP(Minimum Value Prototyping) 제작") == english


def test_attached_expansion_correction_preserves_quote_and_requires_independent_review(monkeypatch) -> None:
    source = "HSS(Housing Support Scheme) 소개"
    notice = normalize_notice(NoticeData(key_details=[LabeledFact(
        text="HSS (Housing Allowance Scheme) is mandatory.", source_evidence=source,
        source_page=1, state=ReviewState.VERIFIED,
    )]), source_text=source)
    corrected = "HSS (Housing Support Scheme) is mandatory."
    assert notice.key_details[0].text == corrected
    assert notice.key_details[0].source_evidence == source
    assert notice.key_details[0].state == ReviewState.NEEDS_REVIEW

    async def reject(fields, actual_source, **kwargs):
        assert actual_source == source
        assert [field.text for field in fields] == [corrected]
        return EnglishSupportResult(
            decisions=(EnglishSupportDecision(id=fields[0].id, status="unsupported", reason="No mandatory condition."),),
            requests=1, unverified_source_ids=frozenset(unit.id for unit in kwargs["source_units"]),
        )

    monkeypatch.setattr(english_review, "verify_english_support", reject)
    result = asyncio.run(english_review.review_notice_english(notice, source))

    assert result.notice.key_details == []
    assert result.has_verification_gaps
    assert result.unverified_source_units == 1


def test_whole_source_context_cannot_expand_an_uncited_summary() -> None:
    source = "HSS(Housing Support Scheme) 신청\n다른 사업 지원 안내"
    notice = NoticeData(
        summary="HSS applications are open.",
        purpose="Explain HSS applications.",
        key_details=[
            LabeledFact(text="Apply to HSS.", source_evidence="HSS(Housing Support Scheme) 신청"),
            LabeledFact(text="HSS support is available.", source_evidence="다른 사업 지원 안내"),
        ],
    )

    normalized = normalize_notice(notice, source_text=source)

    assert normalized.summary == "HSS applications are open."
    assert normalized.purpose == "Explain HSS applications."
    assert normalized.key_details[0].text == "Apply to HSS (Housing Support Scheme)."
    assert normalized.key_details[0].source_evidence == "HSS(Housing Support Scheme) 신청"
    assert normalized.key_details[0].state == ReviewState.NEEDS_REVIEW
    assert normalized.key_details[1].text == "HSS support is available."
    assert correct_grounded_wording("HSS application", source, restore_expansions=False) == "HSS application"


def test_audit_added_detail_restores_the_expansion_from_its_exact_quoted_source_units() -> None:
    source = "MVP(Minimum Value\nPrototyping) 제작"
    parsed = RepairResponse(
        represented_unit_ids=[],
        details=[RepairDetail(
            unit_ids=["P001-L0001", "P001-L0002"],
            text="Develop an MVP.", category="application", certain=True,
        )], decorative=[], unresolved_unit_ids=[],
    )

    class Responses:
        async def parse(self, **kwargs):
            return SimpleNamespace(output_parsed=parsed, usage=None)

    result = asyncio.run(repair_coverage(
        NoticeData(), source, client=SimpleNamespace(responses=Responses()),
    ))

    assert result.notice.key_details[0].text == "Develop an MVP (Minimum Value Prototyping)."
    assert result.notice.key_details[0].source_evidence == source
    assert result.notice.key_details[0].state == ReviewState.NEEDS_REVIEW


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


@pytest.mark.parametrize("name", [
    "Consent for Data Collection",
    "Consent for Data Collection and Use",
    "Consent for Personal Information Collection",
    "Personal Information Consent",
    "Personal Information Consent Form",
])
def test_incomplete_consent_document_names_require_the_full_cited_korean_document(name) -> None:
    evidence = "제출 서류: 개인정보 수집 및 이용 동의서"

    assert correct_grounded_wording(name, evidence) == "Personal information collection and use consent form"
    assert correct_grounded_wording(name, "데이터 수집 동의") == name
    assert correct_grounded_wording(name, "개인정보 수집 동의서") == name


@pytest.mark.parametrize("english", [
    "Obtain consent for data collection.",
    "Personal information consent is optional.",
    "Consent for data collection after approval.",
    "Personal information collection and use consent form",
])
def test_consent_name_correction_does_not_rewrite_verb_phrases_or_complete_names(english) -> None:
    assert correct_grounded_wording(english, "개인정보 수집 및 이용 동의서") == english


@pytest.mark.parametrize("english", [
    "Consent Form for Personal Information Collection and Use",
    "Consent form for the personal information collection and use",
    "Personal Information Collection and Use Consent Form",
    "Submit the Consent Form for Personal Information Collection and Use.",
])
def test_complete_consent_name_scope_is_not_repeated_after_consent_form(english) -> None:
    assert correct_grounded_wording(english, "개인정보 수집 및 이용 동의서") == english


def test_nominal_consent_document_correction_preserves_grounding_and_review_state() -> None:
    evidence = "지원서, 연구계획서, 개인정보 수집 및 이용 동의서"
    notice = NoticeData(
        actions=[Action(
            step=1, action="Submit the documents.",
            required_items=["Consent for Data Collection"], source_evidence=evidence,
        )],
        required_documents=[DocumentRequirement(name="Personal Information Consent", source_evidence=evidence)],
    )

    normalized = normalize_notice(notice)

    assert normalized.actions[0].required_items == ["Personal information collection and use consent form"]
    assert normalized.required_documents[0].name == "Personal information collection and use consent form"
    for item in (normalized.actions[0], normalized.required_documents[0]):
        assert item.source_evidence == evidence
        assert item.state == ReviewState.NEEDS_REVIEW


def test_observed_are_paid_card_wording_is_recast_as_a_purchase_procedure() -> None:
    observed = (
        "Research fees are paid by visiting the Convergence Education Center "
        "and using card payment."
    )
    evidence = "연구비 사용: 융합교육원에 방문하여 카드결제"

    assert correct_grounded_wording(observed, evidence) == (
        "Research expenses are paid by visiting the Convergence Education Center and using card payment."
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
        "Research expenses must be paid at the Convergence Education Center by card during an in-person visit.",
    ]
    assert [item.source_evidence for item in result.notice.key_details + result.notice.financial_support] == lines


@pytest.mark.parametrize(("source", "english"), [
    ("지원금은 2차에 걸쳐 지급하며 결과보고서를 제출한 학생에 한하여 2차 지원금 지급",
     "Support is paid in two installments."),
    ("모집 대상: 융합교육원에서 인정하는 연구 관련 과목을 수강하며 연구지도를 받는 학부생",
     "Undergraduates taking recognized research courses."),
    ("모집 대상: 2027학년도 1학기 학부 재학생",
     "Undergraduates in the first semester of 2027."),
    ("연구비는 기자재 구입 및 대여, 재료비, 도서 구입 및 인쇄비로 사용 가능",
     "Research expenses cover equipment and printing."),
    ("교내 타 프로그램에서 동일하거나 유사한 연구 주제로 지원을 받는 학생 및 팀은 참여 제한",
     "Applicants from other programs cannot participate."),
    ("연구비는 융합교육원에 방문하여 카드결제",
     "Research funding is processed in person at the Convergence Education Center."),
    ("연구비는 산학협력단에 방문하여 카드결제",
     "Research funding is processed in person at the Industry Cooperation Office."),
    ("휴학생도 참여는 가능하나 연구비 및 활동비 지원 대상에서는 제외",
     "Students on leave may participate."),
    ("지원금은 3차에 걸쳐 지급하며 수료한 학생에 한하여 마지막 지원금 지급",
     "Support is paid in three installments."),
])
def test_local_wording_does_not_compose_missing_conditions_or_replace_notice_sentences(source, english) -> None:
    # Incomplete clauses must pass through the independent audit and its retry.
    assert correct_grounded_wording(english, source) == english


@pytest.mark.parametrize("institution", ["Housing Office", "Graduate School", "Regional Research Center"])
def test_glossary_keeps_new_institutions_amounts_and_conditions(institution) -> None:
    english = f"Research fees must be paid by card at the {institution} after approval; maximum KRW 450,000."
    source = "연구비는 승인 후 해당 기관에서 카드결제; 최대 45만원"
    assert correct_grounded_wording(english, source) == english.replace("Research fees", "Research expenses")
