from __future__ import annotations

import asyncio
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


def test_repair_schema_is_valid_for_openai_structured_outputs() -> None:
    schema = to_strict_json_schema(RepairResponse)
    assert schema["additionalProperties"] is False
    assert "represented_unit_ids" in schema["required"]
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
        with pytest.raises(CoverageRepairError, match="uncertain, empty, or not fully in English") as exc:
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
    with pytest.raises(CoverageRepairError, match="cannot be discarded"):
        _run_repair("UNIV", parsed)
    with pytest.raises(CoverageRepairError, match="cannot be discarded"):
        _run_repair("AI", parsed)
    with pytest.raises(CoverageRepairError, match="cannot be discarded"):
        _run_repair("TEPS", parsed)
    with pytest.raises(CoverageRepairError, match="cannot be discarded"):
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
    assert '"cited_english": ["Explore AI wearable devices."]' in calls[0]["input"][1]["content"]


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
    with pytest.raises(CoverageRepairError, match="uncertain, empty, or not fully in English"):
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
