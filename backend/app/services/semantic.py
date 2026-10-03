from __future__ import annotations

import json
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from time import perf_counter

from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict

from app.models import DocumentRequirement, GroundedItem, NoticeData, ReviewState
from app.services.demos import match_demo
from app.services.extraction.reconciliation import evidence_matches_page, exact_values
from app.services.grounded_wording import correct_grounded_wording
from app.services.source_contacts import contact_corrections, email_values, phone_digits, phone_values
from app.services.source_grounding import retain_source_grounded_items


class SemanticError(RuntimeError):
    pass


class SourceCorrectionRequired(SemanticError):
    """Recovered text needs a specific human correction before interpretation."""

    def __init__(self, message: str, corrections: list[dict]) -> None:
        super().__init__(message)
        self.corrections = corrections


@dataclass(frozen=True)
class SemanticResult:
    notice: NoticeData
    provider: str
    requests: int
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    warnings: list[str] = field(default_factory=list)
    extraction_latency_ms: int = 0
    english_repair_latency_ms: int = 0


@dataclass(frozen=True)
class SemanticRepairMetrics:
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class SemanticProvider(ABC):
    name: str

    @abstractmethod
    async def analyze(
        self, source_text: str, translation: str, target_language: str, *, layout_context: str = "", allow_partial: bool = False
    ) -> SemanticResult:
        """Convert bilingual text into typed visual-instruction data."""


