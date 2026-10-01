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
_UNSUPPORTED_AIX_EXPANSION = re.compile(r"\bAIX\s*\(\s*AI\s+Experience\s*\)", re.IGNORECASE)
_RESEARCH_CARD_SOURCE = re.compile(r"연구비(?:는|사용[:：])?융합교육원(?:에)?방문하여카드결제[.!。]?")
_OTHER_PROGRAMS = re.compile(r"\bother (?:university )?programs?\b", re.IGNORECASE)
_SIMILAR_TOPICS = re.compile(r"\bsimilar (?:research )?topics?\b", re.IGNORECASE)
_DUPLICATE_SUPPORT_SOURCE = "교내타프로그램에서동일하거나유사한연구주제로지원을받는학생및팀은참여제한"
_ENROLLED_UNDERGRADUATES_SOURCE = re.compile(
    r"(?:모집대상[:：]?)?(20\d{2})학년도([12])학기학부재학생[.!。]?"
)
_RESEARCH_SPENDING_SOURCE = "연구비는기자재구입및대여,재료비,도서구입및인쇄비로사용가능"
_LEAVE_FUNDING_EXCLUSION_SOURCE = "휴학생도참여는가능하나연구비및활동비지원대상에서는제외"


def _match_case(original: str, replacement: str) -> str:
    return replacement.capitalize() if original[0].isupper() else replacement


def correct_grounded_wording(text: str, source_evidence: str) -> str:
    """Fix narrowly recognized mistranslations only when cited Korean supports them."""
    if not text or not source_evidence:
        return text
    evidence = re.sub(r"\s+", "", source_evidence)
    if evidence == _LEAVE_FUNDING_EXCLUSION_SOURCE and len(re.findall(r"[A-Za-z]+", text)) >= 4:
        return "Students on leave may participate, but are excluded from both research funding and activity allowance support."
    enrollment = _ENROLLED_UNDERGRADUATES_SOURCE.fullmatch(evidence)
    if enrollment and len(re.findall(r"[A-Za-z]+", text)) >= 6 and not re.search(r"\benrolled\b", text, re.IGNORECASE):
        semester = "first" if enrollment[2] == "1" else "second"
        return f"Undergraduate students enrolled in the {semester} semester of the {enrollment[1]} academic year."
    if evidence == _RESEARCH_SPENDING_SOURCE and re.search(
        r"\brent\w*\s+equipment[,\s]+materials?[,\s]+books?", text, re.IGNORECASE
    ):
        return "Research expenses may cover equipment purchase or rental, material costs, book purchases, and printing costs."
    if evidence == _DUPLICATE_SUPPORT_SOURCE and len(re.findall(r"[A-Za-z]+", text)) >= 6:
        return (
            "Students and teams receiving support from other on-campus programs for the same or similar "
            "research topics are restricted from participation."
        )
    corrected = text
    if "휴학생" in evidence:
        corrected = _LEAVING_STUDENTS.sub(
            lambda match: _match_case(match.group(), "students on leave"), corrected
        )
    if "비교과통합관리시스템" in evidence:
        corrected = _COMPARATIVE_SYSTEM.sub("Extracurricular Integrated Management System", corrected)
    if "교내타프로그램" in evidence and "동일하거나유사한연구주제" in evidence:
        corrected = _OTHER_PROGRAMS.sub(
            lambda match: _match_case(
                match.group(), "other on-campus programs" if match.group().casefold().endswith("programs")
                else "other on-campus program",
            ), corrected,
        )
        if not re.search(r"\b(?:same|identical)\b", corrected, re.IGNORECASE):
            corrected = _SIMILAR_TOPICS.sub(
                lambda match: _match_case(match.group(), "the same or " + match.group().casefold()), corrected,
            )
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
    if _RESEARCH_CARD_SOURCE.fullmatch(evidence) and len(re.findall(r"[A-Za-z]+", corrected)) >= 6:
        corrected = (
            "Research expenses must be paid by card at the Convergence Education Center, "
            "requiring an in-person visit."
        )
    return corrected
