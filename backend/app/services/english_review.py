from __future__ import annotations

from dataclasses import dataclass
import re

from app.models import DocumentRequirement, NoticeData, ReviewState
from app.services.coverage import CoverageUnit, audit_coverage, display_text, literal_source_unit_ids
from app.services.english_literals import (
    missing_english_literals, missing_source_conditions, missing_source_values, missing_spending_rules,
    unsupported_currency_amounts, unsupported_source_dates,
)
from app.services.english_verification import (
    EnglishSupportField, EnglishSupportSourceUnit, EnglishSupportProviderError, verify_english_support,
)
from app.services.source_grounding import GROUNDED_FIELDS
from app.services.source_fragments import broken_transliteration_reason
from app.services.text import simplified_text


_BARE_TABLE_VALUE = re.compile(r"(?:(?:팀|개인)\s*)?(?:[\d,.]+|\d+[A-Za-z]+|[A-Za-z]+\d+)\s*(?:(?:만|천|억)?\s*원|명|작품|점?\s*이상)")
_SECTION_HEADING = re.compile(r"[·•*\s]*(?:모집\s*(?:대상|기간|분야|인원)|지원\s*(?:금액|방법|자격)|신청\s*(?:방법|기간)|연구\s*주제|접수\s*방법)[\s:：|>]*")
_DOCUMENT_CITATION = re.compile(r"서류|증명서|성적표|자격증|신청서|지원서|계획서|동의서|제출|준비|지참|document|certificate|transcript|submit|bring", re.IGNORECASE)
_PREFERENCE_LABEL = re.compile(r"\b(?:preference|preferred|priority)\b", re.IGNORECASE)
_GENERIC_DETAIL_LABELS = {"", "additional detail", "other", "other key details", "eligibility detail"}
_FUNDING_HEADER = re.compile(r"(?:상금|시상\s*규모|(?:최)?우수상|대상|장려상|특별상)")
_SOURCE_RELATION = re.compile(r"모집|신청|제출|지급|납부|제외|금지|가능|불가|참여|진행|참조|확인|문의|등록|수령|검색|이용|찾기|결제|\d")
_KOREAN = re.compile(r"[가-힣]")
_SEMESTER_HEADING = re.compile(r"20\d{2}\s*[-.]?\s*[12]\s*학기")
_APPLICATION_PERIOD = re.compile(r"\b(?:application|apply|deadline|closing)\b", re.IGNORECASE)
_BARE_SCHEDULE = re.compile(r"(?:매주\s*[월화수목금토일]요일(?:\s*\d{1,2}\s*시)?|온라인\s*진행|\d{1,2}월)")
_BARE_ENGLISH_SCHEDULE = re.compile(
    r"(?:every\s+(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)|"
    r"(?:conducted\s+)?online(?:\s+proceedings?)?|(?:January|February|March|April|May|June|July|August|September|October|November|December))\.?",
    re.IGNORECASE,
)
_EXPANDED_ONLINE_SCOPE = re.compile(r"\b(?:entire|all|every)\b", re.IGNORECASE)
_EXPENSE_NOUN_FRAGMENT = re.compile(r"(?:비용|항목|경비|지출|소요비|재료비|구입비|인쇄비)[\s.,:：]*$")
_SOURCE_RESTRICTION_MODALITY = re.compile(r"금지|불가|불허|제한|안\s*됨|않|못|사용\s*가능|사용\s*할\s*수")
_EXPECTED_GRADUATION_SOURCE = re.compile(r"졸업\s*(?:[（(]\s*예정\s*[)）]|예정)")
_GRADUATION_ALTERNATIVE_SOURCE = re.compile(r"졸업\s*[（(]\s*예정\s*[)）]")
_GRADUATION_DOCUMENT_ENGLISH = re.compile(r"\b(?:graduat\w*|degree)\b", re.IGNORECASE)
_DOCUMENT_NOUN = re.compile(r"증명서|성적표|자격증|동의서|지원서|신청서|계획서")
_EXPECTED_GRADUATION_ENGLISH = re.compile(
    r"\b(?:expected|anticipated|prospective|pending|scheduled|upcoming)\b[\s()-]*graduat\w*\b|"
    r"\bgraduat\w*[\s/-]*(?:\([^)]*)?(?:expected|anticipated|prospective|pending|scheduled|upcoming)\b",
    re.IGNORECASE,
)
_GRADUATION_ALTERNATIVE_ENGLISH = re.compile(
    r"\bor\b|/|\b(?:including|either|also)\b|\bgraduat\w*\s*\(", re.IGNORECASE,
)
_INTERVIEW_DOCUMENT_PHASE = re.compile(r"면접(?:\s*전형)?\s*(전|후|시|때|단계|당일)")
_INTERVIEW_SUBMISSION_ENGLISH = {
    "전": re.compile(r"\bbefore\b[^.;\n]{0,40}\binterviews?\b", re.IGNORECASE),
    "후": re.compile(r"\bafter\b[^.;\n]{0,40}\binterviews?\b", re.IGNORECASE),
    "시": re.compile(
        r"\b(?:during|at|for)\b[^.;\n]{0,40}\binterviews?\b|\binterviews?[\s-]+(?:stage|phase|process)\b",
        re.IGNORECASE,
    ),
}
_BARE_QUESTION_COUNT = re.compile(r"(?:약\s*|총\s*)?\d+\s*(?:문항|문제)(?:\s*(?:내외|정도|이내|이상))?")
_ENGLISH_MONTH = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
_ENGLISH_DATE = (
    rf"(?:{_ENGLISH_MONTH}\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s+\d{{4}})?|"
    rf"\d{{1,2}}\s+{_ENGLISH_MONTH}(?:\s+\d{{4}})?|\d{{1,4}}[-./]\d{{1,2}}(?:[-./]\d{{1,4}})?)"
)
_ENGLISH_TIME = r"(?:\d{1,2}:\d{2}(?:\s*(?:am|pm))?|\d{1,2}\s*(?:am|pm)|morning|afternoon|evening|noon|midnight)"
_BARE_ENGLISH_DATE_TIME = re.compile(
    rf"(?:{_ENGLISH_DATE}(?:\s*\((?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)(?:day)?\))?"
    rf"(?:[\s,]+(?:at\s+)?{_ENGLISH_TIME})?|{_ENGLISH_TIME})\.?",
    re.IGNORECASE,
)


