from __future__ import annotations

import asyncio
import json
from pathlib import Path
import re
from types import SimpleNamespace

import pytest
from openai.lib._pydantic import to_strict_json_schema

from app.models import LabeledFact, NoticeData, ReviewState, SourceFact
from app.services.coverage import audit_coverage
from app.services.coverage_repair import (
    CoverageProviderError,
    CoverageRepairError,
    DecorativeFragment,
    MAX_COVERAGE_UNITS,
    RepairDetail,
    RepairResponse,
    repair_coverage,
)
from app.services.text import simplified_text
from app.services.grounded_wording import correct_grounded_wording
from app.services.fidelity import calculate_fidelity


class FakeResponses:
    def __init__(self, parsed: RepairResponse | None | list[RepairResponse | None]) -> None:
        self.parsed = parsed if isinstance(parsed, list) else [parsed]
        self.calls: list[dict] = []

    async def parse(self, **kwargs):
        self.calls.append(kwargs)
        index = len(self.calls) - 1
        assert index < len(self.parsed), "An unexpected extra provider request was made."
        return SimpleNamespace(
            output_parsed=self.parsed[index],
            usage=SimpleNamespace(input_tokens=103, output_tokens=47, total_tokens=150),
        )


def _run_repair(source: str, response: RepairResponse | list[RepairResponse], *, notice: NoticeData | None = None):
    responses = FakeResponses(response)
    result = asyncio.run(repair_coverage(
        notice or NoticeData(), source,
        layout_context="(320,450) AI topic", client=SimpleNamespace(responses=responses),
    ))
    return result, responses.calls


def _detail(unit_id: str, text: str, category: str = "other", *, certain: bool = True) -> RepairDetail:
    return RepairDetail(unit_ids=[unit_id], text=text, category=category, certain=certain)


def test_recovered_exact_source_fact_keeps_its_original_fidelity_reference() -> None:
    source = "연구비: 1인당 최대 20만원"
    notice = NoticeData(source_facts=[SourceFact(
        id="F008", kind="financial_support", source_text=source, source_page=1,
    )])
    parsed = RepairResponse(
        represented_unit_ids=[], details=[_detail(
            "P001-L0001", "Research funding is up to KRW 200,000 per person.", "funding",
        )], decorative=[], unresolved_unit_ids=[],
    )

    result, _ = _run_repair(source, parsed, notice=notice)

    assert result.notice.financial_support[0].source_fact_ids == ["F008", "F009"]
    fidelity = calculate_fidelity(result.notice, source)
    assert fidelity.potentially_missing == []
    assert fidelity.critical_fields_represented == 2
    assert fidelity.serious_issue is False


def test_source_fact_reference_recovery_requires_the_same_whole_clause_and_page() -> None:
    source = "[Page 1]\n연구비: 1인당 최대 20만원"
    notice = NoticeData(source_facts=[
        SourceFact(id="F001", kind="financial_support", source_text="연구비: 1인당 최대 20만원", source_page=2),
        SourceFact(id="F002", kind="financial_support", source_text="연구비:", source_page=1),
    ])
    parsed = RepairResponse(
        represented_unit_ids=[], details=[_detail(
            "P001-L0001", "Research funding is up to KRW 200,000 per person.", "funding",
        )], decorative=[], unresolved_unit_ids=[],
    )

    result, _ = _run_repair(source, parsed, notice=notice)

    assert result.notice.financial_support[0].source_fact_ids == ["F003"]


def test_repair_schema_is_valid_for_openai_structured_outputs() -> None:
    schema = to_strict_json_schema(RepairResponse)
    assert schema["additionalProperties"] is False
    assert "represented_unit_ids" in schema["required"]
    assert "unsupported_english_ids" in schema["required"]
    assert schema["properties"]["details"]["items"]["$ref"] == "#/$defs/RepairDetail"


def test_repair_preserves_research_topics_and_distinct_financial_support() -> None:
    source = "\n".join([
        "[Page 1]",
        "AI 웨어러블 기기(스마트 글래스 등) 발굴 및 MVP 제작",
        "AI is Everywhere에 부합하는 AI 기능 개발",
        "AI 원천기술 연구개발",
        "로봇 관련 연구개발",
        "학생 자율선정 주제",
        "연구비: 1인당 최대 20만원",
        "장비 구입 및 임차, 재료비, 도서 구입 및 인쇄 가능",
        "융합교육원 방문하여 카드결제",
        "활동비: 1인당 20만원",
        "연구비 외 비용은 장학금 형태로 지급",
    ])
    english = [
        ("Explore AI wearable devices such as smart glasses and produce an MVP.", "research_topic"),
        ("Develop AI features aligned with the 'AI is Everywhere' theme.", "research_topic"),
        ("Research and develop foundational AI technology.", "research_topic"),
        ("Research and develop robotics-related technology.", "research_topic"),
        ("Students may choose their own research topic.", "research_topic"),
        ("Research funding is up to KRW 200,000 per person.", "funding"),
        ("Research funds may cover equipment purchase or rental, materials, books, and printing.", "funding"),
        ("Visit the Convergence Education Center and pay by card for covered research expenses.", "funding"),
        ("The activity stipend is KRW 200,000 per person.", "funding"),
        ("Expenses outside the research funding are paid as a scholarship.", "funding"),
    ]
    parsed = RepairResponse(
        represented_unit_ids=[],
        details=[_detail(f"P001-L{index:04d}", text, category) for index, (text, category) in enumerate(english, 1)],
        decorative=[], unresolved_unit_ids=[],
    )

    result, calls = _run_repair(source, parsed)

    assert result.requests == 1
    assert (result.input_tokens, result.output_tokens, result.total_tokens) == (103, 47, 150)
    assert result.repaired_unit_count == 10
    assert len(result.notice.key_details) == 5
    assert len(result.notice.financial_support) == 5
    assert result.notice.fees == []
    assert all(item.source_page == 1 and item.state == ReviewState.NEEDS_REVIEW for item in result.notice.key_details + result.notice.financial_support)
    assert all(item.source_fact_ids and item.source_evidence in source for item in result.notice.key_details + result.notice.financial_support)
    prompt = calls[0]["input"][1]["content"]
    assert "(320,450) AI topic" in prompt
    assert "AI 웨어러블 기기(스마트 글래스 등) 발굴 및 MVP 제작" in prompt
    assert "English translation hint" not in prompt


