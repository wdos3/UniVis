from __future__ import annotations

import re
from collections.abc import Iterable

from app.models import FidelityReport, NoticeData, TemplateSelection


def _represented_ids(notice: NoticeData) -> set[str]:
    groups: Iterable[object] = (
        notice.audience
        + notice.actions
        + notice.deadlines
        + notice.required_documents
        + notice.eligibility
        + notice.exceptions
        + notice.warnings
        + notice.consequences
        + notice.locations
        + notice.contacts
        + notice.fees
        + notice.links
        + notice.key_details
        + notice.conditional_groups
    )
    return {
        fact_id
        for item in groups
        for fact_id in getattr(item, "source_fact_ids", [])
    }


def _unmapped_source_lines(notice: NoticeData, source_text: str) -> list[str]:
    groups = (
        notice.audience + notice.actions + notice.deadlines + notice.required_documents
        + notice.eligibility + notice.exceptions + notice.warnings + notice.consequences
        + notice.locations + notice.contacts + notice.fees + notice.links
        + notice.key_details + notice.conditional_groups
    )
    evidence = [re.sub(r"\s+", "", item.source_evidence) for item in groups if item.source_evidence]
    unmapped: list[str] = []
    seen: set[str] = set()
    for raw_line in source_text.splitlines():
        line = raw_line.strip()
        normalized = re.sub(r"\s+", "", line)
        if line.startswith("[Page ") or normalized in seen:
            continue
        seen.add(normalized)
        if not re.search(r"[가-힣0-9]", normalized) or (len(normalized) < 3 and not re.search(r"\d", normalized)):
            continue
        if not any(normalized in quote for quote in evidence):
            unmapped.append(line)
    return unmapped


def calculate_fidelity(notice: NoticeData, source_text: str = "") -> FidelityReport:
    critical = {fact.id for fact in notice.source_facts if fact.critical}
    represented = critical & _represented_ids(notice)
    missing = sorted(critical - represented)
    known = {fact.id for fact in notice.source_facts}
    invented = sorted(_represented_ids(notice) - known)
    unmapped_lines = _unmapped_source_lines(notice, source_text) if source_text else []

    checks: list[str] = []
    if notice.deadlines:
        checks.append("Deadline fields retain source evidence")
    if notice.required_documents:
        checks.append("Document requirements retain source evidence")
    if notice.exceptions:
        checks.append("Exceptions are represented")
    if notice.contacts:
        checks.append("Contact details are represented")
    if not invented:
        checks.append("No unsupported source-fact references detected")

    warnings = list(notice.ambiguities) + list(notice.unverified_items)
    if missing:
        warnings.append("Some critical source facts are not represented in output elements")
    if invented:
        warnings.append("Some output elements reference unknown source facts")
    if unmapped_lines:
        warnings.append(f"{len(unmapped_lines)} OCR line(s) are not linked to a structured output item; review the original notice.")

    return FidelityReport(
        checks=checks,
        warnings=warnings,
        critical_fields_in_source=len(critical),
        critical_fields_represented=len(represented),
        potentially_missing=missing,
        potentially_invented=invented,
        unmapped_source_line_count=len(unmapped_lines),
        unmapped_source_lines=unmapped_lines[:30],
        serious_issue=bool(missing or invented or notice.unverified_items),
    )


def select_templates(notice: NoticeData) -> TemplateSelection:
    conditional_text = " ".join(item.text.lower() for item in notice.eligibility)
    has_branch = any(token in conditional_text for token in ("if ", "only", "unless", "either"))
    selection = TemplateSelection(
        checklist=bool(notice.required_documents or notice.eligibility),
        step_flow=len(notice.actions) >= 2,
        timeline=len(notice.deadlines) >= 2,
        decision_tree=has_branch or bool(notice.conditional_groups),
        warning_cards=bool(notice.warnings or notice.exceptions or notice.consequences),
        information_cards=bool(notice.locations or notice.contacts or notice.fees or notice.links or notice.key_details),
    )
    overrides = notice.template_overrides.model_dump(exclude_none=True)
    return selection.model_copy(update=overrides)
