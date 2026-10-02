from __future__ import annotations

import logging
import os
import re
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from importlib.util import find_spec
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from app.models import (
    AnalysisResult,
    AnalyzeRequest,
    ClientOcrRequest,
    DemoSummary,
    ImageAcquisitionReport,
    ImageDemoSummary,
    ImageQualityIssue,
    NoticeData,
    RecoveredTextUpdate,
    ResearchResultCreate,
    SourcePage,
)
from app.services.demos import DEMOS, get_demo, match_demo
from app.services.fidelity import calculate_fidelity, select_templates
from app.services.coverage import audit_coverage
from app.services.coverage_repair import CoverageProviderError, CoverageRepairError, repair_coverage
from app.services.english_review import EnglishNoticeReview, review_notice_english
from app.services.extraction.reconciliation import add_page_provenance, split_recovered_pages
from app.services.extraction.language_scores import (
    LanguageScoreError, add_aligned_language_scores, mark_unverified_language_scores,
    validate_aligned_language_scores, EXAM_NAME, EXAM_SUFFIX, EXAM_MENTION,
)
from app.services.image_demos import IMAGE_DEMOS
from app.services.images.pdf_images import render_pdf_pages
from app.services.images.preprocessing import ImageProcessingError, prepare_image, upload_root
from app.services.ocr_layout import format_ocr_layout, reorder_ocr_page_columns
from app.services.pdf import DocumentExtractionError, extract_pdf
from app.services.pipeline import PipelineResult, analyze_image_pipeline, analyze_text_pipeline
from app.services.public_access import limit_public_analysis, public_mode, require_admin
from app.services.ocr import OcrError
from app.services.semantic import SemanticError, SourceCorrectionRequired
from app.services.source_contacts import contact_corrections
from app.services.storage import (
    export_research_csv,
    get_notice,
    initialize_database,
    list_notices,
    save_notice,
    save_research_result,
)
from app.services.text import appears_korean, simplified_text
from app.services.translation import TranslationError


load_dotenv(Path(__file__).resolve().parents[2] / ".env")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger("visnotice")
MAX_UPLOAD_BYTES = 15 * 1024 * 1024
MAX_TOTAL_IMAGE_BYTES = 50 * 1024 * 1024


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    yield


app = FastAPI(title="VisNotice — Version 2 API", version="2.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:5174").split(",")],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["*"],
)
DEMO_IMAGE_ROOT = Path(__file__).resolve().parents[2] / "demo_data" / "images"
app.mount("/uploads", StaticFiles(directory=upload_root()), name="uploads")
app.mount("/demo-images", StaticFiles(directory=DEMO_IMAGE_ROOT, check_dir=False), name="demo-images")


def make_result(
    original_text: str,
    translation: str,
    notice: NoticeData,
    provider: str,
    validation_warnings: list[str] | None = None,
    result_id: str | None = None,
    created_at: str | None = None,
    synthetic: bool = False,
    recovered_text: str = "",
    source_pages: list[SourcePage] | None = None,
    acquisition: ImageAcquisitionReport | None = None,
) -> AnalysisResult:
    if validation_warnings:
        notice.unverified_items = list(dict.fromkeys(notice.unverified_items + validation_warnings))
    digest = simplified_text(notice)
    if acquisition and acquisition.english_coverage_status == "partial" and notice.unverified_items:
        digest += "\n\nVerification gaps\n" + "\n".join(f"- {item}" for item in notice.unverified_items)
    return AnalysisResult(
        id=result_id or f"notice-{uuid4().hex}",
        created_at=created_at or datetime.now(UTC).isoformat(),
        original_text=original_text,
        faithful_translation=translation,
        simplified_text=digest,
        notice=notice,
        templates=select_templates(notice),
        fidelity=calculate_fidelity(notice, original_text),
        korean_detected=appears_korean(original_text),
        provider=provider,
        synthetic=synthetic,
        recovered_text=recovered_text,
        source_pages=source_pages or [],
        acquisition=acquisition or ImageAcquisitionReport(),
    )