def test_corrected_sogang_fixture_keeps_all_grounded_requirements_in_english_digest() -> None:
    source = (Path(__file__).parent / "fixtures" / "sogang_research_corrected.txt").read_text(encoding="utf-8")
    expected = [
        ("Creative convergence independent research recruitment for semester 2 of academic year 2026.", "other"),
        ("Applications are open from August 24, 2026 through September 20, 2026.", "application"),
        ("Submit the application form, research plan, and personal information collection and use consent form through the S Plus integrated extracurricular management system.", "application"),
        ("Applicants must be undergraduates enrolled in semester 2 of academic year 2026.", "eligibility"),
        ("Students on leave may participate, but are excluded from both research funding and activity allowance support.", "eligibility"),
        ("Each team must contain 2 to 5 undergraduate students.", "eligibility"),
        ("Students and teams receiving support from other on-campus programs for the same or similar research topics are restricted from participation.", "restriction"),
        ("Duplicate participation within this program is not allowed.", "restriction"),
        ("Research option 1: a designated topic proposed by the Convergence Education Center.", "research_topic"),
        ("Designated topic 1: explore AIX for AI Wearable Devices such as smart glasses and MVP (Minimum Value Prototyping).", "research_topic"),
        ('Designated topic 2: develop AI functions aligned with the motto "AI is Everywhere".', "research_topic"),
        ("Designated topic 3: research and develop foundational AI technology.", "research_topic"),
        ("Designated topic 4: research and develop Robot technology.", "research_topic"),
        ("Check the official notice for the detailed topics.", "research_topic"),
        ("Research option 2: a topic chosen independently by students.", "research_topic"),
        ("Research funding: up to KRW 200,000 per person.", "funding"),
        ("Research expenses may cover equipment purchase or rental, material costs, book purchases, and printing costs.", "funding"),
        ("Research expenses must be paid by card at the Convergence Education Center, requiring an in-person visit.", "funding"),
        ("Activity allowance: KRW 200,000 per person.", "funding"),
        ("Expenses outside the research funding categories are paid as a scholarship.", "funding"),
        ("Contact the Convergence Education Innovation Team at 02-710-2500 or convedu@sogang.ac.kr.", "other"),
    ]
    parsed = RepairResponse(
        represented_unit_ids=[],
        details=[_detail(f"P001-L{index:04d}", text, category) for index, (text, category) in enumerate(expected, 1)],
        decorative=[], unresolved_unit_ids=[],
    )

    result, _ = _run_repair(source, parsed)

    assert result.repaired_unit_count == 21
    assert audit_coverage(result.notice, source).uncovered == []
    digest = simplified_text(result.notice)
    assert not re.search(r"[가-힣]", digest)
    assert all(text in digest for text, _ in expected)
    assert len(result.notice.financial_support) == 5
    assert result.notice.fees == []
    for item in result.notice.financial_support + result.notice.key_details:
        assert item.source_fact_ids
        assert item.source_evidence in source
        assert item.source_page == 1


def test_missing_source_unit_fails_closed() -> None:
    initial = RepairResponse(
        represented_unit_ids=[],
        details=[_detail("P001-L0001", "Research funding is available.", "funding")],
        decorative=[], unresolved_unit_ids=[],
    )
    incomplete_retry = RepairResponse(represented_unit_ids=[], details=[], decorative=[], unresolved_unit_ids=[])
    with pytest.raises(CoverageProviderError, match="incomplete targeted OCR audit"):
        _run_repair("연구비 지원\n활동비 지원", [initial, incomplete_retry])


def test_missing_source_unit_gets_one_focused_retry() -> None:
    initial = RepairResponse(
        represented_unit_ids=[],
        details=[_detail("P001-L0001", "Research funding is available.", "funding")],
        decorative=[], unresolved_unit_ids=[],
    )
    retry = RepairResponse(
        represented_unit_ids=[],
        details=[_detail("P001-L0002", "Activity funding is available.", "funding")],
        decorative=[], unresolved_unit_ids=[],
    )

    result, calls = _run_repair("연구비 지원\n활동비 지원", [initial, retry])

    assert result.requests == len(calls) == 2
    assert result.repaired_unit_count == 2
    assert [item.text for item in result.notice.financial_support] == [
        "Research funding is available.", "Activity funding is available.",
    ]
    assert '"id": "P001-L0002"' in calls[1]["input"][1]["content"]
    assert '"id": "P001-L0001"' not in calls[1]["input"][1]["content"]


def test_uncertain_or_untranslated_detail_fails_closed() -> None:
    for detail in (
        _detail("P001-L0001", "Research funding is available.", certain=False),
        _detail("P001-L0001", "연구비 is available."),
        _detail("P001-L0001", "The funding amount is unreadable."),
    ):
        parsed = RepairResponse(represented_unit_ids=[], details=[detail], decorative=[], unresolved_unit_ids=[])
        with pytest.raises(CoverageProviderError, match="uncertain, empty, or not fully in English") as exc:
            _run_repair("연구비 지원", [parsed, parsed])
        assert "P001-L0001: 연구비 지원" in str(exc.value)


def test_unresolved_source_unit_fails_closed() -> None:
    parsed = RepairResponse(represented_unit_ids=[], details=[], decorative=[], unresolved_unit_ids=["P001-L0001"])
    with pytest.raises(CoverageRepairError, match="P001-L0001: 연구비 지원"):
        _run_repair("연구비 지원", [parsed, parsed])


def test_unresolved_source_unit_gets_one_focused_retry() -> None:
    initial = RepairResponse(represented_unit_ids=[], details=[], decorative=[], unresolved_unit_ids=["P001-L0001"])
    retry = RepairResponse(
        represented_unit_ids=[],
        details=[_detail("P001-L0001", "Research funding is available.", "funding")],
        decorative=[], unresolved_unit_ids=[],
    )

    result, calls = _run_repair("연구비 지원", [initial, retry])

    assert result.requests == len(calls) == 2
    assert result.notice.financial_support[0].text == "Research funding is available."
    assert '"id": "P001-L0001"' in calls[1]["input"][1]["content"]
    assert "speculative clarification" in calls[1]["input"][0]["content"]


