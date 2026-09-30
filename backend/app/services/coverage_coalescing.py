from __future__ import annotations

import re
import unicodedata

from app.models import LabeledFact, NoticeData, ReviewState


LABELED_FIELDS = (
    "audience", "eligibility", "exceptions", "warnings", "consequences",
    "locations", "fees", "financial_support", "links", "key_details",
)


def _english_key(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip().casefold()


def _combined_evidence(first: str, second: str) -> str:
    lines: list[str] = []
    seen: set[str] = set()
    for line in (*first.splitlines(), *second.splitlines()):
        clean = line.strip()
        key = re.sub(r"\s+", "", unicodedata.normalize("NFKC", clean)).casefold()
        if clean and key not in seen:
            lines.append(clean)
            seen.add(key)
    return "\n".join(lines)


def _merge_evidence(kept: LabeledFact, duplicate: LabeledFact) -> None:
    kept.source_evidence = _combined_evidence(kept.source_evidence, duplicate.source_evidence)
    kept.source_fact_ids = list(dict.fromkeys([*kept.source_fact_ids, *duplicate.source_fact_ids]))
    if kept.state != ReviewState.VERIFIED or duplicate.state != ReviewState.VERIFIED:
        kept.state = ReviewState.NEEDS_REVIEW
    if kept.source_image_id != duplicate.source_image_id:
        kept.source_image_id = None
    # One rectangle cannot accurately highlight several independently cited lines.
    kept.bounding_box = None


def coalesce_exact_repair_duplicates(notice: NoticeData) -> NoticeData:
    """Fold exact audit-added repetitions into primary facts on the same page.

    Primary facts remain in their original sections. Exact primary repeats
    within one section are merged only when they quote the same source text.
    Paraphrases remain separate because similar wording can differ in meaning.
    """
    merged = notice.model_copy(deep=True)
    repair_ids = {
        fact.id for fact in merged.source_facts
        if fact.kind.startswith("coverage_repair_")
    }
    primary_by_key: dict[tuple[int, str], LabeledFact] = {}
    primary_by_evidence: dict[tuple[int, str, str, str], LabeledFact] = {}
    repair_by_key: dict[tuple[int, str, str], LabeledFact] = {}
    discarded: set[int] = set()

    for field in LABELED_FIELDS:
        for item in getattr(merged, field):
            if item.source_page is None or not item.source_fact_ids:
                continue
            if set(item.source_fact_ids) <= repair_ids:
                continue
            if item.source_evidence.strip():
                evidence_key = re.sub(r"\s+", "", unicodedata.normalize("NFKC", item.source_evidence)).casefold()
                exact_key = (item.source_page, field, _english_key(item.text), evidence_key)
                existing = primary_by_evidence.get(exact_key)
                if existing is not None:
                    _merge_evidence(existing, item)
                    discarded.add(id(item))
                    continue
                primary_by_evidence[exact_key] = item
            primary_by_key.setdefault((item.source_page, _english_key(item.text)), item)

    for field in LABELED_FIELDS:
        for item in getattr(merged, field):
            if item.source_page is None or not item.source_fact_ids or not set(item.source_fact_ids) <= repair_ids:
                continue
            key = (item.source_page, _english_key(item.text))
            kept = primary_by_key.get(key) or repair_by_key.get((*key, field))
            if kept is None:
                repair_by_key[(*key, field)] = item
                continue
            _merge_evidence(kept, item)
            discarded.add(id(item))

    for field in LABELED_FIELDS:
        setattr(merged, field, [item for item in getattr(merged, field) if id(item) not in discarded])
    return merged
