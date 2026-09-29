from __future__ import annotations

from app.models import BoundingBox, ClientOcrPage, LabeledFact, NoticeData, OcrSpan, ReviewState, SourcePage
from app.services.extraction.language_scores import add_aligned_language_scores, mark_unverified_language_scores


def span(text: str, center_x: float, center_y: float) -> OcrSpan:
    return OcrSpan(
        text=text,
        box=BoundingBox(x=center_x - 0.01, y=center_y - 0.005, width=0.02, height=0.01),
    )


def source_page() -> SourcePage:
    return SourcePage(
        id="poster-page-1", page_number=1, filename="Page 1", media_type="application/octet-stream",
        original_url="", processed_url="", width=1, height=1,
    )


def test_replaces_mispaired_model_scores_with_aligned_ocr_columns() -> None:
    spans = [
        span("·아래 공인어학성적(영어)중 하나 이상 취득한 자", 0.70, 0.53),
        span("TOEFL", 0.78, 0.555), span("TOEIC", 0.86, 0.555),
        span("TOEIC", 0.55, 0.56), span("TEPS", 0.63, 0.56),
        span("FLEX", 0.70, 0.56), span("OPIC", 0.94, 0.56),
        span("(iBT)", 0.78, 0.565), span("Speaking", 0.86, 0.565),
        span("800 이상", 0.55, 0.585), span("309 이상", 0.63, 0.585),
        span("2B 이상", 0.70, 0.585), span("91 이상", 0.78, 0.585),
        span("150이상", 0.86, 0.585), span("IM3 이상", 0.94, 0.585),
    ]
    page = ClientOcrPage(text="\n".join(item.text for item in spans), spans=spans)
    notice = NoticeData(eligibility=[
        LabeledFact(text="TOEFL iBT 800 or above"),
    ], key_details=[LabeledFact(text="TOEIC score of 900 is needed")],
        summary="Applicants need TOEFL iBT 800, but can work in Seoul.")

    count = add_aligned_language_scores(notice, [page], [source_page()])

    assert count == 6
    assert [item.text for item in notice.eligibility] == [
        "Meet at least one of the following English-test score thresholds.",
        "TOEIC: 800 or higher",
        "TEPS: 309 or higher",
        "FLEX: 2B or higher",
        "TOEFL (iBT): 91 or higher",
        "TOEIC Speaking: 150 or higher",
        "OPIC: IM3 or higher",
    ]
    assert all(item.state == ReviewState.NEEDS_REVIEW for item in notice.eligibility[1:])
    assert notice.key_details == []
    assert "800" not in notice.summary
    assert all(item.source_image_id == "poster-page-1" for item in notice.eligibility[1:])
    assert all(item.bounding_box is not None for item in notice.eligibility[1:])


def test_unaligned_score_claim_is_flagged_instead_of_confirmed() -> None:
    notice = NoticeData(eligibility=[LabeledFact(text="TOEFL iBT 800 or above")])
    page = ClientOcrPage(text="TOEFL\n800 이상")

    assert add_aligned_language_scores(notice, [page], [source_page()]) == 0
    assert notice.eligibility[0].state == ReviewState.NEEDS_REVIEW
    assert "could not be checked" in notice.unverified_items[0]


def test_text_only_reprocess_marks_score_claims_for_review() -> None:
    notice = NoticeData(eligibility=[LabeledFact(text="TOEIC score of 900 is needed")])

    mark_unverified_language_scores(notice)

    assert notice.eligibility[0].state == ReviewState.NEEDS_REVIEW
    assert "could not be checked" in notice.unverified_items[0]


def test_text_only_reprocess_warns_when_model_omits_ocr_scores() -> None:
    notice = NoticeData()

    mark_unverified_language_scores(notice, "TOEIC\n800 이상\nTEPS\n309 이상")

    assert "could not be checked" in notice.unverified_items[0]
