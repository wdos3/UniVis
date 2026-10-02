from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app import main
from app.models import Contact, LabeledFact, NoticeData, SourceFact
from app.services import pipeline
from app.services.english_review import EnglishNoticeReview
from app.services.pipeline import PipelineResult
from app.services.coverage_repair import RepairResponse, repair_coverage
from app.services.semantic import OpenAISemanticProvider, SemanticResult, SourceCorrectionRequired
from app.services.translation import TranslationError, TranslationResult


def test_unreadable_photo_returns_english_gap_without_guessing_or_external_calls(client, monkeypatch) -> None:
    async def no_pipeline(*args, **kwargs):
        raise AssertionError("Unreadable input cannot establish notice instructions.")

    monkeypatch.setattr(main, "analyze_text_pipeline", no_pipeline)
    response = client.post("/api/analyze-client-ocr", json={
        "pages": [{"text": ""}], "ocr_latency_ms": 123, "provider": "openai", "allow_partial": True,
    })
    assert response.status_code == 200
    result = response.json()
    assert result["acquisition"]["english_coverage_status"] == "partial"
    assert result["acquisition"]["text_extraction_status"] == "unavailable"
    assert result["notice"]["actions"] == []
    assert "no Korean transcription is required" in result["simplified_text"]
    assert result["source_pages"][0]["original_url"] == ""


def test_damaged_photo_contact_is_withheld_without_blocking_other_audited_facts(client, monkeypatch) -> None:
    source = "모집 안내: 학생 행사\n문의02-123-45O7로 연락"

    class Translator:
        async def translate(self, *args):
            return TranslationResult("Student event. Contact unreadable.", "test", 1)

    class Responses:
        async def parse(self, *, text_format, **kwargs):
            if text_format is not RepairResponse:
                return SimpleNamespace(output_parsed=NoticeData(
                    title="Student event", source_facts=[
                        SourceFact(id="F001", source_text="모집 안내: 학생 행사", kind="event"),
                        SourceFact(id="F002", source_text="문의02-123-45O7로 연락", kind="contact"),
                    ], key_details=[LabeledFact(text="Student event recruitment.", source_evidence="모집 안내: 학생 행사", source_fact_ids=["F001"])],
                    contacts=[Contact(phone="02-123-4507", source_evidence="문의02-123-45O7로 연락", source_fact_ids=["F002"])],
                ), usage=None)
            return SimpleNamespace(output_parsed=RepairResponse(
                represented_unit_ids=["P001-L0001"], details=[], decorative=[], unresolved_unit_ids=["P001-L0002"],
            ), usage=None)

    responses = Responses()
    monkeypatch.setattr(pipeline, "choose_translation_provider", lambda **kwargs: Translator())
    monkeypatch.setattr(pipeline, "choose_semantic_provider", lambda *args: OpenAISemanticProvider(client=SimpleNamespace(responses=responses)))

    async def audit(*args, **kwargs):
        return await repair_coverage(*args, client=SimpleNamespace(responses=responses), **kwargs)

    monkeypatch.setattr(main, "repair_coverage", audit)
    async def final_review(notice, source_text, **kwargs):
        assert notice.contacts == []
        assert notice.key_details[0].text == "Student event recruitment."
        return EnglishNoticeReview(notice=notice)

    monkeypatch.setattr(main, "review_notice_english", final_review)
    response = client.post("/api/analyze-client-ocr", json={
        "pages": [{"text": source}], "ocr_latency_ms": 100, "provider": "openai", "allow_partial": True,
    })
    assert response.status_code == 200
    result = response.json()
    assert result["acquisition"]["english_coverage_status"] == "partial"
    assert "Student event recruitment" in result["simplified_text"]
    assert "02-123-4507" not in result["simplified_text"]
    assert "Verification gaps" in result["simplified_text"]
    assert "문의" not in result["simplified_text"]
    assert result["recovered_text"].endswith("문의02-123-45O7로 연락")


def test_temporary_translator_outage_can_use_source_semantics_only_when_requested(monkeypatch) -> None:
    class Translator:
        async def translate(self, *args):
            raise TranslationError("Temporary quota exhausted")

    class Semantic:
        name = "openai-semantic:test"

        async def analyze(self, source, translation, language, **kwargs):
            assert source == "신청 마감 2027.03.01"
            assert translation == ""
            assert kwargs["allow_partial"] is True
            return SemanticResult(NoticeData(title="Application notice"), self.name, 1)

    monkeypatch.setattr(pipeline, "choose_translation_provider", lambda **kwargs: Translator())
    monkeypatch.setattr(pipeline, "choose_semantic_provider", lambda *args: Semantic())
    result = asyncio.run(pipeline.analyze_text_pipeline("신청 마감 2027.03.01", "en", "openai", allow_partial=True))
    assert result.translation_provider == "unavailable"
    assert result.translation == ""
    assert "unavailable" in result.warnings[0]
    with pytest.raises(TranslationError):
        asyncio.run(pipeline.analyze_text_pipeline("신청 마감 2027.03.01", "en", "openai"))
    with pytest.raises(SourceCorrectionRequired):
        asyncio.run(pipeline.analyze_text_pipeline("문의02-123-45O7", "en", "openai"))


def test_photo_service_outage_returns_english_unavailable_state_and_keeps_strict_api_errors(client, monkeypatch) -> None:
    from fastapi import HTTPException

    async def unavailable(*args, **kwargs):
        raise HTTPException(status_code=503, detail="Provider unavailable")

    monkeypatch.setattr(main, "_run_text_pipeline", unavailable)
    payload = {"pages": [{"text": "신청 마감 2027.03.01"}], "ocr_latency_ms": 100, "provider": "openai", "allow_partial": True}
    response = client.post("/api/analyze-client-ocr", json=payload)
    assert response.status_code == 200
    result = response.json()
    assert result["notice"]["title"] == "English interpretation unavailable"
    assert result["notice"]["deadlines"] == []
    assert result["acquisition"]["english_coverage_status"] == "partial"
    assert "no notice instructions" in result["simplified_text"].lower()
    assert "2027.03.01" not in result["simplified_text"]
    payload["allow_partial"] = False
    assert client.post("/api/analyze-client-ocr", json=payload).status_code == 503


def test_failed_audit_preserves_known_completed_stage_usage(client, monkeypatch) -> None:
    from fastapi import HTTPException

    async def completed(*args, **kwargs):
        return PipelineResult(
            source_text="신청 안내", translation="Application notice", notice=NoticeData(),
            provider="test", translation_provider="test-translation", semantic_provider="openai-semantic:test",
            translation_requests=2, semantic_requests=1, semantic_input_tokens=100,
            semantic_output_tokens=20, semantic_total_tokens=120,
            translation_latency_ms=30, semantic_latency_ms=40,
        )

    async def failed_audit(*args, **kwargs):
        raise HTTPException(status_code=502, detail="Audit unavailable")

    monkeypatch.setattr(main, "_run_text_pipeline", completed)
    monkeypatch.setattr(main, "_complete_english_coverage", failed_audit)
    response = client.post("/api/analyze-client-ocr", json={
        "pages": [{"text": "신청 안내"}], "ocr_latency_ms": 100, "provider": "openai", "allow_partial": True,
    })
    assert response.status_code == 200
    result = response.json()
    measured = result["acquisition"]
    assert measured["translation_requests"] == 2
    assert measured["semantic_requests"] == 1
    assert measured["semantic_total_tokens"] == 120
    assert measured["translation_latency_ms"] == 30
    assert measured["semantic_latency_ms"] == 40
    assert measured["metrics_complete"] is False
    assert result["notice"]["deadlines"] == []
