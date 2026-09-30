from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.models import OcrSpan
from app.services.pipeline import analyze_text_pipeline
from app.services.semantic import SourceCorrectionRequired


def test_corrupted_phone_requires_correction_before_external_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.pipeline.choose_semantic_provider",
        lambda _: SimpleNamespace(name="openai-semantic:gpt-4o-mini"),
    )

    def unexpected_translator(**kwargs):
        raise AssertionError("Unreadable contact should be detected before translation requests")

    monkeypatch.setattr("app.services.pipeline.choose_translation_provider", unexpected_translator)
    with pytest.raises(SourceCorrectionRequired) as raised:
        asyncio.run(analyze_text_pipeline("[Page 2]\n문의: 02.710.25n0", "en", "openai"))
    assert raised.value.corrections == [{
        "page": 2, "line": 1, "text": "문의: 02.710.25n0",
        "reason": "The phone number contains unreadable OCR characters: 02.710.25n0. "
        "Read the exact digits from the photo or upload a close-up of the contact line.",
    }]


def test_client_ocr_returns_actionable_source_correction(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.pipeline.choose_semantic_provider",
        lambda _: SimpleNamespace(name="openai-semantic:gpt-4o-mini"),
    )
    response = client.post("/api/analyze-client-ocr", json={
        "pages": [{"text": "문의:융합교육혁신팀(02.710.25n0 |convedu@sogang.ac.kr)"}],
        "ocr_latency_ms": 100, "provider": "openai",
    })
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "source_correction_required"
    assert detail["corrections"][0]["page"] == 1
    assert "25n0" in detail["corrections"][0]["text"]
    assert "2500" not in detail["message"]


def test_sogang_raw_contact_fixture_cannot_silently_infer_phone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.pipeline.choose_semantic_provider",
        lambda _: SimpleNamespace(name="openai-semantic:gpt-4o-mini"),
    )
    fixture = json.loads((Path(__file__).parent / "fixtures" / "sogang_research_2026_browser_ocr.json").read_text(encoding="utf-8"))
    text = "\n".join(item["text"] for item in fixture["items"])
    with pytest.raises(SourceCorrectionRequired):
        asyncio.run(analyze_text_pipeline(text, "en", "openai"))


def test_ocr_confidence_is_optional_and_bounded() -> None:
    span = {"text": "지원서", "box": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.1}}
    assert OcrSpan.model_validate(span).confidence is None
    assert OcrSpan.model_validate({**span, "confidence": 0.708}).confidence == 0.708
    for value in (-0.01, 1.01, float("nan")):
        with pytest.raises(ValidationError):
            OcrSpan.model_validate({**span, "confidence": value})


def test_incomplete_score_table_requires_correction_before_semantics(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def unexpected_pipeline(*args, **kwargs):
        raise AssertionError("An ambiguous table must be corrected before external requests")

    monkeypatch.setattr("app.main._run_text_pipeline", unexpected_pipeline)
    lines = [("TOEIC", 0.1, 0.1), ("TEPS", 0.3, 0.1), ("800 이상", 0.1, 0.15)]
    response = client.post("/api/analyze-client-ocr", json={
        "pages": [{
            "text": "영어 어학 성적\n" + "\n".join(line[0] for line in lines),
            "spans": [{"text": text, "box": {"x": x, "y": y, "width": 0.1, "height": 0.02}}
                      for text, x, y in lines],
        }],
        "ocr_latency_ms": 100, "provider": "openai",
    })
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "source_correction_required"
    assert any(item["text"] == "TEPS" for item in detail["corrections"])
