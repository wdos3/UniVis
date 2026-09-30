from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ReviewState(StrEnum):
    VERIFIED = "verified"
    NEEDS_REVIEW = "needs_review"
    NOT_STATED = "not_stated"


class BoundingBox(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)


class GroundedItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_evidence: str = ""
    source_fact_ids: list[str] = Field(default_factory=list)
    state: ReviewState = ReviewState.VERIFIED
    source_page: int | None = Field(default=None, ge=1)
    source_image_id: str | None = None
    bounding_box: BoundingBox | None = None


class Action(GroundedItem):
    step: int = Field(ge=1)
    action: str = Field(min_length=1)
    details: str = ""
    deadline: str | None = None
    location: str | None = None
    required_items: list[str] = Field(default_factory=list)


class Deadline(GroundedItem):
    date: str = ""
    time: str = ""
    description: str = ""


class DocumentRequirement(GroundedItem):
    name: str = Field(min_length=1)
    required: bool = True
    condition: str = ""


class LabeledFact(GroundedItem):
    text: str = Field(min_length=1)
    label: str = ""


class Contact(GroundedItem):
    name: str = ""
    phone: str = ""
    email: str = ""
    details: str = ""


class SourceFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^F\d{3,}$")
    kind: str
    source_text: str
    critical: bool = True
    state: ReviewState = ReviewState.VERIFIED
    source_page: int | None = Field(default=None, ge=1)
    source_image_id: str | None = None
    bounding_box: BoundingBox | None = None


class OcrSpan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=500)
    box: BoundingBox
    confidence: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def box_stays_on_page(self) -> OcrSpan:
        if self.box.x + self.box.width > 1.000001 or self.box.y + self.box.height > 1.000001:
            raise ValueError("OCR layout boxes must stay within the page.")
        return self


class ConditionalGroup(GroundedItem):
    group: str = Field(min_length=1)
    application_period: str = ""
    details: str = ""


class QRCode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    source_page: int = Field(ge=1)
    bounding_box: BoundingBox | None = None


class ImageQualityIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    severity: Literal["warning", "blocking"] = "warning"


class SourcePage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    page_number: int = Field(ge=1)
    filename: str
    media_type: str
    original_url: str
    processed_url: str
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    readable: bool = True
    quality_issues: list[ImageQualityIssue] = Field(default_factory=list)
    qr_codes: list[QRCode] = Field(default_factory=list)


class ImageAcquisitionReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_type: Literal["text", "pdf_text", "camera_photo", "uploaded_image", "image_pdf"] = "text"
    source_pages: int = 0
    text_extraction_status: Literal["not_applicable", "available", "partial", "unavailable"] = "not_applicable"
    quality_warnings: int = 0
    pages_needing_review: int = 0
    critical_facts_needing_review: int = 0
    reconciliation_conflicts: list[str] = Field(default_factory=list)
    ocr_provider: str = "not_applicable"
    translation_provider: str = "not_applicable"
    semantic_provider: str = "not_applicable"
    translation_requests: int = Field(default=0, ge=0)
    semantic_requests: int = Field(default=0, ge=0)
    semantic_input_tokens: int = Field(default=0, ge=0)
    semantic_output_tokens: int = Field(default=0, ge=0)
    semantic_total_tokens: int = Field(default=0, ge=0)
    ocr_latency_ms: int = Field(default=0, ge=0)
    translation_latency_ms: int = Field(default=0, ge=0)
    semantic_latency_ms: int = Field(default=0, ge=0)
    extraction_latency_ms: int = Field(default=0, ge=0)
    english_repair_latency_ms: int = Field(default=0, ge=0)
    coverage_latency_ms: int = Field(default=0, ge=0)
    total_latency_ms: int = Field(default=0, ge=0)


