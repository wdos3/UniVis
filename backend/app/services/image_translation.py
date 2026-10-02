from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from time import perf_counter
from typing import Literal

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.public_access import limit_public_analysis
from app.services.translation import (
    LibreTranslateProvider,
    MyMemoryTranslationProvider,
    TranslationError,
    TranslationProvider,
    choose_translation_provider,
)


# Include isolated letters as well as syllables; even a small Korean suffix
# should prevent an untranslated block from replacing its source image text.
HANGUL = re.compile(r"[\u1100-\u11ff\u3130-\u318f\ua960-\ua97f\uac00-\ud7af\ud7b0-\ud7ff]")
STANDALONE_THRESHOLD = re.compile(
    r"(?P<value>[+-]?(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?%?"
    r"|(?=[A-Za-z0-9]*[0-9])[A-Za-z0-9]+)\s*(?P<comparison>이상|이하|초과|미만)"
)
MAX_TRANSLATION_CONCURRENCY = 4


class ImageTextRegion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=4000)

    @field_validator("id", "text")
    @classmethod
    def require_nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Region IDs and text must not be blank.")
        return value


class ImageTextTranslationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    regions: list[ImageTextRegion] = Field(min_length=1, max_length=200)
    target_language: Literal["en"] = "en"

    @model_validator(mode="after")
    def bound_regions(self) -> ImageTextTranslationRequest:
        if len({region.id for region in self.regions}) != len(self.regions):
            raise ValueError("Region IDs must be unique.")
        if sum(len(region.text) for region in self.regions) > 20000:
            raise ValueError("Combined region text must not exceed 20000 characters.")
        return self


class TranslatedImageTextRegion(BaseModel):
    id: str
    source_text: str
    translated_text: str
    status: Literal["translated", "unchanged", "failed"]
    error: str | None = None


class ImageTextTranslationResponse(BaseModel):
    regions: list[TranslatedImageTextRegion]
    provider: str
    request_count: int = Field(ge=0)
    latency_ms: int = Field(ge=0)
    metrics_complete: bool


@dataclass(frozen=True)
class _TranslationOutcome:
    text: str
    status: Literal["translated", "failed"]
    request_count: int = 0
    error: str | None = None
    metrics_complete: bool = True


def _translate_standalone_threshold(text: str) -> str | None:
    # Only a complete value-and-comparator cell is safe to translate locally.
    # Larger sentences can use the same Korean words with different meanings.
    threshold = STANDALONE_THRESHOLD.fullmatch(text.strip())
    if not threshold:
        return None
    value = threshold["value"]
    match threshold["comparison"]:
        case "이상":
            return f"{value} or more"
        case "이하":
            return f"{value} or less"
        case "초과":
            return f"More than {value}"
        case "미만":
            return f"Less than {value}"
    return None


async def _translate_unique_regions(
    provider: TranslationProvider, texts: list[str]
) -> dict[str, _TranslationOutcome]:
    semaphore = asyncio.Semaphore(MAX_TRANSLATION_CONCURRENCY)

    async def translate(text: str) -> _TranslationOutcome:
        async with semaphore:
            try:
                result = await provider.translate(text, "ko", "en")
            except TranslationError as exc:
                # The provider cannot report usage for a partially failed call.
                # Other independently readable regions can still be translated.
                return _TranslationOutcome(
                    text=text,
                    status="failed",
                    error=str(exc),
                    metrics_complete=False,
                )
            translated = result.text.strip()
            if not translated or HANGUL.search(translated):
                return _TranslationOutcome(
                    text=text,
                    status="failed",
                    request_count=result.request_count,
                    error="The translation was empty or still contained Korean. The original text was retained.",
                )
            return _TranslationOutcome(
                text=translated, status="translated", request_count=result.request_count
            )

    tasks = [asyncio.create_task(translate(text)) for text in texts]
    try:
        outcomes = await asyncio.gather(*tasks)
        return dict(zip(texts, outcomes))
    finally:
        # Cancel queued work before closing its shared HTTP client on an
        # unexpected failure or client cancellation.
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def _translate_with_session(
    provider: TranslationProvider, texts: list[str]
) -> dict[str, _TranslationOutcome]:
    if isinstance(provider, (MyMemoryTranslationProvider, LibreTranslateProvider)) and provider.client is None:
        # MyMemory also splits long blocks into requests. Connection limits
        # bound those nested requests as well as the region-level semaphore.
        limits = httpx.Limits(
            max_connections=MAX_TRANSLATION_CONCURRENCY,
            max_keepalive_connections=MAX_TRANSLATION_CONCURRENCY,
        )
        async with httpx.AsyncClient(limits=limits) as client:
            provider.client = client
            try:
                return await _translate_unique_regions(provider, texts)
            finally:
                provider.client = None
    return await _translate_unique_regions(provider, texts)


async def translate_image_regions(
    request: ImageTextTranslationRequest,
) -> ImageTextTranslationResponse:
    started = perf_counter()
    texts = list(dict.fromkeys(region.text for region in request.regions if HANGUL.search(region.text)))
    outcomes: dict[str, _TranslationOutcome] = {}
    for text in texts:
        translated = _translate_standalone_threshold(text)
        if translated is not None:
            outcomes[text] = _TranslationOutcome(text=translated, status="translated")
    provider_name = "local" if outcomes else "not-needed"
    provider_texts = [text for text in texts if text not in outcomes]
    if provider_texts:
        try:
            provider = choose_translation_provider(mock=False)
        except TranslationError as exc:
            provider_name = "unavailable"
            outcomes.update({
                text: _TranslationOutcome(
                    text=text, status="failed", error=str(exc), metrics_complete=False
                )
                for text in provider_texts
            })
        else:
            provider_name = provider.name
            outcomes.update(await _translate_with_session(provider, provider_texts))

    regions: list[TranslatedImageTextRegion] = []
    for region in request.regions:
        outcome = outcomes.get(region.text)
        regions.append(TranslatedImageTextRegion(
            id=region.id,
            source_text=region.text,
            translated_text=outcome.text if outcome else region.text,
            status=outcome.status if outcome else "unchanged",
            error=outcome.error if outcome else None,
        ))
    return ImageTextTranslationResponse(
        regions=regions,
        provider=provider_name,
        request_count=sum(outcome.request_count for outcome in outcomes.values()),
        latency_ms=round((perf_counter() - started) * 1000),
        metrics_complete=all(outcome.metrics_complete for outcome in outcomes.values()),
    )


router = APIRouter()


@router.post(
    "/api/translate-image-text",
    response_model=ImageTextTranslationResponse,
    response_model_exclude_none=True,
    dependencies=[Depends(limit_public_analysis)],
)
async def translate_image_text(
    request: ImageTextTranslationRequest,
) -> ImageTextTranslationResponse:
    return await translate_image_regions(request)
