from __future__ import annotations

import asyncio
from types import SimpleNamespace
import httpx
import pytest

from app.models import Action, Contact, DocumentRequirement, LabeledFact, NoticeData, ReviewState, SourceFact
from app.services import pipeline
from app.services.pipeline import analyze_text_pipeline
from app.services.semantic import SemanticError, SemanticResult, normalize_notice
from app.services.translation import MyMemoryTranslationProvider, TranslationError, TranslationResult, split_utf8_chunks


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


def test_partial_photo_stages_overlap_with_independent_timing_and_usage(monkeypatch):
    clock = SimpleNamespace(now=0.0)
    semantic_started = asyncio.Event()
    translation_finished = asyncio.Event()
    calls = []

    async def translate(text, source_language, target_language):
        calls.append("translation")
        assert (text, source_language, target_language) == ("신청 안내", "ko", "en")
        await semantic_started.wait()
        clock.now = 0.010
        translation_finished.set()
        return TranslationResult("Independent baseline", "test-translation", 3)

    async def analyze(source, baseline, target, **kwargs):
        calls.append("semantic")
        assert (source, baseline, target) == ("신청 안내", "", "en")
        assert kwargs == {"layout_context": "positioned source", "allow_partial": True}
        semantic_started.set()
        await translation_finished.wait()
        clock.now = 0.030
        return SemanticResult(NoticeData(title="Application notice"), "test-semantic", 2, 120, 80, 200,
                              extraction_latency_ms=22, english_repair_latency_ms=8)

    monkeypatch.setattr(pipeline, "perf_counter", lambda: clock.now)
    monkeypatch.setattr(pipeline, "choose_translation_provider", lambda mock=False: SimpleNamespace(translate=translate))
    monkeypatch.setattr(pipeline, "choose_semantic_provider", lambda provider: SimpleNamespace(name="openai-semantic", analyze=analyze))

    async def exercise():
        return await asyncio.wait_for(analyze_text_pipeline(
            "신청 안내", "en", "openai", allow_partial=True, layout_context="positioned source",
        ), timeout=0.5)

    result = asyncio.run(exercise())
    assert sorted(calls) == ["semantic", "translation"]
    assert result.translation == "Independent baseline"
    assert (result.translation_latency_ms, result.semantic_latency_ms, result.total_latency_ms) == (10, 30, 30)
    assert result.total_latency_ms < result.translation_latency_ms + result.semantic_latency_ms
    assert (result.extraction_latency_ms, result.english_repair_latency_ms) == (22, 8)
    assert result.translation_requests == 3 and result.semantic_requests == 2
    assert (result.semantic_input_tokens, result.semantic_output_tokens, result.semantic_total_tokens) == (120, 80, 200)
    assert result.metrics_complete and result.warnings == []


@pytest.mark.parametrize("semantic_name,allow_partial", [
    ("openai-semantic", False), ("mock-semantic", False), ("mock-semantic", True),
])
def test_strict_and_mock_stages_keep_translation_dependency(monkeypatch, semantic_name, allow_partial):
    clock = SimpleNamespace(now=0.0)
    events = []

    async def translate(*args):
        events.append("translation started")
        await asyncio.sleep(0)
        clock.now = 0.015
        events.append("translation completed")
        return TranslationResult("Forward this baseline", "test-translation", 2)

    async def analyze(source, baseline, target, **kwargs):
        assert events == ["translation started", "translation completed"]
        assert baseline == "Forward this baseline"
        assert kwargs == {"layout_context": ""} | ({"allow_partial": True} if allow_partial else {})
        events.append("semantic started")
        clock.now = 0.050
        return SemanticResult(NoticeData(title="Notice"), semantic_name, 1)

    def choose_translation(mock=False):
        assert mock is (semantic_name == "mock-semantic")
        return SimpleNamespace(translate=translate)

    monkeypatch.setattr(pipeline, "perf_counter", lambda: clock.now)
    monkeypatch.setattr(pipeline, "choose_translation_provider", choose_translation)
    monkeypatch.setattr(pipeline, "choose_semantic_provider", lambda provider: SimpleNamespace(name=semantic_name, analyze=analyze))
    result = asyncio.run(analyze_text_pipeline("신청 안내", "en", "auto", allow_partial=allow_partial))
    assert events[-1] == "semantic started"
    assert (result.translation_latency_ms, result.semantic_latency_ms, result.total_latency_ms) == (15, 35, 50)
    assert result.translation == "Forward this baseline" and result.translation_requests == 2


