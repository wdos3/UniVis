from __future__ import annotations

import re

from app.models import NoticeData, ReviewState, SourcePage


EXACT_VALUE_PATTERN = re.compile(
    r"(?:https?://\S+|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|₩\s?[\d,]+|\d{2,4}[./-]\d{1,2}(?:[./-]\d{1,2})?|\d{1,2}:\d{2}|\d{2,4}-\d{3,4}-\d{4}|[A-Z]\d{2,4})",
    re.IGNORECASE,
)


def exact_values(text: str) -> set[str]:
    return {value.rstrip(".,)") for value in EXACT_VALUE_PATTERN.findall(text)}


def reconcile_text_sources(vision_text: str, local_ocr_pages: list[str]) -> list[str]:
    local_text = "\n".join(text for text in local_ocr_pages if text.strip())
    if not local_text:
        return []
    vision_values = exact_values(vision_text)
    ocr_values = exact_values(local_text)
    conflicts: list[str] = []
    for value in sorted((vision_values | ocr_values) - (vision_values & ocr_values)):
        conflicts.append(f"Exact value needs review because OCR and vision did not both confirm it: {value}")
    return conflicts


def add_page_provenance(notice: NoticeData, recovered_pages: list[str], source_pages: list[SourcePage]) -> None:
    groups = (
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
        + notice.source_facts
    )
    page_by_number = {page.page_number: page for page in source_pages}
    for item in groups:
        evidence = getattr(item, "source_evidence", "") or getattr(item, "source_text", "")
        if item.source_page is None and evidence:
            for index, page_text in enumerate(recovered_pages, start=1):
                if evidence.replace(" ", "") in page_text.replace(" ", ""):
                    item.source_page = index
                    break
        if item.source_page is not None and item.source_page in page_by_number:
            source_page = page_by_number[item.source_page]
            item.source_image_id = source_page.id
            if not source_page.readable:
                item.state = ReviewState.NEEDS_REVIEW
