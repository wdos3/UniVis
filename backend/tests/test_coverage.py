from __future__ import annotations

from pathlib import Path

from app.models import Action, DocumentRequirement, LabeledFact, NoticeData, SourceFact
from app.services.coverage import audit_coverage, display_text


def test_coverage_uses_grounded_output_not_model_claimed_source_facts() -> None:
    source = "[Page 1]\n활동비: 20만원\n연구비: 1인당 최대 20만원"
    notice = NoticeData(
        fees=[LabeledFact(text="Activity fee: KRW 200,000", source_evidence="활동비: 20만원")],
        source_facts=[
            SourceFact(id="F001", kind="fee", source_text="활동비: 20만원"),
            SourceFact(id="F002", kind="fee", source_text="연구비: 1인당 최대 20만원"),
        ],
    )

    audit = audit_coverage(notice, source)

    assert audit.total_count == 2
    assert audit.covered_count == 1
    assert audit.cited_english_by_unit["P001-L0001"] == ["Activity fee: KRW 200,000"]
    assert audit.cited_english_by_unit["P001-L0002"] == []
    assert [(unit.id, unit.page, unit.text) for unit in audit.uncovered] == [
        ("P001-L0002", 1, "연구비: 1인당 최대 20만원")
    ]


def test_audit_can_see_rendered_optional_document_and_mandatory_action_items() -> None:
    source = "지원서를 제출"
    notice = NoticeData(
        actions=[Action(
            step=1, action="Submit the application.", required_items=["Application form"], source_evidence=source,
        )],
        required_documents=[DocumentRequirement(
            name="Application form", condition="Required for application submission", required=False,
            source_evidence=source,
        )],
    )

    audit = audit_coverage(notice, source)

    assert audit.cited_english_by_unit["P001-L0001"] == [
        "Submit the application. | Required items: Application form",
        "Application form | Required for application submission | optional",
    ]
    notice.required_documents[0].required = True
    assert display_text(notice.required_documents[0]) == "Application form | Required for application submission"


def test_partial_quote_does_not_cover_the_rest_of_an_ocr_line() -> None:
    notice = NoticeData(eligibility=[LabeledFact(
        text="Students may participate", source_evidence="휴학생도 참여는 가능하나"
    )])

    audit = audit_coverage(notice, "휴학생도 참여는 가능하나 연구비 및 활동비 지원 대상에서는 제외")

    assert audit.covered_count == 0
    assert audit.uncovered[0].text.endswith("지원 대상에서는 제외")


def test_whitespace_normalization_and_duplicate_lines_within_a_page() -> None:
    notice = NoticeData(key_details=[LabeledFact(
        text="Research topic: AI wearables",
        source_evidence="AI 웨어러블 기기 연구",
    )])

    audit = audit_coverage(notice, "[Page 1]\nAI 웨어러블 기기 연구\nAI  웨어러블 기기 연구\nvs")

    assert audit.total_count == 2
    assert audit.covered_count == 1
    assert [(unit.id, unit.text) for unit in audit.uncovered] == [("P001-L0002", "vs")]


def test_identical_lines_on_different_pages_need_page_specific_evidence() -> None:
    source = "[Page 1]\n신청 기간\n[Page 2]\n신청 기간"
    notice = NoticeData(key_details=[LabeledFact(
        text="Application period", source_evidence="신청 기간", source_page=1
    )])

    audit = audit_coverage(notice, source)

    assert audit.total_count == 2
    assert audit.covered_count == 1
    assert [(unit.id, unit.page) for unit in audit.uncovered] == [("P002-L0001", 2)]


def test_ambiguous_page_does_not_certify_repeated_line() -> None:
    source = "[Page 1]\n지원 대상\n[Page 2]\n지원 대상"
    notice = NoticeData(audience=[LabeledFact(text="Eligible audience", source_evidence="지원 대상")])

    audit = audit_coverage(notice, source)

    assert audit.covered_count == 0
    assert [unit.id for unit in audit.uncovered] == ["P001-L0001", "P002-L0001"]


def test_evidence_from_another_page_cannot_cover_a_unique_line() -> None:
    notice = NoticeData(key_details=[LabeledFact(
        text="AI research topic", source_evidence="AI 연구주제", source_page=2
    )])

    audit = audit_coverage(notice, "[Page 1]\nAI 연구주제\n[Page 2]\n지원 기간")

    assert [unit.id for unit in audit.uncovered] == ["P001-L0001", "P002-L0001"]


def test_empty_page_markers_and_standalone_separators_are_not_units() -> None:
    audit = audit_coverage(NoticeData(), "[Page 1]\n  \n*\n→\n[Page 2]\n 9 ")

    assert [(unit.id, unit.text) for unit in audit.units] == [
        ("P002-L0001", "9"),
    ]


def test_short_fragment_is_not_covered_by_incidental_substring() -> None:
    notice = NoticeData(key_details=[LabeledFact(text="September 9", source_evidence="2026.9.9")])

    audit = audit_coverage(notice, "9\n2026.9.9")

    assert [unit.text for unit in audit.uncovered] == ["9"]


def test_labels_not_shown_in_simplified_text_cannot_prove_english_coverage() -> None:
    source = "2026학년도 2학기 학부 재학생"
    notice = NoticeData(eligibility=[LabeledFact(
        label="Must be enrolled in the second semester of 2026",
        text="Required",
        source_evidence=source,
    )])

    audit = audit_coverage(notice, source)

    assert audit.cited_english_by_unit["P001-L0001"] == ["Required"]

    notice.eligibility[0].text = ""
    empty_audit = audit_coverage(notice, source)
    assert empty_audit.cited_english_by_unit["P001-L0001"] == []
    assert empty_audit.uncovered == empty_audit.units


def test_attached_research_poster_omissions_are_independently_detected() -> None:
    source = (Path(__file__).parent / "fixtures" / "sogang_research_ocr.txt").read_text(encoding="utf-8")
    sparse = NoticeData(
        audience=[LabeledFact(text="Enrolled undergraduate students", source_evidence="2026학년도 2학기 학부 재학생")],
        financial_support=[LabeledFact(text="Up to KRW 200,000 per person", source_evidence="연구비:1인당 최대 20만원")],
    )

    missing = {unit.text for unit in audit_coverage(sparse, source).uncovered}

    assert "3.AI 원천 기술 연구개발" in missing
    assert "4.Robot 관련 연구 개발" in missing
    assert "2.학생 자율 선정 주제" in missing
    assert "기자재 구입 및 대여,재료비," in missing
    assert "장학금 형태로 지급" in missing
