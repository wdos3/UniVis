from __future__ import annotations

import re

from app.models import NoticeData, ReviewState, SourceFact
from app.services.coverage_coalescing import LABELED_FIELDS
from app.services.extraction.reconciliation import PAGE_MARKER_PATTERN, evidence_matches_page


GROUNDED_FIELDS = (*LABELED_FIELDS, "actions", "deadlines", "required_documents", "contacts", "conditional_groups")


def retain_source_grounded_items(notice: NoticeData, source_text: str) -> NoticeData:
    """Reject invented citations before the independent, full-source audit.

    This does not discard OCR units or certify English meaning. The subsequent
    audit must recover every substantive source unit before publishing a digest.
    A correct repair must not leave an unsupported primary claim beside it.
    """
    grounded = notice.model_copy(deep=True)
    segments = PAGE_MARKER_PATTERN.split(source_text)
    pages = [segments[0], *segments[2::2]] if len(segments) > 1 else segments

    def exists(evidence: str) -> bool:
        return any(evidence_matches_page(evidence, page) for page in pages)

    next_id = max((int(fact.id[1:]) for fact in grounded.source_facts), default=0) + 1
    grounded.source_facts = [fact for fact in grounded.source_facts if exists(fact.source_text)]
    facts_by_id = {fact.id: fact for fact in grounded.source_facts}
    for field in GROUNDED_FIELDS:
        retained = []
        for item in getattr(grounded, field):
            if not exists(item.source_evidence):
                continue
            evidence = re.sub(r"\s+", "", item.source_evidence)
            related_ids = [
                fact_id for fact_id in item.source_fact_ids
                if (fact := facts_by_id.get(fact_id)) is not None
                and (
                    re.sub(r"\s+", "", fact.source_text) in evidence
                    or evidence in re.sub(r"\s+", "", fact.source_text)
                )
            ]
            if related_ids != item.source_fact_ids:
                item.state = ReviewState.NEEDS_REVIEW
            if not related_ids:
                fact = SourceFact(
                    id=f"F{next_id:03d}", kind="source_grounded_evidence",
                    source_text=item.source_evidence, source_page=item.source_page,
                    state=ReviewState.NEEDS_REVIEW,
                )
                next_id += 1
                grounded.source_facts.append(fact)
                facts_by_id[fact.id] = fact
                related_ids = [fact.id]
                item.state = ReviewState.NEEDS_REVIEW
            item.source_fact_ids = list(dict.fromkeys(related_ids))
            retained.append(item)
        setattr(grounded, field, retained)
    for step, action in enumerate(grounded.actions, start=1):
        action.step = step
    return grounded
