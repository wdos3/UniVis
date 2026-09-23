from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
    links: list[LabeledFact] = Field(default_factory=list)
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
