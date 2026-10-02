from __future__ import annotations

import re


_PAYER_TERMS = re.compile(r"납부|부담|입금|납입|수수료|등록금|참가비")
_LEAVING_STUDENTS = re.compile(r"\b(?:leaving|leave) students\b", re.IGNORECASE)
_COMPARATIVE_SYSTEM = re.compile(
    r"\b(?:comparative|comparison)(?:\s+and)?\s+integrated\s+management\s+system\b",
    re.IGNORECASE,
)
_RESEARCH_CARD_PAYMENT = re.compile(r"\bresearch fees? (?:must be|are|is) paid\b", re.IGNORECASE)
_RESEARCH_FEE = re.compile(r"\bresearch fees?\b", re.IGNORECASE)
_ACTIVITY_FEE = re.compile(r"\bactivity fees?\b", re.IGNORECASE)
_COMBINED_SUPPORT_FEES = re.compile(r"\bresearch and activity fees\b", re.IGNORECASE)
_CONSENT_FORM = re.compile(
    r"\b(?:(?:(?:personal information|privacy)(?: collection and use)?|collection and use)\s+)?consent form\b"
    r"(?!\s+for\s+(?:the\s+)?(?:personal information|privacy)\s+collection\s+and\s+use\b)",
    re.IGNORECASE,
)
_INCOMPLETE_CONSENT_NAME = re.compile(
    r"(?:consent for (?:personal information|data) collection(?: and use)?(?: form)?"
    r"|personal information consent(?: form)?)",
    re.IGNORECASE,
)
_COMPLETE_CONSENT_NAME = re.compile(
    r"(?:(?:personal information|privacy) collection and use consent form"
    r"|consent form for (?:the )?(?:personal information|privacy) collection and use)",
    re.IGNORECASE,
)
_ORIGINAL_AI_TECHNOLOGY = re.compile(r"\boriginal AI technolog(?:y|ies)\b", re.IGNORECASE)
_ACRONYM_EXPANSION_OPENING = re.compile(
    r"(?<![A-Za-z0-9_])([A-Z][A-Z0-9]+)[ \t]*(?:\r?\n[ \t]*)?\("
)
_ENGLISH_EXPANSION = re.compile(r"[A-Za-z0-9\s&/,'’\".+:;\-]+")
_EXPANSION_FUNCTION_WORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in",
    "is", "it", "of", "on", "or", "the", "to", "was", "were", "with",
})
_EXPANSION_QUALIFIERS = frozenset({
    "optional", "required", "mandatory", "conditional", "unless", "except", "excluding",
    "excluded", "not", "no", "never", "without", "only", "if", "when", "must", "may",
    "can", "cannot", "should", "will", "shall", "eligible", "ineligible", "is", "are",
})


def _match_case(original: str, replacement: str) -> str:
    return replacement[0].upper() + replacement[1:] if original[0].isupper() else replacement


