from __future__ import annotations

import json
from types import SimpleNamespace

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


@pytest.mark.parametrize("layout", ["rows", "columns"])
@pytest.mark.parametrize("rating", ["IH", "AL"])
def test_letter_only_opic_rating_keeps_its_test_pair_for_different_layouts(layout: str, rating: str) -> None:
    if layout == "rows":
        table_spans = [
            span("TOEIC", 0.3, 0.2), span("810 이상", 0.6, 0.2),
            span("OPIc", 0.3, 0.28), span(f"{rating} 이상", 0.6, 0.28),
        ]
    else:
        table_spans = [
            span("TOEIC", 0.3, 0.2), span("OPIc", 0.6, 0.2),
            span("810 이상", 0.3, 0.23), span(f"{rating} 이상", 0.6, 0.23),
        ]
    spans = [span("영어 성적", 0.5, 0.1), *table_spans]
    page = ClientOcrPage(text="\n".join(item.text for item in spans), spans=spans)
    notice = NoticeData(
        eligibility=[LabeledFact(text="OPIc: IL or higher")],
        summary="OPIc score of IL or higher is required; Bring your student ID.",
    )


    validate_aligned_language_scores([page])
    assert add_aligned_language_scores(notice, [page], [source_page()]) == 2

    assert [item.text for item in notice.eligibility] == [
        "TOEIC: 810 or higher", f"OPIc: {rating} or higher",
    ]
    opic = notice.eligibility[1]
    assert opic.source_evidence == f"OPIc\n{rating} 이상"
    assert opic.source_page == 1
    assert opic.source_fact_ids and opic.bounding_box is not None
    assert opic.state == ReviewState.NEEDS_REVIEW
    assert "IL" not in notice.summary
    assert notice.summary == "Bring your student ID."


@pytest.mark.parametrize("invalid", ["AI 이상", "ALPHA 이상", "AL 이상 취득", "I H 이상"])
def test_prose_and_damaged_letters_cannot_be_used_as_opic_rating(invalid: str) -> None:
    spans = [
        span("영어 성적", 0.5, 0.1),
        span("TOEIC", 0.3, 0.2), span("OPIc", 0.6, 0.2),
        span("810 이상", 0.3, 0.23), span(invalid, 0.6, 0.23),
    ]
    page = ClientOcrPage(text="\n".join(item.text for item in spans), spans=spans)
    notice = NoticeData(eligibility=[LabeledFact(text="OPIc AL or higher")])
    original = notice.model_copy(deep=True)

    with pytest.raises(LanguageScoreError) as failure:
        add_aligned_language_scores(notice, [page], [source_page()])

    assert notice == original
    assert any(item["text"] == "OPIc" for item in failure.value.corrections)


@pytest.mark.parametrize("claim", [
    "OPIc rating IH or higher is required", "OPIc grade must be AL", "OPIc level is IH or above",
])
def test_text_only_letter_rating_claim_needs_review(claim: str) -> None:
    notice = NoticeData(eligibility=[LabeledFact(text=claim)])

    mark_unverified_language_scores(notice)

    assert notice.eligibility[0].state == ReviewState.NEEDS_REVIEW
    assert "could not be checked" in notice.unverified_items[0]


def test_unrelated_prose_is_retained_when_letter_scores_are_reconstructed() -> None:
    spans = [
        span("영어 성적", 0.5, 0.1),
        span("TOEIC", 0.3, 0.2), span("OPIc", 0.6, 0.2),
        span("810 이상", 0.3, 0.23), span("AL 이상", 0.6, 0.23),
    ]
    page = ClientOcrPage(text="\n".join(item.text for item in spans), spans=spans)
    prose = "OPIc applicants may submit a portfolio."
    notice = NoticeData(key_details=[LabeledFact(text=prose)])

    assert add_aligned_language_scores(notice, [page], [source_page()]) == 2

    assert notice.key_details[0].text == prose


def test_document_choice_does_not_create_an_or_qualification_for_score_table() -> None:
    tokens = [span("영어 시험 기준", 0.5, 0.5), span("TOEIC", 0.4, 0.55),
              span("TEPS", 0.7, 0.55), span("800 이상", 0.4, 0.58), span("309 이상", 0.7, 0.58)]
    page = ClientOcrPage(text="제출 서류 중 하나 이상\n" + "\n".join(item.text for item in tokens), spans=tokens)
    notice = NoticeData()
    assert add_aligned_language_scores(notice, [page], [source_page()]) == 2
    assert not any("at least one" in item.text for item in notice.eligibility)


