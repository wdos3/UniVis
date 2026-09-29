from __future__ import annotations

import json
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from openai import AsyncOpenAI

from app.models import DocumentRequirement, NoticeData, ReviewState
from app.services.demos import match_demo
from app.services.extraction.reconciliation import exact_values
from app.services.text import appears_korean


class SemanticError(RuntimeError):
    pass


@dataclass(frozen=True)
class SemanticResult:
    notice: NoticeData
    provider: str
    requests: int
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    warnings: list[str] = field(default_factory=list)


class SemanticProvider(ABC):
    name: str

    @abstractmethod
    async def analyze(
        self, source_text: str, translation: str, target_language: str, *, layout_context: str = ""
    ) -> SemanticResult:
        """Convert bilingual text into typed visual-instruction data."""


class MockSemanticProvider(SemanticProvider):
    name = "mock-semantic"

    async def analyze(
        self, source_text: str, translation: str, target_language: str, *, layout_context: str = ""
    ) -> SemanticResult:
        demo = match_demo(source_text)
        if not demo:
            notice = NoticeData(
                title="Notice needs semantic review",
                notice_type="Other",
                purpose="The mock semantic provider cannot interpret arbitrary notices.",
                summary="Configure OPENAI_API_KEY to analyze non-demo text.",
                target_language=target_language,
                ambiguities=["No matching synthetic example was found."],
                unverified_items=["Arbitrary notice content was not interpreted in mock mode."],
            )
            return SemanticResult(
                notice=notice,
                provider=self.name,
                requests=0,
                warnings=["Use a bundled synthetic example or configure the OpenAI semantic provider."],
            )
        notice = demo.notice.model_copy(deep=True)
        notice.target_language = target_language
        return SemanticResult(notice=notice, provider=self.name, requests=0)


SYSTEM_PROMPT = """You convert Korean-language notices into typed, evidence-grounded instructions and key details.
The Korean OCR text is the evidence authority. The English translation is a reading aid and may contain errors.
The OCR source can contain labeled, overlapping OCR passes. Reconcile their duplicate lines; do not treat repeated content as separate facts.
Never infer missing facts. Preserve every date, time, amount, qualification, exception, optional condition, contact, URL, and table-row distinction.
Spatial OCR hints give text positions on a 0-1000 page grid. In a table, pair a heading and its value by horizontal alignment, not by the OCR or translation reading order. If alignment is uncertain, report the unpaired text for review instead of guessing.
Extract all applicant requirements and score options, work or program duties, preferred qualifications, process stages, employment terms, and application-writing restrictions. Use key_details for grounded information that has no more specific field. A short summary is not a substitute for these details.
User-facing text must be in the requested target language. Keep Korean only in source_evidence and source_facts.source_text. Do not output "N/A" for absent contact fields; leave them empty.
Create sequential source facts F001, F002, and so on. Every actionable or factual output item must reference valid source_fact_ids and quote Korean source_evidence exactly.
Every critical source fact must be represented by at least one grounded output item: use fees for amounts, deadlines for dates, eligibility/audience for qualifications, actions for submission details, warnings/consequences for payment conditions or restrictions, contacts/links for contact data, and key_details for other factual sections. Do not leave a critical source fact referenced only by source_facts.
For a table-row pairing, source_evidence may quote its exact Korean header and value as separate lines. Mark the item needs_review if the source layout is ambiguous.
Create one required_documents item per document, even when several documents share one source fact and evidence line.
Set heading/title-only source facts to critical=false; critical means a fact that changes eligibility, money, dates, actions, documents, restrictions, or contact details.
Use source_page from [Page N] markers when possible. Mark uncertain OCR content needs_review and explain it in ambiguities or unverified_items.
Select no presentation HTML: return only the requested structured data. The application renders diagrams deterministically."""


