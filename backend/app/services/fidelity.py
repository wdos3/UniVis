from __future__ import annotations

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
        + notice.conditional_groups
    )
    return {
        fact_id
        for item in groups
        for fact_id in getattr(item, "source_fact_ids", [])
    }


def calculate_fidelity(notice: NoticeData) -> FidelityReport:
    critical = {fact.id for fact in notice.source_facts if fact.critical}
    represented = critical & _represented_ids(notice)
    missing = sorted(critical - represented)
    known = {fact.id for fact in notice.source_facts}
    invented = sorted(_represented_ids(notice) - known)

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

    return FidelityReport(
        checks=checks,
        warnings=warnings,
        critical_fields_in_source=len(critical),
        critical_fields_represented=len(represented),
        potentially_missing=missing,
        potentially_invented=invented,
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
        information_cards=bool(notice.locations or notice.contacts or notice.fees),
    )
    overrides = notice.template_overrides.model_dump(exclude_none=True)
    return selection.model_copy(update=overrides)
