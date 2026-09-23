from __future__ import annotations

import asyncio
import httpx
import pytest

from app.models import Action, Contact, DocumentRequirement, NoticeData, SourceFact
from app.services.pipeline import analyze_text_pipeline
from app.services.semantic import SemanticResult, normalize_notice
from app.services.translation import MyMemoryTranslationProvider, TranslationResult, split_utf8_chunks


def test_translation_chunks_stay_within_mymemory_byte_limit() -> None:
    chunks = split_utf8_chunks("지원 기간은 2026년 10월 5일까지입니다. " * 80)
    assert len(chunks) > 1
    assert all(len(chunk.encode("utf-8")) <= 480 for chunk in chunks)


def test_mymemory_provider_uses_no_key_and_reports_request_count() -> None:
    seen_queries: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        query = request.url.params["q"]
        seen_queries.append(query)
        assert request.url.params["langpair"] == "ko|en"
        assert "key" not in request.url.params
        return httpx.Response(200, json={"responseStatus": 200, "responseData": {"translatedText": "Translated chunk"}})

    async def exercise() -> TranslationResult:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await MyMemoryTranslationProvider(client).translate("지원 안내 " * 120, "ko", "en")

    result = asyncio.run(exercise())

    assert result.provider == "mymemory"
    assert result.request_count == len(seen_queries) > 1
    assert all(len(query.encode("utf-8")) <= 480 for query in seen_queries)


def test_pipeline_calls_semantic_provider_once(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeTranslator:
        name = "free-test-translation"

        async def translate(self, text: str, source_language: str, target_language: str) -> TranslationResult:
            return TranslationResult("Application deadline: October 5, 2026.", self.name, 2)

    class FakeSemantic:
        name = "openai-semantic"

        def __init__(self) -> None:
            self.calls = 0

        async def analyze(self, source_text: str, translation: str, target_language: str) -> SemanticResult:
            self.calls += 1
            assert source_text == "지원 마감: 2026.10.05"
            assert "October 5" in translation
            return SemanticResult(NoticeData(title="Application notice"), self.name, 1, 120, 80, 200)

    semantic = FakeSemantic()
    monkeypatch.setattr("app.services.pipeline.choose_translation_provider", lambda mock=False: FakeTranslator())
    monkeypatch.setattr("app.services.pipeline.choose_semantic_provider", lambda provider: semantic)

    result = asyncio.run(analyze_text_pipeline("지원 마감: 2026.10.05", "en", "openai"))

    assert semantic.calls == 1
    assert result.semantic_requests == 1
    assert result.semantic_total_tokens == 200
    assert result.translation_requests == 2


def test_semantic_cleanup_splits_documents_and_keeps_suspect_email_unverified() -> None:
    notice = NoticeData(
        source_facts=[SourceFact(id="F001", kind="heading", source_text="지원 프로그램")],
        actions=[Action(step=1, action="Prepare", required_items=["지원서", "연구계획서"], source_fact_ids=["F002"])],
        required_documents=[DocumentRequirement(name="지원서, 연구계획서", source_fact_ids=["F002"], source_evidence="지원서, 연구계획서")],
        contacts=[Contact(email="convedu@sogand-act", source_evidence="convedu@sogand-act")],
    )

    normalized = normalize_notice(notice)

    assert [item.name for item in normalized.required_documents] == ["지원서", "연구계획서"]
    assert normalized.contacts[0].email == ""
    assert "needs review" in normalized.contacts[0].details
    assert normalized.source_facts[0].critical is False