class OpenAISemanticProvider(SemanticProvider):
    name = "openai-semantic"

    def __init__(self, client: AsyncOpenAI | None = None) -> None:
        api_key = os.getenv("OPENAI_API_KEY")
        if client is None and not api_key:
            raise SemanticError("OPENAI_API_KEY is not configured.")
        self.client = client or AsyncOpenAI(api_key=api_key)
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    async def analyze(
        self, source_text: str, translation: str, target_language: str, *, layout_context: str = ""
    ) -> SemanticResult:
        values = sorted(exact_values(source_text))
        layout_block = f"SPATIAL OCR HINTS (not additional evidence):\n{layout_context}\n\n" if layout_context else ""
        prompt = (
            f"TARGET LANGUAGE: {target_language}\n"
            f"EXACT VALUES DETECTED LOCALLY: {json.dumps(values, ensure_ascii=False)}\n\n"
            f"KOREAN OCR SOURCE:\n{source_text}\n\n"
            f"{layout_block}"
            f"TEMPORARY MACHINE TRANSLATION:\n{translation}\n\n"
            "Return a complete NoticeData object. Keep source_language='ko' and set target_language to the requested language."
        )
        try:
            response = await self.client.responses.parse(
                model=self.model,
                input=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                text_format=NoticeData,
            )
        except Exception as exc:
            raise SemanticError("The OpenAI semantic provider could not structure the translated notice.") from exc
        if response.output_parsed is None:
            raise SemanticError("The OpenAI semantic provider returned no parseable structured output.")
        usage = getattr(response, "usage", None)
        notice = normalize_notice(response.output_parsed)
        return SemanticResult(
            notice=notice,
            provider=f"{self.name}:{self.model}",
            requests=1,
            input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
            total_tokens=int(getattr(usage, "total_tokens", 0) or 0),
        )


def normalize_notice(notice: NoticeData) -> NoticeData:
    """Apply conservative, deterministic cleanup that does not invent source content."""
    for fact in notice.source_facts:
        if fact.kind.strip().lower() in {"heading", "title", "program_title", "notice_title"}:
            fact.critical = False

    if len(notice.required_documents) == 1:
        combined = notice.required_documents[0]
        matching_action = next(
            (
                action
                for action in notice.actions
                if len(action.required_items) > 1
                and set(action.source_fact_ids) & set(combined.source_fact_ids)
            ),
            None,
        )
        if matching_action:
            notice.required_documents = [
                DocumentRequirement(
                    name=item,
                    required=combined.required,
                    condition=combined.condition,
                    source_evidence=combined.source_evidence,
                    source_fact_ids=combined.source_fact_ids,
                    state=combined.state,
                    source_page=combined.source_page,
                    source_image_id=combined.source_image_id,
                    bounding_box=combined.bounding_box,
                )
                for item in matching_action.required_items
            ]

    for contact in notice.contacts:
        if contact.phone.strip().lower() in {"n/a", "none", "not provided"}:
            contact.phone = ""
        if contact.email.strip().lower() in {"n/a", "none", "not provided"}:
            contact.email = ""
        if contact.email and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[A-Za-z]{2,}", contact.email):
            suspect = contact.email
            contact.email = ""
            contact.details = f"{contact.details} OCR email needs review: {suspect}".strip()
            contact.state = ReviewState.NEEDS_REVIEW

    untranslated = any(appears_korean(value) for value in (notice.title, notice.summary, notice.purpose))
    text_items = (
        notice.audience + notice.eligibility + notice.exceptions + notice.warnings
        + notice.consequences + notice.locations + notice.fees + notice.links + notice.key_details
    )
    for item in text_items:
        if appears_korean(item.text):
            item.state = ReviewState.NEEDS_REVIEW
            untranslated = True
    for action in notice.actions:
        if any(appears_korean(value) for value in (action.action, action.details, *action.required_items)):
            action.state = ReviewState.NEEDS_REVIEW
            untranslated = True
    for document in notice.required_documents:
        if any(appears_korean(value) for value in (document.name, document.condition)):
            document.state = ReviewState.NEEDS_REVIEW
            untranslated = True
    for deadline in notice.deadlines:
        if any(appears_korean(value) for value in (deadline.date, deadline.time, deadline.description)):
            deadline.state = ReviewState.NEEDS_REVIEW
            untranslated = True
    for contact in notice.contacts:
        if any(appears_korean(value) for value in (contact.name, contact.details)):
            contact.state = ReviewState.NEEDS_REVIEW
            untranslated = True
    for group in notice.conditional_groups:
        if any(appears_korean(value) for value in (group.group, group.application_period, group.details)):
            group.state = ReviewState.NEEDS_REVIEW
            untranslated = True
    if untranslated and notice.target_language == "en":
        notice.unverified_items.append("Some user-facing details remain in Korean; review the English translation before acting.")
    return notice


def choose_semantic_provider(provider: str) -> SemanticProvider:
    if provider == "mock":
        return MockSemanticProvider()
    if provider == "openai":
        return OpenAISemanticProvider()
    if provider == "auto":
        return OpenAISemanticProvider() if os.getenv("OPENAI_API_KEY") else MockSemanticProvider()
    raise SemanticError("Semantic provider must be auto, mock, or openai.")
