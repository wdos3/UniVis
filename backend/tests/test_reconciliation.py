from __future__ import annotations

import pytest

from app.models import Action, BoundingBox, NoticeData, ReviewState, SourceFact, SourcePage
from app.services.extraction.reconciliation import add_page_provenance, split_recovered_pages


def source_page(number: int) -> SourcePage:
    return SourcePage(
        id=f"page-{number}",
        page_number=number,
        filename=f"Page {number}",
        media_type="application/octet-stream",
        original_url="",
        processed_url="",
        width=1,
        height=1,
    )


def test_recovered_pages_preserve_empty_and_explicit_page_numbers() -> None:
    assert split_recovered_pages("[Page 3]\ngamma\n\n[Page 1]\nalpha\n\n[Page 2]\n", 3) == ["alpha", "", "gamma"]
    assert split_recovered_pages("[Page 1]\nalpha\n\n[Page 3]\ngamma", 3) == ["alpha", "", "gamma"]


@pytest.mark.parametrize(
    "text",
    [
        "alpha",  # multi-page text without page headings has unknown provenance
        "[Page 1]\nalpha\n[Page 1]\nbeta",
        "[Page 3]\nalpha",
        "unlabeled preamble\n[Page 1]\nalpha",
        "[Page 1]\n[Page 2]\n",
    ],
)
def test_recovered_pages_reject_ambiguous_page_mapping(text: str) -> None:
    with pytest.raises(ValueError):
        split_recovered_pages(text, 2)


def test_page_provenance_corrects_model_page_and_discards_stale_highlight() -> None:
    notice = NoticeData(
        actions=[Action(
            step=1,
            action="Submit the form",
            source_evidence="신청서를 제출하십시오",
            source_page=1,
            source_image_id="page-1",
            bounding_box=BoundingBox(x=0.1, y=0.1, width=0.2, height=0.2),
        )],
        source_facts=[SourceFact(id="F001", kind="action", source_text="신청서를 제출하십시오", source_page=1)],
    )

    add_page_provenance(notice, ["첫째 페이지", "신청서를 제출하십시오"], [source_page(1), source_page(2)])

    assert notice.actions[0].source_page == 2
    assert notice.actions[0].source_image_id == "page-2"
    assert notice.actions[0].bounding_box is None
    assert notice.actions[0].state == ReviewState.VERIFIED
    assert notice.source_facts[0].source_page == 2


def test_page_provenance_marks_unmatched_and_repeated_evidence_for_review() -> None:
    notice = NoticeData(
        actions=[
            Action(step=1, action="Do one", source_evidence="반복 문구", source_page=1, source_image_id="page-1"),
            Action(step=2, action="Do two", source_evidence="없는 문구", source_page=2, source_image_id="page-2"),
        ],
        source_facts=[SourceFact(id="F001", kind="action", source_text="반복 문구", source_page=1)],
    )

    add_page_provenance(notice, ["반복 문구", "반복 문구"], [source_page(1), source_page(2)])

    for item in [*notice.actions, *notice.source_facts]:
        assert item.source_page is None
        assert item.source_image_id is None
        assert item.state == ReviewState.NEEDS_REVIEW
    assert len(notice.unverified_items) == 1
