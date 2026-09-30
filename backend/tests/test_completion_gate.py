from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import main
from app.models import LabeledFact, NoticeData
from app.services.coverage_repair import (
    CoverageProviderError, CoverageRepairError, CoverageRepairResult, RepairResponse, repair_coverage,
)
from app.services.pipeline import PipelineResult


def _pipeline(*, provider: str = "openai-semantic:gpt-4o-mini", language: str = "en") -> PipelineResult:
    return PipelineResult(
        source_text="연구비: 1인당 최대 20만원",
        translation="Research funding: up to KRW 200,000 per person",
        notice=NoticeData(target_language=language),
        provider=provider,
        translation_provider="mymemory",
        semantic_provider=provider,
        translation_requests=1,
        semantic_requests=1,
        semantic_input_tokens=100,
        semantic_output_tokens=40,
        semantic_total_tokens=140,
        semantic_latency_ms=500,
        total_latency_ms=700,
    )


def test_coverage_completion_adds_grounded_english_details_and_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_repair(notice, source_text, *, layout_context):
        assert source_text == "연구비: 1인당 최대 20만원"
        assert layout_context == "research amount at bottom right"
        updated = notice.model_copy(deep=True)
        updated.financial_support.append(LabeledFact(
            text="Research funding: up to KRW 200,000 per person",
            source_evidence=source_text,
            source_page=1,
        ))
        return CoverageRepairResult(updated, requests=1, input_tokens=20, output_tokens=10, total_tokens=30)

    monkeypatch.setattr(main, "repair_coverage", fake_repair)
    result = asyncio.run(main._complete_english_coverage(_pipeline(), layout_context="research amount at bottom right"))

    assert result.notice.financial_support[0].text.startswith("Research funding")
    assert result.semantic_requests == 2
    assert (result.semantic_input_tokens, result.semantic_output_tokens, result.semantic_total_tokens) == (120, 50, 170)
    assert result.semantic_latency_ms >= 500
    assert result.total_latency_ms >= 700


def test_coverage_completion_rejects_unresolved_details(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_repair(*args, **kwargs):
        raise CoverageRepairError("Some OCR source lines could not be confidently interpreted.")

    monkeypatch.setattr(main, "repair_coverage", fake_repair)
    with pytest.raises(HTTPException, match="complete English interpretation could not be verified") as exc:
        asyncio.run(main._complete_english_coverage(_pipeline()))
    assert exc.value.status_code == 422


def test_coverage_completion_reports_provider_failure_as_gateway_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_repair(*args, **kwargs):
        raise CoverageProviderError("The semantic provider could not audit notice completeness.")

    monkeypatch.setattr(main, "repair_coverage", fake_repair)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(main._complete_english_coverage(_pipeline()))
    assert exc.value.status_code == 502
    assert "Retake the photo" not in exc.value.detail


def test_invalid_provider_partition_is_a_retryable_gateway_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class Responses:
        async def parse(self, **kwargs):
            return SimpleNamespace(output_parsed=RepairResponse(
                represented_unit_ids=["P001-L9999"], details=[], decorative=[], unresolved_unit_ids=[],
            ), usage=None)

    async def real_repair(notice, source_text, *, layout_context):
        return await repair_coverage(
            notice, source_text, layout_context=layout_context,
            client=SimpleNamespace(responses=Responses()),
        )

    monkeypatch.setattr(main, "repair_coverage", real_repair)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(main._complete_english_coverage(_pipeline()))

    assert exc.value.status_code == 502
    assert "retry the analysis" in exc.value.detail.lower()
    assert "Retake the photo" not in exc.value.detail


def test_coverage_completion_skips_mock_and_non_english(monkeypatch: pytest.MonkeyPatch) -> None:
    async def should_not_call(*args, **kwargs):
        raise AssertionError("Unexpected repair call")

    monkeypatch.setattr(main, "repair_coverage", should_not_call)
    mock = _pipeline(provider="mock-semantic")
    korean = _pipeline(language="ko")
    assert asyncio.run(main._complete_english_coverage(mock)) is mock
    assert asyncio.run(main._complete_english_coverage(korean)) is korean