def test_evidence_cannot_be_combined_across_pages() -> None:
    parsed = RepairResponse(
        represented_unit_ids=[],
        details=[RepairDetail(
            unit_ids=["P001-L0001", "P002-L0001"],
            text="The notice offers research and activity stipends.",
            category="funding", certain=True,
        )],
        decorative=[], unresolved_unit_ids=[],
    )
    with pytest.raises(CoverageProviderError, match="inconsistent OCR coverage"):
        _run_repair("[Page 1]\n연구비 지원\n[Page 2]\n활동비 지원", parsed)


def test_source_unit_cannot_be_repeated_across_details() -> None:
    parsed = RepairResponse(
        represented_unit_ids=[],
        details=[
            _detail("P001-L0001", "Research funding is available.", "funding"),
            _detail("P001-L0001", "Funding covers materials.", "funding"),
        ],
        decorative=[], unresolved_unit_ids=[],
    )
    with pytest.raises(CoverageProviderError, match="inconsistent OCR coverage"):
        _run_repair("연구비 지원", parsed)


def test_grouped_evidence_follows_ocr_order_not_model_id_order() -> None:
    parsed = RepairResponse(
        represented_unit_ids=[],
        details=[RepairDetail(
            unit_ids=["P001-L0002", "P001-L0001"],
            text="The research allowance is paid as a scholarship.",
            category="funding", certain=True,
        )],
        decorative=[], unresolved_unit_ids=[],
    )

    result, _ = _run_repair("연구비 외 비용\n장학금 형태로 지급", parsed)

    assert result.notice.financial_support[0].source_evidence == "연구비 외 비용\n장학금 형태로 지급"


def test_short_latin_fragment_cannot_be_discarded_without_image_confirmation() -> None:
    parsed = RepairResponse(
        represented_unit_ids=[],
        details=[], decorative=[DecorativeFragment(unit_id="P001-L0001", reason="Broken logo lettering", certain=True)],
        unresolved_unit_ids=[],
    )
    with pytest.raises(CoverageProviderError, match="cannot be discarded"):
        _run_repair("UNIV", parsed)
    with pytest.raises(CoverageProviderError, match="cannot be discarded"):
        _run_repair("AI", parsed)
    with pytest.raises(CoverageProviderError, match="cannot be discarded"):
        _run_repair("TEPS", parsed)
    with pytest.raises(CoverageProviderError, match="cannot be discarded"):
        _run_repair("지원", parsed)


def test_cited_line_still_receives_semantic_audit() -> None:
    responses = FakeResponses(RepairResponse(
        represented_unit_ids=["P001-L0001"], details=[], decorative=[], unresolved_unit_ids=[],
    ))
    notice = NoticeData(key_details=[LabeledFact(text="Funding available", source_evidence="연구비 지원")])

    result = asyncio.run(repair_coverage(
        notice, "연구비 지원", client=SimpleNamespace(responses=responses)
    ))

    assert result.requests == 1
    assert len(responses.calls) == 1
    assert result.notice is not notice


def test_invented_primary_citation_is_removed_before_full_source_audit_recovers_the_real_rule() -> None:
    source = "휴학생도 참여는 가능하나 연구비 및 활동비 지원 대상에서는 제외"
    invented_quote = "미래세대도 참여는 가능하나 연구비 및 활동비 지원 대상에서는 제외"
    invented_english = "Participants who are leaving students can join but are excluded from funding for research and activities."
    notice = NoticeData(
        eligibility=[LabeledFact(
            text=invented_english, source_evidence=invented_quote,
            source_fact_ids=["F001"], state=ReviewState.VERIFIED,
        )],
        source_facts=[SourceFact(id="F001", kind="eligibility", source_text=invented_quote)],
    )
    complete = "Students on leave may participate, but are excluded from both research funding and activity allowance support."
    parsed = RepairResponse(
        represented_unit_ids=[], details=[_detail("P001-L0001", complete, "eligibility")],
        decorative=[], unresolved_unit_ids=[],
    )

    result, calls = _run_repair(source, parsed, notice=notice)

    payload = json.loads(calls[0]["input"][1]["content"])
    assert payload["source_units"][0]["cited_english_ids"] == []
    assert payload["source_units"][0]["requires_full_detail"] is True
    assert result.notice.eligibility == []
    assert [item.text for item in result.notice.key_details] == [complete]
    assert invented_english not in simplified_text(result.notice)
    assert result.notice.key_details[0].source_evidence == source
    assert all(fact.source_text == source for fact in result.notice.source_facts)
    assert not audit_coverage(result.notice, source).uncovered
    assert notice.eligibility[0].text == invented_english


def test_audit_reuses_english_fields_while_checking_every_source_line() -> None:
    source = "연구비 지원\n활동비 지원"
    english = "Research and activity funding are available."
    notice = NoticeData(financial_support=[LabeledFact(text=english, source_evidence=source)])
    parsed = RepairResponse(
        represented_unit_ids=["P001-L0001", "P001-L0002"], details=[], decorative=[], unresolved_unit_ids=[],
    )

    result, calls = _run_repair(source, parsed, notice=notice)

    payload = json.loads(calls[0]["input"][1]["content"])
    assert [unit["korean_ocr"] for unit in payload["source_units"]] == source.splitlines()
    assert [unit["cited_english_ids"] for unit in payload["source_units"]] == [["E001"], ["E001"]]
    assert payload["english_fields"] == {"E001": english}
    assert calls[0]["input"][1]["content"].count(english) == 1
    assert result.requests == 1
    assert result.repaired_unit_count == 0


