from __future__ import annotations

import re


_PAYER_TERMS = re.compile(r"납부|부담|입금|납입|수수료|등록금|참가비")
_LEAVING_STUDENTS = re.compile(r"\bleaving students\b", re.IGNORECASE)
_COMPARATIVE_SYSTEM = re.compile(
    r"\b(?:comparative|comparison)\s+integrated\s+management\s+system\b",
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
_UNSUPPORTED_AIX_EXPANSION = re.compile(r"\bAIX\s*\(\s*AI\s+Experience\s*\)", re.IGNORECASE)


def _match_case(original: str, replacement: str) -> str:
    return replacement.capitalize() if original[0].isupper() else replacement


def correct_grounded_wording(text: str, source_evidence: str) -> str:
    """Fix narrowly recognized mistranslations only when cited Korean supports them."""
    if not text or not source_evidence:
        return text
    evidence = re.sub(r"\s+", "", source_evidence)
    corrected = text
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
    if re.search(r"\bAIX\b", source_evidence, re.IGNORECASE) and not re.search(
        r"\bAI\s+Experience\b", source_evidence, re.IGNORECASE
    ):
        corrected = _UNSUPPORTED_AIX_EXPANSION.sub("AIX", corrected)
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
                        "research-funded purchases must be paid for"
                        if "must be paid" in match.group().casefold()
                        else "research-funded purchases are paid for",
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
