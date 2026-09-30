from __future__ import annotations

import re

from app.models import Action, NoticeData


KOREAN_PATTERN = re.compile(r"[\uac00-\ud7a3]")


def appears_korean(text: str) -> bool:
    non_space = len(re.sub(r"\s", "", text))
    if non_space == 0:
        return False
    return len(KOREAN_PATTERN.findall(text)) / non_space >= 0.08


def _action_line(action: Action) -> str:
    parts = [f"{action.step}. {action.action}"]
    if action.details:
        parts.append(action.details)
    if action.deadline:
        parts.append(f"Deadline: {action.deadline}")
    if action.location:
        parts.append(f"Where: {action.location}")
    if action.required_items:
        parts.append(f"Required items: {', '.join(action.required_items)}")
    return " — ".join(parts)


def simplified_text(notice: NoticeData) -> str:
    sections: list[tuple[str, list[str]]] = []
    if notice.audience:
        sections.append(("Who this is for", [item.text for item in notice.audience]))
    if notice.summary:
        sections.append(("What this notice says", [notice.summary]))
    if notice.actions:
        sections.append(("What you must do", [_action_line(action) for action in notice.actions]))
    if notice.deadlines:
        sections.append(
            ("Deadlines", [" — ".join(filter(None, (d.date, d.time, d.description))) for d in notice.deadlines])
        )
    if notice.required_documents:
        sections.append(
            (
                "Required documents",
                [
                    f"{d.name}{f' ({d.condition})' if d.condition else ''}{' — optional' if not d.required else ''}"
                    for d in notice.required_documents
                ],
            )
        )
    if notice.eligibility:
        sections.append(("Eligibility", [item.text for item in notice.eligibility]))
    if notice.conditional_groups:
        sections.append(
            (
                "Dates by student group",
                [" — ".join(filter(None, (item.group, item.application_period, item.details))) for item in notice.conditional_groups],
            )
        )
    if notice.exceptions:
        sections.append(("Exceptions", [item.text for item in notice.exceptions]))
    if notice.warnings or notice.consequences:
        sections.append(("Important", [item.text for item in notice.warnings + notice.consequences]))
    if notice.locations:
        sections.append(("Where", [item.text for item in notice.locations]))
    if notice.key_details:
        details_by_topic: dict[str, list[str]] = {}
        for item in notice.key_details:
            details_by_topic.setdefault(item.label.strip() or "Other key details", []).append(item.text)
        sections.extend(details_by_topic.items())
    if notice.fees:
        sections.append(("Fees", [item.text for item in notice.fees]))
    if notice.financial_support:
        sections.append(("Financial support", [item.text for item in notice.financial_support]))
    if notice.links:
        sections.append(("Online links", [item.text for item in notice.links]))
    if notice.contacts:
        sections.append(
            (
                "Contact",
                [" · ".join(filter(None, (c.name, c.phone, c.email, c.details))) for c in notice.contacts],
            )
        )
    return "\n\n".join(f"{title}\n" + "\n".join(f"- {line}" for line in lines) for title, lines in sections)