async def analyze(request: AnalyzeRequest) -> AnalysisResult:
    logger.info("analysis_started provider=%s korean_detected=%s", request.provider, appears_korean(request.text))
    pipeline = await _run_text_pipeline(request)
    pipeline = await _complete_english_coverage(pipeline)
    acquisition = _pipeline_acquisition(pipeline, "text")
    result = make_result(
        pipeline.source_text,
        pipeline.translation,
        pipeline.notice,
        pipeline.provider,
        pipeline.warnings,
        synthetic=pipeline.semantic_provider == "mock-semantic" and match_demo(request.text) is not None,
        acquisition=acquisition,
    )
    save_notice(result)
    logger.info("analysis_completed notice_id=%s provider=%s semantic_requests=%s semantic_tokens=%s", result.id, pipeline.provider, pipeline.semantic_requests, pipeline.semantic_total_tokens)
    return result


async def _run_text_pipeline(request: AnalyzeRequest, *, layout_context: str = "", allow_partial: bool = False) -> PipelineResult:
    try:
        return await analyze_text_pipeline(
            request.text, request.target_language, request.provider, layout_context=layout_context, allow_partial=allow_partial,
        )
    except SourceCorrectionRequired as exc:
        raise _source_correction_error(exc) from exc
    except (TranslationError, SemanticError) as exc:
        logger.warning("analysis_failed provider=%s reason=%s", request.provider, type(exc).__name__)
        status = 422 if "Mock" in str(exc) or "not configured" in str(exc) else 502
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("analysis_failed provider=%s", request.provider)
        raise HTTPException(status_code=502, detail="The configured Version 2 pipeline could not complete the analysis.") from exc


def _source_correction_error(exc: Exception, *, message: str | None = None) -> HTTPException:
    return HTTPException(status_code=422, detail={
        "code": "source_correction_required",
        "message": message or str(exc),
        "corrections": getattr(exc, "corrections", []),
    })


async def _complete_english_coverage(
    pipeline: PipelineResult, *, layout_context: str = "", allow_partial: bool = False,
    unverified_source_texts: tuple[str, ...] = (),
) -> PipelineResult:
    if not pipeline.semantic_provider.startswith("openai-semantic:") or pipeline.notice.target_language != "en":
        return pipeline
    started = perf_counter()
    try:
        options = {"layout_context": layout_context}
        if allow_partial:
            options.update(allow_partial=True, unverified_source_texts=unverified_source_texts)
        repair = await repair_coverage(pipeline.notice, pipeline.source_text, **options)
    except CoverageProviderError as exc:
        logger.warning("coverage_provider_failed reason=%s", type(exc).__name__)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except CoverageRepairError as exc:
        logger.warning("coverage_repair_failed reason=%s", type(exc).__name__)
        raise _source_correction_error(
            exc, message=f"A complete English interpretation could not be verified: {exc} Correct the listed source text and retry.",
        ) from exc
    final_review = EnglishNoticeReview(notice=repair.notice)
    review_started = perf_counter()
    if allow_partial:
        final_review = await review_notice_english(
            repair.review_candidates or repair.notice, pipeline.source_text, layout_context=layout_context, primary_notice_title=pipeline.notice.title,
        )
    elapsed_ms = round((perf_counter() - started) * 1000)
    verification_ms = round((perf_counter() - review_started) * 1000) if allow_partial else 0
    return replace(
        pipeline,
        notice=final_review.notice,
        semantic_requests=pipeline.semantic_requests + repair.requests + final_review.requests,
        semantic_input_tokens=pipeline.semantic_input_tokens + repair.input_tokens + final_review.input_tokens,
        semantic_output_tokens=pipeline.semantic_output_tokens + repair.output_tokens + final_review.output_tokens,
        semantic_total_tokens=pipeline.semantic_total_tokens + repair.total_tokens + final_review.total_tokens,
        semantic_latency_ms=pipeline.semantic_latency_ms + elapsed_ms,
        coverage_latency_ms=elapsed_ms - verification_ms,
        english_verification_latency_ms=verification_ms,
        total_latency_ms=pipeline.total_latency_ms + elapsed_ms,
        english_coverage_status="partial" if (final_review.has_verification_gaps if allow_partial else repair.has_verification_gaps) else "audited",
        unverified_source_units=final_review.unverified_source_units if allow_partial else len(repair.unverified_units),
        metrics_complete=pipeline.metrics_complete and repair.usage_complete and final_review.usage_complete,
    )