def test_audit_rejects_invented_sanction_despite_real_source_quote_and_recovers_submission_rule() -> None:
    source = "비교과통합관리시스템(S Plus)로 제출"
    invented = "Failure to submit through specified channels may result in disqualification."
    supported = "Submit through the Extracurricular Integrated Management System (S Plus)."
    notice = NoticeData(
        title="Email Submission Required", purpose="Application submission instructions.",
        summary="Email submissions are mandatory; incorrect submissions lead to disqualification.",
        consequences=[LabeledFact(text=invented, source_evidence=source, source_page=1)],
        key_details=[LabeledFact(text=supported, source_evidence=source, source_page=1)],
    )
    initial = RepairResponse(
        represented_unit_ids=["P001-L0001"], details=[], decorative=[], unresolved_unit_ids=[],
        unsupported_english_ids=["E001", "E003", "E005"],
    )
    retry = RepairResponse(
        represented_unit_ids=[], details=[_detail("P001-L0001", supported, "application")],
        decorative=[], unresolved_unit_ids=[],
    )

    result, calls = _run_repair(source, [initial, retry], notice=notice)

    payload = json.loads(calls[0]["input"][1]["content"])
    assert payload["english_fields"]["E001"] == invented
    assert payload["notice_context"] == {
        "title": "E003", "purpose": "E004", "summary": "E005", "ambiguities": [], "unverified_items": [],
    }
    retry_payload = json.loads(calls[1]["input"][1]["content"])
    assert retry_payload["source_units"][0]["cited_english_ids"] == ["E002"]
    assert retry_payload["source_units"][0]["requires_full_detail"] is True
    assert any("unsupported claims" in issue for issue in retry_payload["source_units"][0]["previous_audit_issues"])
    assert invented not in calls[1]["input"][1]["content"]
    assert result.notice.consequences == []
    assert result.notice.title == "Untitled notice"
    assert result.notice.summary == ""
    assert result.notice.purpose == notice.purpose
    assert supported in simplified_text(result.notice)
    assert "disqualification" not in simplified_text(result.notice)
    assert audit_coverage(result.notice, source).uncovered == []
    assert notice.consequences[0].text == invented


def test_unsupported_summary_and_review_claims_are_removed_without_dropping_supported_facts() -> None:
    source = "휴학생도 참여 가능"
    supported = "Students on leave may participate."
    wrong = "Students on leave cannot participate."
    notice = NoticeData(
        key_details=[LabeledFact(text=supported, source_evidence=source)],
        summary=wrong, ambiguities=["", wrong], unverified_items=[""],
    )
    initial = RepairResponse(
        represented_unit_ids=["P001-L0001"], details=[], decorative=[], unresolved_unit_ids=[],
        unsupported_english_ids=["E002"],
    )

    result, calls = _run_repair(source, initial, notice=notice)

    assert result.requests == 1
    assert result.notice.summary == ""
    assert result.notice.ambiguities == [""]
    assert result.notice.key_details[0].text == supported
    context = json.loads(calls[0]["input"][1]["content"])["notice_context"]
    assert context["ambiguities"] == ["E002"]
    assert context["unverified_items"] == []


def test_audit_can_reject_an_unsupported_optional_document_qualifier_and_recover_required_submission() -> None:
    from app.models import DocumentRequirement

    source = "지원서를 제출"
    notice = NoticeData(required_documents=[DocumentRequirement(
        name="Application form", required=False, source_evidence=source,
    )])
    initial = RepairResponse(
        represented_unit_ids=["P001-L0001"], details=[], decorative=[], unresolved_unit_ids=[],
        unsupported_english_ids=["E001"],
    )
    required = "Submit the application form."
    retry = RepairResponse(
        represented_unit_ids=[], details=[_detail("P001-L0001", required, "application")],
        decorative=[], unresolved_unit_ids=[],
    )

    result, calls = _run_repair(source, [initial, retry], notice=notice)

    payload = json.loads(calls[0]["input"][1]["content"])
    assert payload["english_fields"] == {"E001": "Application form | optional"}
    assert result.notice.required_documents == []
    assert required in simplified_text(result.notice)
    assert "optional" not in simplified_text(result.notice)
    assert not audit_coverage(result.notice, source).uncovered


@pytest.mark.parametrize("faithful_retry", [True, False])
def test_rejected_sanction_cannot_return_as_initial_or_retry_detail(faithful_retry: bool) -> None:
    source = "비교과통합관리시스템(S Plus)로 제출"
    invented = "Failure to submit through the S Plus system may result in disqualification."
    notice = NoticeData(summary=invented)
    initial = RepairResponse(
        represented_unit_ids=[], details=[_detail("P001-L0001", invented, "application")],
        decorative=[], unresolved_unit_ids=[], unsupported_english_ids=["E001"],
    )
    faithful = "Submit through the Extracurricular Integrated Management System (S Plus)."
    retry = RepairResponse(
        represented_unit_ids=[], details=[_detail(
            "P001-L0001", faithful if faithful_retry else invented.replace(" system ", "\n system  "), "application",
        )], decorative=[], unresolved_unit_ids=[],
    )

    if not faithful_retry:
        with pytest.raises(CoverageProviderError, match="reintroduced a previously rejected unsupported English claim"):
            _run_repair(source, [initial, retry], notice=notice)
        return

    result, calls = _run_repair(source, [initial, retry], notice=notice)

    assert result.requests == 2
    assert result.notice.summary == ""
    assert [item.text for item in result.notice.key_details] == [faithful]
    retry_unit = json.loads(calls[1]["input"][1]["content"])["source_units"][0]
    assert retry_unit["previous_audit_issues"] == [
        "A repair detail reintroduced a previously rejected unsupported English claim."
    ]
    assert "disqualification" not in simplified_text(result.notice)
    assert not audit_coverage(result.notice, source).uncovered


@pytest.mark.parametrize("unsupported", [["E999"], ["E001", "E001"]])
def test_unsupported_english_ids_must_be_known_and_unique(unsupported: list[str]) -> None:
    source = "연구비 지원"
    notice = NoticeData(key_details=[LabeledFact(text="Research funding is available.", source_evidence=source)])
    invalid = RepairResponse(
        represented_unit_ids=["P001-L0001"], details=[], decorative=[], unresolved_unit_ids=[],
        unsupported_english_ids=unsupported,
    )
    with pytest.raises(CoverageProviderError, match="unknown or duplicate English fields"):
        _run_repair(source, invalid, notice=notice)


def test_removing_unsupported_action_renumbers_remaining_steps_and_recovers_its_real_source() -> None:
    from app.models import Action

    source = "신청서 제출\n지원팀에 문의"
    wrong = "Pay a non-refundable application fee."
    notice = NoticeData(actions=[
        Action(step=1, action=wrong, source_evidence="신청서 제출"),
        Action(step=2, action="Contact the support team.", source_evidence="지원팀에 문의"),
    ])
    initial = RepairResponse(
        represented_unit_ids=["P001-L0001", "P001-L0002"], details=[], decorative=[], unresolved_unit_ids=[],
        unsupported_english_ids=["E001"],
    )
    retry = RepairResponse(
        represented_unit_ids=[], details=[_detail("P001-L0001", "Submit the application form.", "application")],
        decorative=[], unresolved_unit_ids=[],
    )

    result, _ = _run_repair(source, [initial, retry], notice=notice)

    assert [(item.step, item.action) for item in result.notice.actions] == [(1, "Contact the support team.")]
    assert "Submit the application form." in simplified_text(result.notice)
    assert "application fee" not in simplified_text(result.notice)
    assert not audit_coverage(result.notice, source).uncovered


