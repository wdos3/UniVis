from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

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
    source_unit_ids: list[str] = Field(default_factory=list)
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
        if (
            self.box.x + self.box.width > 1.000001
            or self.box.y + self.box.height > 1.000001
        ):
            raise ValueError("OCR layout boxes must stay within the page.")
        return self


class SourcePoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class OcrCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(max_length=20000)
    confidence: float | None = Field(default=None, ge=0, le=1)
    pass_name: str = Field(default="original", max_length=128)


TranslationStatus = Literal["pending", "translated", "literal", "source_crop"]
SourceIdentifier = Annotated[str, Field(min_length=1, max_length=128)]


class SourceUnit(BaseModel):
    """A physical source observation, independent of generated claims."""

    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=128)
    page_number: int = Field(ge=1, le=12)
    image_id: str = Field(min_length=1, max_length=128)
    order: int = Field(ge=0)
    source_text: str = Field(max_length=20000)
    recovered_source_text: str | None = Field(default=None, max_length=20000)
    recovery_source: Literal["ocr_candidate", "vision"] | None = None
    box: BoundingBox | None = None
    polygon: list[SourcePoint] = Field(default_factory=list, max_length=8)
    confidence: float | None = Field(default=None, ge=0, le=1)
    alternatives: list[OcrCandidate] = Field(default_factory=list, max_length=24)
    block_id: str = Field(default="", max_length=128)
    section_id: str = Field(default="", max_length=128)
    table_id: str | None = Field(default=None, max_length=128)
    table_row: int | None = Field(default=None, ge=0)
    table_column: int | None = Field(default=None, ge=0)
    english: str = Field(default="", max_length=40000)
    translation_provider: str = Field(default="pending", max_length=128)
    translation_status: TranslationStatus = "pending"
    translation_source_ids: list[SourceIdentifier] = Field(
        default_factory=list, max_length=4000
    )
    semantic_refs: list[SourceIdentifier] = Field(default_factory=list, max_length=128)
    display_destinations: list[SourceIdentifier] = Field(
        default_factory=list, max_length=16
    )

    @model_validator(mode="after")
    def bounded_geometry(self) -> SourceUnit:
        if self.box and (
            self.box.x + self.box.width > 1.000001
            or self.box.y + self.box.height > 1.000001
        ):
            raise ValueError("Source boxes must stay within the image.")
        return self


class SourceBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: SourceIdentifier
    unit_ids: list[SourceIdentifier] = Field(min_length=1, max_length=4000)
    kind: Literal[
        "heading", "paragraph", "list", "table_cell", "caption", "condition"
    ] = "paragraph"
    section_id: str = ""
    source_text: str = Field(default="", max_length=150000)
    english: str = Field(default="", max_length=150000)
    translation_status: TranslationStatus = "pending"
    table_id: str | None = None
    table_row: int | None = Field(default=None, ge=0)
    table_column: int | None = Field(default=None, ge=0)


class LedgerCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_unit_ids: list[str] = Field(default_factory=list)
    translated_unit_ids: list[str] = Field(default_factory=list)
    displayed_unit_ids: list[str] = Field(default_factory=list)
    semantic_unit_ids: list[str] = Field(default_factory=list)
    fallback_unit_ids: list[str] = Field(default_factory=list)
    protected_value_gaps: list[str] = Field(default_factory=list)
    # Display reconciliation is evidence of survival, not a meaning audit.
    meaning_checked: bool = False


class LedgerMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ocr_ms: int = Field(default=0, ge=0)
    layout_ms: int = Field(default=0, ge=0)
    translation_ms: int = Field(default=0, ge=0)
    semantic_ms: int = Field(default=0, ge=0)
    validation_ms: int = Field(default=0, ge=0)
    rendering_ms: int = Field(default=0, ge=0)
    translation_requests: int = Field(default=0, ge=0)
    semantic_requests: int = Field(default=0, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    usage_complete: bool = True


class SourceLedger(BaseModel):
    model_config = ConfigDict(extra="forbid")
    units: list[SourceUnit] = Field(default_factory=list, max_length=4000)
    blocks: list[SourceBlock] = Field(default_factory=list, max_length=4000)
    coverage: LedgerCoverage = Field(default_factory=LedgerCoverage)
    metrics: LedgerMetrics = Field(default_factory=LedgerMetrics)

    @model_validator(mode="after")
    def unique_and_mapped(self) -> SourceLedger:
        ids = [unit.id for unit in self.units]
        if len(ids) != len(set(ids)):
            raise ValueError("Source unit IDs must be unique.")
        if sum(len(unit.source_text) for unit in self.units) > 150000:
            raise ValueError("Source text exceeds the 150,000-character ledger limit.")
        if (
            sum(
                len(candidate.text)
                for unit in self.units
                for candidate in unit.alternatives
            )
            > 300000
        ):
            raise ValueError(
                "OCR candidates exceed the 300,000-character ledger limit."
            )
        if (
            sum(len(unit.english) for unit in self.units)
            + sum(len(block.english) for block in self.blocks)
            > 750000
        ):
            raise ValueError(
                "English translations exceed the 750,000-character ledger limit."
            )
        if len({block.id for block in self.blocks}) != len(self.blocks):
            raise ValueError("Source block IDs must be unique.")
        if any(
            not set(block.unit_ids).issubset(ids)
            or len(set(block.unit_ids)) != len(block.unit_ids)
            for block in self.blocks
        ):
            raise ValueError("Blocks must reference unique, existing source units.")
        mapped_ids = [unit_id for block in self.blocks for unit_id in block.unit_ids]
        if len(mapped_ids) != len(set(mapped_ids)):
            raise ValueError(
                "Each source unit must belong to at most one layout block."
            )
        return self


class LedgerVisionRegion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    unit_ids: list[str] = Field(min_length=1, max_length=4000)
    data_url: str = Field(max_length=1200000)

    @field_validator("data_url")
    @classmethod
    def inline_image_only(cls, value: str) -> str:
        import base64
        import binascii

        prefixes = {
            "data:image/jpeg;base64,": b"\xff\xd8\xff",
            "data:image/png;base64,": b"\x89PNG\r\n\x1a\n",
        }
        prefix = next((prefix for prefix in prefixes if value.startswith(prefix)), None)
        if not prefix:
            raise ValueError(
                "Recovery images must be inline JPEG or PNG data, never remote URLs."
            )
        try:
            decoded = base64.b64decode(value[len(prefix) :], validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("Invalid recovery image encoding.") from exc
        if not decoded.startswith(prefixes[prefix]):
            raise ValueError("Recovery image format does not match its media type.")
        return value


class LedgerTranslationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    units: list[SourceUnit] = Field(min_length=1, max_length=4000)
    ocr_latency_ms: int = Field(default=0, ge=0, le=3600000)
    layout_latency_ms: int = Field(default=0, ge=0, le=3600000)

    @model_validator(mode="after")
    def valid_inventory(self) -> LedgerTranslationRequest:
        SourceLedger(units=self.units)
        return self


class LedgerAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ledger: SourceLedger
    provider: Literal["auto", "mock", "openai"] = "auto"
    input_type: Literal["camera_photo", "uploaded_image"] = "uploaded_image"
    regions: list[LedgerVisionRegion] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def bounded_recovery(self) -> LedgerAnalysisRequest:
        if sum(len(region.data_url) for region in self.regions) > 1500000:
            raise ValueError("Recovery images exceed the 1.5 MB request budget.")
        ids = {unit.id for unit in self.ledger.units}
        if any(not set(region.unit_ids).issubset(ids) for region in self.regions):
            raise ValueError("Recovery crops must reference existing source units.")
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

    input_type: Literal[
        "text", "pdf_text", "camera_photo", "uploaded_image", "image_pdf"
    ] = "text"
    source_pages: int = 0
    text_extraction_status: Literal[
        "not_applicable", "available", "partial", "unavailable"
    ] = "not_applicable"
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
    english_verification_latency_ms: int = Field(default=0, ge=0)
    total_latency_ms: int = Field(default=0, ge=0)
    english_coverage_status: Literal["not_audited", "audited", "partial"] = (
        "not_audited"
    )
    unverified_source_units: int = Field(default=0, ge=0)
    metrics_complete: bool = True


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
    source_ledger: SourceLedger | None = None


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
    allow_partial: bool = False

    @model_validator(mode="after")
    def limit_recognized_text(self) -> ClientOcrRequest:
        if sum(len(page.text) for page in self.pages) > 50_000:
            raise ValueError(
                "Recognized text exceeds the 50,000-character notice limit."
            )
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