def _pipeline_acquisition(
    pipeline: PipelineResult,
    input_type: str,
    *,
    source_pages: int = 0,
    quality_warnings: int = 0,
    pages_needing_review: int = 0,
    critical_facts_needing_review: int = 0,
) -> ImageAcquisitionReport:
    return ImageAcquisitionReport(
        input_type=input_type,
        source_pages=source_pages,
        text_extraction_status=pipeline.ocr_status,
        quality_warnings=quality_warnings,
        pages_needing_review=pages_needing_review,
        critical_facts_needing_review=critical_facts_needing_review,
        reconciliation_conflicts=[],
        ocr_provider=pipeline.ocr_provider,
        translation_provider=pipeline.translation_provider,
        semantic_provider=pipeline.semantic_provider,
        translation_requests=pipeline.translation_requests,
        semantic_requests=pipeline.semantic_requests,
        semantic_input_tokens=pipeline.semantic_input_tokens,
        semantic_output_tokens=pipeline.semantic_output_tokens,
        semantic_total_tokens=pipeline.semantic_total_tokens,
        ocr_latency_ms=pipeline.ocr_latency_ms,
        translation_latency_ms=pipeline.translation_latency_ms,
        semantic_latency_ms=pipeline.semantic_latency_ms,
        extraction_latency_ms=pipeline.extraction_latency_ms,
        english_repair_latency_ms=pipeline.english_repair_latency_ms,
        coverage_latency_ms=pipeline.coverage_latency_ms,
        english_verification_latency_ms=pipeline.english_verification_latency_ms,
        total_latency_ms=pipeline.total_latency_ms,
        english_coverage_status=pipeline.english_coverage_status,
        unverified_source_units=pipeline.unverified_source_units,
        metrics_complete=pipeline.metrics_complete,
    )


@app.get("/api/health")
def health() -> dict[str, object]:
    if os.getenv("PADDLEOCR_SERVICE_URL", "").strip():
        ocr_provider = "paddleocr-ppocrv5-korean-container"
    else:
        ocr_provider = "paddleocr-ppocrv5-korean-local"
    if os.getenv("VERCEL") == "1" and find_spec("paddleocr") is None and not os.getenv("PADDLEOCR_SERVICE_URL", "").strip():
        ocr_provider = "paddleocr-local-unavailable-on-vercel"
    return {
        "status": "ok",
        "version": 2,
        "openai_configured": bool(os.getenv("OPENAI_API_KEY")),
        "default_provider": "openai" if os.getenv("OPENAI_API_KEY") else "mock",
        "translation_provider": os.getenv("TRANSLATION_PROVIDER", "mymemory"),
        "ocr_provider": ocr_provider,
        "semantic_model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        "public_mode": public_mode(),
    }


@app.get("/api/demos", response_model=list[DemoSummary])
def demos() -> list[DemoSummary]:
    return [DemoSummary(id=demo.id, title=demo.notice.title, category=demo.notice.notice_type, original_text=demo.original_text, questions=demo.questions) for demo in DEMOS]


@app.get("/api/demos/{demo_id}", response_model=AnalysisResult)
def demo_detail(demo_id: str) -> AnalysisResult:
    demo = get_demo(demo_id)
    if not demo:
        raise HTTPException(status_code=404, detail="Demo notice not found.")
    return make_result(demo.original_text, demo.translation, demo.notice.model_copy(deep=True), "mock", result_id=demo.id, synthetic=True)


@app.get("/api/image-demos", response_model=list[ImageDemoSummary])
def image_demos() -> list[ImageDemoSummary]:
    return IMAGE_DEMOS


@app.post("/api/analyze", response_model=AnalysisResult, dependencies=[Depends(limit_public_analysis)])
async def analyze_text(request: AnalyzeRequest) -> AnalysisResult:
    return await analyze(request)