def test_audit_guard_labels_cannot_substitute_for_a_translated_restriction() -> None:
    source = "교내 타 프로그램에서 동일하거나 유사한 연구 주제로 지원을 받는 학생 및 팀은 참여 제한"
    echoed = "Students applying for these topics are restricted. Required conditions include on-campus scope, same topic, similar topic, and receiving support qualification."
    initial = RepairResponse(
        represented_unit_ids=[], details=[_detail("P001-L0001", echoed, "restriction")],
        decorative=[], unresolved_unit_ids=[],
    )
    complete = "Students and teams receiving support from other on-campus programs for the same or similar research topics are restricted from participation."
    retry = RepairResponse(
        represented_unit_ids=[], details=[_detail("P001-L0001", complete, "restriction")],
        decorative=[], unresolved_unit_ids=[],
    )

    result, calls = _run_repair(source, [initial, retry])

    assert result.requests == 2
    assert [item.text for item in result.notice.key_details] == [complete]
    unit = json.loads(calls[1]["input"][1]["content"])["source_units"][0]
    assert unit["previous_audit_issues"] == [
        "A repair detail echoed audit labels instead of translating the source meaning."
    ]


def test_unresolved_audit_returns_specific_source_correction() -> None:
    parsed = RepairResponse(
        represented_unit_ids=[], details=[], decorative=[], unresolved_unit_ids=["P002-L0001"],
    )
    with pytest.raises(CoverageRepairError) as exc:
        _run_repair("[Page 2]\n기간입C이끼지", [parsed, parsed])

    assert exc.value.corrections == [{
        "page": 2, "line": 1, "text": "기간입C이끼지",
        "reason": "Compare this line with the photo and correct its exact wording, or upload a close-up of this section.",
    }]


def test_source_correction_uses_physical_line_despite_blank_duplicate_and_symbol_lines() -> None:
    source = "[Page 1]\n참가자 모집\n\n참가자 모집\n---\n기간입C이끼지"
    notice = NoticeData(key_details=[LabeledFact(text="Participant recruitment", source_evidence="참가자 모집")])
    initial = RepairResponse(
        represented_unit_ids=["P001-L0001"], details=[], decorative=[], unresolved_unit_ids=["P001-L0002"],
    )
    retry = RepairResponse(
        represented_unit_ids=[], details=[], decorative=[], unresolved_unit_ids=["P001-L0002"],
    )
    with pytest.raises(CoverageRepairError) as exc:
        _run_repair(source, [initial, retry], notice=notice)

    assert exc.value.corrections[0]["line"] == 5
    assert exc.value.corrections[0]["text"] == "기간입C이끼지"
    assert [unit.id for unit in audit_coverage(notice, source).units] == ["P001-L0001", "P001-L0002"]


def test_audit_cannot_invent_contact_information() -> None:
    parsed = RepairResponse(
        represented_unit_ids=[],
        details=[_detail("P001-L0001", "Contact the research team at help@example.org.")],
        decorative=[], unresolved_unit_ids=[],
    )
    with pytest.raises(CoverageProviderError, match="invented or altered contact"):
        _run_repair("문의 연구팀", [parsed, parsed])


@pytest.mark.parametrize("field", ["summary", "purpose", "title", "key_details"])
def test_final_visible_output_cannot_add_contact_missing_from_source(field: str) -> None:
    source = "문의 02-710-2500"
    notice = NoticeData(key_details=[LabeledFact(
        text="Call 02-710-2500.", source_evidence=source,
    )])
    extra = "Call 02-710-2500 or 02-710-2501."
    if field == "key_details":
        notice.key_details[0].text = extra
    else:
        setattr(notice, field, extra)
    parsed = RepairResponse(
        represented_unit_ids=["P001-L0001"], details=[], decorative=[], unresolved_unit_ids=[],
    )

    with pytest.raises(CoverageProviderError, match="added contact information not present"):
        _run_repair(source, parsed, notice=notice)


def test_certain_spending_detail_omitting_printing_gets_targeted_retry() -> None:
    source = "연구비는 기자재 구입, 대여, 재료비, 도서 구입 및 인쇄비에 사용 가능"
    initial = RepairResponse(
        represented_unit_ids=[], decorative=[], unresolved_unit_ids=[],
        details=[_detail("P001-L0001", "Research funding covers equipment purchase and rental, materials, and books.", "funding")],
    )
    retry = RepairResponse(
        represented_unit_ids=[], decorative=[], unresolved_unit_ids=[],
        details=[_detail("P001-L0001", "Research funding covers equipment purchase and rental, materials, books, and printing.", "funding")],
    )

    result, calls = _run_repair(source, [initial, retry])

    assert result.requests == 2
    assert "printing" in result.notice.financial_support[0].text
    retry_unit = json.loads(calls[1]["input"][1]["content"])["source_units"][0]
    assert retry_unit["previous_audit_issues"] == ["A repair detail omitted source spending rules: printing"]


@pytest.mark.parametrize("incomplete", [
    "Research funding covers equipment purchase and rental, materials, and printing costs.",
    "Research funding covers equipment purchase and rental, materials, and books.",
])
def test_recognized_spending_clause_restores_all_categories_without_a_paid_retry(incomplete: str) -> None:
    source = "연구비는 기자재 구입 및 대여, 재료비, 도서 구입 및 인쇄비로 사용 가능"
    response = RepairResponse(
        represented_unit_ids=[], decorative=[], unresolved_unit_ids=[],
        details=[_detail("P001-L0001", incomplete, "funding")],
    )

    result, calls = _run_repair(source, response)

    assert result.requests == len(calls) == 1
    detail = result.notice.financial_support[0]
    assert detail.source_evidence == source
    assert detail.source_page == 1
    assert detail.text == (
        "Research expenses may cover equipment purchase or rental, material costs, book purchases, and printing costs."
    )
    assert audit_coverage(result.notice, source).uncovered == []


