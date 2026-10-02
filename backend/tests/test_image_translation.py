from __future__ import annotations

import asyncio

import httpx
import pytest

from app.services import image_translation
from app.services.image_translation import ImageTextTranslationRequest, translate_image_regions
from app.services.public_access import PublicAnalysisLimiter
from app.services.translation import MyMemoryTranslationProvider, TranslationError, TranslationProvider, TranslationResult


class RegionTranslationProvider(TranslationProvider):
    name = "test-translation"

    def __init__(self, translations: dict[str, str | TranslationError]) -> None:
        self.translations = translations
        self.calls: list[tuple[str, str, str]] = []

    async def translate(self, text: str, source_language: str, target_language: str) -> TranslationResult:
        self.calls.append((text, source_language, target_language))
        await asyncio.sleep(0)
        result = self.translations[text]
        if isinstance(result, TranslationError):
            raise result
        return TranslationResult(text=result, provider=self.name, request_count=1)


def request_for(*texts: str) -> ImageTextTranslationRequest:
    return ImageTextTranslationRequest(regions=[{"id": str(index), "text": text} for index, text in enumerate(texts)])


def test_translations_preserve_order_ids_exact_source_and_duplicate_associations(client, monkeypatch):
    provider = RegionTranslationProvider({"지원 안내": "Application instructions", "문의": "Contact"})
    monkeypatch.setattr(image_translation, "choose_translation_provider", lambda mock: provider)
    response = client.post("/api/translate-image-text", json={"regions": [
        {"id": "second", "text": "지원 안내"},
        {"id": "first", "text": "  TOEIC 800  "},
        {"id": "third", "text": "문의"},
        {"id": "duplicate", "text": "지원 안내"},
    ], "target_language": "en"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["regions"] == [
        {"id": "second", "source_text": "지원 안내", "translated_text": "Application instructions", "status": "translated"},
        {"id": "first", "source_text": "  TOEIC 800  ", "translated_text": "  TOEIC 800  ", "status": "unchanged"},
        {"id": "third", "source_text": "문의", "translated_text": "Contact", "status": "translated"},
        {"id": "duplicate", "source_text": "지원 안내", "translated_text": "Application instructions", "status": "translated"},
    ]
    assert provider.calls == [("지원 안내", "ko", "en"), ("문의", "ko", "en")]
    assert payload["provider"] == "test-translation"
    assert payload["request_count"] == 2
    assert payload["metrics_complete"] is True
    assert payload["latency_ms"] >= 0


def test_non_korean_text_never_uses_any_provider_or_semantic_pipeline(client, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("No provider, semantic processing, or persistence should be used.")

    monkeypatch.setattr(image_translation, "choose_translation_provider", forbidden)
    monkeypatch.setattr("app.services.pipeline.choose_semantic_provider", forbidden)
    monkeypatch.setattr("app.main.save_notice", forbidden)
    response = client.post("/api/translate-image-text", json={"regions": [
        {"id": "url", "text": "https://example.org/apply?q=2026"},
        {"id": "number", "text": "2026.08.24 — 2026.09.20 / 2–5"},
        {"id": "latin", "text": "TOEIC Speaking 150"},
    ]})

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "not-needed"
    assert payload["request_count"] == 0
    assert payload["metrics_complete"] is True
    assert all(region["status"] == "unchanged" for region in payload["regions"])
    assert all(region["translated_text"] == region["source_text"] for region in payload["regions"])


def test_korean_route_has_no_openai_or_persistence_dependency(client, monkeypatch):
    provider = RegionTranslationProvider({"모집": "Recruitment"})
    monkeypatch.setattr(image_translation, "choose_translation_provider", lambda mock: provider)

    def forbidden(*args, **kwargs):
        raise AssertionError("Image-region translation must bypass semantic analysis and persistence.")

    monkeypatch.setattr("app.services.pipeline.choose_semantic_provider", forbidden)
    monkeypatch.setattr("app.main.analyze_text_pipeline", forbidden)
    monkeypatch.setattr("app.main.repair_coverage", forbidden)
    monkeypatch.setattr("app.main.review_notice_english", forbidden)
    monkeypatch.setattr("app.main.save_notice", forbidden)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    response = client.post("/api/translate-image-text", json={"regions": [{"id": "r1", "text": "모집"}]})
    assert response.status_code == 200
    assert response.json()["regions"][0]["translated_text"] == "Recruitment"


def test_one_quota_failure_retains_its_source_without_losing_other_translations(client, monkeypatch):
    provider = RegionTranslationProvider({
        "모집": "Recruitment",
        "문의": TranslationError("The translation quota was reached. Try again later."),
        "기간": "Dates",
    })
    monkeypatch.setattr(image_translation, "choose_translation_provider", lambda mock: provider)
    response = client.post("/api/translate-image-text", json=request_for("모집", "문의", "기간", "문의").model_dump())
    assert response.status_code == 200
    payload = response.json()
    assert [region["status"] for region in payload["regions"]] == ["translated", "failed", "translated", "failed"]
    assert payload["regions"][1]["translated_text"] == "문의"
    assert payload["regions"][3]["source_text"] == "문의"
    assert "quota" in payload["regions"][1]["error"]
    assert len(provider.calls) == 3
    assert payload["request_count"] == 2
    assert payload["metrics_complete"] is False


@pytest.mark.parametrize("translated", ["", "Dates 기간", "Application ᄀ", "Information ㄱ"])
def test_empty_or_partly_korean_english_cannot_replace_original(translated, monkeypatch):
    provider = RegionTranslationProvider({"기간": translated})
    monkeypatch.setattr(image_translation, "choose_translation_provider", lambda mock: provider)
    result = asyncio.run(translate_image_regions(request_for("기간")))
    assert result.regions[0].status == "failed"
    assert result.regions[0].source_text == "기간"
    assert result.regions[0].translated_text == "기간"
    assert result.regions[0].error
    # This failed output still has a known provider request count.
    assert result.request_count == 1
    assert result.metrics_complete is True


def test_even_a_small_korean_suffix_is_sent_for_translation(monkeypatch):
    source = "https://example.org/application " + "A" * 200 + " 안내"
    provider = RegionTranslationProvider({source: "Application information"})
    monkeypatch.setattr(image_translation, "choose_translation_provider", lambda mock: provider)
    result = asyncio.run(translate_image_regions(request_for(source)))
    assert result.regions[0].status == "translated"
    assert provider.calls == [(source, "ko", "en")]


@pytest.mark.parametrize(("source", "expected"), [
    ("800 이상", "800 or more"),
    ("800이하", "800 or less"),
    ("800 초과", "More than 800"),
    ("800 미만", "Less than 800"),
    ("IM3 이상", "IM3 or more"),
    ("2B이상", "2B or more"),
    ("  007 이상  ", "007 or more"),
    ("1,000.50 이상", "1,000.50 or more"),
    ("-003.50 이하", "-003.50 or less"),
    ("0.5% 초과", "More than 0.5%"),
])
def test_standalone_threshold_translation_preserves_literal_value_and_comparison(client, monkeypatch, source, expected):
    def forbidden(*args, **kwargs):
        raise AssertionError("Standalone thresholds must not use an external provider.")

    monkeypatch.setattr(image_translation, "choose_translation_provider", forbidden)
    response = client.post("/api/translate-image-text", json=request_for(source, source, "TOEIC").model_dump())
    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "local"
    assert payload["request_count"] == 0
    assert payload["metrics_complete"] is True
    assert [region["status"] for region in payload["regions"]] == ["translated", "translated", "unchanged"]
    assert payload["regions"][0]["source_text"] == source
    assert payload["regions"][0]["translated_text"] == expected
    assert payload["regions"][1]["translated_text"] == expected


@pytest.mark.parametrize("source", [
    "기간 이상", "IM 이상", "800 이상 지원 가능", "800 이상 또는 면제", "800 이상이 아님",
    "TOEIC 800 이상", "1000원 이상", "1,,000 이상", "IM 3 이상", "800 이상.",
])
def test_threshold_rule_does_not_translate_prose_units_or_ambiguous_values(source, monkeypatch):
    provider = RegionTranslationProvider({source: "Provider translation"})
    monkeypatch.setattr(image_translation, "choose_translation_provider", lambda mock: provider)
    result = asyncio.run(translate_image_regions(request_for(source)))
    assert result.provider == "test-translation"
    assert result.request_count == 1
    assert result.regions[0].translated_text == "Provider translation"
    assert provider.calls == [(source, "ko", "en")]


def test_local_thresholds_preserve_order_without_contributing_to_external_request_count(monkeypatch):
    provider = RegionTranslationProvider({"문의": "Contact"})
    monkeypatch.setattr(image_translation, "choose_translation_provider", lambda mock: provider)
    result = asyncio.run(translate_image_regions(request_for("800 이상", "문의", "IM3 이상", "문의")))
    assert result.provider == "test-translation"
    assert result.request_count == 1
    assert [region.translated_text for region in result.regions] == ["800 or more", "Contact", "IM3 or more", "Contact"]
    assert provider.calls == [("문의", "ko", "en")]


def test_local_threshold_remains_translated_during_provider_configuration_failure(monkeypatch):
    monkeypatch.setenv("TRANSLATION_PROVIDER", "not-supported")
    result = asyncio.run(translate_image_regions(request_for("800 이상", "문의")))
    assert result.provider == "unavailable"
    assert [region.status for region in result.regions] == ["translated", "failed"]
    assert result.regions[0].translated_text == "800 or more"
    assert result.request_count == 0
    assert result.metrics_complete is False


def test_provider_configuration_failure_is_reported_per_korean_region(client, monkeypatch):
    monkeypatch.setenv("TRANSLATION_PROVIDER", "not-supported")
    response = client.post("/api/translate-image-text", json=request_for("문의", "123").model_dump())
    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "unavailable"
    assert [region["status"] for region in payload["regions"]] == ["failed", "unchanged"]
    assert payload["regions"][0]["translated_text"] == "문의"
    assert payload["metrics_complete"] is False


def test_out_of_order_completion_does_not_reassociate_regions(monkeypatch):
    class OutOfOrderProvider(TranslationProvider):
        name = "out-of-order"

        async def translate(self, text, source_language, target_language):
            await asyncio.sleep(0.01 if text == "먼저" else 0)
            return TranslationResult(text={"먼저": "First", "나중": "Later"}[text], provider=self.name, request_count=1)

    monkeypatch.setattr(image_translation, "choose_translation_provider", lambda mock: OutOfOrderProvider())
    result = asyncio.run(translate_image_regions(request_for("먼저", "나중")))
    assert [region.translated_text for region in result.regions] == ["First", "Later"]


def test_concurrency_is_bounded_and_successes_are_counted_once(monkeypatch):
    class ConcurrentProvider(TranslationProvider):
        name = "concurrent"
        active = 0
        peak = 0

        async def translate(self, text, source_language, target_language):
            self.active += 1
            self.peak = max(self.peak, self.active)
            try:
                await asyncio.sleep(0.005)
                return TranslationResult(text="Translated " + text.split()[-1], provider=self.name, request_count=2)
            finally:
                self.active -= 1

    provider = ConcurrentProvider()
    monkeypatch.setattr(image_translation, "choose_translation_provider", lambda mock: provider)
    result = asyncio.run(translate_image_regions(request_for(*(f"문의 {index}" for index in range(12)))))
    assert provider.peak == 4
    assert provider.active == 0
    assert len(result.regions) == 12
    assert result.request_count == 24


def test_native_provider_shares_client_and_restores_session_after_translation(monkeypatch):
    provider = MyMemoryTranslationProvider()
    clients: list[httpx.AsyncClient] = []
    original_client = httpx.AsyncClient
    calls: list[str] = []

    def handler(request):
        calls.append(request.url.params["q"])
        return httpx.Response(200, json={"responseStatus": 200, "responseData": {"translatedText": "Translated"}})

    def client_factory(*, limits):
        assert limits.max_connections == 4
        assert limits.max_keepalive_connections == 4
        client = original_client(transport=httpx.MockTransport(handler))
        clients.append(client)
        return client

    monkeypatch.setattr(image_translation.httpx, "AsyncClient", client_factory)
    monkeypatch.setattr(image_translation, "choose_translation_provider", lambda mock: provider)
    result = asyncio.run(translate_image_regions(request_for("문의", "모집", "문의")))
    assert len(clients) == 1
    assert clients[0].is_closed
    assert provider.client is None
    assert set(calls) == {"문의", "모집"}
    assert result.request_count == 2


@pytest.mark.parametrize("unexpected_failure", [False, True])
def test_cancellation_or_unexpected_failure_stops_pending_regions(monkeypatch, unexpected_failure):
    async def exercise():
        started = asyncio.Event()
        active = 0
        finished = 0
        calls = 0

        class WaitingProvider(TranslationProvider):
            name = "waiting"

            async def translate(self, text, source_language, target_language):
                nonlocal active, finished, calls
                active += 1
                calls += 1
                if active == 4:
                    started.set()
                try:
                    await started.wait()
                    if unexpected_failure and text == "문의 0":
                        raise ValueError("Unexpected programming failure")
                    await asyncio.Event().wait()
                finally:
                    active -= 1
                    finished += 1

        monkeypatch.setattr(image_translation, "choose_translation_provider", lambda mock: WaitingProvider())
        task = asyncio.create_task(translate_image_regions(request_for(*(f"문의 {index}" for index in range(10)))))
        await asyncio.wait_for(started.wait(), timeout=1)
        if not unexpected_failure:
            task.cancel()
        with pytest.raises(ValueError if unexpected_failure else asyncio.CancelledError):
            await task
        assert active == 0
        assert finished == calls
        assert calls <= 5

    asyncio.run(exercise())


@pytest.mark.parametrize("body", [
    {"regions": []},
    {"regions": [{"id": str(i), "text": "A"} for i in range(201)]},
    {"regions": [{"id": "x", "text": "A"}, {"id": "x", "text": "B"}]},
    {"regions": [{"id": "", "text": "A"}]},
    {"regions": [{"id": " ", "text": "A"}]},
    {"regions": [{"id": "x", "text": ""}]},
    {"regions": [{"id": "x", "text": "\n \t"}]},
    {"regions": [{"id": "x", "text": "A" * 4001}]},
    {"regions": [{"id": str(i), "text": "A" * 4000} for i in range(6)]},
    {"regions": [{"id": "x", "text": "A"}], "target_language": "ko"},
    {"regions": [{"id": "x", "text": "A", "image": "photo bytes"}]},
    {"regions": [{"id": "x", "text": "A"}], "photo": "photo bytes"},
])
def test_request_bounds_reject_invalid_input_before_provider_calls(client, monkeypatch, body):
    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid requests must not call the provider.")

    monkeypatch.setattr(image_translation, "choose_translation_provider", forbidden)
    assert client.post("/api/translate-image-text", json=body).status_code == 422


def test_exact_region_and_total_character_limits_are_accepted(client):
    regions = [{"id": str(i), "text": "A" * 100} for i in range(200)]
    response = client.post("/api/translate-image-text", json={"regions": regions})
    assert response.status_code == 200
    assert len(response.json()["regions"]) == 200
    response = client.post("/api/translate-image-text", json=request_for(*("A" * 4000 for _ in range(5))).model_dump())
    assert response.status_code == 200


def test_image_translation_uses_existing_public_limiter(client, monkeypatch):
    from app.services import public_access

    limiter = PublicAnalysisLimiter(max_concurrent=1, max_per_minute=1)
    monkeypatch.setattr(public_access, "analysis_limiter", limiter)
    monkeypatch.setenv("VISNOTICE_PUBLIC_MODE", "true")
    body = request_for("TOEIC 800").model_dump()
    assert client.post("/api/translate-image-text", json=body).status_code == 200
    response = client.post("/api/translate-image-text", json=body)
    assert response.status_code == 429
    assert response.headers["Retry-After"]
    assert limiter._active == 0