class MockSemanticProvider(SemanticProvider):
    name = "mock-semantic"

    async def analyze(
        self, source_text: str, translation: str, target_language: str, *, layout_context: str = "", allow_partial: bool = False
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
Keep Latin acronyms exactly as printed. Do not expand an acronym unless its expansion is explicitly present in the source.
Spatial OCR hints give text positions on a 0-1000 page grid. In a table, pair a heading and its value by horizontal alignment, not by the OCR or translation reading order. If alignment is uncertain, report the unpaired text for review instead of guessing.
Adapt to the notice's actual content: applications, hiring, fees, housing, courses, scholarships, public benefits, events, and other announcements. Extract every meaningful requirement, option, benefit, duty, process stage, and restriction. Use key_details for grounded information that has no more specific field. A short summary is not a substitute for these details.
An OCR line is a physical text fragment, not necessarily a complete fact. Combine headings and continuations into coherent English items with the exact relevant source lines quoted together. Each restriction must identify the affected people and qualifying circumstance; each funding item must identify its category, spending scope and payment procedure; each listed option must retain its complete subject. Do not split one relationship into detached English fragments or substitute a broader summary for enumerated options. Preserve quoted or parenthesized English terminology word for word, including line-spanning phrases.
User-facing text must be in the requested target language. Keep Korean only in source_evidence and source_facts.source_text. Do not output "N/A" for absent contact fields; leave them empty.
For English output, translate every user-facing Korean phrase yourself even if the temporary translation is garbled. Never copy Korean OCR wording into a user-facing field.
Money awarded or reimbursed to participants belongs in financial_support. Use fees only for money applicants must pay. Keep these directions of payment distinct.
Preserve who pays or receives money, permitted spending, payment procedures, caps, installments, and prerequisites. Preserve AND/OR choices, negations, scope, and conditional relationships; do not turn a mandatory procedure into an option or a conditional benefit into an unconditional award.
If a photo includes multiple unrelated notices or a cut-off neighboring poster, report the distinct/cropped content for review rather than blending its requirements into one notice.
Create sequential source facts F001, F002, and so on. Every actionable or factual output item must reference valid source_fact_ids and quote Korean source_evidence exactly.
Every critical source fact must be represented by at least one grounded output item: use financial_support for funding and fees for payments owed, deadlines for dates, eligibility/audience for qualifications, actions for submission details, warnings/consequences for payment conditions or restrictions, contacts/links for contact data, and key_details for other factual sections. Do not leave a critical source fact referenced only by source_facts.
For a table-row pairing, source_evidence may quote its exact Korean header and value as separate lines. Mark the item needs_review if the source layout is ambiguous.
Create one required_documents item per document, even when several documents share one source fact and evidence line.
Set heading/title-only source facts to critical=false; critical means a fact that changes eligibility, money, dates, actions, documents, restrictions, or contact details.
The application assigns page/image provenance from exact source evidence. Mark uncertain OCR content needs_review and explain it in ambiguities or unverified_items.
Select no presentation HTML: return only the requested structured data. The application renders diagrams deterministically."""


class _SemanticNotice(NoticeData):
    """Keep the semantic contract while omitting application-owned metadata.

    Inherited defaults restore the complete NoticeData object after parsing;
    the model need not generate empty image boxes or presentation settings.
    """

    @classmethod
    def model_json_schema(cls, *args, **kwargs) -> dict:
        schema = super().model_json_schema(*args, **kwargs)
        application_fields = {
            "source_image_id", "bounding_box", "source_page",
            "source_language", "target_language", "template_overrides", "source_unit_ids",
        }
        for node in (schema, *schema.get("$defs", {}).values()):
            properties = node.get("properties", {})
            for name in application_fields:
                properties.pop(name, None)
            if "required" in node:
                node["required"] = [name for name in node["required"] if name not in application_fields]
        for name in ("BoundingBox", "TemplateOverrides"):
            schema.get("$defs", {}).pop(name, None)
        return schema


class _PhotoSemanticNotice(_SemanticNotice):
    """Generate meanings and exact quotations; assign redundant IDs locally."""

    @classmethod
    def model_json_schema(cls, *args, **kwargs) -> dict:
        schema = super().model_json_schema(*args, **kwargs)
        for node in (schema, *schema.get("$defs", {}).values()):
            properties = node.get("properties", {})
            for name in ("source_facts", "source_fact_ids"):
                properties.pop(name, None)
            if "required" in node:
                node["required"] = [name for name in node["required"] if name not in {"source_facts", "source_fact_ids"}]
        schema.get("$defs", {}).pop("SourceFact", None)
        return schema


class OpenAISemanticProvider(SemanticProvider):
    name = "openai-semantic"

    def __init__(self, client: AsyncOpenAI | None = None) -> None:
        api_key = os.getenv("OPENAI_API_KEY")
        if client is None and not api_key:
            raise SemanticError("OPENAI_API_KEY is not configured.")
        self.client = client or AsyncOpenAI(api_key=api_key, max_retries=0, timeout=45)
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    async def analyze(
        self, source_text: str, translation: str, target_language: str, *, layout_context: str = "", allow_partial: bool = False
    ) -> SemanticResult:
        corrections = contact_corrections(source_text)
        if corrections and not allow_partial:
            examples = "; ".join(
                f"Page {item['page']}, line {item['line']}: {item['text']}" for item in corrections[:3]
            )
            raise SourceCorrectionRequired(
                "A contact phone number has unreadable OCR characters. Correct its exact digits from the photo "
                f"or upload a close-up of the contact line, then retry. {examples}",
                corrections,
            )
        values = sorted(exact_values(source_text))
        layout_block = f"SPATIAL OCR HINTS (not additional evidence):\n{layout_context}\n\n" if layout_context else ""
        prompt = (
            f"TARGET LANGUAGE: {target_language}\n"
            f"EXACT VALUES DETECTED LOCALLY: {json.dumps(values, ensure_ascii=False)}\n\n"
            f"KOREAN OCR SOURCE:\n{source_text}\n\n"
            f"{layout_block}"
            # Photo semantics uses Korean evidence directly. The separately
            # displayed MyMemory baseline can be noisy and repeats the input.
            + (f"TEMPORARY MACHINE TRANSLATION:\n{translation}\n\n" if not allow_partial else "")
            + "Return all semantic fields in the requested target language. Application-owned provenance and settings are assigned locally."
            + (" Unreadable OCR is not evidence for a guessed fact. Omit undecipherable details, especially phone digits, "
               "and describe their uncertainty in English. Interpret legible source details directly from Korean. "
               "Source fact IDs and the source-fact inventory are assigned by the application from your exact source_evidence quotations; do not generate them."
               if allow_partial else "")
        )
        extraction_started = perf_counter()
        try:
            response = await self.client.responses.parse(
                model=self.model,
                input=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                text_format=_PhotoSemanticNotice if allow_partial else _SemanticNotice,
            )
        except Exception as exc:
            raise SemanticError("The OpenAI semantic provider could not structure the translated notice.") from exc
        if response.output_parsed is None:
            raise SemanticError("The OpenAI semantic provider returned no parseable structured output.")
        usage = getattr(response, "usage", None)
        # The requested language is API input, not a model decision. A model
        # returning "ko" must not disable the English-output safeguards.
        notice = NoticeData.model_validate(response.output_parsed.model_dump())
        notice.source_language = "ko"
        notice.target_language = target_language
        if allow_partial:
            notice = retain_source_grounded_items(notice, source_text)
        notice = normalize_notice(notice, source_text=source_text)
        extraction_latency_ms = round((perf_counter() - extraction_started) * 1000)
        repair_started = perf_counter()
        repair = await repair_english_fields(notice, self.client, self.model)
        english_repair_latency_ms = round((perf_counter() - repair_started) * 1000)
        if repair.requests:
            notice.unverified_items = [
                item for item in notice.unverified_items if item != _UNTRANSLATED_WARNING
            ]
            # The translation pass can introduce a fluent but incorrect term
            # after the first normalization. Recheck the grounded English.
            notice = normalize_notice(notice, source_text=source_text)
        return SemanticResult(
            notice=notice,
            provider=f"{self.name}:{self.model}",
            requests=1 + repair.requests,
            input_tokens=int(getattr(usage, "input_tokens", 0) or 0) + repair.input_tokens,
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0) + repair.output_tokens,
            total_tokens=int(getattr(usage, "total_tokens", 0) or 0) + repair.total_tokens,
            extraction_latency_ms=extraction_latency_ms,
            english_repair_latency_ms=english_repair_latency_ms,
        )


_UNTRANSLATED_WARNING = "Some user-facing details remain in Korean; review the English translation before acting."
_REPAIR_BATCH_SIZE = 40
_KOREAN_SCRIPT = re.compile(r"[\u1100-\u11FF\u3130-\u318F\uA960-\uA97F\uAC00-\uD7AF\uD7B0-\uD7FF]")
_CLOCK_TIME = re.compile(
    r"(?<!\d)(?:(오전|오후|AM|PM)\s*)?(\d{1,2}):([0-5]\d)(?:\s*(AM|PM|오전|오후))?(?!\d)",
    re.IGNORECASE,
)
_KOREAN_HOUR = re.compile(r"(?<!\d)(?:(오전|오후)\s*)?(\d{1,2})\s*시(?:\s*(\d{1,2})\s*분)?")
_ENGLISH_HOUR = re.compile(r"(?<!\d)(\d{1,2})\s*(AM|PM)\b", re.IGNORECASE)
_PHONE_REVIEW_NOTE = "Phone number does not match the cited source text; verify it against the notice."
_REQUIRED_DOCUMENT_SOURCE = re.compile(r"필수(?:제출|서류)|제출(?:[.!。]|$|해야|필수|하세요|바랍니다)")
_OPTIONAL_DOCUMENT_SOURCE = re.compile(
    r"선택|희망|해당|경우|[가-힣]만(?=[가-힣,.]|$)|(?:으?면|때)|(?:필요|요청)시|"
    r"제출(?:가능|할수|여부|하지|안해|안함|면제|생략|불필요)|"
    r"필수(?:제출)?(?:는|가|이)?(?:아니|아님)|(?:있|없)(?:으면|을때)"
)
_UNCONDITIONAL_DOCUMENT_CONDITION = re.compile(
    r"required(?: for (?:application(?: submission)?|submission))?\.?", re.IGNORECASE,
)
_CONDITIONAL_DOCUMENT_ENGLISH = re.compile(
    r"\b(?:not required|not mandatory|optional|if|when|unless|applicable|conditional|may|can|as needed|upon request)\b",
    re.IGNORECASE,
)


def _clock_minutes(hour: int, minute: int, meridiem: str | None) -> int | None:
    if minute > 59:
        return None
    if meridiem:
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if meridiem.casefold() in {"pm", "오후"} else 0)
    elif not 0 <= hour <= 23:
        return None
    return hour * 60 + minute


def _explicit_times(text: str) -> set[int]:
    times: set[int] = set()
    for match in _CLOCK_TIME.finditer(text):
        value = _clock_minutes(int(match[2]), int(match[3]), match[1] or match[4])
        if value is not None:
            times.add(value)
    for match in _KOREAN_HOUR.finditer(text):
        value = _clock_minutes(int(match[2]), int(match[3] or 0), match[1])
        if value is not None:
            times.add(value)
    for match in _ENGLISH_HOUR.finditer(text):
        value = _clock_minutes(int(match[1]), 0, match[2])
        if value is not None:
            times.add(value)
    return times


def _phone_matches_evidence(phone: str, evidence: str) -> bool:
    wanted = phone_digits(phone)
    return bool(wanted) and wanted in phone_values(evidence)


def _contains_korean_script(value: str) -> bool:
    return bool(_KOREAN_SCRIPT.search(value))


class _EnglishRepair(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    english: str


class _EnglishRepairBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repairs: list[_EnglishRepair]


@dataclass(frozen=True)
class _TextField:
    owner: BaseModel
    name: str
    index: int | None = None

    @property
    def text(self) -> str:
        value = getattr(self.owner, self.name)
        return value[self.index] if self.index is not None else value

    def replace(self, text: str) -> None:
        if self.index is None:
            setattr(self.owner, self.name, text)
        else:
            getattr(self.owner, self.name)[self.index] = text
        if isinstance(self.owner, GroundedItem):
            self.owner.state = ReviewState.NEEDS_REVIEW


def _user_facing_text_fields(notice: NoticeData) -> list[_TextField]:
    fields = [_TextField(notice, name) for name in ("title", "notice_type", "purpose", "summary")]
    for collection_name in (
        "audience", "eligibility", "exceptions", "warnings", "consequences",
        "locations", "fees", "financial_support", "links", "key_details",
    ):
        for item in getattr(notice, collection_name):
            fields.extend((_TextField(item, "text"), _TextField(item, "label")))
    for action in notice.actions:
        fields.extend(_TextField(action, name) for name in ("action", "details", "deadline", "location"))
        fields.extend(_TextField(action, "required_items", index) for index in range(len(action.required_items)))
    for deadline in notice.deadlines:
        fields.extend(_TextField(deadline, name) for name in ("date", "time", "description"))
    for document in notice.required_documents:
        fields.extend((_TextField(document, "name"), _TextField(document, "condition")))
    for contact in notice.contacts:
        fields.extend(_TextField(contact, name) for name in ("name", "phone", "email", "details"))
    for group in notice.conditional_groups:
        fields.extend(_TextField(group, name) for name in ("group", "application_period", "details"))
    for name in ("ambiguities", "unverified_items"):
        fields.extend(_TextField(notice, name, index) for index in range(len(getattr(notice, name))))
    return [field for field in fields if field.text and _contains_korean_script(field.text)]


async def repair_english_fields(
    notice: NoticeData, client: AsyncOpenAI, model: str
) -> SemanticRepairMetrics:
    """Translate only untranslated display fields; provenance remains in Korean."""
    if notice.target_language != "en":
        return SemanticRepairMetrics()
    fields = _user_facing_text_fields(notice)
    if not fields:
        return SemanticRepairMetrics()

    requests = input_tokens = output_tokens = total_tokens = 0
    for offset in range(0, len(fields), _REPAIR_BATCH_SIZE):
        batch = fields[offset:offset + _REPAIR_BATCH_SIZE]
        by_id = {f"T{offset + index + 1:03d}": reference for index, reference in enumerate(batch)}
        payload = [{"id": id_, "text": reference.text} for id_, reference in by_id.items()]
        try:
            response = await client.responses.parse(
                model=model,
                input=[
                    {"role": "system", "content": (
                        "Translate each notice field to natural English. Return exactly one repair per input ID. "
                        "Preserve all conditions, negation, numbers, units, dates, and proper names. "
                        "Do not summarize, combine fields, infer missing facts, or add information. "
                        "Retain existing English where appropriate, but write no Hangul in the english field."
                    )},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                text_format=_EnglishRepairBatch,
            )
        except Exception as exc:
            raise SemanticError("The semantic provider could not finish translating the English summary.") from exc
        parsed = response.output_parsed
        if parsed is None or len(parsed.repairs) != len(by_id):
            raise SemanticError("The semantic provider returned an incomplete English summary.")
        repaired = {item.id: item.english.strip() for item in parsed.repairs}
        if set(repaired) != set(by_id) or any(not value or _contains_korean_script(value) for value in repaired.values()):
            raise SemanticError("The semantic provider returned untranslated or mismatched English fields.")
        for id_, reference in by_id.items():
            reference.replace(repaired[id_])
        usage = getattr(response, "usage", None)
        requests += 1
        input_tokens += int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens += int(getattr(usage, "output_tokens", 0) or 0)
        total_tokens += int(getattr(usage, "total_tokens", 0) or 0)
    if _user_facing_text_fields(notice):
        raise SemanticError("The semantic provider left untranslated Korean in the English summary.")
    return SemanticRepairMetrics(requests, input_tokens, output_tokens, total_tokens)


def _reconcile_required_documents(notice: NoticeData) -> None:
    """Resolve a required/optional contradiction only with a shared submit clause."""
    for document in notice.required_documents:
        evidence = re.sub(r"\s+", "", document.source_evidence)
        if (
            document.required
            or not _REQUIRED_DOCUMENT_SOURCE.search(evidence)
            or _OPTIONAL_DOCUMENT_SOURCE.search(evidence)
            or (document.condition.strip() and not _UNCONDITIONAL_DOCUMENT_CONDITION.fullmatch(
                re.sub(r"\s+", " ", document.condition).strip()
            ))
            or _CONDITIONAL_DOCUMENT_ENGLISH.search(
                " ".join((document.name, document.condition, document.source_evidence))
            )
        ):
            continue
        name = re.sub(r"\s+", " ", document.name).strip().casefold()
        for action in notice.actions:
            if evidence != re.sub(r"\s+", "", action.source_evidence):
                continue
            required_names = {re.sub(r"\s+", " ", item).strip().casefold() for item in action.required_items}
            if name in required_names:
                document.required = True
                document.state = ReviewState.NEEDS_REVIEW
                break


def normalize_notice(notice: NoticeData, *, source_text: str = "") -> NoticeData:
    """Apply conservative, deterministic cleanup that does not invent source content."""
    if source_text:
        page_texts: dict[int, list[str]] = {1: []}
        page = 1
        for line in source_text.splitlines():
            marker = re.fullmatch(r"\[Page (\d+)\]", line.strip())
            if marker:
                page = int(marker[1])
                page_texts.setdefault(page, [])
            else:
                page_texts[page].append(line)
        # Reuse the same evidence matching as image provenance; repeated text
        # on several pages never receives a guessed page number.
        page_sources = {number: "\n".join(lines) for number, lines in page_texts.items()}
        for item in (
            *notice.audience, *notice.actions, *notice.deadlines, *notice.required_documents,
            *notice.eligibility, *notice.exceptions, *notice.warnings, *notice.consequences,
            *notice.locations, *notice.contacts, *notice.fees, *notice.financial_support,
            *notice.links, *notice.key_details, *notice.conditional_groups, *notice.source_facts,
        ):
            evidence = getattr(item, "source_evidence", "") or getattr(item, "source_text", "")
            matches = [number for number, text in page_sources.items() if evidence_matches_page(evidence, text)]
            item.source_page = matches[0] if len(matches) == 1 else None
        notice.purpose = correct_grounded_wording(notice.purpose, source_text, restore_expansions=False)
        notice.summary = correct_grounded_wording(notice.summary, source_text, restore_expansions=False)
    for fact in notice.source_facts:
        if fact.kind.strip().lower() in {"heading", "title", "program_title", "notice_title"}:
            fact.critical = False

    # A card payment can describe how the institute spends a research grant;
    # it does not by itself make that grant a fee charged to applicants.
    payable_terms = re.compile(r"납부|부담|입금|납입|수수료|등록금|참가비")
    support_terms = re.compile(r"연구비|활동비|장학금|지원금액")
    remaining_fees = []
    for fee in notice.fees:
        if support_terms.search(fee.source_evidence) and not payable_terms.search(fee.source_evidence):
            fee.text = re.sub(r"(?i)\bResearch fee\b", "Research funding", fee.text)
            fee.text = re.sub(r"(?i)\bActivity fee\b", "Activity allowance", fee.text)
            notice.financial_support.append(fee)
        else:
            remaining_fees.append(fee)
    notice.fees = remaining_fees

    for item in notice.key_details:
        if item.label.strip().casefold() in {"key_details", "other"}:
            item.label = "Other key details"

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

    for deadline in notice.deadlines:
        if deadline.time.strip():
            stated_times = _explicit_times(deadline.time)
            if not stated_times or not stated_times <= _explicit_times(deadline.source_evidence):
                deadline.time = ""
                deadline.state = ReviewState.NEEDS_REVIEW

    for contact in notice.contacts:
        if contact.phone.strip().lower() in {"n/a", "none", "not provided"}:
            contact.phone = ""
        if contact.phone and not _phone_matches_evidence(contact.phone, contact.source_evidence):
            contact.phone = ""
            if _PHONE_REVIEW_NOTE not in contact.details:
                contact.details = f"{contact.details} {_PHONE_REVIEW_NOTE}".strip()
            contact.state = ReviewState.NEEDS_REVIEW
        if contact.email.strip().lower() in {"n/a", "none", "not provided"}:
            contact.email = ""
        if contact.email and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[A-Za-z]{2,}", contact.email):
            suspect = contact.email
            contact.email = ""
            contact.details = f"{contact.details} OCR email needs review: {suspect}".strip()
            contact.state = ReviewState.NEEDS_REVIEW
        elif contact.email and contact.email.casefold() not in email_values(contact.source_evidence):
            contact.email = ""
            contact.details = f"{contact.details} Email address does not match the cited source text; verify it against the notice.".strip()
            contact.state = ReviewState.NEEDS_REVIEW

    untranslated = any(_contains_korean_script(value) for value in (notice.title, notice.summary, notice.purpose, notice.notice_type))
    text_items = (
        notice.audience + notice.eligibility + notice.exceptions + notice.warnings
        + notice.consequences + notice.locations + notice.fees + notice.financial_support
        + notice.links + notice.key_details
    )
    for item in text_items:
        corrected_text = correct_grounded_wording(item.text, item.source_evidence)
        corrected_label = correct_grounded_wording(item.label, item.source_evidence)
        if (corrected_text, corrected_label) != (item.text, item.label):
            item.text, item.label = corrected_text, corrected_label
            item.state = ReviewState.NEEDS_REVIEW
        if _contains_korean_script(item.text) or _contains_korean_script(item.label):
            item.state = ReviewState.NEEDS_REVIEW
            untranslated = True
    for action in notice.actions:
        corrected_action = correct_grounded_wording(action.action, action.source_evidence)
        corrected_details = correct_grounded_wording(action.details, action.source_evidence)
        corrected_items = [
            correct_grounded_wording(value, action.source_evidence) for value in action.required_items
        ]
        if (corrected_action, corrected_details, corrected_items) != (
            action.action, action.details, action.required_items
        ):
            action.action = corrected_action
            action.details = corrected_details
            action.required_items = corrected_items
            action.state = ReviewState.NEEDS_REVIEW
        if any(_contains_korean_script(value) for value in (action.action, action.details, *action.required_items)):
            action.state = ReviewState.NEEDS_REVIEW
            untranslated = True
    for document in notice.required_documents:
        corrected_name = correct_grounded_wording(document.name, document.source_evidence)
        corrected_condition = correct_grounded_wording(document.condition, document.source_evidence)
        if (corrected_name, corrected_condition) != (document.name, document.condition):
            document.name, document.condition = corrected_name, corrected_condition
            document.state = ReviewState.NEEDS_REVIEW
        if any(_contains_korean_script(value) for value in (document.name, document.condition)):
            document.state = ReviewState.NEEDS_REVIEW
            untranslated = True
    _reconcile_required_documents(notice)
    for deadline in notice.deadlines:
        if any(_contains_korean_script(value) for value in (deadline.date, deadline.time, deadline.description)):
            deadline.state = ReviewState.NEEDS_REVIEW
            untranslated = True
    for contact in notice.contacts:
        if any(_contains_korean_script(value) for value in (contact.name, contact.details)):
            contact.state = ReviewState.NEEDS_REVIEW
            untranslated = True
    for group in notice.conditional_groups:
        if any(_contains_korean_script(value) for value in (group.group, group.application_period, group.details)):
            group.state = ReviewState.NEEDS_REVIEW
            untranslated = True
    if untranslated and notice.target_language == "en":
        notice.unverified_items.append(_UNTRANSLATED_WARNING)
    return notice


def choose_semantic_provider(provider: str) -> SemanticProvider:
    if provider == "mock":
        return MockSemanticProvider()
    if provider == "openai":
        return OpenAISemanticProvider()
    if provider == "auto":
        return OpenAISemanticProvider() if os.getenv("OPENAI_API_KEY") else MockSemanticProvider()
    raise SemanticError("Semantic provider must be auto, mock, or openai.")