def test_card_payment_location_alone_does_not_replace_in_person_procedure() -> None:
    source = "융합교육원에 방문하여 카드결제"
    notice = NoticeData(locations=[LabeledFact(
        text="Pay by card at the Convergence Education Center.", source_evidence=source,
    )])
    initial = RepairResponse(
        represented_unit_ids=["P001-L0001"], details=[], decorative=[], unresolved_unit_ids=[],
    )
    retry = RepairResponse(
        represented_unit_ids=[], decorative=[], unresolved_unit_ids=[],
        details=[_detail("P001-L0001", "Visit the Convergence Education Center to pay by card for covered research purchases.", "funding")],
    )

    result, _ = _run_repair(source, [initial, retry], notice=notice)

    assert result.requests == 2
    assert result.notice.financial_support[0].text.startswith("Visit")


@pytest.mark.parametrize("outcome", ["represented", "detail"])
@pytest.mark.parametrize(("source", "incomplete", "complete", "category", "local_wording_repair"), [
    ("교내 타 프로그램에서 동일하거나 유사한 연구 주제로 지원을 받는 학생 및 팀은 참여 제한",
     "Students and teams supported for similar topics in other programs are restricted from participation.",
     "Students and teams receiving support for the same or a similar research topic from another on-campus program are restricted from participation.", "restriction", True),
    ("교내 타 프로그램에서 동일하거나 유사한 연구 주제로 지원을 받는 학생 및 팀은 참여 제한",
     "Students and teams with the same or similar research topics in other on-campus programs are restricted from participation.",
     "Students and teams receiving support for the same or a similar research topic from another on-campus program are restricted from participation.", "restriction", True),
    ("연구비: 1인당 최대 20만원", "Research funding: KRW 200,000 per team.",
     "Research funding: up to KRW 200,000 per person.", "funding", False),
])
def test_omitted_scope_and_funding_conditions_trigger_grounded_repair(
    outcome: str, source: str, incomplete: str, complete: str, category: str, local_wording_repair: bool,
) -> None:
    field = "financial_support" if category == "funding" else "warnings"
    notice = NoticeData.model_validate({field: [{
        "text": incomplete, "source_evidence": source, "source_fact_ids": ["F001"], "source_page": 1,
    }], "source_facts": [{"id": "F001", "kind": category, "source_text": source}]})
    initial = RepairResponse(
        represented_unit_ids=["P001-L0001"] if outcome == "represented" else [],
        details=[_detail("P001-L0001", incomplete, category)] if outcome == "detail" else [],
        decorative=[], unresolved_unit_ids=[],
    )
    retry = RepairResponse(
        represented_unit_ids=[], details=[_detail("P001-L0001", complete, category)],
        decorative=[], unresolved_unit_ids=[],
    )

    result, calls = _run_repair(source, [initial, retry], notice=notice)

    recovered_locally = outcome == "detail" and local_wording_repair
    assert result.requests == (1 if recovered_locally else 2)
    expected_text = correct_grounded_wording(incomplete if recovered_locally else complete, source)
    assert [item.text for item in getattr(result.notice, field)] == [expected_text]
    assert incomplete not in simplified_text(result.notice)
    assert getattr(result.notice, field)[0].source_fact_ids == ["F001", "F002"]
    assert getattr(result.notice, field)[0].source_evidence == source
    assert '"required_conditions"' in calls[0]["input"][1]["content"]
    assert notice.model_dump()[field][0]["text"] == incomplete


def test_cited_but_incomplete_research_topic_is_repaired() -> None:
    source = "AI 웨어러블 기기 발굴 및 MVP 제작"
    notice = NoticeData(key_details=[LabeledFact(
        text="Explore AI wearable devices.", source_evidence=source,
    )])
    parsed = RepairResponse(
        represented_unit_ids=[],
        details=[_detail("P001-L0001", "Produce an MVP for the AI wearable device.", "research_topic")],
        decorative=[], unresolved_unit_ids=[],
    )

    result, calls = _run_repair(source, parsed, notice=notice)

    assert result.repaired_unit_count == 1
    assert result.notice.key_details[0].text == "Explore AI wearable devices."
    assert result.notice.key_details[1].text.startswith("Produce an MVP")
    assert result.notice.key_details[1].source_evidence == source
    payload = json.loads(calls[0]["input"][1]["content"])
    assert payload["source_units"][0]["cited_english_ids"] == ["E001"]
    assert payload["english_fields"] == {"E001": "Explore AI wearable devices."}


@pytest.mark.parametrize("invalid", [
    _detail("P001-L0001", "Research funding is available.", "funding", certain=False),
    _detail("P001-L0001", "연구비 is available.", "funding"),
    _detail("P001-L0001", "The funding amount is unreadable.", "funding"),
])
def test_invalid_initial_detail_gets_one_targeted_retry(invalid: RepairDetail) -> None:
    initial = RepairResponse(represented_unit_ids=[], details=[invalid], decorative=[], unresolved_unit_ids=[])
    retry = RepairResponse(
        represented_unit_ids=[],
        details=[_detail("P001-L0001", "Research funding is available.", "funding")],
        decorative=[], unresolved_unit_ids=[],
    )

    result, calls = _run_repair("연구비 지원", [initial, retry])

    assert result.requests == len(calls) == 2
    assert len(result.notice.financial_support) == 1
    assert result.notice.financial_support[0].text == "Research funding is available."
    assert '"id": "P001-L0001"' in calls[1]["input"][1]["content"]


def test_wrong_literal_detail_gets_one_targeted_retry() -> None:
    source = "MVP(Minimum Value Prototyping)의 개발"
    initial = RepairResponse(
        represented_unit_ids=[],
        details=[_detail("P001-L0001", "Develop an MVP through Minimum Viable Prototyping.", "research_topic")],
        decorative=[], unresolved_unit_ids=[],
    )
    retry = RepairResponse(
        represented_unit_ids=[],
        details=[_detail("P001-L0001", "Develop an MVP through Minimum Value Prototyping.", "research_topic")],
        decorative=[], unresolved_unit_ids=[],
    )

    result, calls = _run_repair(source, [initial, retry])

    assert result.requests == len(calls) == 2
    assert result.notice.key_details[0].text.endswith("Minimum Value Prototyping.")


