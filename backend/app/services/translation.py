from __future__ import annotations

import html
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx

from app.services.demos import match_demo


class TranslationError(RuntimeError):
    pass


@dataclass(frozen=True)
class TranslationResult:
    text: str
    provider: str
    request_count: int


def split_utf8_chunks(text: str, max_bytes: int = 480) -> list[str]:
    """Split text without breaking Unicode code points or exceeding an API byte limit."""
    if max_bytes < 4:
        raise ValueError("max_bytes must be at least 4")
    if not text:
        return []

    chunks: list[str] = []
    current = ""
    for token in re.findall(r"\S+\s*|\s+", text):
        candidate = current + token
        if len(candidate.encode("utf-8")) <= max_bytes:
            current = candidate
            continue
        if current:
            chunks.append(current.rstrip())
            current = ""
        while len(token.encode("utf-8")) > max_bytes:
            split_at = 0
            byte_count = 0
            for index, character in enumerate(token):
                next_count = byte_count + len(character.encode("utf-8"))
                if next_count > max_bytes:
                    break
                split_at = index + 1
                byte_count = next_count
            chunks.append(token[:split_at].rstrip())
            token = token[split_at:]
        current = token
    if current:
        chunks.append(current.rstrip())
    return [chunk for chunk in chunks if chunk]


class TranslationProvider(ABC):
    name: str

    @abstractmethod
    async def translate(self, text: str, source_language: str, target_language: str) -> TranslationResult:
        """Translate source text without interpreting or restructuring it."""


class MockTranslationProvider(TranslationProvider):
    name = "mock-translation"

    async def translate(self, text: str, source_language: str, target_language: str) -> TranslationResult:
        demo = match_demo(text)
        translated = demo.translation if demo else "A faithful translation is unavailable in mock mode for this text."
        return TranslationResult(text=translated, provider=self.name, request_count=0)


class MyMemoryTranslationProvider(TranslationProvider):
    name = "mymemory"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self.client = client
        self.endpoint = os.getenv("MYMEMORY_URL", "https://api.mymemory.translated.net/get")
        self.timeout = float(os.getenv("TRANSLATION_TIMEOUT_SECONDS", "20"))

    async def _translate_chunk(self, chunk: str, source_language: str, target_language: str) -> str:
        params = {"q": chunk, "langpair": f"{source_language}|{target_language}"}
        if self.client is not None:
            response = await self.client.get(self.endpoint, params=params, timeout=self.timeout)
        else:
            async with httpx.AsyncClient() as client:
                response = await client.get(self.endpoint, params=params, timeout=self.timeout)
        response.raise_for_status()
        payload = response.json()
        if int(payload.get("responseStatus", response.status_code)) != 200:
            raise TranslationError(str(payload.get("responseDetails") or "MyMemory rejected the translation request."))
        translated = html.unescape(str(payload.get("responseData", {}).get("translatedText", ""))).strip()
        if not translated:
            raise TranslationError("MyMemory returned an empty translation.")
        return translated

    async def translate(self, text: str, source_language: str, target_language: str) -> TranslationResult:
        chunks = split_utf8_chunks(text)
        try:
            translated = [await self._translate_chunk(chunk, source_language, target_language) for chunk in chunks]
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise TranslationError("The temporary MyMemory translation service is unavailable or its quota was reached.") from exc
        return TranslationResult(text="\n\n".join(translated), provider=self.name, request_count=len(chunks))


class LibreTranslateProvider(TranslationProvider):
    name = "libretranslate"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        base_url = os.getenv("LIBRETRANSLATE_URL", "http://127.0.0.1:5000").rstrip("/")
        self.endpoint = f"{base_url}/translate"
        self.api_key = os.getenv("LIBRETRANSLATE_API_KEY", "")
        self.client = client
        self.timeout = float(os.getenv("TRANSLATION_TIMEOUT_SECONDS", "20"))

    async def translate(self, text: str, source_language: str, target_language: str) -> TranslationResult:
        body: dict[str, str] = {"q": text, "source": source_language, "target": target_language, "format": "text"}
        if self.api_key:
            body["api_key"] = self.api_key
        try:
            if self.client is not None:
                response = await self.client.post(self.endpoint, json=body, timeout=self.timeout)
            else:
                async with httpx.AsyncClient() as client:
                    response = await client.post(self.endpoint, json=body, timeout=self.timeout)
            response.raise_for_status()
            translated = str(response.json().get("translatedText", "")).strip()
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise TranslationError("The configured LibreTranslate service could not translate this notice.") from exc
        if not translated:
            raise TranslationError("LibreTranslate returned an empty translation.")
        return TranslationResult(text=translated, provider=self.name, request_count=1)


def choose_translation_provider(mock: bool = False) -> TranslationProvider:
    if mock:
        return MockTranslationProvider()
    provider = os.getenv("TRANSLATION_PROVIDER", "mymemory").strip().lower()
    if provider == "mymemory":
        return MyMemoryTranslationProvider()
    if provider == "libretranslate":
        return LibreTranslateProvider()
    raise TranslationError("TRANSLATION_PROVIDER must be 'mymemory' or 'libretranslate'.")