@app.post("/api/analyze-client-ocr", response_model=AnalysisResult, dependencies=[Depends(limit_public_analysis)])
async def analyze_client_ocr(request: ClientOcrRequest) -> AnalysisResult:
    ordered_pages = [reorder_ocr_page_columns(page) for page in request.pages]
    unverified_texts: list[str] = []
    table_uncertain = False
    try:
        validate_aligned_language_scores(ordered_pages)
    except LanguageScoreError as exc:
        if not request.allow_partial:
            raise _source_correction_error(exc) from exc
        table_uncertain = True
        unverified_texts.extend(str(item["text"]) for item in exc.corrections)
        for page in ordered_pages:
            if not EXAM_MENTION.search(page.text):
                continue
            unverified_texts.extend(
                line.strip() for line in page.text.splitlines()
                if EXAM_NAME.fullmatch(line.strip()) or EXAM_SUFFIX.fullmatch(line.strip())
                or re.fullmatch(r"[A-Za-z0-9.() -]{1,16}\s*(?:점\s*)?이상", line.strip())
            )
    page_texts = [page.text.strip() for page in ordered_pages]
    source_text = "\n\n".join(f"[Page {index}]\n{text}" for index, text in enumerate(page_texts, start=1))
    if request.allow_partial:
        unverified_texts.extend(item["text"] for item in contact_corrections(source_text))
    if len(re.findall(r"[가-힣]", source_text)) < 4:
        if request.allow_partial and request.provider != "mock":
            return _client_ocr_unverified_result(
                request, page_texts, source_text,
                "The image did not yield enough readable Korean to verify instructions. No dates, amounts, eligibility, or actions could be established. A closer, brighter photo of the notice can improve automatic reading; no Korean transcription is required.",
                extraction_status="unavailable",
            )
        raise HTTPException(
            status_code=422,
            detail="Browser OCR recovered too little Korean text. Retake the photo closer, brighter, and straight-on.",
        )

    layout_context = format_ocr_layout(ordered_pages)
    started = perf_counter()
    try:
        pipeline = await _run_text_pipeline(
            AnalyzeRequest(text=source_text, target_language=request.target_language, provider=request.provider),
            layout_context=layout_context,
            allow_partial=request.allow_partial,
        )
    except HTTPException as exc:
        if not request.allow_partial or exc.status_code < 500:
            raise
        return _client_ocr_unverified_result(
            request, page_texts, source_text,
            "The interpretation service could not verify this attempt. No notice instructions are presented as established facts. Your photo and recognized text are retained; retrying does not require Korean transcription.",
            elapsed_ms=round((perf_counter() - started) * 1000),
        )
    if pipeline.semantic_provider == "mock-semantic":
        normalized_ocr = re.sub(r"\s+", "", "".join(page_texts))
        if not any(re.sub(r"\s+", "", demo.original_text) == normalized_ocr for demo in DEMOS):
            raise HTTPException(
                status_code=422,
                detail="Mock analysis cannot interpret an incomplete or real notice photo. Use a bundled synthetic demo or configure the OpenAI semantic provider.",
            )
    result_id = f"notice-{uuid4().hex}"
    pages = _client_ocr_source_pages(page_texts, result_id)
    add_page_provenance(pipeline.notice, page_texts, pages)
    if table_uncertain:
        mark_unverified_language_scores(pipeline.notice, source_text)
    try:
        pipeline = await _complete_english_coverage(
            pipeline, layout_context=layout_context, allow_partial=request.allow_partial,
            unverified_source_texts=tuple(unverified_texts),
        )
    except HTTPException as exc:
        if not request.allow_partial or exc.status_code not in (422, 502, 503):
            raise
        return _client_ocr_unverified_result(
            request, page_texts, source_text,
            "The recovered notice could not pass source verification within this attempt's limits. Its instructions are withheld. Your photo and text are retained, and retrying does not require Korean transcription.",
            elapsed_ms=round((perf_counter() - started) * 1000),
            completed_pipeline=pipeline,
        )
    add_page_provenance(pipeline.notice, page_texts, pages)
    if not table_uncertain:
        # Literal cell pairs have independent positional evidence. A semantic
        # judgment of applicability cannot erase the printed pairings or turn
        # an unrelated/non-applicable table into positive eligibility.
        add_aligned_language_scores(
            pipeline.notice, ordered_pages, pages,
            presentation="printed_table" if request.allow_partial else "eligibility",
        )
    blank_pages = [page.page_number for page in pages if not page.readable]
    warnings = [f"Browser OCR recovered no text from page(s): {', '.join(map(str, blank_pages))}."] if blank_pages else []
    acquisition = _pipeline_acquisition(
        pipeline,
        request.input_type,
        source_pages=len(pages),
        quality_warnings=len(blank_pages),
        pages_needing_review=len(blank_pages),
        critical_facts_needing_review=sum(fact.critical and fact.state.value == "needs_review" for fact in pipeline.notice.source_facts),
    ).model_copy(update={
        "text_extraction_status": "partial" if blank_pages else "available",
        "ocr_provider": "browser-ocr-kor-eng",
        "ocr_latency_ms": request.ocr_latency_ms,
        "total_latency_ms": request.ocr_latency_ms + pipeline.total_latency_ms,
        "english_coverage_status": "partial" if blank_pages else pipeline.english_coverage_status,
    })
    result = make_result(
        pipeline.source_text,
        pipeline.translation,
        pipeline.notice,
        pipeline.provider,
        pipeline.warnings + warnings,
        result_id=result_id,
        synthetic=pipeline.semantic_provider == "mock-semantic",
        recovered_text=pipeline.source_text,
        source_pages=pages,
        acquisition=acquisition,
    )
    save_notice(result)
    logger.info(
        "client_ocr_analysis_completed notice_id=%s provider=%s pages=%s semantic_requests=%s semantic_tokens=%s",
        result.id, pipeline.provider, len(pages), pipeline.semantic_requests, pipeline.semantic_total_tokens,
    )
    return result


