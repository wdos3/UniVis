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


def _run_repair(
    source: str, response: RepairResponse | list[RepairResponse], *, notice: NoticeData | None = None,
    allow_partial: bool = False, unverified_source_texts: tuple[str, ...] = (),
):
    responses = FakeResponses(response)
    result = asyncio.run(repair_coverage(
        notice or NoticeData(), source,
        layout_context="(320,450) AI topic", client=SimpleNamespace(responses=responses),
        allow_partial=allow_partial, unverified_source_texts=unverified_source_texts,
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
        _run_repair("[Page 1]\n연구비 지원\n[Page 2]\n활동비 지원", [parsed, parsed])


def test_source_unit_cannot_be_repeated_across_details() -> None:
    parsed = RepairResponse(
        represented_unit_ids=[],
        details=[
            _detail("P001-L0001", "Research funding is available.", "funding"),
            _detail("P001-L0001", "Funding covers materials.", "funding"),
        ],
        decorative=[], unresolved_unit_ids=[],
    )
    with pytest.raises(CoverageProviderError, match="inconsistent targeted OCR audit"):
        _run_repair("연구비 지원", [parsed, parsed])


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
        _run_repair("UNIV", [parsed, parsed])
    with pytest.raises(CoverageProviderError, match="cannot be discarded"):
        _run_repair("AI", [parsed, parsed])
    with pytest.raises(CoverageProviderError, match="cannot be discarded"):
        _run_repair("TEPS", [parsed, parsed])
    with pytest.raises(CoverageProviderError, match="cannot be discarded"):
        _run_repair("지원", [parsed, parsed])


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
        _run_repair(source, [invalid, invalid], notice=notice)


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
def test_spending_clause_omission_gets_grounded_retry_without_rewriting_the_source(incomplete: str) -> None:
    source = "연구비는 기자재 구입 및 대여, 재료비, 도서 구입 및 인쇄비로 사용 가능"
    response = RepairResponse(
        represented_unit_ids=[], decorative=[], unresolved_unit_ids=[],
        details=[_detail("P001-L0001", incomplete, "funding")],
    )

    complete = "Research expenses may cover equipment purchase or rental, material costs, book purchases, and printing costs."
    retry = RepairResponse(
        represented_unit_ids=[], decorative=[], unresolved_unit_ids=[],
        details=[_detail("P001-L0001", complete, "funding")],
    )
    result, calls = _run_repair(source, [response, retry])

    assert result.requests == len(calls) == 2
    detail = result.notice.financial_support[0]
    assert detail.source_evidence == source
    assert detail.source_page == 1
    assert detail.text == complete
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
     "Students and teams receiving support for the same or a similar research topic from another on-campus program are restricted from participation.", "restriction", False),
    ("교내 타 프로그램에서 동일하거나 유사한 연구 주제로 지원을 받는 학생 및 팀은 참여 제한",
     "Students and teams with the same or similar research topics in other on-campus programs are restricted from participation.",
     "Students and teams receiving support for the same or a similar research topic from another on-campus program are restricted from participation.", "restriction", False),
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
    assert len(result.notice.financial_support) == 1
    assert "equipment purchase or rental, materials, books, and printing" in result.notice.financial_support[0].text
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
def test_repeated_invalid_partition_fails_after_one_bounded_retry(invalid: RepairResponse) -> None:
    responses = FakeResponses([invalid, invalid])

    with pytest.raises(CoverageProviderError, match="targeted OCR audit"):
        asyncio.run(repair_coverage(
            NoticeData(), "연구비 지원", client=SimpleNamespace(responses=responses),
        ))

    assert len(responses.calls) == 2


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
        with pytest.raises(CoverageProviderError, match="targeted OCR audit"):
            _run_repair("연구비 지원", [parsed, parsed], notice=notice)


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


@pytest.mark.parametrize(("source", "first", "second", "first_category", "second_category"), [
    (
        "등록금 납부 기간: 2027.02.15 ~ 2027.02.19\n납부 금액: 1,240,000원",
        "Pay tuition between February 15, 2027 and February 19, 2027.",
        "The tuition payment is KRW 1,240,000.", "schedule", "fee",
    ),
    (
        "응시 자격: 학사 학위 소지자\n서류 제출 마감: 2027.01.12 17:00",
        "Applicants must hold a bachelor's degree.",
        "Submit the documents by January 12, 2027 at 17:00.", "eligibility", "application",
    ),
    (
        "입사 신청 기간: 2027.01.10 ~ 2027.01.20\n보증금 50,000원 납부",
        "Apply for dormitory residence between January 10, 2027 and January 20, 2027.",
        "Pay a KRW 50,000 deposit.", "schedule", "fee",
    ),
    (
        "수강 신청: 2027.03.02 ~ 2027.03.05\n준비물: 학생증 및 노트북",
        "Register for courses between March 2, 2027 and March 5, 2027.",
        "Bring your student ID and laptop.", "schedule", "document",
    ),
    (
        "신청 대상: 학부 재학생\n장학금: 1인당 50만원",
        "Enrolled undergraduate students may apply.",
        "The scholarship is KRW 500,000 per person.", "eligibility", "funding",
    ),
])
def test_partition_recovery_preserves_unaffected_facts_across_notice_categories(
    source: str, first: str, second: str, first_category: str, second_category: str,
) -> None:
    initial = RepairResponse(
        represented_unit_ids=["P001-L0001"],
        details=[
            _detail("P001-L0001", "A generic unsupported summary."),
            _detail("P001-L0002", second, second_category),
        ], decorative=[], unresolved_unit_ids=[],
    )
    retry = RepairResponse(
        represented_unit_ids=[], details=[_detail("P001-L0001", first, first_category)],
        decorative=[], unresolved_unit_ids=[],
    )

    result, calls = _run_repair(source, [initial, retry])

    assert result.requests == len(calls) == 2
    assert result.repaired_unit_count == 2
    digest = simplified_text(result.notice)
    assert first in digest and second in digest
    assert "generic unsupported summary" not in digest
    assert not re.search(r"[가-힣]", digest)
    assert audit_coverage(result.notice, source).uncovered == []
    retry_payload = json.loads(calls[1]["input"][1]["content"])
    assert [unit["id"] for unit in retry_payload["source_units"]] == ["P001-L0001"]
    assert "more than once" in " ".join(retry_payload["source_units"][0]["previous_audit_issues"])
    if second_category == "fee":
        assert [item.text for item in result.notice.fees] == [second]
        assert result.notice.financial_support == []
    assert calls[0]["model"] == calls[1]["model"] == "gpt-4o-mini"


def test_cross_page_provider_group_gets_one_retry_with_separate_evidence() -> None:
    source = "[Page 1]\n입사 신청서 제출\n[Page 2]\n보증금 50,000원 납부"
    initial = RepairResponse(
        represented_unit_ids=[], details=[RepairDetail(
            unit_ids=["P001-L0001", "P002-L0001"],
            text="Submit a residence application and pay a KRW 50,000 deposit.",
            category="other", certain=True,
        )], decorative=[], unresolved_unit_ids=[],
    )
    retry = RepairResponse(
        represented_unit_ids=[], details=[
            _detail("P001-L0001", "Submit the residence application.", "application"),
            _detail("P002-L0001", "Pay a KRW 50,000 deposit.", "fee"),
        ], decorative=[], unresolved_unit_ids=[],
    )

    result, calls = _run_repair(source, [initial, retry])

    assert result.requests == len(calls) == 2
    assert [(item.source_page, item.source_evidence) for item in result.notice.key_details] == [
        (1, "입사 신청서 제출"),
    ]
    assert [(item.source_page, item.source_evidence) for item in result.notice.fees] == [
        (2, "보증금 50,000원 납부"),
    ]
    assert audit_coverage(result.notice, source).uncovered == []


def test_unknown_source_id_rechecks_all_source_without_guessing_its_evidence() -> None:
    source = "신청서 제출\n면접 참석"
    initial = RepairResponse(
        represented_unit_ids=[], details=[
            _detail("P001-L0001", "Submit the application form.", "application"),
            _detail("P001-L0002", "Attend the interview.", "application"),
            _detail("P001-L9999", "Pay an application fee.", "fee"),
        ], decorative=[], unresolved_unit_ids=[],
    )
    retry = RepairResponse(
        represented_unit_ids=[], details=initial.details[:2], decorative=[], unresolved_unit_ids=[],
    )

    result, calls = _run_repair(source, [initial, retry])

    assert result.requests == 2
    retry_payload = json.loads(calls[1]["input"][1]["content"])
    assert [unit["id"] for unit in retry_payload["source_units"]] == ["P001-L0001", "P001-L0002"]
    assert result.notice.fees == []
    assert "application fee" not in simplified_text(result.notice)
    assert all(item.source_evidence in source for item in result.notice.key_details)


def test_malformed_english_ids_get_one_full_source_and_display_recheck() -> None:
    source = "신청서 제출\n면접 참석"
    notice = NoticeData(
        title="Hiring instructions", summary="Interviews are optional.",
        key_details=[LabeledFact(text="Submit the application form.", source_evidence="신청서 제출")],
    )
    initial = RepairResponse(
        represented_unit_ids=["P001-L0001"],
        details=[_detail("P001-L0002", "Attend the interview.", "application")],
        decorative=[], unresolved_unit_ids=[], unsupported_english_ids=["E999"],
    )
    retry = RepairResponse(
        represented_unit_ids=[], details=[
            _detail("P001-L0001", "Submit the application form.", "application"),
            _detail("P001-L0002", "Attend the interview.", "application"),
        ], decorative=[], unresolved_unit_ids=[], unsupported_english_ids=["E003"],
    )

    result, calls = _run_repair(source, [initial, retry], notice=notice)

    assert result.requests == len(calls) == 2
    initial_payload = json.loads(calls[0]["input"][1]["content"])
    retry_payload = json.loads(calls[1]["input"][1]["content"])
    assert retry_payload["english_fields"] == initial_payload["english_fields"]
    assert len(retry_payload["source_units"]) == 2
    assert result.notice.summary == ""
    assert "optional" not in simplified_text(result.notice)


def test_legible_fragment_misclassified_as_decoration_can_be_recovered() -> None:
    initial = RepairResponse(
        represented_unit_ids=[], details=[],
        decorative=[DecorativeFragment(unit_id="P001-L0001", reason="Short heading", certain=True)],
        unresolved_unit_ids=[],
    )
    retry = RepairResponse(
        represented_unit_ids=[], details=[_detail("P001-L0001", "Required documents", "document")],
        decorative=[], unresolved_unit_ids=[],
    )

    result, calls = _run_repair("제출 서류", [initial, retry])

    assert result.requests == len(calls) == 2
    assert result.decorative_unit_count == 0
    assert "Required documents" in simplified_text(result.notice)
    assert audit_coverage(result.notice, "제출 서류").uncovered == []


def test_literal_term_in_an_unseen_notice_is_preserved_without_named_prompt_examples() -> None:
    source = "국제교류 (Global Bridge) 참여자 모집"
    initial = RepairResponse(
        represented_unit_ids=[], details=[_detail("P001-L0001", "Join the Global Bridges exchange.", "topic")],
        decorative=[], unresolved_unit_ids=[],
    )
    retry = RepairResponse(
        represented_unit_ids=[], details=[_detail("P001-L0001", "Recruitment for the Global Bridge international exchange.", "topic")],
        decorative=[], unresolved_unit_ids=[],
    )

    result, calls = _run_repair(source, [initial, retry])

    assert result.requests == len(calls) == 2
    assert result.notice.key_details[0].label == "Topic or option"
    assert "Global Bridge international exchange" in simplified_text(result.notice)
    assert all("Minimum Value Prototyping" not in call["input"][0]["content"] for call in calls)


@pytest.mark.parametrize("initial", [
    RepairResponse(
        represented_unit_ids=["P001-L0001", "P001-L0001"],
        details=[], decorative=[], unresolved_unit_ids=[],
    ),
    RepairResponse(
        represented_unit_ids=[], details=[], decorative=[],
        unresolved_unit_ids=["P001-L0001", "P001-L0001"],
    ),
    RepairResponse(
        represented_unit_ids=[], details=[RepairDetail(
            unit_ids=["P001-L0001", "P001-L0001"], text="Deadline announced.", category="schedule", certain=True,
        )], decorative=[], unresolved_unit_ids=[],
    ),
    RepairResponse(
        represented_unit_ids=[], details=[RepairDetail(
            unit_ids=["P001-L0001", "P001-L9999"], text="Deadline announced.", category="schedule", certain=True,
        )], decorative=[], unresolved_unit_ids=[],
    ),
    RepairResponse(
        represented_unit_ids=[], details=[RepairDetail(
            unit_ids=[], text="Deadline announced.", category="schedule", certain=True,
        )], decorative=[], unresolved_unit_ids=[],
    ),
])
def test_duplicate_empty_and_mixed_unknown_ids_can_be_recovered_without_guessing(initial: RepairResponse) -> None:
    source = "2027.03.05 접수 마감"
    faithful = "Applications close on March 5, 2027."
    retry = RepairResponse(
        represented_unit_ids=[], details=[_detail("P001-L0001", faithful, "schedule")],
        decorative=[], unresolved_unit_ids=[],
    )

    result, calls = _run_repair(source, [initial, retry])

    assert result.requests == len(calls) == 2
    assert [item.text for item in result.notice.key_details] == [faithful]
    assert result.notice.key_details[0].source_evidence == source
    assert audit_coverage(result.notice, source).uncovered == []


def test_overlapping_grouped_claims_retry_all_their_source_units() -> None:
    source = "지원서 제출\n자기소개서 제출\n면접 참석"
    initial = RepairResponse(
        represented_unit_ids=[], details=[
            RepairDetail(
                unit_ids=["P001-L0001", "P001-L0002"], text="Submit your application and personal statement.",
                category="document", certain=True,
            ),
            RepairDetail(
                unit_ids=["P001-L0002", "P001-L0003"], text="Submit your personal statement and attend the interview.",
                category="application", certain=True,
            ),
        ], decorative=[], unresolved_unit_ids=[],
    )
    retry = RepairResponse(
        represented_unit_ids=[], details=[
            _detail("P001-L0001", "Submit your application.", "document"),
            _detail("P001-L0002", "Submit your personal statement.", "document"),
            _detail("P001-L0003", "Attend the interview.", "application"),
        ], decorative=[], unresolved_unit_ids=[],
    )

    result, calls = _run_repair(source, [initial, retry])

    assert result.requests == len(calls) == 2
    assert result.repaired_unit_count == 3
    retry_payload = json.loads(calls[1]["input"][1]["content"])
    assert [unit["korean_ocr"] for unit in retry_payload["source_units"]] == source.splitlines()
    assert audit_coverage(result.notice, source).uncovered == []


def test_partial_notice_keeps_main_facts_when_a_small_seal_remains_unreadable() -> None:
    source = "신청 마감: 2027.03.05\n\n대H"
    deadline = "Applications close on March 5, 2027."
    initial = RepairResponse(
        represented_unit_ids=[], details=[_detail("P001-L0001", deadline, "schedule")],
        decorative=[], unresolved_unit_ids=["P001-L0002"],
    )
    retry = RepairResponse(
        represented_unit_ids=[], details=[], decorative=[], unresolved_unit_ids=["P001-L0002"],
    )
    invented = "The university guarantees acceptance."
    notice = NoticeData(
        title="Guaranteed acceptance", purpose=invented, summary=invented,
        key_details=[LabeledFact(text=invented, source_evidence="대H", source_fact_ids=["F001"], source_page=1)],
        source_facts=[SourceFact(id="F001", kind="other", source_text="대H", source_page=1)],
    )

    result, calls = _run_repair(source, [initial, retry], notice=notice, allow_partial=True)

    assert result.requests == len(calls) == 2
    assert result.has_verification_gaps is True
    assert [(unit.id, unit.page, unit.line) for unit in result.unverified_units] == [("P001-L0002", 1, 3)]
    assert result.repaired_unit_count == 1
    assert deadline in simplified_text(result.notice)
    assert invented not in simplified_text(result.notice)
    assert result.notice.title == "Untitled notice"
    assert result.notice.summary == result.notice.purpose == ""
    assert result.notice.source_facts[0].state == ReviewState.NEEDS_REVIEW
    assert result.notice.unverified_items == [
        "Page 1, line 3: This section could not be verified automatically. "
        "Its details are withheld; a clearer photo of this area may recover them."
    ]
    assert not re.search(r"[가-힣]", "\n".join(result.notice.unverified_items))
    assert [unit.id for unit in audit_coverage(result.notice, source).uncovered] == ["P001-L0002"]


@pytest.mark.parametrize(("source_line", "invalid", "certain"), [
    ("보증금 60,000원", "A deposit is required.", True),
    ("문의 담당팀", "Contact the team at invented@example.org.", True),
    ("신청 방법", "신청 instructions.", True),
    ("수료증 발급", "Completion certificates are issued.", False),
    ("국제교류 (Future Bridge)", "International exchange through Future Bridges.", True),
])
def test_partial_mode_withholds_invalid_repair_meaning_instead_of_displaying_it(
    source_line: str, invalid: str, certain: bool,
) -> None:
    source = f"입사 신청서 제출\n{source_line}"
    valid = "Submit the residence application."
    bad = _detail("P001-L0002", invalid, certain=certain)
    initial = RepairResponse(
        represented_unit_ids=[], details=[_detail("P001-L0001", valid, "application"), bad],
        decorative=[], unresolved_unit_ids=[],
    )
    retry = RepairResponse(represented_unit_ids=[], details=[bad], decorative=[], unresolved_unit_ids=[])

    result, calls = _run_repair(source, [initial, retry], allow_partial=True)

    assert result.requests == len(calls) == 2
    assert result.has_verification_gaps is True
    assert [unit.id for unit in result.unverified_units] == ["P001-L0002"]
    digest = simplified_text(result.notice)
    assert valid in digest and invalid not in digest
    assert "invented@example.org" not in digest
    assert not re.search(r"[가-힣]", digest)
    assert all(fact.state == ReviewState.NEEDS_REVIEW for fact in result.notice.source_facts)
    assert "Page 1, line 2" in result.notice.unverified_items[0]


def test_partial_mode_records_omitted_ids_from_a_valid_but_incomplete_second_audit() -> None:
    initial = RepairResponse(
        represented_unit_ids=[], details=[_detail("P001-L0001", "Submit the application form.", "application")],
        decorative=[], unresolved_unit_ids=[],
    )
    retry = RepairResponse(represented_unit_ids=[], details=[], decorative=[], unresolved_unit_ids=[])

    result, calls = _run_repair("신청서 제출\n면접 일정 안내", [initial, retry], allow_partial=True)

    assert result.requests == len(calls) == 2
    assert "Submit the application form." in simplified_text(result.notice)
    assert [unit.id for unit in result.unverified_units] == ["P001-L0002"]
    assert result.has_verification_gaps is True


@pytest.mark.parametrize("retry", [
    RepairResponse(
        represented_unit_ids=[], details=[_detail("P001-L9999", "Attend the interview.")],
        decorative=[], unresolved_unit_ids=[],
    ),
    RepairResponse(
        represented_unit_ids=[], details=[
            _detail("P001-L0002", "Attend the interview."), _detail("P001-L0002", "An interview is scheduled."),
        ], decorative=[], unresolved_unit_ids=[],
    ),
])
def test_partial_mode_discards_malformed_second_protocol_response_and_withholds_its_targets(retry: RepairResponse) -> None:
    initial = RepairResponse(
        represented_unit_ids=[], details=[_detail("P001-L0001", "Submit the application form.")],
        decorative=[], unresolved_unit_ids=["P001-L0002"],
    )

    result, calls = _run_repair("신청서 제출\n면접 안내", [initial, retry], allow_partial=True)

    assert result.requests == len(calls) == 2
    assert "Submit the application form." in simplified_text(result.notice)
    assert "Attend the interview." not in simplified_text(result.notice)
    assert "An interview is scheduled." not in simplified_text(result.notice)
    assert [unit.id for unit in result.unverified_units] == ["P001-L0002"]
    assert result.has_verification_gaps is True


def test_partial_mode_discards_cross_page_second_group_and_keeps_unaffected_first_audit_facts() -> None:
    initial = RepairResponse(
        represented_unit_ids=[], details=[_detail("P001-L0001", "Submit the application form.")],
        decorative=[], unresolved_unit_ids=["P001-L0002", "P002-L0001"],
    )
    retry = RepairResponse(
        represented_unit_ids=[], details=[RepairDetail(
            unit_ids=["P001-L0002", "P002-L0001"], text="Both interview instructions apply together.",
            category="application", certain=True,
        )], decorative=[], unresolved_unit_ids=[],
    )

    result, calls = _run_repair(
        "[Page 1]\n신청서 제출\n면접 대상\n[Page 2]\n면접 안내", [initial, retry], allow_partial=True,
    )

    assert result.requests == len(calls) == 2
    assert "Submit the application form." in simplified_text(result.notice)
    assert "Both interview instructions" not in simplified_text(result.notice)
    assert [unit.id for unit in result.unverified_units] == ["P001-L0002", "P002-L0001"]
    assert result.has_verification_gaps is True


def test_partial_mode_removes_an_unsafe_primary_contact_and_marks_its_real_source_location() -> None:
    source = "담당팀에 문의\n신청서 제출"
    invented = "Contact the team at invented@example.org."
    notice = NoticeData(key_details=[LabeledFact(text=invented, source_evidence="담당팀에 문의")])
    parsed = RepairResponse(
        represented_unit_ids=["P001-L0001"],
        details=[_detail("P001-L0002", "Submit the application form.", "application")],
        decorative=[], unresolved_unit_ids=[],
    )

    result, calls = _run_repair(source, parsed, notice=notice, allow_partial=True)

    assert result.requests == len(calls) == 1
    assert invented not in simplified_text(result.notice)
    assert "Submit the application form." in simplified_text(result.notice)
    assert [unit.id for unit in result.unverified_units] == ["P001-L0001"]
    assert result.has_verification_gaps is True


def test_partial_mode_removes_an_unlocated_unsafe_summary_without_fabricating_a_source_line() -> None:
    source = "신청서 제출"
    notice = NoticeData(summary="Contact invented@example.org.")
    parsed = RepairResponse(
        represented_unit_ids=[], details=[_detail("P001-L0001", "Submit the application form.", "application")],
        decorative=[], unresolved_unit_ids=[],
    )

    result, _ = _run_repair(source, parsed, notice=notice, allow_partial=True)

    assert result.notice.summary == ""
    assert "Submit the application form." in simplified_text(result.notice)
    assert result.unverified_units == ()
    assert result.has_verification_gaps is True
    assert result.notice.unverified_items == [
        "An unverified generated detail was withheld. Verify important information against the original image."
    ]


def test_partial_mode_withholds_all_lines_of_an_altered_literal_split_across_ocr_lines() -> None:
    source = "국제교류 (Future\nBridge) 참여자 모집\n신청서 제출"
    parsed = RepairResponse(
        represented_unit_ids=[], details=[
            _detail("P001-L0001", "International Future exchanges.", "topic"),
            _detail("P001-L0002", "Join the Bridges program.", "topic"),
            _detail("P001-L0003", "Submit the application form.", "application"),
        ], decorative=[], unresolved_unit_ids=[],
    )

    result, _ = _run_repair(source, parsed, allow_partial=True)

    assert [unit.id for unit in result.unverified_units] == ["P001-L0001", "P001-L0002"]
    assert result.repaired_unit_count == 1
    digest = simplified_text(result.notice)
    assert "Submit the application form." in digest
    assert "Future" not in digest and "Bridges" not in digest
    assert len(result.notice.unverified_items) == 2


def test_known_unreadable_contact_cannot_be_reconstructed_by_the_semantic_audit() -> None:
    source = "신청서 제출\n문의: 02-710-25n0"
    invented = "Call 02-710-2500."
    parsed = RepairResponse(
        represented_unit_ids=[], details=[
            _detail("P001-L0001", "Submit the application form.", "application"),
            _detail("P001-L0002", invented, "contact"),
        ], decorative=[], unresolved_unit_ids=[],
    )
    notice = NoticeData(key_details=[LabeledFact(text=invented, source_evidence="문의: 02-710-25n0")])

    result, calls = _run_repair(
        source, parsed, notice=notice, allow_partial=True,
        unverified_source_texts=(" 문의: 02-710-25n0 ",),
    )

    assert result.requests == len(calls) == 1
    assert invented not in simplified_text(result.notice)
    assert "Submit the application form." in simplified_text(result.notice)
    assert [unit.id for unit in result.unverified_units] == ["P001-L0002"]
    assert "25n0" not in "\n".join(result.notice.unverified_items)


def test_unreadable_source_hints_do_not_change_the_default_strict_contract() -> None:
    parsed = RepairResponse(
        represented_unit_ids=[], details=[], decorative=[], unresolved_unit_ids=["P001-L0001"],
    )

    with pytest.raises(CoverageRepairError, match="could not be confidently interpreted"):
        _run_repair("대H", [parsed, parsed], unverified_source_texts=("대H",))


def test_partial_mode_keeps_complete_valid_notice_context_when_no_gaps_exist() -> None:
    source = "신청서 제출"
    notice = NoticeData(title="Application instructions", summary="Submit the application form.")
    parsed = RepairResponse(
        represented_unit_ids=[], details=[_detail("P001-L0001", "Submit the application form.", "application")],
        decorative=[], unresolved_unit_ids=[],
    )

    result, _ = _run_repair(source, parsed, notice=notice, allow_partial=True)

    assert result.unverified_units == ()
    assert result.has_verification_gaps is False
    assert result.notice.title == notice.title and result.notice.summary == notice.summary
    assert result.notice.unverified_items == []


def test_withheld_unsafe_fragment_is_reported_even_if_a_complete_valid_fact_covers_the_source() -> None:
    from app.models import Contact

    source = "신청서를 학생지원팀에 제출"
    notice = NoticeData(
        key_details=[LabeledFact(text="Submit the application form to the Student Support Team.", source_evidence=source)],
        contacts=[Contact(
            name="Student Support Team", email="invented@example.org",
            source_evidence="학생지원팀", source_fact_ids=["F001"], source_page=1,
        )],
        source_facts=[SourceFact(id="F001", kind="contact", source_text="학생지원팀", source_page=1)],
    )
    parsed = RepairResponse(
        represented_unit_ids=["P001-L0001"], details=[], decorative=[], unresolved_unit_ids=[],
    )

    result, _ = _run_repair(source, parsed, notice=notice, allow_partial=True)

    assert result.notice.contacts == []
    assert result.unverified_units == ()
    assert result.has_verification_gaps is True
    assert "Submit the application form" in simplified_text(result.notice)
    assert result.notice.source_facts[0].state == ReviewState.NEEDS_REVIEW
    assert result.notice.unverified_items == [
        "An unverified generated detail was withheld. Verify important information against the original image."
    ]


def test_valid_independent_detail_survives_pruning_of_a_same_worded_primary_with_unreadable_evidence() -> None:
    source = "신청서 제출\n대H"
    valid = "Submit the application form."
    notice = NoticeData(key_details=[LabeledFact(text=valid, source_evidence=source, source_page=1)])
    initial = RepairResponse(
        represented_unit_ids=[], details=[_detail("P001-L0001", valid, "application")],
        decorative=[], unresolved_unit_ids=["P001-L0002"],
    )
    retry = RepairResponse(
        represented_unit_ids=[], details=[], decorative=[], unresolved_unit_ids=["P001-L0002"],
    )

    result, _ = _run_repair(source, [initial, retry], notice=notice, allow_partial=True)

    assert [item.text for item in result.notice.key_details] == [valid]
    assert result.notice.key_details[0].source_evidence == "신청서 제출"
    assert [unit.id for unit in result.unverified_units] == ["P001-L0002"]
    assert result.repaired_unit_count == 1


def test_partial_mode_withholds_all_claims_when_retry_english_ids_cannot_be_localized() -> None:
    source = "신청서 제출\n면접 참석"
    initial = RepairResponse(
        represented_unit_ids=[], details=[_detail("P001-L0001", "Submit the application form.")],
        decorative=[], unresolved_unit_ids=["P001-L0002"],
    )
    retry = RepairResponse(
        represented_unit_ids=[], details=[_detail("P001-L0002", "Attend the interview.")],
        decorative=[], unresolved_unit_ids=[], unsupported_english_ids=["E999"],
    )

    result, calls = _run_repair(source, [initial, retry], allow_partial=True)

    assert result.requests == len(calls) == 2
    assert simplified_text(result.notice) == ""
    assert [unit.id for unit in result.unverified_units] == ["P001-L0001", "P001-L0002"]
    assert result.has_verification_gaps is True
    assert result.usage_complete is True and result.total_tokens == 300


@pytest.mark.parametrize("fail_first", [True, False])
def test_partial_provider_failure_withholds_unaudited_claims_and_reports_only_known_usage(fail_first: bool) -> None:
    source = "신청서 제출\n면접 안내"
    initial = RepairResponse(
        represented_unit_ids=[], details=[_detail("P001-L0001", "Submit the application form.")],
        decorative=[], unresolved_unit_ids=["P001-L0002"],
    )

    class FailingResponses:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        async def parse(self, **kwargs):
            self.calls.append(kwargs)
            if fail_first or len(self.calls) == 2:
                raise RuntimeError("provider unavailable")
            return SimpleNamespace(
                output_parsed=initial,
                usage=SimpleNamespace(input_tokens=103, output_tokens=47, total_tokens=150),
            )

    responses = FailingResponses()
    notice = NoticeData(summary="All applicants are guaranteed acceptance.")
    result = asyncio.run(repair_coverage(
        notice, source, client=SimpleNamespace(responses=responses), allow_partial=True,
    ))

    assert result.requests == len(responses.calls) == (1 if fail_first else 2)
    assert result.failed_requests == 1 and result.usage_complete is False
    assert result.total_tokens == (0 if fail_first else 150)
    assert result.input_tokens == (0 if fail_first else 103)
    assert result.output_tokens == (0 if fail_first else 47)
    assert result.has_verification_gaps is True
    assert result.notice.summary == ""
    if fail_first:
        assert simplified_text(result.notice) == ""
        assert [unit.id for unit in result.unverified_units] == ["P001-L0001", "P001-L0002"]
    else:
        assert "Submit the application form." in simplified_text(result.notice)
        assert [unit.id for unit in result.unverified_units] == ["P001-L0002"]
    assert all("Page 1, line" in gap for gap in result.notice.unverified_items)


@pytest.mark.parametrize("token", ["OK", "2", "O", "0", "e", "JU", "00", "Um", "Pay"])
def test_short_standalone_ocr_echoes_cannot_substitute_for_comprehension(token: str) -> None:
    bad = RepairResponse(
        represented_unit_ids=[], details=[_detail("P001-L0001", token)], decorative=[], unresolved_unit_ids=[],
    )
    with pytest.raises(CoverageProviderError, match="short OCR fragment"):
        _run_repair(token, [bad, bad])

    result, calls = _run_repair(token, [bad, bad], allow_partial=True)

    assert result.requests == len(calls) == 2
    assert simplified_text(result.notice) == ""
    assert result.has_verification_gaps is True
    assert [unit.text for unit in result.unverified_units] == [token]
    assert not re.search(rf"(?<![A-Za-z0-9]){re.escape(token)}(?![A-Za-z0-9])", result.notice.unverified_items[0].split(":", 1)[1])


def test_short_source_values_can_have_full_english_score_context() -> None:
    source = "OPIc\nIH"
    notice = NoticeData(eligibility=[LabeledFact(
        text="OPIc: IH or higher", source_evidence=source, source_page=1,
    )])
    parsed = RepairResponse(
        represented_unit_ids=["P001-L0001"],
        details=[_detail("P001-L0002", "OPIc: IH or higher", "eligibility")],
        decorative=[], unresolved_unit_ids=[],
    )

    result, _ = _run_repair(source, parsed, notice=notice)

    assert "OPIc: IH or higher" in simplified_text(result.notice)
    assert result.has_verification_gaps is False


def test_grouped_short_value_and_korean_context_are_interpreted_as_one_fact() -> None:
    parsed = RepairResponse(
        represented_unit_ids=[], details=[RepairDetail(
            unit_ids=["P001-L0001", "P001-L0002"], text="Up to 2 participants are selected.",
            category="eligibility", certain=True,
        )], decorative=[], unresolved_unit_ids=[],
    )

    result, _ = _run_repair("2\n명까지 선발", parsed)

    assert "Up to 2 participants are selected." in simplified_text(result.notice)
    assert result.repaired_unit_count == 2


def test_unfinished_object_fragment_cannot_invent_mandatory_submission() -> None:
    source = "외국인 유학생의 입사 신청서를"
    invented = "International students are required to submit residence applications."
    bad = RepairResponse(
        represented_unit_ids=[], details=[_detail("P001-L0001", invented, "application")],
        decorative=[], unresolved_unit_ids=[],
    )
    with pytest.raises(CoverageProviderError, match="unfinished source fragment"):
        _run_repair(source, [bad, bad])

    result, _ = _run_repair(source, [bad, bad], allow_partial=True)

    assert invented not in simplified_text(result.notice)
    assert result.has_verification_gaps is True
    assert [unit.text for unit in result.unverified_units] == [source]


def test_fragment_retry_includes_the_completing_source_clause_and_preserves_restriction_direction() -> None:
    source = "중복 신청자의 기숙사 지원서를\n접수하지 않음"
    invented = "Duplicate applicants must submit dormitory applications."
    initial = RepairResponse(
        represented_unit_ids=[], details=[
            _detail("P001-L0001", invented, "application"),
            _detail("P001-L0002", "Applications are not accepted.", "restriction"),
        ], decorative=[], unresolved_unit_ids=[],
    )
    correct = "Dormitory applications from duplicate applicants are not accepted."
    retry = RepairResponse(
        represented_unit_ids=[], details=[RepairDetail(
            unit_ids=["P001-L0001", "P001-L0002"], text=correct, category="restriction", certain=True,
        )], decorative=[], unresolved_unit_ids=[],
    )

    result, calls = _run_repair(source, [initial, retry])

    assert result.requests == len(calls) == 2
    assert correct in simplified_text(result.notice)
    assert invented not in simplified_text(result.notice)
    retry_payload = json.loads(calls[1]["input"][1]["content"])
    assert [unit["korean_ocr"] for unit in retry_payload["source_units"]] == source.splitlines()


@pytest.mark.parametrize("allow_partial", [False, True])
def test_complete_audit_detail_removes_a_conflicting_typed_primary_deadline(allow_partial: bool) -> None:
    from app.models import Deadline

    source = "납부 마감: 2029.11.18"
    notice = NoticeData(
        deadlines=[Deadline(date="November 17, 2029", source_evidence=source, source_fact_ids=["F001"], source_page=1)],
        source_facts=[SourceFact(id="F001", kind="deadline", source_text=source, source_page=1)],
    )
    correct = "The payment deadline is November 18, 2029."
    parsed = RepairResponse(
        represented_unit_ids=[], details=[_detail("P001-L0001", correct, "schedule")],
        decorative=[], unresolved_unit_ids=[],
    )

    result, _ = _run_repair(source, parsed, notice=notice, allow_partial=allow_partial)

    digest = simplified_text(result.notice)
    assert correct in digest
    assert "November 17" not in digest
    assert result.notice.deadlines == []
    assert result.notice.key_details[0].source_fact_ids == ["F001", "F002"]
    assert result.has_verification_gaps is False


@pytest.mark.parametrize("allow_partial", [False, True])
def test_complete_audit_detail_removes_a_conflicting_primary_amount(allow_partial: bool) -> None:
    source = "참가비: 35,000원"
    wrong = "The participation fee is KRW 25,000."
    correct = "The participation fee is KRW 35,000."
    notice = NoticeData(fees=[LabeledFact(text=wrong, source_evidence=source, source_page=1)])
    parsed = RepairResponse(
        represented_unit_ids=[], details=[_detail("P001-L0001", correct, "fee")],
        decorative=[], unresolved_unit_ids=[],
    )

    result, _ = _run_repair(source, parsed, notice=notice, allow_partial=allow_partial)

    assert [item.text for item in result.notice.fees] == [correct]
    assert wrong not in simplified_text(result.notice)
    assert result.has_verification_gaps is False


def test_quantitative_reconciliation_does_not_trust_a_wrong_primary_page_tag() -> None:
    source = "[Page 1]\n신청서 제출\n[Page 2]\n참가비 1만원"
    wrong = "Pay KRW 99,000."
    notice = NoticeData(fees=[LabeledFact(text=wrong, source_evidence="참가비 1만원", source_page=1)])
    parsed = RepairResponse(
        represented_unit_ids=[], details=[
            _detail("P001-L0001", "Submit the application form.", "application"),
            _detail("P002-L0001", "The fee is KRW 10,000.", "fee"),
        ], decorative=[], unresolved_unit_ids=[],
    )

    result, _ = _run_repair(source, parsed, notice=notice, allow_partial=True)

    assert wrong not in simplified_text(result.notice)
    assert [item.text for item in result.notice.fees] == ["The fee is KRW 10,000."]
    assert result.notice.fees[0].source_page == 2


def test_grouped_complete_condition_repair_replaces_a_stale_same_quote_primary() -> None:
    source = "*휴학생도 참여는 가능하나,연구비 및\n활동비 지원 대상에서는 제외"
    incomplete = "Students on leave can participate but are excluded from funding support."
    complete = "Students on leave may participate, but are excluded from both research funding and activity allowance support."
    notice = NoticeData(eligibility=[LabeledFact(
        text=incomplete, source_evidence=source.replace("\n", " "), source_page=1,
    )])
    parsed = RepairResponse(
        represented_unit_ids=[], details=[RepairDetail(
            unit_ids=["P001-L0001", "P001-L0002"], text=complete, category="eligibility", certain=True,
        )], decorative=[], unresolved_unit_ids=[],
    )

    result, _ = _run_repair(source, parsed, notice=notice, allow_partial=True)

    assert [item.text for item in result.notice.eligibility] == [complete]
    assert incomplete not in simplified_text(result.notice)
    assert result.has_verification_gaps is False


@pytest.mark.parametrize(("source", "bad", "correct", "category"), [
    (
        "신청 마감: 2028년 3월 20일", "Applications close on March 20, 2028 or March 19, 2028.",
        "Applications close on March 20, 2028.", "schedule",
    ),
    (
        "참가비: 1만원", "The fee is KRW 10,000 plus an additional KRW 99,000.",
        "The fee is KRW 10,000.", "fee",
    ),
])
def test_complete_quantitative_audit_supersedes_primary_containing_correct_and_invented_values(
    source: str, bad: str, correct: str, category: str,
) -> None:
    notice = NoticeData(key_details=[LabeledFact(text=bad, source_evidence=source, source_page=1)])
    parsed = RepairResponse(
        represented_unit_ids=[], details=[_detail("P001-L0001", correct, category)],
        decorative=[], unresolved_unit_ids=[],
    )

    result, _ = _run_repair(source, parsed, notice=notice, allow_partial=True)

    digest = simplified_text(result.notice)
    assert correct in digest and bad not in digest
    assert "March 19" not in digest and "99,000" not in digest
    assert result.has_verification_gaps is False


def test_quantitative_replacement_preserves_a_valid_identical_quote_on_another_page() -> None:
    from app.models import Deadline

    quote = "신청 마감: 2028년 3월 20일"
    source = f"[Page 1]\n{quote}\n[Page 2]\n{quote}"
    notice = NoticeData(deadlines=[
        Deadline(date="March 19, 2028", source_evidence=quote, source_page=1),
        Deadline(date="March 20, 2028", source_evidence=quote, source_page=2),
    ])
    parsed = RepairResponse(
        represented_unit_ids=["P002-L0001"],
        details=[_detail("P001-L0001", "Applications close on March 20, 2028.", "schedule")],
        decorative=[], unresolved_unit_ids=[],
    )

    result, _ = _run_repair(source, parsed, notice=notice, allow_partial=True)

    assert [(item.date, item.source_page) for item in result.notice.deadlines] == [("March 20, 2028", 2)]
    assert result.has_verification_gaps is False
    assert result.unverified_units == ()


def test_award_misclassified_as_fee_is_retried_as_financial_support() -> None:
    source = "상금: 대상 30만원"
    initial = RepairResponse(
        represented_unit_ids=[], details=[_detail("P001-L0001", "Pay an entry fee of KRW 300,000.", "fee")],
        decorative=[], unresolved_unit_ids=[],
    )
    correct = "The grand prize is KRW 300,000."
    retry = RepairResponse(
        represented_unit_ids=[], details=[_detail("P001-L0001", correct, "funding")],
        decorative=[], unresolved_unit_ids=[],
    )

    result, calls = _run_repair(source, [initial, retry])

    assert len(calls) == 2
    assert result.notice.fees == []
    assert [item.text for item in result.notice.financial_support] == [correct]


@pytest.mark.parametrize("source", ["500000", "재료비 카드결제 지원"])
def test_bare_amount_or_covered_expense_cannot_establish_an_applicant_fee(source: str) -> None:
    bad = RepairResponse(
        represented_unit_ids=[], details=[_detail("P001-L0001", "Pay a KRW 500,000 fee by card for materials.", "fee")],
        decorative=[], unresolved_unit_ids=[],
    )
    with pytest.raises(CoverageProviderError, match="payment owed"):
        _run_repair(source, [bad, bad])

    result, _ = _run_repair(source, [bad, bad], allow_partial=True)

    assert result.notice.fees == []
    assert result.has_verification_gaps is True
    assert simplified_text(result.notice) == ""


def test_grouped_award_headers_and_values_retain_each_pairing_as_support() -> None:
    source = "시상\n대상\n300000원\n우수상\n150000원"
    correct = "The grand prize is KRW 300,000; the excellence award is KRW 150,000."
    parsed = RepairResponse(
        represented_unit_ids=[], details=[RepairDetail(
            unit_ids=[f"P001-L{line:04d}" for line in range(1, 6)],
            text=correct, category="funding", certain=True,
        )], decorative=[], unresolved_unit_ids=[],
    )

    result, _ = _run_repair(source, parsed)

    assert result.notice.fees == []
    assert [item.text for item in result.notice.financial_support] == [correct]
    assert result.notice.financial_support[0].source_evidence == source


def test_primary_award_fee_is_withheld_even_when_audit_wrongly_marks_it_represented() -> None:
    source = "상금 30만원\n신청서 제출"
    notice = NoticeData(fees=[LabeledFact(
        text="Pay an entry fee of KRW 300,000.", source_evidence="상금 30만원", source_page=1,
    )])
    parsed = RepairResponse(
        represented_unit_ids=["P001-L0001"],
        details=[_detail("P001-L0002", "Submit the application form.", "application")],
        decorative=[], unresolved_unit_ids=[],
    )

    result, _ = _run_repair(source, parsed, notice=notice, allow_partial=True)

    assert result.notice.fees == []
    assert "Submit the application form." in simplified_text(result.notice)
    assert result.has_verification_gaps is True
    assert [unit.id for unit in result.unverified_units] == ["P001-L0001"]


@pytest.mark.parametrize("source,text", [
    ("참가비 3만원 납부", "Pay the participation fee of KRW 30,000."),
    ("참가비 무료", "Participation is free."),
])
def test_grounded_payment_or_free_entry_remains_a_valid_fee(source: str, text: str) -> None:
    parsed = RepairResponse(
        represented_unit_ids=[], details=[_detail("P001-L0001", text, "fee")],
        decorative=[], unresolved_unit_ids=[],
    )

    result, _ = _run_repair(source, parsed)

    assert [item.text for item in result.notice.fees] == [text]
    assert result.has_verification_gaps is False


@pytest.mark.parametrize("count", ["0명", "00명"])
def test_bare_zero_recruitment_notation_does_not_establish_zero_vacancies(count: str) -> None:
    source = count + "\n온라인 지원"
    notice = NoticeData(key_details=[LabeledFact(text="0 recruits.", source_evidence=count, source_page=1)])
    parsed = RepairResponse(
        represented_unit_ids=["P001-L0001"],
        details=[_detail("P001-L0002", "Apply online.", "application")],
        decorative=[], unresolved_unit_ids=[],
    )
    result, _ = _run_repair(source, parsed, notice=notice, allow_partial=True)
    assert "0 recruits" not in simplified_text(result.notice)
    assert "Apply online" in simplified_text(result.notice)
    assert [unit.id for unit in result.unverified_units] == ["P001-L0001"]


def test_zero_non_recruitment_count_is_not_rejected_as_a_vacancy_placeholder() -> None:
    parsed = RepairResponse(
        represented_unit_ids=[], details=[_detail("P001-L0001", "There are 0 confirmed cases.", "other")],
        decorative=[], unresolved_unit_ids=[],
    )
    result, _ = _run_repair("확진자 0명", parsed, allow_partial=True)
    assert "0 confirmed cases" in simplified_text(result.notice)
    assert result.has_verification_gaps is False


def test_unfinished_alternative_cannot_gain_an_invented_date_continuation() -> None:
    source = "11.19(목) 또는\n온라인 신청"
    parsed = RepairResponse(
        represented_unit_ids=[], details=[
            _detail("P001-L0001", "November 19 or December.", "schedule"),
            _detail("P001-L0002", "Apply online.", "application"),
        ], decorative=[], unresolved_unit_ids=[],
    )
    result, _ = _run_repair(source, parsed, allow_partial=True)
    assert "November 19 or December" not in simplified_text(result.notice)
    assert "Apply online" in simplified_text(result.notice)
    assert result.has_verification_gaps is True


def test_unfinished_restriction_does_not_assign_an_invented_recipient_scope() -> None:
    source = "타 프로그램에서 동일한 연구 주제로\n지원을 받는 학생은 제외\n온라인 신청"
    wrong = "Participants must not have the same research topic as another program."
    notice = NoticeData(key_details=[LabeledFact(text=wrong, source_evidence=source.splitlines()[0], source_page=1)])
    parsed = RepairResponse(
        represented_unit_ids=["P001-L0001"], details=[
            _detail("P001-L0002", "Students receiving support are excluded.", "restriction"),
            _detail("P001-L0003", "Apply online.", "application"),
        ], decorative=[], unresolved_unit_ids=[],
    )
    result, _ = _run_repair(source, parsed, notice=notice, allow_partial=True)
    assert wrong not in simplified_text(result.notice)
    assert "Apply online" in simplified_text(result.notice)
    assert result.has_verification_gaps


def test_grouped_restriction_preserves_the_actual_recipients_and_topic_scope() -> None:
    source = "타 프로그램에서 동일한 연구 주제로\n지원을 받는 학생은 제외"
    correct = "Students receiving funding for the same research topic from another program are excluded."
    parsed = RepairResponse(represented_unit_ids=[], details=[RepairDetail(
        unit_ids=["P001-L0001", "P001-L0002"], text=correct, category="restriction", certain=True,
    )], decorative=[], unresolved_unit_ids=[])
    result, _ = _run_repair(source, parsed, allow_partial=True)
    assert correct in simplified_text(result.notice)
    assert not result.has_verification_gaps