def test_parallel_translation_outage_preserves_source_semantics_and_incomplete_metrics(monkeypatch):
    clock = SimpleNamespace(now=0.0)
    semantic_started = asyncio.Event()
    translation_finished = asyncio.Event()

    async def translate(*args):
        await semantic_started.wait()
        clock.now = 0.012
        translation_finished.set()
        raise TranslationError("Quota exhausted")

    async def analyze(source, baseline, target, **kwargs):
        assert baseline == "" and kwargs["allow_partial"] is True
        semantic_started.set()
        await translation_finished.wait()
        clock.now = 0.020
        return SemanticResult(NoticeData(title="Source-interpreted notice"), "test-semantic", 1, 40, 10, 50,
                              warnings=["Independent semantic warning"])

    monkeypatch.setattr(pipeline, "perf_counter", lambda: clock.now)
    monkeypatch.setattr(pipeline, "choose_translation_provider", lambda mock=False: SimpleNamespace(translate=translate))
    monkeypatch.setattr(pipeline, "choose_semantic_provider", lambda provider: SimpleNamespace(name="openai-semantic", analyze=analyze))

    async def exercise():
        return await asyncio.wait_for(analyze_text_pipeline("신청 안내", "en", "openai", allow_partial=True), timeout=0.5)

    result = asyncio.run(exercise())
    assert result.notice.title == "Source-interpreted notice"
    assert result.translation == "" and result.translation_provider == "unavailable"
    assert result.translation_requests == 0 and result.semantic_requests == 1
    assert (result.semantic_input_tokens, result.semantic_output_tokens, result.semantic_total_tokens) == (40, 10, 50)
    assert (result.translation_latency_ms, result.semantic_latency_ms, result.total_latency_ms) == (12, 20, 20)
    assert result.metrics_complete is False
    assert "temporary translation service was unavailable" in result.warnings[0]
    assert result.warnings[1] == "Independent semantic warning"


@pytest.mark.parametrize("failing_stage", ["translation", "semantic"])
def test_parallel_fatal_stage_error_cancels_and_awaits_sibling_cleanup(monkeypatch, failing_stage):
    started = {stage: asyncio.Event() for stage in ("translation", "semantic")}
    cleanup_finished = asyncio.Event()
    original = RuntimeError("Unexpected translation failure") if failing_stage == "translation" else SemanticError("Invalid semantic response")

    async def stage(name):
        started[name].set()
        await started["semantic" if name == "translation" else "translation"].wait()
        if name == failing_stage:
            raise original
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0)
            cleanup_finished.set()

    async def translate(*args):
        return await stage("translation")

    async def analyze(*args, **kwargs):
        return await stage("semantic")

    monkeypatch.setattr(pipeline, "choose_translation_provider", lambda mock=False: SimpleNamespace(translate=translate))
    monkeypatch.setattr(pipeline, "choose_semantic_provider", lambda provider: SimpleNamespace(name="openai-semantic", analyze=analyze))

    async def exercise():
        with pytest.raises(type(original)) as caught:
            await asyncio.wait_for(analyze_text_pipeline("신청 안내", "en", "openai", allow_partial=True), timeout=0.5)
        assert caught.value is original
        assert cleanup_finished.is_set()
        assert [task for task in asyncio.all_tasks() if task is not asyncio.current_task()] == []

    asyncio.run(exercise())


def test_caller_cancellation_awaits_both_independent_stages(monkeypatch):
    started = {stage: asyncio.Event() for stage in ("translation", "semantic")}
    cleaned = set()

    async def stage(name):
        started[name].set()
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0)
            cleaned.add(name)

    async def translate(*args):
        return await stage("translation")

    async def analyze(*args, **kwargs):
        return await stage("semantic")

    monkeypatch.setattr(pipeline, "choose_translation_provider", lambda mock=False: SimpleNamespace(translate=translate))
    monkeypatch.setattr(pipeline, "choose_semantic_provider", lambda provider: SimpleNamespace(name="openai-semantic", analyze=analyze))

    async def exercise():
        task = asyncio.create_task(analyze_text_pipeline("신청 안내", "en", "openai", allow_partial=True))
        await asyncio.wait_for(asyncio.gather(*(event.wait() for event in started.values())), timeout=0.5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cleaned == {"translation", "semantic"}
        assert [pending for pending in asyncio.all_tasks() if pending is not asyncio.current_task()] == []

    asyncio.run(exercise())
