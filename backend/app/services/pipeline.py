from __future__ import annotations

import re
from time import perf_counter
from dataclasses import dataclass, field

from app.models import ConditionalGroup, NoticeData
from app.services.demos import DEMOS
from app.services.images.models import PreparedImage
from app.services.ocr import OcrResult, choose_ocr_provider
from app.services.semantic import SemanticResult, SourceCorrectionRequired, choose_semantic_provider
from app.services.source_contacts import contact_corrections
from app.services.translation import TranslationError, TranslationResult, choose_translation_provider


@dataclass(frozen=True)
class PipelineResult:
    source_text: str
    translation: str
    notice: NoticeData
    provider: str
    translation_provider: str
    semantic_provider: str
    translation_requests: int
    semantic_requests: int
    semantic_input_tokens: int
    semantic_output_tokens: int
    semantic_total_tokens: int
    ocr_latency_ms: int = 0
    translation_latency_ms: int = 0
    semantic_latency_ms: int = 0
    extraction_latency_ms: int = 0
    english_repair_latency_ms: int = 0
    coverage_latency_ms: int = 0
    english_verification_latency_ms: int = 0
    total_latency_ms: int = 0
    warnings: list[str] = field(default_factory=list)
    ocr_provider: str = "not_applicable"
    ocr_status: str = "not_applicable"
    page_texts: list[str] = field(default_factory=list)
    english_coverage_status: str = "not_audited"
    unverified_source_units: int = 0
    metrics_complete: bool = True


def _demo_for_images(images: list[PreparedImage]):
    names = " ".join(image.page.filename.lower() for image in images)
    if any(token in names for token in ("visa", "angled", "qr", "mixed")):
        return DEMOS[0]
    if "tuition" in names:
        return DEMOS[1]
    if any(token in names for token in ("scholarship", "multi-page")):
        return DEMOS[2]
    if "dorm" in names:
        return DEMOS[3]
    if any(token in names for token in ("table", "course")):
        return DEMOS[4]
    return None


async def analyze_text_pipeline(
    text: str, target_language: str, provider: str, *, layout_context: str = "", allow_partial: bool = False
) -> PipelineResult:
    pipeline_started = perf_counter()
    semantic = choose_semantic_provider(provider)
    is_mock = semantic.name == "mock-semantic"
    if not is_mock and not allow_partial and (corrections := contact_corrections(text)):
        raise SourceCorrectionRequired("Correct the unreadable phone number in the recovered text and retry.", corrections)
    translator = choose_translation_provider(mock=is_mock)
    translation_started = perf_counter()
    warnings: list[str] = []
    try:
        translation: TranslationResult = await translator.translate(text, "ko", target_language)
    except TranslationError:
        if not allow_partial or is_mock:
            raise
        translation = TranslationResult(text="", provider="unavailable", request_count=0)
        warnings.append("The temporary translation service was unavailable. English instructions were interpreted directly from the recovered source; the separate baseline translation is unavailable.")
    translation_latency_ms = round((perf_counter() - translation_started) * 1000)
    semantic_started = perf_counter()
    semantic_options = {"layout_context": layout_context}
    if allow_partial:
        semantic_options["allow_partial"] = True
    structured: SemanticResult = await semantic.analyze(text, translation.text, target_language, **semantic_options)
    semantic_latency_ms = round((perf_counter() - semantic_started) * 1000)
    return PipelineResult(
        source_text=text,
        translation=translation.text,
        notice=structured.notice,
        provider=f"{translation.provider} → {structured.provider}",
        translation_provider=translation.provider,
        semantic_provider=structured.provider,
        translation_requests=translation.request_count,
        semantic_requests=structured.requests,
        semantic_input_tokens=structured.input_tokens,
        semantic_output_tokens=structured.output_tokens,
        semantic_total_tokens=structured.total_tokens,
        translation_latency_ms=translation_latency_ms,
        semantic_latency_ms=semantic_latency_ms,
        extraction_latency_ms=structured.extraction_latency_ms,
        english_repair_latency_ms=structured.english_repair_latency_ms,
        total_latency_ms=round((perf_counter() - pipeline_started) * 1000),
        warnings=warnings + structured.warnings,
        metrics_complete=not warnings,
    )


async def analyze_image_pipeline(images: list[PreparedImage], target_language: str, provider: str) -> PipelineResult:
    pipeline_started = perf_counter()
    semantic = choose_semantic_provider(provider)
    if semantic.name == "mock-semantic":
        demo = _demo_for_images(images)
        if demo is None:
            from app.services.semantic import SemanticError

            raise SemanticError("Mock analysis recognizes only the bundled synthetic image demos. Configure OPENAI_API_KEY for real photographs.")
        ocr = OcrResult(
            text=demo.original_text,
            page_texts=[demo.original_text] + [f"[Synthetic continuation page {index}]" for index in range(2, len(images) + 1)],
            provider="synthetic-demo-ocr",
            status="available",
        )
        ocr_latency_ms = 0
    else:
        ocr_started = perf_counter()
        ocr = await choose_ocr_provider().extract(images)
        ocr_latency_ms = round((perf_counter() - ocr_started) * 1000)
        if len(re.findall(r"[가-힣]", ocr.text)) < 4:
            from app.services.ocr import OcrError

            raise OcrError("Unable to reliably read this notice. PaddleOCR recovered no Korean text; please retake the photo.")

    if semantic.name != "mock-semantic" and (corrections := contact_corrections(ocr.text)):
        raise SourceCorrectionRequired("Correct the unreadable phone number in the recovered text and retry.", corrections)
    translator = choose_translation_provider(mock=semantic.name == "mock-semantic")
    translation_started = perf_counter()
    translation = await translator.translate(ocr.text, "ko", target_language)
    translation_latency_ms = round((perf_counter() - translation_started) * 1000)
    semantic_started = perf_counter()
    structured = await semantic.analyze(ocr.text, translation.text, target_language)
    semantic_latency_ms = round((perf_counter() - semantic_started) * 1000)
    if semantic.name == "mock-semantic" and demo.id == "demo-courses-2027":
        structured.notice.conditional_groups = [
            ConditionalGroup(group="Enrolled students", application_period="February 15–17, 2027", source_evidence=demo.notice.deadlines[0].source_evidence, source_fact_ids=["F001"], source_page=1),
            ConditionalGroup(group="New students", application_period="February 19, 2027", source_evidence=demo.notice.deadlines[1].source_evidence, source_fact_ids=["F002"], source_page=1),
        ]
    return PipelineResult(
        source_text=ocr.text,
        translation=translation.text,
        notice=structured.notice,
        provider=f"{ocr.provider} → {translation.provider} → {structured.provider}",
        ocr_provider=ocr.provider,
        ocr_status=ocr.status,
        page_texts=ocr.page_texts,
        translation_provider=translation.provider,
        semantic_provider=structured.provider,
        translation_requests=translation.request_count,
        semantic_requests=structured.requests,
        semantic_input_tokens=structured.input_tokens,
        semantic_output_tokens=structured.output_tokens,
        semantic_total_tokens=structured.total_tokens,
        ocr_latency_ms=ocr_latency_ms,
        translation_latency_ms=translation_latency_ms,
        semantic_latency_ms=semantic_latency_ms,
        extraction_latency_ms=structured.extraction_latency_ms,
        english_repair_latency_ms=structured.english_repair_latency_ms,
        total_latency_ms=round((perf_counter() - pipeline_started) * 1000),
        warnings=ocr.warnings + structured.warnings,
    )
