from __future__ import annotations

import logging
import os
import re
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from importlib.util import find_spec
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from app.models import (
    AnalysisResult,
    AnalyzeRequest,
    DemoSummary,
    ImageAcquisitionReport,
    ImageDemoSummary,
    NoticeData,
    RecoveredTextUpdate,
    ResearchResultCreate,
    SourcePage,
)
from app.services.demos import DEMOS, get_demo, match_demo
from app.services.fidelity import calculate_fidelity, select_templates
from app.services.extraction.reconciliation import add_page_provenance
from app.services.image_demos import IMAGE_DEMOS
from app.services.images.pdf_images import render_pdf_pages
from app.services.images.preprocessing import ImageProcessingError, prepare_image, upload_root
from app.services.pdf import DocumentExtractionError, extract_pdf
from app.services.pipeline import PipelineResult, analyze_image_pipeline, analyze_text_pipeline
from app.services.ocr import OcrError
from app.services.semantic import SemanticError
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
    return AnalysisResult(
        id=result_id or f"notice-{uuid4().hex[:12]}",
        created_at=created_at or datetime.now(UTC).isoformat(),
        original_text=original_text,
        faithful_translation=translation,
        simplified_text=simplified_text(notice),
        notice=notice,
        templates=select_templates(notice),
        fidelity=calculate_fidelity(notice),
        korean_detected=appears_korean(original_text),
        provider=provider,
        synthetic=synthetic,
        recovered_text=recovered_text,
        source_pages=source_pages or [],
        acquisition=acquisition or ImageAcquisitionReport(),
    )


async def analyze(request: AnalyzeRequest) -> AnalysisResult:
    logger.info("analysis_started provider=%s korean_detected=%s", request.provider, appears_korean(request.text))
    try:
        pipeline = await analyze_text_pipeline(request.text, request.target_language, request.provider)
    except (TranslationError, SemanticError) as exc:
        logger.warning("analysis_failed provider=%s reason=%s", request.provider, type(exc).__name__)
        status = 422 if "Mock" in str(exc) or "not configured" in str(exc) else 502
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("analysis_failed provider=%s", request.provider)
        raise HTTPException(status_code=502, detail="The configured Version 2 pipeline could not complete the analysis.") from exc
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
        total_latency_ms=pipeline.total_latency_ms,
    )


@app.get("/api/health")
def health() -> dict[str, object]:
    ocr_provider = "paddleocr-ppocrv5-korean-local"
    if os.getenv("VERCEL") == "1" and find_spec("paddleocr") is None:
        ocr_provider = "paddleocr-local-unavailable-on-vercel"
    return {
        "status": "ok",
        "version": 2,
        "openai_configured": bool(os.getenv("OPENAI_API_KEY")),
        "default_provider": "openai" if os.getenv("OPENAI_API_KEY") else "mock",
        "translation_provider": os.getenv("TRANSLATION_PROVIDER", "mymemory"),
        "ocr_provider": ocr_provider,
        "semantic_model": os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
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


@app.post("/api/analyze", response_model=AnalysisResult)
async def analyze_text(request: AnalyzeRequest) -> AnalysisResult:
    return await analyze(request)


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
        data = await file.read()
        total_size += len(data)
        if len(data) > 15 * 1024 * 1024 or total_size > 50 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Images exceed the 15 MB per-page or 50 MB total prototype limit.")
        try:
            prepared.append(prepare_image(data, file.filename or f"page-{page_number}{suffix}", file.content_type or "application/octet-stream", analysis_id, page_number))
        except ImageProcessingError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return prepared


@app.post("/api/analyze-images", response_model=AnalysisResult)
async def analyze_images(
    files: list[UploadFile] = File(...),
    target_language: str = Form("en"),
    provider: str = Form("auto"),
    input_type: str = Form("uploaded_image"),
) -> AnalysisResult:
    if input_type not in {"camera_photo", "uploaded_image"}:
        raise HTTPException(status_code=422, detail="Image input type must be camera_photo or uploaded_image.")
    analysis_id = f"image-{uuid4().hex[:12]}"
    prepared = await prepare_uploads(files, analysis_id)
    return await analyze_prepared_images(prepared, provider, target_language, input_type)


@app.post("/api/upload", response_model=AnalysisResult)
async def analyze_upload(file: UploadFile = File(...), target_language: str = Form("en"), provider: str = Form("auto")) -> AnalysisResult:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".pdf", ".txt"}:
        raise HTTPException(status_code=415, detail="Only .pdf and .txt files are supported.")
    data = await file.read()
    if len(data) > 15 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="The file exceeds the 15 MB prototype limit.")
    try:
        if suffix == ".pdf":
            try:
                supplemental_text = extract_pdf(data)
            except DocumentExtractionError:
                supplemental_text = ""
            if not supplemental_text:
                analysis_id = f"pdf-{uuid4().hex[:12]}"
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


@app.get("/api/notices", response_model=list[AnalysisResult])
def notice_index() -> list[AnalysisResult]:
    return list_notices()


@app.put("/api/notices/{notice_id}", response_model=AnalysisResult)
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


@app.post("/api/notices/{notice_id}/reprocess-recovered-text", response_model=AnalysisResult)
async def reprocess_recovered_text(notice_id: str, update: RecoveredTextUpdate) -> AnalysisResult:
    existing = get_notice(notice_id)
    if not existing or not existing.source_pages:
        raise HTTPException(status_code=404, detail="Image-based notice not found.")
    try:
        pipeline = await analyze_text_pipeline(update.text, "en", update.provider)
    except (TranslationError, SemanticError) as exc:
        status = 422 if "Mock" in str(exc) or "not configured" in str(exc) else 502
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    recovered_pages = [page for page in re.split(r"\[Page \d+\]\s*", update.text) if page.strip()]
    add_page_provenance(pipeline.notice, recovered_pages or [update.text], existing.source_pages)
    acquisition = _pipeline_acquisition(
        pipeline,
        existing.acquisition.input_type,
        source_pages=len(existing.source_pages),
        quality_warnings=existing.acquisition.quality_warnings,
        pages_needing_review=existing.acquisition.pages_needing_review,
        critical_facts_needing_review=sum(fact.critical and fact.state.value == "needs_review" for fact in pipeline.notice.source_facts),
    ).model_copy(update={"ocr_provider": existing.acquisition.ocr_provider, "text_extraction_status": "available"})
    result = make_result(
        update.text,
        pipeline.translation,
        pipeline.notice,
        pipeline.provider,
        pipeline.warnings,
        result_id=existing.id,
        created_at=existing.created_at,
        synthetic=existing.synthetic,
        recovered_text=update.text,
        source_pages=existing.source_pages,
        acquisition=acquisition,
    )
    save_notice(result)
    return result


@app.post("/api/research/results", status_code=201)
def create_research_result(result: ResearchResultCreate) -> dict[str, int]:
    return {"id": save_research_result(result)}


@app.get("/api/research/results.csv", response_class=PlainTextResponse)
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