def test_exact_repair_duplicate_is_folded_into_existing_category_with_evidence() -> None:
    source = "[Page 1]\n연구비 지원\n연구 자금 지원"
    notice = NoticeData(
        financial_support=[LabeledFact(
            text="Research funding is available.",
            source_evidence="연구비 지원", source_fact_ids=["F001"], source_page=1,
        )],
        source_facts=[SourceFact(id="F001", kind="funding", source_text="연구비 지원")],
    )
    parsed = RepairResponse(
        represented_unit_ids=["P001-L0001"],
        details=[_detail("P001-L0002", "Research funding is available.", "funding")],
        decorative=[], unresolved_unit_ids=[],
    )

    result, _ = _run_repair(source, parsed, notice=notice)

    assert result.requests == 1
    assert result.repaired_unit_count == 1
    assert result.notice.key_details == []
    assert len(result.notice.financial_support) == 1
    kept = result.notice.financial_support[0]
    assert kept.source_evidence == "연구비 지원\n연구 자금 지원"
    assert kept.source_fact_ids == ["F001", "F002"]
    assert len(result.notice.source_facts) == 2
    assert audit_coverage(result.notice, source).uncovered == []


def test_multi_clause_line_wrongly_marked_represented_gets_targeted_retry() -> None:
    source = "연구비 1인당 최대 20만원, 장비 구입 및 임차, 재료비, 도서 구입 및 인쇄 가능"
    notice = NoticeData(financial_support=[LabeledFact(
        text="Research funding is up to KRW 200,000 per person.", source_evidence=source,
    )])
    initial = RepairResponse(
        represented_unit_ids=["P001-L0001"], details=[], decorative=[], unresolved_unit_ids=[],
    )
    retry = RepairResponse(
        represented_unit_ids=[],
        details=[_detail(
            "P001-L0001",
            "Research funding is up to KRW 200,000 per person and covers equipment purchase or rental, materials, books, and printing.",
            "funding",
        )],
        decorative=[], unresolved_unit_ids=[],
    )

    result, calls = _run_repair(source, [initial, retry], notice=notice)

    assert result.requests == 2
    assert (result.input_tokens, result.output_tokens, result.total_tokens) == (206, 94, 300)
    assert result.repaired_unit_count == 1
    assert len(result.notice.financial_support) == 2
    assert calls[1]["input"][0]["content"].startswith("Your previous coverage audit")
    assert '"id": "P001-L0001"' in calls[1]["input"][1]["content"]
    assert '"korean_ocr": "연구비 1인당 최대 20만원' in calls[1]["input"][1]["content"]


def test_cited_wrong_financial_fact_cannot_pass_as_represented() -> None:
    source = "연구비: 1인당 최대 20만원"
    notice = NoticeData(key_details=[LabeledFact(
        text="AI-related research", source_evidence=source, source_page=1,
    )])
    initial = RepairResponse(
        represented_unit_ids=["P001-L0001"], details=[], decorative=[], unresolved_unit_ids=[],
    )
    retry = RepairResponse(
        represented_unit_ids=[], decorative=[], unresolved_unit_ids=[],
        details=[_detail("P001-L0001", "Research funding is up to KRW 200,000 per person.", "funding")],
    )

    result, calls = _run_repair(source, [initial, retry], notice=notice)

    assert result.requests == len(calls) == 2
    assert result.notice.financial_support[0].text == "Research funding is up to KRW 200,000 per person."


def test_cited_correct_financial_fact_remains_represented() -> None:
    source = "연구비: 1인당 최대 20만원"
    notice = NoticeData(financial_support=[LabeledFact(
        text="Research funding is up to KRW 200,000 per person.", source_evidence=source, source_page=1,
    )])
    parsed = RepairResponse(
        represented_unit_ids=["P001-L0001"], details=[], decorative=[], unresolved_unit_ids=[],
    )

    result, calls = _run_repair(source, parsed, notice=notice)

    assert result.requests == len(calls) == 1
    assert result.repaired_unit_count == 0


def test_fully_grounded_dotted_application_dates_need_no_provider_retry() -> None:
    source = "신청 기간: 2026.08.24(월) ~ 2026.09.20(일)"
    parsed = RepairResponse(
        represented_unit_ids=[], decorative=[], unresolved_unit_ids=[],
        details=[_detail("P001-L0001", "Application Period: 2026.08.24 (Monday) ~ 2026.09.20 (Sunday)", "application")],
    )

    result, calls = _run_repair(source, parsed)

    assert result.requests == len(calls) == 1
    assert "2026.08.24" in simplified_text(result.notice)
    assert "2026.09.20" in simplified_text(result.notice)


def test_model_date_omission_is_a_provider_failure_without_source_correction() -> None:
    source = "신청 기간: 2026.08.24(월) ~ 2026.09.20(일)"
    parsed = RepairResponse(
        represented_unit_ids=[], decorative=[], unresolved_unit_ids=[],
        details=[_detail("P001-L0001", "The application period is announced.", "application")],
    )

    with pytest.raises(CoverageProviderError, match="omitted exact source values") as exc:
        _run_repair(source, [parsed, parsed])

    assert "retry the analysis" in str(exc.value).lower()
    assert not hasattr(exc.value, "corrections")


@pytest.mark.parametrize(("source", "wrong", "correct"), [
    ("2026.09.20 신청 마감", "Applications close on September 21, 2026.", "Applications close on September 20, 2026."),
    ("TOEIC 800 이상", "An English test score is required.", "A TOEIC score of at least 800 is required."),
])
def test_cited_wrong_date_or_test_score_gets_targeted_retry(source: str, wrong: str, correct: str) -> None:
    notice = NoticeData(key_details=[LabeledFact(text=wrong, source_evidence=source, source_page=1)])
    initial = RepairResponse(
        represented_unit_ids=["P001-L0001"], details=[], decorative=[], unresolved_unit_ids=[],
    )
    retry = RepairResponse(
        represented_unit_ids=[], decorative=[], unresolved_unit_ids=[],
        details=[_detail("P001-L0001", correct)],
    )

    result, calls = _run_repair(source, [initial, retry], notice=notice)

    assert result.requests == len(calls) == 2
    assert result.notice.key_details[-1].text == correct