def test_captured_browser_crop_duplicates_keep_all_six_score_pairs() -> None:
    # These cells reproduce the KCCI photo request's page-relative positions.
    cells = [
        ("TOEFL", 0.756969, 0.550000, 0.045296, 0.009804),
        ("TOEIC", 0.834930, 0.550000, 0.041812, 0.009559),
        ("TOEIC", 0.529181, 0.554902, 0.041376, 0.010049),
        ("TEPS", 0.607143, 0.555637, 0.037456, 0.009314),
        ("FLEX", 0.683362, 0.554902, 0.037892, 0.010049),
        ("OPIC", 0.915505, 0.554412, 0.040070, 0.011765),
        ("(iBT)", 0.761324, 0.559804, 0.037892, 0.011520),
        ("Speaking", 0.820993, 0.559314, 0.072300, 0.012745),
        ("800 이상", 0.520470, 0.578431, 0.059669, 0.010784),
        ("309 이상", 0.596254, 0.578676, 0.060105, 0.010784),
        ("2B 이상", 0.676394, 0.578676, 0.052700, 0.011029),
        ("91 이상", 0.755226, 0.578922, 0.049652, 0.011029),
        ("150이상", 0.829268, 0.579412, 0.058362, 0.010294),
        ("IM3 이상", 0.907666, 0.580147, 0.058798, 0.009559),
        ("OPIc", 0.917247, 0.554902, 0.037456, 0.010784),
        ("150 이상", 0.828833, 0.579167, 0.058798, 0.011029),
    ]
    spans = [
        OcrSpan(text=text, box=BoundingBox(x=x, y=y, width=width, height=height))
        for text, x, y, width, height in cells
    ]
    page = ClientOcrPage(text="영어 성적\n" + "\n".join(item.text for item in spans), spans=spans)
    notice = NoticeData()

    validate_aligned_language_scores([page])
    assert add_aligned_language_scores(notice, [page], [source_page()]) == 6

    assert [item.text for item in notice.eligibility] == [
        "TOEIC: 800 or higher", "TEPS: 309 or higher", "FLEX: 2B or higher",
        "TOEFL (iBT): 91 or higher", "TOEIC Speaking: 150 or higher", "OPIC: IM3 or higher",
    ]
    assert notice.eligibility[-2].source_evidence == "TOEIC\nSpeaking\n150이상"


@pytest.mark.parametrize("layout", ["rows", "columns"])
def test_equivalent_crop_observations_do_not_duplicate_other_score_tables(layout: str) -> None:
    if layout == "rows":
        cells = [span("IELTS", 0.3, 0.2), span("7.5 이상", 0.6, 0.2),
                 span("OPIc", 0.3, 0.3), span("IH 이상", 0.6, 0.3)]
    else:
        cells = [span("IELTS", 0.3, 0.2), span("OPIc", 0.6, 0.2),
                 span("7.5 이상", 0.3, 0.23), span("IH 이상", 0.6, 0.23)]
    duplicated = [item.model_copy(deep=True) for item in cells]
    for item in duplicated:
        item.text = item.text.swapcase().replace(" ", "")
        item.box.x += 0.001
        item.box.y += 0.0005
    spans = [*cells, *duplicated]
    page = ClientOcrPage(text="영어 성적\n" + "\n".join(item.text for item in spans), spans=spans)
    notice = NoticeData()

    assert add_aligned_language_scores(notice, [page], [source_page()]) == 2
    assert [item.text for item in notice.eligibility] == ["IELTS: 7.5 or higher", "OPIc: IH or higher"]


def test_conflicting_crop_score_values_at_the_same_position_remain_unverified() -> None:
    spans = [span("TOEIC", 0.3, 0.2), span("OPIc", 0.6, 0.2),
             span("820 이상", 0.3, 0.23), span("IH 이상", 0.6, 0.23),
             span("AL 이상", 0.6, 0.23)]
    page = ClientOcrPage(text="영어 성적\n" + "\n".join(item.text for item in spans), spans=spans)

    with pytest.raises(LanguageScoreError) as failure:
        validate_aligned_language_scores([page])

    assert any(item["text"] == "AL 이상" for item in failure.value.corrections)


