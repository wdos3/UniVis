from __future__ import annotations

import asyncio
from types import SimpleNamespace

from openai.lib._pydantic import to_strict_json_schema

from app.models import NoticeData
from app.services.semantic import OpenAISemanticProvider, _SemanticNotice, normalize_notice


def test_model_schema_omits_application_metadata_but_keeps_semantics_and_evidence() -> None:
    compact = to_strict_json_schema(_SemanticNotice)
    public = to_strict_json_schema(NoticeData)
    assert {"source_language", "target_language", "template_overrides"} <= set(public["properties"])
    assert not {"source_language", "target_language", "template_overrides"} & set(compact["properties"])
    assert {"source_facts", "financial_support", "actions", "key_details", "required_documents"} <= set(compact["properties"])
    for name in ("LabeledFact", "Action", "SourceFact", "Contact", "DocumentRequirement"):
        properties = compact["$defs"][name]["properties"]
        assert not {"source_page", "source_image_id", "bounding_box"} & set(properties)
        assert "source_text" in properties if name == "SourceFact" else "source_evidence" in properties
        assert compact["$defs"][name]["additionalProperties"] is False
        assert set(compact["$defs"][name]["required"]) == set(properties)
    assert "BoundingBox" not in compact["$defs"]
    assert "TemplateOverrides" not in compact["$defs"]


def test_compact_semantic_response_restores_public_defaults_and_exact_page_evidence() -> None:
    payload = {
        "title": "Research support",
        "financial_support": [{
            "text": "Research funding: up to KRW 200,000 per person.",
            "source_evidence": "연구비: 1인당 최대 20만원",
            "source_fact_ids": ["F001"],
        }],
        "source_facts": [{"id": "F001", "kind": "funding", "source_text": "연구비: 1인당 최대 20만원"}],
    }

    class Responses:
        async def parse(self, *, text_format, **kwargs):
            assert text_format is _SemanticNotice
            return SimpleNamespace(output_parsed=text_format.model_validate(payload), usage=None)

    result = asyncio.run(OpenAISemanticProvider(client=SimpleNamespace(responses=Responses())).analyze(
        "[Page 1]\n참가자 모집\n[Page 2]\n연구비: 1인당 최대 20만원", "Funding available", "en",
    ))

    assert type(result.notice) is NoticeData
    assert result.notice.source_language == "ko"
    assert result.notice.target_language == "en"
    assert result.notice.template_overrides.model_dump() == NoticeData().template_overrides.model_dump()
    funding = result.notice.financial_support[0]
    assert funding.source_page == result.notice.source_facts[0].source_page == 2
    assert funding.source_evidence == payload["financial_support"][0]["source_evidence"]
    assert funding.source_image_id is None
    assert funding.bounding_box is None
    assert result.requests == 1


def test_repeated_source_quote_on_multiple_pages_gets_no_guessed_page() -> None:
    notice = NoticeData.model_validate({
        "eligibility": [{"text": "Undergraduates may apply.", "source_evidence": "학부생 지원 가능", "source_page": 2}],
    })
    normalized = normalize_notice(notice, source_text="[Page 1]\n학부생 지원 가능\n[Page 2]\n학부생 지원 가능")
    assert normalized.eligibility[0].source_page is None