def _unassociated_source_fragment(field: EnglishSupportField) -> bool:
    """Bare cells and short generic captions require contextual source evidence.

    This cannot identify every OCR error. It prevents a catch-all detail field
    from presenting detached values or naming noise as comprehended facts.
    Explicit topics, contacts, locations, and contextual clauses remain eligible
    for the semantic review; arbitrary proper nouns are not corrected locally.
    """
    lines = [line.strip() for line in field.source_evidence.splitlines() if line.strip()]
    if lines and all(_SECTION_HEADING.fullmatch(line) for line in lines):
        return True
    if len(lines) != 1:
        return False
    source = lines[0]
    if _BARE_QUESTION_COUNT.fullmatch(source):
        return True
    if (
        field.field == "key_details" and field.label.casefold() in _GENERIC_DETAIL_LABELS | {"schedule"}
        and _BARE_ENGLISH_DATE_TIME.fullmatch(field.text.strip())
    ):
        return True
    if (
        field.label.casefold() == "restriction" and _EXPENSE_NOUN_FRAGMENT.search(source)
        and not _SOURCE_RESTRICTION_MODALITY.search(source)
    ):
        # A detached expense category cannot establish a prohibition or its
        # funding recipient. A complete spending rule remains reviewable.
        return True
    if (
        field.field == "key_details" and field.label.casefold() in _GENERIC_DETAIL_LABELS
        and not _KOREAN.search(source) and len(source) <= 12
        and re.sub(r"[\s.]", "", source).casefold() == re.sub(r"[\s.]", "", field.text).casefold()
    ):
        return True
    if _SEMESTER_HEADING.fullmatch(source) and _APPLICATION_PERIOD.search(field.text):
        return True
    if _BARE_SCHEDULE.fullmatch(source):
        if _BARE_ENGLISH_SCHEDULE.fullmatch(field.text.strip()):
            return True
        if source.replace(" ", "") == "온라인진행" and _EXPANDED_ONLINE_SCOPE.search(field.text):
            return True
    if _BARE_TABLE_VALUE.fullmatch(source):
        return True
    if field.field == "financial_support" and _FUNDING_HEADER.fullmatch(source):
        return True
    return bool(
        field.field == "key_details"
        and field.label.casefold() in {"", "additional detail", "other", "other key details"}
        and _KOREAN.search(source)
        and len(re.sub(r"\s+", "", source)) <= 20
        and not _SOURCE_RELATION.search(source)
    )