def _client_ocr_source_pages(page_texts: list[str], result_id: str) -> list[SourcePage]:
    return [
        SourcePage(
            id=f"{result_id}-page-{index}",
            page_number=index,
            filename=f"Page {index}",
            media_type="application/octet-stream",
            original_url="",
            processed_url="",
            width=1,
            height=1,
            readable=bool(text),
            quality_issues=(
                [] if text else [ImageQualityIssue(code="ocr_empty_page", message="Browser OCR recovered no text from this page.")]
            ),
        )
        for index, text in enumerate(page_texts, start=1)
    ]


def _client_ocr_unverified_result(
    request: ClientOcrRequest, page_texts: list[str], source_text: str, message: str,
    *, extraction_status: str = "available", elapsed_ms: int = 0,
    completed_pipeline: PipelineResult | None = None,
) -> AnalysisResult:
    """Keep the photo workflow usable without presenting unaudited facts."""
    result_id = f"notice-{uuid4().hex}"
    acquisition = (
        _pipeline_acquisition(completed_pipeline, request.input_type, source_pages=len(page_texts))
        if completed_pipeline else ImageAcquisitionReport(input_type=request.input_type, source_pages=len(page_texts))
    ).model_copy(update={
        "text_extraction_status": extraction_status, "english_coverage_status": "partial",
        "unverified_source_units": len(audit_coverage(NoticeData(), source_text).units),
        "pages_needing_review": len(page_texts), "ocr_provider": "browser-ocr-kor-eng",
        "ocr_latency_ms": request.ocr_latency_ms, "total_latency_ms": request.ocr_latency_ms + elapsed_ms,
        "metrics_complete": extraction_status == "unavailable",
    })
    result = make_result(
        source_text, "", NoticeData(title="English interpretation unavailable", unverified_items=[message]),
        "browser-ocr-kor-eng", result_id=result_id, recovered_text=source_text,
        source_pages=_client_ocr_source_pages(page_texts, result_id),
        acquisition=acquisition,
    )
    save_notice(result)
    return result


async def analyze_prepared_images(
    prepared_images,
    provider: str,
    target_language: str,
    input_type: str,
    supplemental_text: str = "",
) -> AnalysisResult:
    if prepared_images and all(not image.page.readable for image in prepared_images):
        raise HTTPException(
            status_code=422,
            detail="Unable to reliably read this notice. Retake the photo closer, brighter, and straight-on.",
        )
    try:
        pipeline = await analyze_image_pipeline(prepared_images, target_language, provider)
    except OcrError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SourceCorrectionRequired as exc:
        raise _source_correction_error(exc) from exc
    except (TranslationError, SemanticError) as exc:
        logger.warning("pipeline_analysis_failed provider=%s reason=%s", provider, type(exc).__name__)
        status = 422 if "Mock" in str(exc) or "not configured" in str(exc) else 502
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("pipeline_analysis_failed provider=%s", provider)
        raise HTTPException(status_code=502, detail="The configured Version 2 pipeline could not complete the analysis.") from exc

    pages = [image.page for image in prepared_images]
    quality_warnings = sum(len(page.quality_issues) for page in pages)
    pages_needing_review = sum(not page.readable or bool(page.quality_issues) for page in pages)
    add_page_provenance(pipeline.notice, pipeline.page_texts or [pipeline.source_text], pages)
    pipeline = await _complete_english_coverage(pipeline)
    add_page_provenance(pipeline.notice, pipeline.page_texts or [pipeline.source_text], pages)
    critical_review = sum(fact.critical and fact.state.value == "needs_review" for fact in pipeline.notice.source_facts)
    acquisition = _pipeline_acquisition(
        pipeline,
        input_type,
        source_pages=len(pages),
        quality_warnings=quality_warnings,
        pages_needing_review=pages_needing_review,
        critical_facts_needing_review=critical_review,
    )
    result = make_result(
        pipeline.source_text,
        pipeline.translation,
        pipeline.notice,
        pipeline.provider,
        pipeline.warnings,
        synthetic=pipeline.semantic_provider == "mock-semantic",
        recovered_text=pipeline.source_text,
        source_pages=pages,
        acquisition=acquisition,
    )
    save_notice(result)
    logger.info("pipeline_analysis_completed notice_id=%s provider=%s pages=%s semantic_requests=%s semantic_tokens=%s", result.id, pipeline.provider, len(pages), pipeline.semantic_requests, pipeline.semantic_total_tokens)
    return result


