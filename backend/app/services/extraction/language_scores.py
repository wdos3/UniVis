from __future__ import annotations

import re
from collections import defaultdict, deque

from app.models import BoundingBox, ClientOcrPage, LabeledFact, NoticeData, OcrSpan, ReviewState, SourceFact, SourcePage


EXAM_NAME = re.compile(r"^(?:TOEIC(?:\s+Speaking)?|TOEFL(?:\s*\(?iBT\)?)?|TEPS|FLEX|OPIC|IELTS)$", re.IGNORECASE)
EXAM_MENTION = re.compile(r"\b(?:TOEIC|TOEFL|TEPS|FLEX|OPIC|IELTS)\b", re.IGNORECASE)
SCORE = re.compile(r"^((?:\d{1,4}(?:\.\d+)?|\d+[A-Z]|[A-Z]{1,3}\d+))\s*(?:점\s*)?이상$", re.IGNORECASE)
EXAM_SUFFIX = re.compile(r"^(?:\(?iBT\)?|Speaking)$", re.IGNORECASE)
EXAM_SCORE_CLAIM = re.compile(
    r"\b(?:TOEIC|TOEFL|TEPS|FLEX|OPIC|IELTS)\b.{0,36}?"
    r"(?:\b\d{1,4}(?:\.\d+)?\b|\b\d+[A-Z]\b|\b[A-Z]{1,3}\d+\b)",
    re.IGNORECASE,
)
ONE_OF_SCORES = re.compile(r"(?:중\s*하나\s*이상|중\s*1개\s*이상)")


class LanguageScoreError(ValueError):
    def __init__(self, corrections: list[dict[str, int | str]]) -> None:
        super().__init__(
            "The English-test table has unreadable or ambiguous test/score pairs. "
            "Correct the indicated test names and score thresholds together, or upload a clearer crop of the table."
        )
        self.corrections = corrections


def _center(span: OcrSpan) -> tuple[float, float]:
    return span.box.x + span.box.width / 2, span.box.y + span.box.height / 2


def _union_box(spans: list[OcrSpan]) -> BoundingBox:
    left = min(span.box.x for span in spans)
    top = min(span.box.y for span in spans)
    right = max(span.box.x + span.box.width for span in spans)
    bottom = max(span.box.y + span.box.height for span in spans)
    return BoundingBox(x=left, y=top, width=right - left, height=bottom - top)


def _score_pairs(
    page: ClientOcrPage, page_number: int = 1
) -> list[tuple[str, str, str, BoundingBox]]:
    if not any(token in page.text for token in ("어학", "영어")):
        return []
    headers = [span for span in page.spans if EXAM_NAME.fullmatch(span.text.strip())]
    scores = [span for span in page.spans if SCORE.fullmatch(span.text.strip())]
    if len(headers) < 2:
        return []
    pairs: list[tuple[str, str, str, BoundingBox]] = []
    paired_headers: set[int] = set()
    headers_by_label: dict[str, list[tuple[OcrSpan, str]]] = {}
    unresolved: list[OcrSpan] = []
    for score in scores:
        score_x, score_y = _center(score)
        candidates = [
            header
            for header in headers
            if (
                abs(_center(header)[0] - score_x) <= 0.025
                and 0 < score_y - _center(header)[1] <= 0.06
            )
            or (
                abs(_center(header)[1] - score_y)
                <= max(header.box.height, score.box.height) / 2
                and 0 < score_x - _center(header)[0] <= 0.6
            )
        ]
        if len(candidates) != 1 or id(candidates[0]) in paired_headers:
            # Only flag nearby table values; unrelated thresholds elsewhere on
            # the page must not prevent a well-formed language table.
            if any(abs(_center(header)[1] - score_y) <= 0.06 for header in headers):
                unresolved.append(score)
            continue
        header = candidates[0]
        paired_headers.add(id(header))
        header_y = _center(header)[1]
        suffixes = [
            span for span in page.spans
            if EXAM_SUFFIX.fullmatch(span.text.strip())
            and abs(_center(span)[0] - score_x) <= 0.025
            and header_y < _center(span)[1] < score_y
        ]
        suffixes.sort(key=lambda span: _center(span)[1])
        unknown_suffixes = [
            span for span in page.spans
            if span not in suffixes
            and re.fullmatch(r"[A-Za-z0-9() -]{2,18}", span.text.strip())
            and re.search(r"[A-Za-z]", span.text)
            and abs(_center(span)[0] - score_x) <= 0.025
            and header_y < _center(span)[1] < score_y
        ]
        unresolved.extend(unknown_suffixes)
        fragments = [header, *suffixes, score]
        label = " ".join(span.text.strip() for span in fragments[:-1])
        threshold = SCORE.fullmatch(score.text.strip())
        assert threshold is not None
        label_key = re.sub(r"[\s()]", "", label).casefold()
        headers_by_label.setdefault(label_key, []).append((header, threshold.group(1)))
        pairs.append((label, threshold.group(1), "\n".join(span.text.strip() for span in fragments), _union_box(fragments)))

    unresolved.extend(header for header in headers if id(header) not in paired_headers)
    # A missing Speaking subtitle would turn two distinct TOEIC exams into
    # conflicting thresholds for the same test. Do not infer the missing name.
    for repeated in headers_by_label.values():
        if len({threshold for _, threshold in repeated}) > 1:
            unresolved.extend(header for header, _ in repeated)
    if unresolved:
        line_slots: dict[str, deque[int]] = defaultdict(deque)
        for index, line in enumerate(page.text.splitlines(), start=1):
            line_slots[line.strip()].append(index)
        line_numbers = {
            id(span): line_slots[span.text.strip()].popleft()
            for span in page.spans if line_slots[span.text.strip()]
        }
        corrections = [
            {
                "page": page_number,
                "line": line_numbers.get(id(span), 1),
                "text": span.text.strip(),
                "reason": "Confirm this test name together with its score threshold; OCR positions do not establish a unique pair.",
            }
            for span in {id(span): span for span in unresolved}.values()
        ]
        raise LanguageScoreError(corrections)
    return pairs