@dataclass(frozen=True)
class EnglishNoticeReview:
    notice: NoticeData
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    usage_complete: bool = True
    unverified_source_units: int = 0
    has_verification_gaps: bool = False


def _document_contexts(item: DocumentRequirement, units: list[CoverageUnit]) -> list[str]:
    """Recover a shortened document quote's own source line, without crossing pages."""
    evidence = re.sub(r"\s+", "", item.source_evidence)
    if not evidence:
        return []
    matching = [
        unit.text for unit in units
        if (item.source_page is None or unit.page == item.source_page)
        and evidence in re.sub(r"\s+", "", unit.text)
    ]
    return list(dict.fromkeys([item.source_evidence, *matching]))


def _document_omits_source_condition(item: DocumentRequirement, units: list[CoverageUnit]) -> bool:
    english = display_text(item)
    graduation_document = bool(
        _GRADUATION_DOCUMENT_ENGLISH.search(item.name)
        or (_EXPECTED_GRADUATION_SOURCE.search(item.source_evidence) and len(_DOCUMENT_NOUN.findall(item.source_evidence)) == 1)
    )
    for source in _document_contexts(item, units):
        # A shared document-list quotation does not make a transcript another
        # graduation certificate. Only check the relevant document's alternative.
        if graduation_document and _EXPECTED_GRADUATION_SOURCE.search(source):
            if not _EXPECTED_GRADUATION_ENGLISH.search(english):
                return True
            if _GRADUATION_ALTERNATIVE_SOURCE.search(source) and not _GRADUATION_ALTERNATIVE_ENGLISH.search(english):
                return True
        if not re.search(r"제출|지참", source):
            continue
        for match in _INTERVIEW_DOCUMENT_PHASE.finditer(source):
            phase = match.group(1)
            required_phase = _INTERVIEW_SUBMISSION_ENGLISH[phase if phase in {"전", "후"} else "시"]
            if not required_phase.search(english):
                return True
    return False


def _prepare_review_notice(notice: NoticeData, source_text: str) -> tuple[NoticeData, bool]:
    """Resolve local presentation rules before certifying the displayed meaning."""
    prepared = notice.model_copy(deep=True)
    prepared.ambiguities = []
    prepared.unverified_items = []
    structural_gaps = False
    source_units = audit_coverage(prepared, source_text).units
    documents = [
        item for item in prepared.required_documents if not _document_omits_source_condition(item, source_units)
    ]
    if len(documents) != len(prepared.required_documents):
        prepared.required_documents = documents
        structural_gaps = True
    for action in prepared.actions:
        if action.required_items and not _DOCUMENT_CITATION.search(action.source_evidence):
            # An application quote alone cannot place interview documents in
            # the application checklist. Review the actual retained checklist.
            action.required_items = []
            structural_gaps = True
    preferences = [item for item in prepared.eligibility if _PREFERENCE_LABEL.search(item.label)]
    if preferences:
        prepared.eligibility = [item for item in prepared.eligibility if item not in preferences]
        if "우대" in source_text:
            prepared.key_details.extend(preferences)
        else:
            structural_gaps = True
    return prepared, structural_gaps