async def prepare_uploads(files: list[UploadFile], analysis_id: str):
    if not files:
        raise HTTPException(status_code=422, detail="Add at least one notice image.")
    if len(files) > 12:
        raise HTTPException(status_code=413, detail="A notice can contain at most 12 image pages.")
    prepared = []
    total_size = 0
    allowed = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}
    for page_number, file in enumerate(files, start=1):
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in allowed:
            raise HTTPException(status_code=415, detail=f"{file.filename or 'The file'} is not a supported JPG, PNG, WEBP, HEIC, or HEIF image.")
        data = await file.read(MAX_UPLOAD_BYTES + 1)
        total_size += len(data)
        if len(data) > MAX_UPLOAD_BYTES or total_size > MAX_TOTAL_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail="Images exceed the 15 MB per-page or 50 MB total prototype limit.")
        try:
            prepared.append(prepare_image(data, file.filename or f"page-{page_number}{suffix}", file.content_type or "application/octet-stream", analysis_id, page_number))
        except ImageProcessingError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return prepared


@app.post("/api/analyze-images", response_model=AnalysisResult, dependencies=[Depends(limit_public_analysis)])
async def analyze_images(
    files: list[UploadFile] = File(...),
    target_language: str = Form("en"),
    provider: str = Form("auto"),
    input_type: str = Form("uploaded_image"),
) -> AnalysisResult:
    if input_type not in {"camera_photo", "uploaded_image"}:
        raise HTTPException(status_code=422, detail="Image input type must be camera_photo or uploaded_image.")
    analysis_id = f"image-{uuid4().hex}"
    prepared = await prepare_uploads(files, analysis_id)
    return await analyze_prepared_images(prepared, provider, target_language, input_type)


@app.post("/api/upload", response_model=AnalysisResult, dependencies=[Depends(limit_public_analysis)])
async def analyze_upload(file: UploadFile = File(...), target_language: str = Form("en"), provider: str = Form("auto")) -> AnalysisResult:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".pdf", ".txt"}:
        raise HTTPException(status_code=415, detail="Only .pdf and .txt files are supported.")
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="The file exceeds the 15 MB prototype limit.")
    try:
        if suffix == ".pdf":
            try:
                supplemental_text = extract_pdf(data)
            except DocumentExtractionError:
                supplemental_text = ""
            if not supplemental_text:
                if os.getenv("VERCEL") == "1" and not os.getenv("PADDLEOCR_SERVICE_URL", "").strip():
                    raise HTTPException(
                        status_code=422,
                        detail="Scanned PDFs cannot be analyzed on this hosted version. Save each page as an image and use browser OCR, or upload a text-based PDF.",
                    )
                analysis_id = f"pdf-{uuid4().hex}"
                rendered = render_pdf_pages(data)
                source_stem = Path(file.filename or "notice").stem
                prepared = [prepare_image(page_data, f"{source_stem}-{filename}", "image/png", analysis_id, index) for index, (page_data, filename) in enumerate(rendered, start=1)]
                return await analyze_prepared_images(prepared, provider, target_language, "image_pdf", supplemental_text)
            result = await analyze(AnalyzeRequest(text=supplemental_text, target_language=target_language, provider=provider))
            result.acquisition = result.acquisition.model_copy(update={"input_type": "pdf_text", "text_extraction_status": "available"})
            save_notice(result)
            return result
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=422, detail="The text file must use UTF-8 encoding.") from exc
    except DocumentExtractionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return await analyze(AnalyzeRequest(text=text, target_language=target_language, provider=provider))