@pytest.mark.parametrize("conflicting_geometry", [False, True])
@pytest.mark.parametrize("applicability", ["unresolved", "not_applicable"])
def test_photo_keeps_independent_table_pairs_after_an_unresolved_semantic_audit(
    client, monkeypatch, conflicting_geometry: bool, applicability: str,
) -> None:
    from app import main
    from app.services.coverage_repair import RepairResponse, repair_coverage
    from app.services.english_review import EnglishNoticeReview
    from app.services.pipeline import PipelineResult

    spans = [
        span("아래 공인어학성적(영어)중 하나 이상 취득한 자", 0.70, 0.53),
        span("TOEIC", 0.55, 0.56), span("TEPS", 0.63, 0.56), span("FLEX", 0.70, 0.56),
        span("TOEFL", 0.78, 0.555), span("TOEIC", 0.86, 0.555), span("OPIc", 0.94, 0.56),
        span("(iBT)", 0.78, 0.565), span("Speaking", 0.86, 0.565),
        span("810 이상", 0.55, 0.585), span("320 이상", 0.63, 0.585),
        span("2A 이상", 0.70, 0.585), span("95 이상", 0.78, 0.585),
        span("160 이상", 0.86, 0.585), span("IH 이상", 0.94, 0.585),
    ]
    if conflicting_geometry:
        spans.append(span("AL 이상", 0.94, 0.585))
    non_applicability = "이 영어 성적 표는 이번 채용에 적용되지 않음"
    if applicability == "not_applicable":
        spans.append(span(non_applicability, 0.70, 0.61))
    page = ClientOcrPage(text="\n".join(item.text for item in spans), spans=spans)

    async def extracted(request, **kwargs):
        return PipelineResult(
            source_text=request.text, translation="Language test qualifications.",
            notice=NoticeData(title="Language requirements", eligibility=[LabeledFact(text="TOEIC: 999 or higher")]),
            provider="test", translation_provider="test", semantic_provider="openai-semantic:test",
            translation_requests=1, semantic_requests=1, semantic_input_tokens=0,
            semantic_output_tokens=0, semantic_total_tokens=0,
        )

    class Responses:
        async def parse(self, **kwargs):
            payload = json.loads(kwargs["input"][1]["content"])
            return SimpleNamespace(output_parsed=RepairResponse(
                represented_unit_ids=[], details=[], decorative=[],
                unresolved_unit_ids=[unit["id"] for unit in payload["source_units"]],
                unsupported_english_ids=list(payload["english_fields"]),
            ), usage=None)

    async def audit(*args, **kwargs):
        return await repair_coverage(*args, client=SimpleNamespace(responses=Responses()), **kwargs)

    async def final_review(notice, *args, **kwargs):
        if applicability == "not_applicable":
            notice.eligibility.append(LabeledFact(
                text="The table does not apply to this hiring round.", source_evidence=non_applicability,
            ))
        return EnglishNoticeReview(notice=notice, has_verification_gaps=True, unverified_source_units=1)

    monkeypatch.setattr(main, "_run_text_pipeline", extracted)
    monkeypatch.setattr(main, "repair_coverage", audit)
    monkeypatch.setattr(main, "review_notice_english", final_review)
    response = client.post("/api/analyze-client-ocr", json={
        "pages": [page.model_dump()], "ocr_latency_ms": 100, "provider": "openai", "allow_partial": True,
    })

    assert response.status_code == 200
    result = response.json()
    assert result["acquisition"]["english_coverage_status"] == "partial"
    assert "999" not in result["simplified_text"]
    assert [item["text"] for item in result["notice"]["eligibility"]] == (
        ["The table does not apply to this hiring round."] if applicability == "not_applicable" else []
    )
    assert "Meet at least one" not in result["simplified_text"]
    if conflicting_geometry:
        assert result["notice"]["key_details"] == []
        assert "810 or higher" not in result["simplified_text"]
    else:
        assert [item["text"] for item in result["notice"]["key_details"]] == [
            "Printed table: TOEIC — 810 or higher", "Printed table: TEPS — 320 or higher",
            "Printed table: FLEX — 2A or higher", "Printed table: TOEFL (iBT) — 95 or higher",
            "Printed table: TOEIC Speaking — 160 or higher", "Printed table: OPIc — IH or higher",
        ]
        assert all(item["bounding_box"] for item in result["notice"]["key_details"])
        assert all(item["label"] == "Printed English-score table (applicability unverified)"
                   for item in result["notice"]["key_details"])
        assert "Printed table: TOEIC Speaking — 160 or higher" in result["simplified_text"]


def test_distant_or_qualification_is_not_applied_to_a_score_table() -> None:
    spans = [span("영어 자격 중 하나 이상", 0.7, 0.1),
             span("TOEIC", 0.4, 0.55), span("TEPS", 0.7, 0.55),
             span("810 이상", 0.4, 0.58), span("320 이상", 0.7, 0.58)]
    page = ClientOcrPage(text="\n".join(item.text for item in spans), spans=spans)
    notice = NoticeData()

    assert add_aligned_language_scores(notice, [page], [source_page()]) == 2
    assert not any("at least one" in item.text for item in notice.eligibility)


def test_printed_table_mode_preserves_accepted_scope_without_creating_eligibility() -> None:
    spans = [span("영어 시험 중 하나 이상", 0.5, 0.18),
             span("TOEIC", 0.3, 0.2), span("OPIc", 0.6, 0.2),
             span("730 이상", 0.3, 0.23), span("IH 이상", 0.6, 0.23)]
    page = ClientOcrPage(text="\n".join(item.text for item in spans), spans=spans)
    accepted_scope = LabeledFact(text="These historical thresholds do not apply to the current round.")
    retained_detail = LabeledFact(text="Submit applications through the online portal.")
    notice = NoticeData(eligibility=[accepted_scope], key_details=[retained_detail])

    assert add_aligned_language_scores(notice, [page], [source_page()], presentation="printed_table") == 2

    assert notice.eligibility == [accepted_scope]
    assert notice.key_details[0] == retained_detail
    assert [item.text for item in notice.key_details[1:]] == [
        "Printed table: TOEIC — 730 or higher", "Printed table: OPIc — IH or higher",
    ]
    assert "at least one" not in " ".join(item.text for item in notice.eligibility + notice.key_details)
    assert all(fact.kind == "printed_language_score" for fact in notice.source_facts)
