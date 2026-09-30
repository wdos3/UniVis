from __future__ import annotations

import pytest

from app.models import BoundingBox, ClientOcrPage, LabeledFact, NoticeData, OcrSpan, ReviewState, SourcePage
from app.services.extraction.language_scores import (
    LanguageScoreError,
    add_aligned_language_scores,
    mark_unverified_language_scores,
    validate_aligned_language_scores,
)


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
    assert "can work in Seoul" in notice.summary
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


def test_incomplete_table_requires_correction_without_mutating_the_notice() -> None:
    spans = [
        span("영어 성적", 0.5, 0.1),
        span("TOEIC", 0.3, 0.2),
        span("TEPS", 0.6, 0.2),
        span("800 이상", 0.3, 0.23),
    ]
    page = ClientOcrPage(text="\n".join(item.text for item in spans), spans=spans)
    notice = NoticeData(eligibility=[LabeledFact(text="TEPS 309 or higher")])
    original = notice.model_copy(deep=True)

    with pytest.raises(LanguageScoreError) as failure:
        add_aligned_language_scores(notice, [page], [source_page()])

    assert notice == original
    assert failure.value.corrections == [
        {
            "page": 1,
            "line": 3,
            "text": "TEPS",
            "reason": "Confirm this test name together with its score threshold; OCR positions do not establish a unique pair.",
        }
    ]


def test_score_cannot_be_reused_for_two_ambiguous_headers() -> None:
    spans = [
        span("영어 성적", 0.5, 0.1),
        span("TOEIC", 0.3, 0.2),
        span("TEPS", 0.32, 0.2),
        span("800 이상", 0.31, 0.23),
    ]
    page = ClientOcrPage(text="\n".join(item.text for item in spans), spans=spans)

    with pytest.raises(LanguageScoreError, match="test/score pairs"):
        validate_aligned_language_scores([page])


def test_row_table_scores_and_unrelated_mixed_details_are_preserved() -> None:
    spans = [
        span("영어 성적", 0.5, 0.1),
        span("TOEIC", 0.3, 0.2),
        span("800점 이상", 0.6, 0.2),
        span("TEPS", 0.3, 0.25),
        span("309 이상", 0.6, 0.25),
    ]
    page = ClientOcrPage(text="\n".join(item.text for item in spans), spans=spans)
    notice = NoticeData(
        key_details=[
            LabeledFact(
                text="TOEIC 999 is needed; Submit the application by September 20."
            )
        ]
    )

    assert add_aligned_language_scores(notice, [page], [source_page()]) == 2

    assert [item.text for item in notice.eligibility] == [
        "TOEIC: 800 or higher",
        "TEPS: 309 or higher",
    ]
    assert notice.key_details[0].text == "Submit the application by September 20."


def test_two_score_values_for_one_header_require_correction() -> None:
    spans = [
        span("영어 성적", 0.5, 0.1),
        span("TOEIC", 0.3, 0.2),
        span("TEPS", 0.6, 0.2),
        span("800 이상", 0.3, 0.23),
        span("900 이상", 0.3, 0.24),
        span("309 이상", 0.6, 0.23),
    ]
    page = ClientOcrPage(text="\n".join(item.text for item in spans), spans=spans)

    with pytest.raises(LanguageScoreError) as failure:
        validate_aligned_language_scores([page])

    assert [item["line"] for item in failure.value.corrections] == [5]


@pytest.mark.parametrize("subtitle", ["Speakin9", "i8T"])
def test_unreadable_test_subtitle_requires_exact_correction(subtitle: str) -> None:
    spans = [
        span("영어 성적", 0.5, 0.1),
        span("TOEIC", 0.3, 0.2), span("TOEFL", 0.6, 0.2),
        span(subtitle, 0.6, 0.21),
        span("800 이상", 0.3, 0.23), span("91 이상", 0.6, 0.23),
    ]
    page = ClientOcrPage(text="\n".join(item.text for item in spans), spans=spans)

    with pytest.raises(LanguageScoreError) as failure:
        validate_aligned_language_scores([page])

    assert any(item["text"] == subtitle and item["line"] == 4 for item in failure.value.corrections)


def test_missing_speaking_subtitle_cannot_create_two_conflicting_toeic_scores() -> None:
    spans = [
        span("영어 성적", 0.5, 0.1),
        span("TOEIC", 0.3, 0.2), span("TOEIC", 0.6, 0.2),
        span("800 이상", 0.3, 0.23), span("150 이상", 0.6, 0.23),
    ]
    page = ClientOcrPage(text="\n".join(item.text for item in spans), spans=spans)

    with pytest.raises(LanguageScoreError) as failure:
        validate_aligned_language_scores([page])

    assert [item["line"] for item in failure.value.corrections] == [2, 3]


def test_one_digit_decimal_model_score_is_replaced_by_aligned_threshold() -> None:
    spans = [
        span("영어 성적", 0.5, 0.1),
        span("TOEIC", 0.3, 0.2), span("IELTS", 0.6, 0.2),
        span("800 이상", 0.3, 0.23), span("7.5 이상", 0.6, 0.23),
    ]
    page = ClientOcrPage(text="\n".join(item.text for item in spans), spans=spans)
    notice = NoticeData(eligibility=[LabeledFact(text="IELTS 8.0 or higher")])

    assert add_aligned_language_scores(notice, [page], [source_page()]) == 2

    assert [item.text for item in notice.eligibility] == ["TOEIC: 800 or higher", "IELTS: 7.5 or higher"]
    assert all("8.0" not in item.text for item in notice.eligibility)
