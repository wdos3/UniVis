from __future__ import annotations

import re

from app.models import NoticeData, ReviewState, SourcePage


EXACT_VALUE_PATTERN = re.compile(
    r"(?:https?://\S+|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|₩\s?[\d,]+|\d{2,4}[./-]\d{1,2}(?:[./-]\d{1,2})?|\d{1,2}:\d{2}|\d{2,4}-\d{3,4}-\d{4}|[A-Z]\d{2,4})",
    re.IGNORECASE,
)
PAGE_MARKER_PATTERN = re.compile(r"(?m)^\[Page (\d+)\][ \t]*(?:\r?\n|$)")


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


def split_recovered_pages(text: str, page_count: int) -> list[str]:
    """Keep OCR page numbers intact when edited text is reprocessed."""
    markers = list(PAGE_MARKER_PATTERN.finditer(text))
    if not markers:
        if page_count == 1:
            if text.strip():
                return [text.strip()]
            raise ValueError("Add recovered text before reprocessing.")
        raise ValueError("Keep [Page N] headings when correcting a multi-page notice.")
    if text[:markers[0].start()].strip():
        raise ValueError("Place corrected text beneath its [Page N] heading.")

    pages = [""] * page_count
    seen: set[int] = set()
    for index, marker in enumerate(markers):
        page_number = int(marker.group(1))
        if page_number < 1 or page_number > page_count or page_number in seen:
            raise ValueError("Page headings must use each original page number at most once.")
        seen.add(page_number)
        end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
        pages[page_number - 1] = text[marker.end():end].strip()
    if not any(pages):
        raise ValueError("Add recovered text to at least one page before reprocessing.")
    return pages


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
        + notice.key_details
        + notice.conditional_groups
        + notice.source_facts
    )
    page_by_number = {page.page_number: page for page in source_pages}
    normalized_pages = {
        page.page_number: re.sub(r"\s+", "", recovered_pages[page.page_number - 1])
        for page in source_pages
        if page.page_number <= len(recovered_pages)
    }
    uncertain = False
    for item in groups:
        evidence = getattr(item, "source_evidence", "") or getattr(item, "source_text", "")
        normalized_evidence = re.sub(r"\s+", "", evidence)
        matching_pages = [
            number
            for number, page_text in normalized_pages.items()
            if normalized_evidence and normalized_evidence in page_text
        ]
        if len(matching_pages) != 1:
            item.source_page = None
            item.source_image_id = None
            item.bounding_box = None
            if item.state == ReviewState.VERIFIED:
                item.state = ReviewState.NEEDS_REVIEW
            uncertain = True
            continue

        page_number = matching_pages[0]
        if item.source_page != page_number:
            item.bounding_box = None
        item.source_page = page_number
        source_page = page_by_number[page_number]
        item.source_image_id = source_page.id
        if not source_page.readable and item.state == ReviewState.VERIFIED:
            item.state = ReviewState.NEEDS_REVIEW
            uncertain = True
    if uncertain:
        notice.unverified_items.append("Some source evidence could not be uniquely matched to a readable page; review highlighted facts.")
