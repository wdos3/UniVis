from __future__ import annotations

import pytest
from openai.lib._pydantic import to_strict_json_schema
from pydantic import ValidationError

from app.models import NoticeData, SourceFact
from app.services.demos import DEMOS
from app.services.fidelity import calculate_fidelity, select_templates
from app.services.semantic import OpenAISemanticProvider, SemanticError
from app.services.text import appears_korean


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