@app.post("/api/rerender", response_model=AnalysisResult)
def rerender(notice: NoticeData) -> AnalysisResult:
    return make_result("", "", notice, "manual-edit")


@app.get("/api/notices", response_model=list[AnalysisResult], dependencies=[Depends(require_admin)])
def notice_index() -> list[AnalysisResult]:
    return list_notices()


@app.put("/api/notices/{notice_id}", response_model=AnalysisResult, dependencies=[Depends(require_admin)])
def update_notice(notice_id: str, notice: NoticeData) -> AnalysisResult:
    existing = get_notice(notice_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Notice not found.")
    updated = make_result(
        existing.original_text,
        existing.faithful_translation,
        notice,
        "manual-edit",
        result_id=existing.id,
        created_at=existing.created_at,
        synthetic=existing.synthetic,
        recovered_text=existing.recovered_text,
        source_pages=existing.source_pages,
        acquisition=existing.acquisition,
    )
    save_notice(updated)
    return updated


@app.post("/api/notices/{notice_id}/reprocess-recovered-text", response_model=AnalysisResult, dependencies=[Depends(require_admin)])
async def reprocess_recovered_text(notice_id: str, update: RecoveredTextUpdate) -> AnalysisResult:
    existing = get_notice(notice_id)
    if not existing or not existing.source_pages:
        raise HTTPException(status_code=404, detail="Image-based notice not found.")
    try:
        recovered_pages = split_recovered_pages(update.text, len(existing.source_pages))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    normalized_text = (
        update.text
        if len(recovered_pages) == 1
        else "\n\n".join(f"[Page {index}]\n{text}" for index, text in enumerate(recovered_pages, start=1))
    )
    if len(normalized_text) > 200_000:
        raise HTTPException(status_code=413, detail="Corrected text exceeds the 200,000-character notice limit.")
    pipeline = await _run_text_pipeline(AnalyzeRequest(text=normalized_text, target_language="en", provider=update.provider))
    add_page_provenance(pipeline.notice, recovered_pages, existing.source_pages)
    if existing.acquisition.ocr_provider == "browser-ocr-kor-eng":
        mark_unverified_language_scores(pipeline.notice, normalized_text)
    pipeline = await _complete_english_coverage(pipeline)
    add_page_provenance(pipeline.notice, recovered_pages, existing.source_pages)
    blank_pages = [index for index, text in enumerate(recovered_pages, start=1) if not text]
    warnings = [f"Recovered text remains empty on page(s): {', '.join(map(str, blank_pages))}."] if blank_pages else []
    acquisition = _pipeline_acquisition(
        pipeline,
        existing.acquisition.input_type,
        source_pages=len(existing.source_pages),
        quality_warnings=existing.acquisition.quality_warnings,
        pages_needing_review=sum(
            not text or not page.readable or bool(page.quality_issues)
            for text, page in zip(recovered_pages, existing.source_pages)
        ),
        critical_facts_needing_review=sum(fact.critical and fact.state.value == "needs_review" for fact in pipeline.notice.source_facts),
    ).model_copy(update={
        "ocr_provider": existing.acquisition.ocr_provider,
        "ocr_latency_ms": existing.acquisition.ocr_latency_ms,
        "text_extraction_status": "partial" if blank_pages else "available",
        "total_latency_ms": existing.acquisition.ocr_latency_ms + pipeline.total_latency_ms,
    })
    result = make_result(
        normalized_text,
        pipeline.translation,
        pipeline.notice,
        pipeline.provider,
        pipeline.warnings + warnings,
        result_id=existing.id,
        created_at=existing.created_at,
        synthetic=existing.synthetic,
        recovered_text=normalized_text,
        source_pages=existing.source_pages,
        acquisition=acquisition,
    )
    save_notice(result)
    return result


@app.post("/api/research/results", status_code=201)
def create_research_result(result: ResearchResultCreate) -> dict[str, int]:
    return {"id": save_research_result(result)}


@app.get("/api/research/results.csv", response_class=PlainTextResponse, dependencies=[Depends(require_admin)])
def research_results_csv() -> PlainTextResponse:
    return PlainTextResponse(
        export_research_csv(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=visnotice-study-results.csv"},
    )


# Vercel's Python framework build serves the backend as the primary function.
# Mount the already-built React bundle there so the hosted project remains a
# single origin; local development continues to use Vite on port 5174.
if os.getenv("VERCEL") == "1":
    frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if frontend_dist.exists():
        app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
