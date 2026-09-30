from __future__ import annotations

from collections import Counter, defaultdict, deque

from app.models import ClientOcrPage, OcrSpan


def _column(span_x: float, span_width: float) -> str:
    """Only classify text wholly outside the center gutter as a column."""
    right = span_x + span_width
    if right <= 0.49:
        return "left"
    if span_x >= 0.51:
        return "right"
    return "bridge"


def reorder_ocr_page_columns(page: ClientOcrPage) -> ClientOcrPage:
    """Read substantial side-by-side sections column-first, without dropping OCR lines.

    Browser OCR commonly returns lines in top-to-bottom order across both
    columns. Reorder only when every nonblank text line has a matching position
    and a wide, unambiguous two-column band is bounded by center-crossing text.
    This deliberately leaves sparse tables and incomplete layout data alone.
    """
    lines = page.text.splitlines()
    nonblank = [line.strip() for line in lines if line.strip()]
    if len(nonblank) != len(page.spans) or Counter(nonblank) != Counter(span.text.strip() for span in page.spans):
        return page

    line_slots: dict[str, deque[int]] = defaultdict(deque)
    for index, line in enumerate(lines):
        if line.strip():
            line_slots[line.strip()].append(index)

    positioned = [
        (line_slots[span.text.strip()].popleft(), span)
        for span in page.spans
    ]
    bridges = sorted(
        span.box.y + span.box.height / 2
        for _, span in positioned
        if _column(span.box.x, span.box.width) == "bridge"
    )
    if not bridges:
        return page

    ordered_lines = lines.copy()
    ordered_spans: list[OcrSpan | None] = [None] * len(lines)
    for index, span in positioned:
        ordered_spans[index] = span

    changed = False
    column_boundaries: list[int] = []
    for upper, lower in zip(bridges, bridges[1:]):
        band = [
            (index, span)
            for index, span in positioned
            if upper < span.box.y + span.box.height / 2 < lower
            and _column(span.box.x, span.box.width) != "bridge"
        ]
        left = [(index, span) for index, span in band if _column(span.box.x, span.box.width) == "left"]
        right = [(index, span) for index, span in band if _column(span.box.x, span.box.width) == "right"]
        if min(len(left), len(right)) < 5:
            continue
        left_y = [span.box.y + span.box.height / 2 for _, span in left]
        right_y = [span.box.y + span.box.height / 2 for _, span in right]
        shared_height = min(max(left_y), max(right_y)) - max(min(left_y), min(right_y))
        if shared_height < 0.12:
            continue

        positions = sorted(index for index, _ in band)
        reading_order = sorted(left, key=lambda item: (item[1].box.y, item[1].box.x)) + sorted(
            right, key=lambda item: (item[1].box.y, item[1].box.x)
        )
        if positions == [index for index, _ in reading_order]:
            continue
        for target_index, (source_index, span) in zip(positions, reading_order):
            ordered_lines[target_index] = lines[source_index]
            ordered_spans[target_index] = span
        column_boundaries.append(positions[len(left)])
        changed = True

    if not changed:
        return page
    # Preserve the section boundary for free machine translation chunking.
    # A blank line does not alter any recognized text or positioned OCR span.
    for index in sorted(set(column_boundaries), reverse=True):
        if index > 0 and ordered_lines[index - 1].strip():
            ordered_lines.insert(index, "")
    return ClientOcrPage(text="\n".join(ordered_lines), spans=[span for span in ordered_spans if span is not None])


def format_ocr_layout(pages: list[ClientOcrPage]) -> str:
    """Give the semantic step OCR positions without sending photo pixels."""
    formatted: list[str] = []
    for page_number, page in enumerate(pages, start=1):
        if not page.spans:
            continue
        formatted.append(f"[Page {page_number}; x,y are centers on a 0-1000 page grid]")
        for span in page.spans:
            center_x = round((span.box.x + span.box.width / 2) * 1000)
            center_y = round((span.box.y + span.box.height / 2) * 1000)
            formatted.append(f"({center_x:03d},{center_y:03d}) {span.text}")
    return "\n".join(formatted)
