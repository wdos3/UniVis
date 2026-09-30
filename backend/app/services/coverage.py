from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

from app.models import GroundedItem, NoticeData


PAGE_MARKER = re.compile(r"^\[Page (\d+)\]$")


@dataclass(frozen=True)
class CoverageUnit:
    id: str
    page: int
    text: str
    line: int = 0


@dataclass(frozen=True)
class CoverageAudit:
    units: list[CoverageUnit]
    uncovered: list[CoverageUnit]
    covered_count: int
    cited_english_by_unit: dict[str, list[str]]

    @property
    def total_count(self) -> int:
        return len(self.units)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text)).casefold()


def _source_units(source_text: str) -> list[CoverageUnit]:
    units: list[CoverageUnit] = []
    seen_by_page: dict[int, set[str]] = {}
    page = 1
    line_number = 0
    for raw_line in source_text.splitlines():
        line = raw_line.strip()
        marker = PAGE_MARKER.fullmatch(line)
        if marker:
            page = int(marker.group(1))
            line_number = 0
            continue
        line_number += 1
        # OCR often emits isolated bullets/arrows/borders. They carry no
        # standalone notice fact; keep every line with a letter or number.
        if not line or not any(character.isalnum() for character in line):
            continue
        normalized = _normalize(line)
        seen = seen_by_page.setdefault(page, set())
        if normalized in seen:
            continue
        seen.add(normalized)
        units.append(CoverageUnit(id=f"P{page:03d}-L{len(seen):04d}", page=page, text=line, line=line_number))
    return units


def _grounded_items(notice: NoticeData) -> list[GroundedItem]:
    return [
        *notice.audience,
        *notice.actions,
        *notice.deadlines,
        *notice.required_documents,
        *notice.eligibility,
        *notice.exceptions,
        *notice.warnings,
        *notice.consequences,
        *notice.locations,
        *notice.contacts,
        *notice.fees,
        *notice.financial_support,
        *notice.links,
        *notice.key_details,
        *notice.conditional_groups,
    ]


def _quotes_unit(unit_text: str, evidence_text: str) -> bool:
    evidence_lines = {_normalize(line) for line in evidence_text.splitlines() if line.strip()}
    if unit_text in evidence_lines:
        return True
    # A short OCR fragment such as "9" or "지원" appearing inside another line
    # is not reliable evidence that the fragment itself was represented.
    return len(unit_text) >= 8 and unit_text in _normalize(evidence_text)


def display_text(item: GroundedItem) -> str:
    # Labels are omitted from most simplified-text entries, so they cannot
    # certify that a Korean fact reached the English digest.
    displayed_fields = (
        "text", "action", "details", "deadline", "location", "required_items",
        "date", "time", "description", "name", "condition", "phone", "email",
        "group", "application_period",
    )
    values: list[str] = []
    for field in displayed_fields:
        value = getattr(item, field, None)
        if isinstance(value, str) and value.strip():
            values.append(value.strip())
        elif isinstance(value, list):
            values.extend(part.strip() for part in value if isinstance(part, str) and part.strip())
    return " | ".join(values)


def audit_coverage(notice: NoticeData, source_text: str) -> CoverageAudit:
    """Audit OCR citations independently of the model's self-reported source facts.

    A source line is covered only when a displayed, grounded item quotes that
    entire line. Quoting just part of a line must not certify the rest of it.
    This checks citation coverage, not the semantic accuracy of the English item.
    """
    units = _source_units(source_text)
    occurrence_count = Counter(_normalize(unit.text) for unit in units)
    evidence = [
        (item.source_evidence, item.source_page, display)
        for item in _grounded_items(notice)
        if item.source_evidence.strip() and (display := display_text(item))
    ]
    cited_english_by_unit: dict[str, list[str]] = {}
    uncovered: list[CoverageUnit] = []
    for unit in units:
        citations = [
            display
            for quote, source_page, display in evidence
            if _quotes_unit(_normalize(unit.text), quote)
            and (source_page == unit.page or (source_page is None and occurrence_count[_normalize(unit.text)] == 1))
        ]
        cited_english_by_unit[unit.id] = list(dict.fromkeys(citations))
        if not citations:
            uncovered.append(unit)
    return CoverageAudit(
        units=units,
        uncovered=uncovered,
        covered_count=len(units) - len(uncovered),
        cited_english_by_unit=cited_english_by_unit,
    )