def validate_aligned_language_scores(ocr_pages: list[ClientOcrPage]) -> None:
    """Reject an incomplete positioned score table before paid semantic calls."""
    for page_number, page in enumerate(ocr_pages, start=1):
        _score_pairs(page, page_number)


def _model_score_claim(text: str) -> bool:
    return bool(EXAM_SCORE_CLAIM.search(text))


def _without_model_score_claims(text: str) -> str:
    if not _model_score_claim(text):
        return text
    clauses = re.split(
        r"(?<=[.!?])\s+|;\s*|,\s*(?:but|and)\s+", text, flags=re.IGNORECASE
    )
    return " ".join(
        clause for clause in clauses if not _model_score_claim(clause)
    ).strip()


def _remove_model_score_claims(notice: NoticeData) -> None:
    # The model sees OCR text in reading order, which is not reliable for table columns.
    for field in (
        "audience",
        "eligibility",
        "exceptions",
        "warnings",
        "consequences",
        "locations",
        "fees",
        "financial_support",
        "links",
        "key_details",
    ):
        retained = []
        for item in getattr(notice, field):
            text = _without_model_score_claims(item.text)
            if text:
                item.text = text
                retained.append(item)
        setattr(notice, field, retained)
    for field in ("purpose", "summary"):
        value = getattr(notice, field)
        if _model_score_claim(value):
            setattr(
                notice,
                field,
                _without_model_score_claims(value)
                or "Check the English-test score requirements against the original notice.",
            )


def mark_unverified_language_scores(notice: NoticeData, source_text: str = "") -> None:
    """A text-only reprocess has no trustworthy column alignment for score pairs."""
    score_claims = [
        item for field in ("audience", "eligibility", "exceptions", "warnings", "consequences", "locations", "fees", "financial_support", "links", "key_details")
        for item in getattr(notice, field) if _model_score_claim(item.text)
    ]
    for item in score_claims:
        item.state = ReviewState.NEEDS_REVIEW
    source_has_scores = bool(EXAM_MENTION.search(source_text) and ("이상" in source_text or "score" in source_text.lower()))
    if score_claims or source_has_scores or any(_model_score_claim(getattr(notice, field)) for field in ("summary", "purpose")):
        notice.unverified_items.append(
            "English-test score pairs could not be checked against OCR positions; verify them against the official notice."
        )


def add_aligned_language_scores(notice: NoticeData, ocr_pages: list[ClientOcrPage], source_pages: list[SourcePage]) -> int:
    """Replace model-guessed exam thresholds with OCR column-aligned values."""
    found: list[tuple[int, str, str, str, BoundingBox]] = []
    for page_number, page in enumerate(ocr_pages, start=1):
        found.extend((page_number, *pair) for pair in _score_pairs(page, page_number))
    if not found:
        mark_unverified_language_scores(notice, "\n".join(page.text for page in ocr_pages))
        return 0

    _remove_model_score_claims(notice)

    next_id = max((int(fact.id[1:]) for fact in notice.source_facts), default=0) + 1
    # Preserve the source's OR condition, not six simultaneous requirements.
    one_of = next(
        ((page_number, line.strip(), page) for page_number, page in enumerate(ocr_pages, start=1)
         for line in page.text.splitlines() if ONE_OF_SCORES.search(line)),
        None,
    )
    if one_of and not any("at least one" in item.text.lower() for item in notice.eligibility):
        page_number, line, page = one_of
        fact_id = f"F{next_id:03d}"
        next_id += 1
        box = next((span.box for span in page.spans if span.text.strip() == line), None)
        source_image_id = source_pages[page_number - 1].id
        notice.source_facts.append(SourceFact(
            id=fact_id, kind="language_score_choice", source_text=line, critical=True,
            state=ReviewState.NEEDS_REVIEW, source_page=page_number,
            source_image_id=source_image_id, bounding_box=box,
        ))
        notice.eligibility.append(LabeledFact(
            text="Meet at least one of the following English-test score thresholds.",
            label="English language qualification", source_evidence=line,
            source_fact_ids=[fact_id], state=ReviewState.NEEDS_REVIEW,
            source_page=page_number, source_image_id=source_image_id, bounding_box=box,
        ))

    for page_number, label, threshold, evidence, box in found:
        fact_id = f"F{next_id:03d}"
        next_id += 1
        source_image_id = source_pages[page_number - 1].id
        notice.source_facts.append(SourceFact(
            id=fact_id, kind="language_score", source_text=evidence, critical=True,
            state=ReviewState.NEEDS_REVIEW, source_page=page_number,
            source_image_id=source_image_id, bounding_box=box,
        ))
        notice.eligibility.append(LabeledFact(
            text=f"{label}: {threshold} or higher", label="English test score",
            source_evidence=evidence, source_fact_ids=[fact_id], state=ReviewState.NEEDS_REVIEW,
            source_page=page_number, source_image_id=source_image_id, bounding_box=box,
        ))
    notice.unverified_items.append(
        "English-test score pairs were reconstructed from OCR column alignment; verify them against the official notice."
    )
    return len(found)
