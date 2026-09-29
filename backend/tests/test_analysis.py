from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from openai.lib._pydantic import to_strict_json_schema
from pydantic import ValidationError

from app.models import Action, LabeledFact, NoticeData, SourceFact
from app.services.demos import DEMOS
from app.services.fidelity import calculate_fidelity, select_templates
from app.services.semantic import OpenAISemanticProvider, SemanticError
from app.services.text import appears_korean, simplified_text


def test_korean_detection() -> None:
    assert appears_korean("외국인 유학생 등록 안내입니다.")
    assert not appears_korean("This is an English notice.")


def test_schema_rejects_duplicate_fact_ids() -> None:
    with pytest.raises(ValidationError):
        NoticeData(source_facts=[SourceFact(id="F001", kind="date", source_text="날짜"), SourceFact(id="F001", kind="action", source_text="신청")])


def test_schema_rejects_malformed_model_response() -> None:
    with pytest.raises(ValidationError):
        NoticeData.model_validate({"actions": [{"step": 0, "action": ""}], "unexpected": "invented"})


def test_notice_schema_is_valid_for_strict_structured_outputs() -> None:
    schema = to_strict_json_schema(NoticeData)

    def assert_closed_objects(node: object) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node.get("additionalProperties") is False
            for value in node.values():
                assert_closed_objects(value)
        elif isinstance(node, list):
            for value in node:
                assert_closed_objects(value)

    assert_closed_objects(schema)


def test_fact_coverage_and_template_selection() -> None:
    notice = DEMOS[0].notice
    report = calculate_fidelity(notice)
    templates = select_templates(notice)
    assert report.critical_fields_in_source == report.critical_fields_represented
    assert report.potentially_missing == []
    assert templates.checklist
    assert templates.step_flow
    assert templates.warning_cards
    assert templates.information_cards


def test_researcher_can_override_a_template() -> None:
    notice = DEMOS[4].notice.model_copy(deep=True)
    assert select_templates(notice).timeline
    notice.template_overrides.timeline = False
    assert not select_templates(notice).timeline


def test_missing_openai_key_is_actionable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(SemanticError, match="OPENAI_API_KEY"):
        OpenAISemanticProvider()


def test_demo_preserves_optional_document_and_numbers() -> None:
    scholarship = DEMOS[2].notice
    optional = next(item for item in scholarship.required_documents if "Volunteer" in item.name)
    assert optional.required is False
    assert "3.5" in scholarship.eligibility[0].text
    assert scholarship.deadlines[0].time == "6:00 p.m."
    assert scholarship.exceptions[0].text == "Exchange students cannot apply."


def test_simplified_text_retains_structured_details() -> None:
    notice = NoticeData(
        actions=[Action(
            step=1, action="Apply online", details="Postal applications are not accepted.",
            deadline="September 30 at 18:00", location="Recruitment site",
            required_items=["Test score"],
        )],
        key_details=[LabeledFact(text="Probation lasts three months.")],
        fees=[LabeledFact(text="No fee stated.")],
        links=[LabeledFact(text="https://example.org/apply")],
    )

    output = simplified_text(notice)
    assert "Postal applications are not accepted" in output
    assert "September 30 at 18:00" in output
    assert "Bring: Test score" in output
    assert "Probation lasts three months" in output
    assert "https://example.org/apply" in output


def test_semantic_prompt_includes_spatial_hints_only_when_supplied() -> None:
    seen: list[str] = []

    class FakeResponses:
        async def parse(self, *, input, **kwargs):
            seen.append(input[1]["content"])
            return SimpleNamespace(output_parsed=NoticeData(title="Recruitment notice"), usage=None)

    client = SimpleNamespace(responses=FakeResponses())
    provider = OpenAISemanticProvider(client=client)
    asyncio.run(provider.analyze("TOEIC\n800 이상", "TOEIC 800 or higher", "en", layout_context="(550,560) TOEIC\n(550,590) 800 이상"))

    assert "SPATIAL OCR HINTS" in seen[0]
    assert "(550,590) 800 이상" in seen[0]


def test_fidelity_exposes_ocr_lines_missing_from_structured_output() -> None:
    notice = NoticeData(eligibility=[LabeledFact(
        text="No age restriction", source_evidence="연령제한 없음",
    )])

    report = calculate_fidelity(
        notice,
        "[Page 1]\n연령제한 없음\n거시경제,AI·성장전략,산업경쟁력 조사·연구\n글로벌 협력사업",
    )

    assert report.unmapped_source_line_count == 2
    assert "글로벌 협력사업" in report.unmapped_source_lines
