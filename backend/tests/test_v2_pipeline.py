from __future__ import annotations

import asyncio
import httpx
import pytest

from app.models import Action, Contact, DocumentRequirement, LabeledFact, NoticeData, ReviewState, SourceFact
from app.services.pipeline import analyze_text_pipeline
from app.services.semantic import SemanticResult, normalize_notice
from app.services.translation import MyMemoryTranslationProvider, TranslationResult, split_utf8_chunks


def test_translation_chunks_stay_within_mymemory_byte_limit() -> None:
    chunks = split_utf8_chunks("지원 기간은 2026년 10월 5일까지입니다. " * 80)
    assert len(chunks) > 1
    assert all(len(chunk.encode("utf-8")) <= 480 for chunk in chunks)


def test_translation_chunks_do_not_mix_ocr_sections_or_pages() -> None:
    source = (
        "[Page 1]\n모집 대상\n2026학년도 2학기 학부 재학생\n"
        "\n연구 주제\nAI Wearable Device 연구\n\n"
        "[Page 2]\n지원 금액\n연구비 1인당 최대 20만원"
    )

    chunks = split_utf8_chunks(source, max_bytes=100)

    assert len(chunks) == 3
    assert chunks[0].startswith("[Page 1]\n")
    assert chunks[1].startswith("연구 주제\n")
    assert chunks[2].startswith("[Page 2]\n")
    assert all(len(chunk.encode("utf-8")) <= 100 for chunk in chunks)
    assert " ".join(" ".join(chunks).split()) == " ".join(source.split())


def test_translation_chunks_prefer_line_and_sentence_boundaries() -> None:
    source = "지원 기간\n2026년 9월 20일까지 신청할 수 있습니다. 연구 계획서를 제출해야 합니다."

    chunks = split_utf8_chunks(source, max_bytes=80)

    assert chunks[0] == "지원 기간"
    assert chunks[1] == "2026년 9월 20일까지 신청할 수 있습니다."
    assert chunks[2] == "연구 계획서를 제출해야 합니다."
    assert all(len(chunk.encode("utf-8")) <= 80 for chunk in chunks)


def test_translation_chunks_fall_back_to_unicode_code_points_for_long_ocr_token() -> None:
    source = "연구주제" * 15

    chunks = split_utf8_chunks(source, max_bytes=25)

    assert len(chunks) > 1
    assert "".join(chunks) == source
    assert all(len(chunk.encode("utf-8")) <= 25 for chunk in chunks)


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

        async def analyze(
            self, source_text: str, translation: str, target_language: str, *, layout_context: str = ""
        ) -> SemanticResult:
            self.calls += 1
            assert source_text == "지원 마감: 2026.10.05"
            assert "October 5" in translation
            assert layout_context == "(550,560) TOEIC"
            return SemanticResult(NoticeData(title="Application notice"), self.name, 1, 120, 80, 200)

    semantic = FakeSemantic()
    monkeypatch.setattr("app.services.pipeline.choose_translation_provider", lambda mock=False: FakeTranslator())
    monkeypatch.setattr("app.services.pipeline.choose_semantic_provider", lambda provider: semantic)

    result = asyncio.run(
        analyze_text_pipeline("지원 마감: 2026.10.05", "en", "openai", layout_context="(550,560) TOEIC")
    )

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


def test_semantic_cleanup_flags_untranslated_user_facing_text() -> None:
    notice = NoticeData(
        title="신입직원 채용",
        eligibility=[LabeledFact(text="학력 제한 없음")],
    )

    normalized = normalize_notice(notice)

    assert normalized.eligibility[0].state == ReviewState.NEEDS_REVIEW
    assert "remain in Korean" in normalized.unverified_items[0]