class TemplateOverrides(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checklist: bool | None = None
    step_flow: bool | None = None
    timeline: bool | None = None
    decision_tree: bool | None = None
    warning_cards: bool | None = None
    information_cards: bool | None = None


class NoticeData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = "Untitled notice"
    notice_type: str = "Other"
    audience: list[LabeledFact] = Field(default_factory=list)
    purpose: str = ""
    summary: str = ""
    actions: list[Action] = Field(default_factory=list)
    deadlines: list[Deadline] = Field(default_factory=list)
    required_documents: list[DocumentRequirement] = Field(default_factory=list)
    eligibility: list[LabeledFact] = Field(default_factory=list)
    exceptions: list[LabeledFact] = Field(default_factory=list)
    warnings: list[LabeledFact] = Field(default_factory=list)
    consequences: list[LabeledFact] = Field(default_factory=list)
    locations: list[LabeledFact] = Field(default_factory=list)
    contacts: list[Contact] = Field(default_factory=list)
    fees: list[LabeledFact] = Field(default_factory=list)
    financial_support: list[LabeledFact] = Field(default_factory=list)
    links: list[LabeledFact] = Field(default_factory=list)
    key_details: list[LabeledFact] = Field(default_factory=list)
    conditional_groups: list[ConditionalGroup] = Field(default_factory=list)
    source_language: str = "ko"
    target_language: str = "en"
    ambiguities: list[str] = Field(default_factory=list)
    unverified_items: list[str] = Field(default_factory=list)
    source_facts: list[SourceFact] = Field(default_factory=list)
    template_overrides: TemplateOverrides = Field(default_factory=TemplateOverrides)

    @field_validator("source_facts")
    @classmethod
    def unique_fact_ids(cls, facts: list[SourceFact]) -> list[SourceFact]:
        ids = [fact.id for fact in facts]
        if len(ids) != len(set(ids)):
            raise ValueError("source fact IDs must be unique")
        return facts


class TemplateSelection(BaseModel):
    checklist: bool = False
    step_flow: bool = False
    timeline: bool = False
    decision_tree: bool = False
    warning_cards: bool = False
    information_cards: bool = False


class FidelityReport(BaseModel):
    checks: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    critical_fields_in_source: int = 0
    critical_fields_represented: int = 0
    potentially_missing: list[str] = Field(default_factory=list)
    potentially_invented: list[str] = Field(default_factory=list)
    unmapped_source_line_count: int = 0
    unmapped_source_lines: list[str] = Field(default_factory=list)
    serious_issue: bool = False


class AnalysisResult(BaseModel):
    id: str
    created_at: str
    original_text: str
    faithful_translation: str
    simplified_text: str
    notice: NoticeData
    templates: TemplateSelection
    fidelity: FidelityReport
    korean_detected: bool
    provider: str
    synthetic: bool = False
    recovered_text: str = ""
    source_pages: list[SourcePage] = Field(default_factory=list)
    acquisition: ImageAcquisitionReport = Field(default_factory=ImageAcquisitionReport)


class AnalyzeRequest(BaseModel):
    text: str = Field(min_length=1, max_length=200_000)
    target_language: str = "en"
    provider: Literal["auto", "mock", "openai"] = "auto"


class ClientOcrPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(max_length=20_000)
    spans: list[OcrSpan] = Field(default_factory=list, max_length=250)

    @model_validator(mode="after")
    def spans_match_text(self) -> ClientOcrPage:
        lines = {line.strip() for line in self.text.splitlines() if line.strip()}
        if any(span.text.strip() not in lines for span in self.spans):
            raise ValueError("OCR layout spans must match recognized text lines.")
        return self


class ClientOcrRequest(BaseModel):
    """Only recognized text crosses the wire; image data stays in the browser."""

    model_config = ConfigDict(extra="forbid")

    pages: list[ClientOcrPage] = Field(min_length=1, max_length=12)
    target_language: Literal["en"] = "en"
    provider: Literal["auto", "mock", "openai"] = "auto"
    input_type: Literal["camera_photo", "uploaded_image"] = "uploaded_image"
    ocr_latency_ms: int = Field(ge=0, le=3_600_000)

    @model_validator(mode="after")
    def limit_recognized_text(self) -> ClientOcrRequest:
        if sum(len(page.text) for page in self.pages) > 50_000:
            raise ValueError("Recognized text exceeds the 50,000-character notice limit.")
        if sum(len(page.spans) for page in self.pages) > 600:
            raise ValueError("OCR layout exceeds the 600-span notice limit.")
        return self


class ResearchAnswer(BaseModel):
    question_id: str
    answer: str
    correct: bool | None = None


class ResearchResultCreate(BaseModel):
    participant_id: str = Field(min_length=1, max_length=80)
    notice_id: str
    condition: Literal["A", "B", "C"]
    started_at: str
    finished_at: str
    duration_seconds: int = Field(ge=0)
    confidence: int = Field(ge=1, le=5)
    answers: list[ResearchAnswer]


class DemoQuestion(BaseModel):
    id: str
    prompt: str
    expected_answer: str
    critical_fact_id: str | None = None


class DemoSummary(BaseModel):
    id: str
    title: str
    category: str
    original_text: str
    questions: list[DemoQuestion]


class ImageDemoSummary(BaseModel):
    id: str
    title: str
    description: str
    page_urls: list[str]


class RecoveredTextUpdate(BaseModel):
    text: str = Field(min_length=1, max_length=200_000)
    provider: Literal["auto", "mock", "openai"] = "auto"