async def review_notice_english(
    notice: NoticeData, source_text: str, *, layout_context: str = "", primary_notice_title: str = "",
) -> EnglishNoticeReview:
    """Review the final display after repair without composing new instructions.

    Coverage repair generates English too. Checking its citations and numeric
    literals alone cannot establish that those sentences preserve source scope.
    This independent pass reviews the final wording and can only withhold it.
    """
    notice, structural_gaps = _prepare_review_notice(notice, source_text)
    fields: list[EnglishSupportField] = []
    source_units = audit_coverage(notice, source_text).units
    item_ids: dict[tuple[str, int], str] = {}
    for field in GROUNDED_FIELDS:
        for index, item in enumerate(getattr(notice, field)):
            text = display_text(item)
            if not text:
                continue
            field_id = f"E{len(fields) + 1:03d}"
            item_ids[(field, index)] = field_id
            fields.append(EnglishSupportField(
                id=field_id, text=text, source_evidence=item.source_evidence,
                source_page=item.source_page, field=field, label=getattr(item, "label", ""),
            ))
    context_ids: dict[str, str] = {}
    for field in ("title", "purpose", "summary"):
        text = getattr(notice, field)
        if not text or (field == "title" and text == "Untitled notice"):
            continue
        field_id = f"E{len(fields) + 1:03d}"
        context_ids[field] = field_id
        fields.append(EnglishSupportField(id=field_id, text=text, field=field))
    if not fields:
        withheld = notice.model_copy(deep=True)
        withheld.ambiguities = []
        withheld.unverified_items = []
        units = audit_coverage(withheld, source_text).units
        if units:
            withheld.unverified_items.append(
                "No factual instructions could be verified from this attempt. Your photo and recognized text are retained; "
                "retrying does not require Korean transcription."
            )
        return EnglishNoticeReview(
            notice=withheld, unverified_source_units=len(units), has_verification_gaps=bool(units),
        )

    locally_rejected = {
        field.id for field in fields
        if _unassociated_source_fragment(field)
        or (field.source_evidence and unsupported_currency_amounts(field.source_evidence, field.text))
        or (field.source_evidence and unsupported_source_dates(field.source_evidence, field.text))
        or broken_transliteration_reason(field.source_evidence, field.text, field=field.field, label=field.label)
    }
    english_by_quote: dict[tuple[int | None, str], list[str]] = {}
    for field in fields:
        if field.id not in locally_rejected and field.source_evidence:
            english_by_quote.setdefault((field.source_page, field.source_evidence), []).append(field.text)
    # Several items may legitimately share a multi-fact quotation. A date does
    # not need to repeat its neighboring topic's printed phrase; the surviving
    # items collectively must preserve it before their source is certified.
    locally_rejected.update(
        field.id for field in fields if field.source_evidence
        and missing_english_literals(
            field.source_evidence, " | ".join(english_by_quote.get((field.source_page, field.source_evidence), [])),
        )
    )
    review_fields = [field for field in fields if field.id not in locally_rejected]
    try:
        verdict = await verify_english_support(
            review_fields, source_text, layout_context=layout_context, primary_notice_title=primary_notice_title, allow_partial=True,
            source_units=[EnglishSupportSourceUnit(id=unit.id, text=unit.text, page=unit.page, line=unit.line) for unit in source_units],
        )
    except EnglishSupportProviderError as exc:
        # No completed support review exists. Keep the local source and English
        # gap messages, but do not publish unchecked repaired instructions.
        rejected = {field.id for field in fields}
        requests = exc.requests
        input_tokens, output_tokens, total_tokens = exc.input_tokens, exc.output_tokens, exc.total_tokens
        usage_complete = exc.usage_complete
        failure = True
        partition_complete = False
        certified_source_ids: set[str] = set()
    else:
        rejected = set(verdict.unsupported_ids) | set(verdict.insufficient_ids)
        requests = verdict.requests
        input_tokens, output_tokens, total_tokens = verdict.input_tokens, verdict.output_tokens, verdict.total_tokens
        usage_complete = verdict.usage_complete
        failure = False
        partition_complete = verdict.partition_complete and verdict.source_partition_complete
        certified_source_ids = set(verdict.fully_covered_source_ids)

    rejected.update(locally_rejected)

    reviewed = notice.model_copy(deep=True)
    # Provider-authored review strings can themselves contain instructions.
    # Rebuild gaps from source coverage instead of treating free prose as safe.
    reviewed.ambiguities = []
    reviewed.unverified_items = []
    rejected_fact_ids: set[str] = set()
    for field in GROUNDED_FIELDS:
        kept = []
        for index, item in enumerate(getattr(reviewed, field)):
            if item_ids.get((field, index)) in rejected:
                rejected_fact_ids.update(item.source_fact_ids)
            else:
                kept.append(item)
        setattr(reviewed, field, kept)
    for field, field_id in context_ids.items():
        if field_id in rejected:
            setattr(reviewed, field, "Untitled notice" if field == "title" else "")
    for step, action in enumerate(reviewed.actions, 1):
        action.step = step
    for fact in reviewed.source_facts:
        if fact.id in rejected_fact_ids:
            fact.state = ReviewState.NEEDS_REVIEW

    source_audit = audit_coverage(reviewed, source_text)
    uncovered_ids = {unit.id for unit in source_audit.uncovered}
    # A supported field may express only one clause of its source quotation.
    # Full-unit verification and actual surviving citations are both required
    # before a former completeness gap can be cleared.
    verified_ids = {
        unit.id for unit in source_audit.units
        if unit.id in certified_source_ids and unit.id not in uncovered_ids
        and not missing_source_values(unit.text, " | ".join(source_audit.cited_english_by_unit[unit.id]))
        and not missing_english_literals(unit.text, " | ".join(source_audit.cited_english_by_unit[unit.id]))
        and not missing_source_conditions(unit.text, " | ".join(source_audit.cited_english_by_unit[unit.id]))
        and not missing_spending_rules(unit.text, " | ".join(source_audit.cited_english_by_unit[unit.id]))
    }
    # Parenthesized printed terminology can span OCR lines. A unit-by-unit
    # check alone would miss a phrase split across two source units.
    page_units: dict[int, list] = {}
    for unit in source_audit.units:
        page_units.setdefault(unit.page, []).append(unit)
    digest = simplified_text(reviewed)
    for units in page_units.values():
        for phrase in missing_english_literals("\n".join(unit.text for unit in units), digest):
            implicated = literal_source_unit_ids(phrase, units)
            verified_ids.difference_update(implicated or {unit.id for unit in units})
    unverified_ids = {unit.id for unit in source_audit.units} - verified_ids
    if unverified_ids:
        if failure:
            message = (
                "The final English verification service was unavailable. Instructions are withheld for this attempt; "
                "your photo and recognized text are retained for retry without Korean transcription."
            )
        else:
            lines_by_page: dict[int, list[int]] = {}
            for unit in source_audit.units:
                if unit.id in unverified_ids:
                    lines_by_page.setdefault(unit.page, []).append(unit.line)
            locations = "; ".join(
                f"page {page}, recovered lines {', '.join(map(str, sorted(set(lines))))}"
                for page, lines in lines_by_page.items()
            )
            message = "Some source details could not be verified automatically and are withheld."
            if locations:
                message += f" Affected evidence: {locations}."
            message += " Retry English interpretation using the retained OCR, or use a closer photo of the affected area; Korean transcription is optional."
        reviewed.unverified_items.append(message)
        if not failure and not partition_complete:
            reviewed.unverified_items.append(
                "The English verification response was incomplete. Missing or conflicting field classifications "
                "were withheld; independently classified fields remain available."
            )
        if structural_gaps:
            reviewed.unverified_items.append(
                "A field or action checklist was withheld because its source did not establish its role, "
                "required items, or submission stage."
            )
    return EnglishNoticeReview(
        notice=reviewed, requests=requests, input_tokens=input_tokens,
        output_tokens=output_tokens, total_tokens=total_tokens, usage_complete=usage_complete,
        unverified_source_units=len(unverified_ids), has_verification_gaps=bool(unverified_ids),
    )