def test_uncited_unit_wrongly_marked_represented_gets_targeted_retry() -> None:
    initial = RepairResponse(
        represented_unit_ids=["P001-L0001"], details=[], decorative=[], unresolved_unit_ids=[],
    )
    retry = RepairResponse(
        represented_unit_ids=[], details=[_detail("P001-L0001", "Research funding is available.", "funding")],
        decorative=[], unresolved_unit_ids=[],
    )

    result, calls = _run_repair("연구비 지원", [initial, retry])

    assert result.requests == len(calls) == 2
    assert result.notice.financial_support[0].text == "Research funding is available."


def test_one_retry_handles_wrongly_represented_unresolved_and_omitted_ids() -> None:
    initial = RepairResponse(
        represented_unit_ids=["P001-L0001"],
        details=[], decorative=[], unresolved_unit_ids=["P001-L0002"],
    )
    retry = RepairResponse(
        represented_unit_ids=[],
        details=[
            _detail("P001-L0001", "Research support is available.", "funding"),
            _detail("P001-L0002", "Activity support is available.", "funding"),
            _detail("P001-L0003", "Applications close on September 20.", "application"),
        ], decorative=[], unresolved_unit_ids=[],
    )

    result, calls = _run_repair("연구비 지원\n활동비 지원\n9월 20일 신청 마감", [initial, retry])

    assert result.requests == len(calls) == 2
    assert result.repaired_unit_count == 3
    retry_payload = calls[1]["input"][1]["content"]
    assert all(f'"id": "P001-L{index:04d}"' in retry_payload for index in (1, 2, 3))


@pytest.mark.parametrize("invalid", [
    RepairResponse(
        represented_unit_ids=["P001-L0001"],
        details=[_detail("P001-L0001", "Research support is available.")],
        decorative=[], unresolved_unit_ids=[],
    ),
    RepairResponse(
        represented_unit_ids=[], details=[], decorative=[],
        unresolved_unit_ids=["P001-L0001", "P001-L0001"],
    ),
    RepairResponse(
        represented_unit_ids=[],
        details=[_detail("P001-L9999", "Research support is available.")],
        decorative=[], unresolved_unit_ids=[],
    ),
])
def test_invalid_initial_partition_fails_before_retry(invalid: RepairResponse) -> None:
    responses = FakeResponses(invalid)

    with pytest.raises(CoverageProviderError, match="inconsistent OCR coverage"):
        asyncio.run(repair_coverage(
            NoticeData(), "연구비 지원", client=SimpleNamespace(responses=responses),
        ))

    assert len(responses.calls) == 1


def test_targeted_retry_must_cover_exact_ids_with_no_represented_claim() -> None:
    initial = RepairResponse(
        represented_unit_ids=["P001-L0001"], details=[], decorative=[], unresolved_unit_ids=[],
    )
    for retry in (
        RepairResponse(represented_unit_ids=[], details=[], decorative=[], unresolved_unit_ids=[]),
        RepairResponse(represented_unit_ids=["P001-L0001"], details=[], decorative=[], unresolved_unit_ids=[]),
        RepairResponse(represented_unit_ids=[], details=[_detail("P001-L9999", "Research funding is available.")], decorative=[], unresolved_unit_ids=[]),
    ):
        with pytest.raises(CoverageProviderError, match="targeted OCR audit"):
            _run_repair("연구비 지원", [initial, retry])


def test_targeted_retry_still_rejects_uncertain_or_unresolved_source() -> None:
    initial = RepairResponse(
        represented_unit_ids=["P001-L0001"], details=[], decorative=[], unresolved_unit_ids=[],
    )
    uncertain = RepairResponse(
        represented_unit_ids=[], details=[_detail("P001-L0001", "Maybe funding is available.", certain=False)],
        decorative=[], unresolved_unit_ids=[],
    )
    with pytest.raises(CoverageProviderError, match="uncertain, empty, or not fully in English"):
        _run_repair("연구비 지원", [initial, uncertain])

    unresolved = RepairResponse(
        represented_unit_ids=[], details=[], decorative=[], unresolved_unit_ids=["P001-L0001"],
    )
    with pytest.raises(CoverageRepairError, match="could not be confidently interpreted"):
        _run_repair("연구비 지원", [initial, unresolved])


def test_targeted_retry_provider_failure_remains_a_provider_error() -> None:
    initial = RepairResponse(
        represented_unit_ids=["P001-L0001"], details=[], decorative=[], unresolved_unit_ids=[],
    )

    class FailingRetryResponses(FakeResponses):
        async def parse(self, **kwargs):
            if self.calls:
                raise RuntimeError("provider unavailable")
            return await super().parse(**kwargs)

    responses = FailingRetryResponses(initial)
    with pytest.raises(CoverageProviderError, match="could not audit notice completeness"):
        asyncio.run(repair_coverage(
            NoticeData(), "연구비 지원", client=SimpleNamespace(responses=responses),
        ))


def test_duplicate_or_unknown_represented_id_fails_closed() -> None:
    notice = NoticeData(key_details=[LabeledFact(text="Funding is available.", source_evidence="연구비 지원")])
    for ids in (["P001-L0001", "P001-L0001"], ["P001-L9999"]):
        parsed = RepairResponse(represented_unit_ids=ids, details=[], decorative=[], unresolved_unit_ids=[])
        with pytest.raises(CoverageProviderError, match="inconsistent OCR coverage"):
            _run_repair("연구비 지원", parsed, notice=notice)


def test_provider_failure_is_not_misreported_as_incomplete_ocr() -> None:
    responses = FakeResponses(None)
    with pytest.raises(CoverageProviderError, match="no usable completeness audit"):
        asyncio.run(repair_coverage(
            NoticeData(), "연구비 지원", client=SimpleNamespace(responses=responses)
        ))


def test_large_notice_fails_before_request_even_when_all_lines_cited() -> None:
    source = "\n".join(f"내용 {index}" for index in range(MAX_COVERAGE_UNITS + 1))
    notice = NoticeData(key_details=[LabeledFact(text="Contents", source_evidence=source)])
    responses = FakeResponses(None)

    with pytest.raises(CoverageRepairError, match="too many OCR lines"):
        asyncio.run(repair_coverage(
            notice, source, client=SimpleNamespace(responses=responses)
        ))
    assert responses.calls == []
