from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.services.translation import (
    LibreTranslateProvider,
    MyMemoryTranslationProvider,
    TranslationError,
    TranslationResult,
)


def translate_payload(payload: object) -> None:
    async def exercise() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, content=json.dumps(payload))
            )
        ) as client:
            await MyMemoryTranslationProvider(client).translate("지원 안내", "ko", "en")

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {"responseStatus": 200, "responseData": None},
        {"responseStatus": 200, "responseData": {"translatedText": None}},
        {"responseStatus": 200, "responseData": {"translatedText": 123}},
    ],
)
def test_malformed_mymemory_response_is_an_actionable_provider_failure(
    payload: object,
) -> None:
    with pytest.raises(TranslationError, match="malformed translation response"):
        translate_payload(payload)


def test_mymemory_quota_message_is_not_presented_as_translated_notice() -> None:
    with pytest.raises(TranslationError, match="quota was reached"):
        translate_payload(
            {
                "responseStatus": 200,
                "quotaFinished": True,
                "responseData": {
                    "translatedText": "MYMEMORY WARNING: daily free quota reached"
                },
            }
        )


def test_repeated_translation_chunks_are_requested_once_without_losing_sections() -> (
    None
):
    seen_queries: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_queries.append(request.url.params["q"])
        return httpx.Response(
            200,
            json={
                "responseStatus": 200,
                "responseData": {"translatedText": "Submit the form."},
            },
        )

    async def exercise() -> TranslationResult:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await MyMemoryTranslationProvider(client).translate(
                "지원서를 제출하세요.\n\n지원서를 제출하세요.", "ko", "en"
            )

    result = asyncio.run(exercise())

    assert seen_queries == ["지원서를 제출하세요."]
    assert result.request_count == 1
    assert result.text == "Submit the form.\n\nSubmit the form."


def test_failed_translation_cancels_queued_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRANSLATION_CONCURRENCY", "1")
    seen_queries: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_queries.append(request.url.params["q"])
        await asyncio.sleep(0)
        return httpx.Response(
            200, json={"responseStatus": 200, "responseData": {"translatedText": ""}}
        )

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await MyMemoryTranslationProvider(client).translate(
                "지원 안내\n\n연구 기간\n\n문의 전화", "ko", "en"
            )

    with pytest.raises(TranslationError, match="empty translation"):
        asyncio.run(exercise())

    assert len(seen_queries) < 3


@pytest.mark.parametrize("payload", [None, [], {"translatedText": None}])
def test_malformed_libretranslate_response_is_an_actionable_provider_failure(
    payload: object,
) -> None:
    async def exercise() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, content=json.dumps(payload))
            )
        ) as client:
            await LibreTranslateProvider(client).translate("지원 안내", "ko", "en")

    with pytest.raises(TranslationError, match="malformed translation response"):
        asyncio.run(exercise())
