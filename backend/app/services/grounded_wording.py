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
    r"\b(?:(?:(?:personal information|privacy)(?: collection and use)?|collection and use)\s+)?consent form\b",
    re.IGNORECASE,
)
_ORIGINAL_AI_TECHNOLOGY = re.compile(r"\boriginal AI technolog(?:y|ies)\b", re.IGNORECASE)


def _match_case(original: str, replacement: str) -> str:
    return replacement[0].upper() + replacement[1:] if original[0].isupper() else replacement


def correct_grounded_wording(text: str, source_evidence: str) -> str:
    """Correct source-backed glossary terms without composing notice clauses.

    Eligibility, conditions, quantities, institutions, and missing meanings are
    the semantic audit's responsibility. Local wording must not substitute a
    remembered poster sentence for the provider's source-grounded translation.
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
    if "개인정보수집및이용동의서" in evidence:
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
    return corrected
