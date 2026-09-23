from __future__ import annotations

import re

from app.models import NoticeData


KOREAN_PATTERN = re.compile(r"[\uac00-\ud7a3]")


def appears_korean(text: str) -> bool:
    non_space = len(re.sub(r"\s", "", text))
    if non_space == 0:
        return False
    return len(KOREAN_PATTERN.findall(text)) / non_space >= 0.08


def simplified_text(notice: NoticeData) -> str:
    sections: list[tuple[str, list[str]]] = []
    if notice.audience:
        sections.append(("Who this is for", [item.text for item in notice.audience]))
    if notice.summary:
        sections.append(("What this notice says", [notice.summary]))
    if notice.actions:
        sections.append(("What you must do", [f"{a.step}. {a.action}" for a in notice.actions]))
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
    if notice.contacts:
        sections.append(
            (
                "Contact",
                [" · ".join(filter(None, (c.name, c.phone, c.email, c.details))) for c in notice.contacts],
            )
        )
    if not notice.actions:
        sections.append(("Action", ["This notice appears primarily informational. No required student action was identified."]))
    return "\n\n".join(f"{title}\n" + "\n".join(f"- {line}" for line in lines) for title, lines in sections)