def _preserve_printed_expansions(text: str, source_evidence: str) -> str:
    expansions: dict[str, set[str]] = {}
    invalid_acronyms: set[str] = set()
    for opening in _ACRONYM_EXPANSION_OPENING.finditer(source_evidence):
        acronym = opening.group(1)
        parenthetical = re.match(r"([^()]*)\)", source_evidence[opening.end():])
        if not parenthetical:
            invalid_acronyms.add(acronym)
            continue
        expansion = re.sub(r"\s+", " ", parenthetical.group(1)).strip()
        if not _ENGLISH_EXPANSION.fullmatch(expansion) or not re.search(r"[A-Za-z]", expansion):
            invalid_acronyms.add(acronym)
            continue
        expansions.setdefault(acronym, set()).add(expansion)

    for acronym, alternatives in expansions.items():
        if acronym in invalid_acronyms or len(alternatives) != 1:
            continue
        expansion = next(iter(alternatives))
        expansion_words = set(re.findall(r"[A-Za-z0-9]+", expansion.casefold())) - _EXPANSION_FUNCTION_WORDS
        mention = re.compile(rf"(?<!\w){re.escape(acronym)}(?!\w)")
        occurrences = list(mention.finditer(text))
        definitions: dict[int, tuple[int, int, str]] = {}
        invalid_definition = False
        for occurrence in occurrences:
            tail = text[occurrence.end():]
            parenthetical = re.match(r"[ \t]*(?:\r?\n[ \t]*)?\(([^()]*)\)", tail)
            if not parenthetical:
                if re.match(r"\s*(?:[-–—:]\s*)?[([{]", tail):
                    invalid_definition = True
                continue
            candidate = re.sub(r"\s+", " ", parenthetical.group(1)).strip()
            candidate_words = re.findall(r"[A-Za-z]+", candidate.casefold())
            substantive_words = [word for word in candidate_words if word not in _EXPANSION_FUNCTION_WORDS]
            initials = "".join(word[0].upper() for word in substantive_words)
            if (
                not _ENGLISH_EXPANSION.fullmatch(candidate) or re.search(r"\d", candidate)
                or len(substantive_words) < 2 or set(candidate_words) & _EXPANSION_QUALIFIERS
                or (candidate_words and candidate_words[0] in _EXPANSION_FUNCTION_WORDS - {"a", "an", "the"})
                or (len(set(substantive_words) & expansion_words) < 2 and initials != acronym)
            ):
                invalid_definition = True
                continue
            definitions[occurrence.start()] = (
                occurrence.end() + parenthetical.start(1),
                occurrence.end() + parenthetical.end(1), candidate,
            )
        if invalid_definition:
            continue
        outside_definitions = text
        for start, end, _ in reversed(list(definitions.values())):
            outside_definitions = outside_definitions[:start] + outside_definitions[end:]
        # Unparenthesized partial wording still needs semantic repair. Adding
        # a definition beside it could conceal a contradictory rendering.
        if set(re.findall(r"[A-Za-z0-9]+", outside_definitions.casefold())) & expansion_words:
            continue
        for occurrence in reversed(occurrences):
            if (definition := definitions.get(occurrence.start())) is not None:
                start, end, candidate = definition
                if candidate.casefold() != expansion.casefold():
                    text = text[:start] + expansion + text[end:]
            else:
                text = text[:occurrence.end()] + f" ({expansion})" + text[occurrence.end():]
    return text


def correct_grounded_wording(
    text: str, source_evidence: str, *, restore_expansions: bool = True,
) -> str:
    """Correct source-backed glossary terms without composing notice clauses.

    Eligibility, conditions, quantities, institutions, and missing meanings are
    the semantic audit's responsibility. Local wording must not substitute a
    remembered poster sentence for the provider's source-grounded translation.
    Acronym expansions use only this field's exact quotation; callers with
    whole-page context must disable that restoration.
    """
    if not text or not source_evidence:
        return text
    evidence = re.sub(r"\s+", "", source_evidence)
    corrected = text
    if "AI원천기술" in evidence:
        corrected = _ORIGINAL_AI_TECHNOLOGY.sub(
            lambda match: _match_case(match.group(), "core AI technologies"), corrected,
        )
    if "휴학생" in evidence:
        corrected = _LEAVING_STUDENTS.sub(
            lambda match: _match_case(match.group(), "students on leave"), corrected
        )
    if "비교과통합관리시스템" in evidence:
        corrected = _COMPARATIVE_SYSTEM.sub("Extracurricular Integrated Management System", corrected)
    if "개인정보수집및이용동의서" in evidence and not _COMPLETE_CONSENT_NAME.fullmatch(corrected.strip()):
        if _INCOMPLETE_CONSENT_NAME.fullmatch(corrected.strip()):
            corrected = _match_case(corrected.strip(), "personal information collection and use consent form")
        corrected = _CONSENT_FORM.sub(
            lambda match: _match_case(match.group(), "personal information collection and use consent form"),
            corrected,
        )
    if not _PAYER_TERMS.search(evidence):
        if "연구비" in evidence and "활동비" in evidence:
            corrected = _COMBINED_SUPPORT_FEES.sub(
                lambda match: _match_case(match.group(), "research funding and activity allowances"),
                corrected,
            )
        if "연구비" in evidence:
            if "카드결제" in evidence:
                corrected = _RESEARCH_CARD_PAYMENT.sub(
                    lambda match: _match_case(
                        match.group(),
                        "research expenses must be paid"
                        if "must be paid" in match.group().casefold()
                        else "research expenses are paid",
                    ),
                    corrected,
                )
            corrected = _RESEARCH_FEE.sub(
                lambda match: _match_case(match.group(), "research funding"), corrected
            )
        if "활동비" in evidence:
            corrected = _ACTIVITY_FEE.sub(
                lambda match: _match_case(match.group(), "activity allowance"), corrected
            )
    return _preserve_printed_expansions(corrected, source_evidence) if restore_expansions else corrected
