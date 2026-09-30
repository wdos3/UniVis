from __future__ import annotations

import asyncio
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
    """Keep OCR paragraphs and lines intact where the translation limit permits."""
    if max_bytes < 4:
        raise ValueError("max_bytes must be at least 4")
    if not text:
        return []

    chunks: list[str] = []
    normalized = re.sub(r"\r\n?", "\n", text)
    for paragraph in re.split(r"\n[ \t]*\n+", normalized):
        if not paragraph.strip():
            continue
        current_lines: list[str] = []
        for line in paragraph.split("\n"):
            line = line.strip()
            if not line:
                continue
            candidate = "\n".join([*current_lines, line])
            if len(candidate.encode("utf-8")) <= max_bytes:
                current_lines.append(line)
                continue
            if current_lines:
                chunks.append("\n".join(current_lines))
                current_lines = []
            if len(line.encode("utf-8")) <= max_bytes:
                current_lines.append(line)
            else:
                chunks.extend(_split_oversize_line(line, max_bytes))
        if current_lines:
            chunks.append("\n".join(current_lines))
    return chunks


def _split_oversize_line(line: str, max_bytes: int) -> list[str]:
    """Prefer sentence or word boundaries before falling back to code points."""
    pieces: list[str] = []
    remaining = line
    while len(remaining.encode("utf-8")) > max_bytes:
        byte_count = 0
        prefix_end = 0
        for index, character in enumerate(remaining):
            byte_count += len(character.encode("utf-8"))
            if byte_count > max_bytes:
                break
            prefix_end = index + 1
        prefix = remaining[:prefix_end]
        sentence_ends = list(re.finditer(r"(?<=[.!?。！？])[ \t]+", prefix))
        word_ends = list(re.finditer(r"[ \t]+", prefix))
        split_at = (sentence_ends or word_ends)[-1].end() if sentence_ends or word_ends else prefix_end
        pieces.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].lstrip()
    if remaining:
        pieces.append(remaining)
    return [piece for piece in pieces if piece]


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

    async def _translate_chunk(
        self,
        chunk: str,
        source_language: str,
        target_language: str,
        client: httpx.AsyncClient,
    ) -> str:
        params = {"q": chunk, "langpair": f"{source_language}|{target_language}"}
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
            concurrency = max(1, int(os.getenv("TRANSLATION_CONCURRENCY", "4")))
            semaphore = asyncio.Semaphore(concurrency)

            async def translate_chunk(chunk: str, client: httpx.AsyncClient) -> str:
                async with semaphore:
                    return await self._translate_chunk(chunk, source_language, target_language, client)

            if self.client is not None:
                translated = await asyncio.gather(*(translate_chunk(chunk, self.client) for chunk in chunks))
            else:
                async with httpx.AsyncClient() as client:
                    translated = await asyncio.gather(*(translate_chunk(chunk, client) for chunk in chunks))
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
