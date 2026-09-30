from __future__ import annotations

from app.models import BoundingBox, LabeledFact, NoticeData, ReviewState, SourceFact, SourcePage
from app.services.coverage import audit_coverage
from app.services.coverage_coalescing import coalesce_exact_repair_duplicates
from app.services.extraction.reconciliation import add_page_provenance
from app.services.text import simplified_text


def _source_page() -> SourcePage:
    return SourcePage(
        id="page-1", page_number=1, filename="notice.png",
        media_type="image/png", original_url="", processed_url="", width=1, height=1,
    )


def test_exact_repair_duplicate_merges_source_evidence_without_losing_coverage() -> None:
    source = "[Page 1]\n연구비 지원\n연구 자금 지원"
    primary = LabeledFact(
        text="Research funding is available.", label="Grant",
        source_evidence="연구비 지원", source_fact_ids=["F001"], source_page=1,
        source_image_id="page-1", bounding_box=BoundingBox(x=0.1, y=0.1, width=0.2, height=0.1),
    )
    duplicate = LabeledFact(
        text="  RESEARCH   funding is available. ", label="Additional detail",
        source_evidence="연구 자금 지원", source_fact_ids=["F002"], source_page=1,
        state=ReviewState.NEEDS_REVIEW,
    )
    notice = NoticeData(
        financial_support=[primary], key_details=[duplicate],
        source_facts=[
            SourceFact(id="F001", kind="funding", source_text="연구비 지원"),
            SourceFact(id="F002", kind="coverage_repair_funding", source_text="연구 자금 지원"),
        ],
    )

    merged = coalesce_exact_repair_duplicates(notice)

    assert len(merged.financial_support) == 1
    assert merged.key_details == []
    kept = merged.financial_support[0]
    assert kept.text == "Research funding is available."
    assert kept.label == "Grant"
    assert kept.source_evidence == "연구비 지원\n연구 자금 지원"
    assert kept.source_fact_ids == ["F001", "F002"]
    assert kept.state == ReviewState.NEEDS_REVIEW
    assert kept.bounding_box is None
    assert len(merged.source_facts) == 2
    assert audit_coverage(merged, source).uncovered == []
    assert simplified_text(merged).count("Research funding is available.") == 1
    add_page_provenance(merged, ["연구비 지원\n연구 자금 지원"], [_source_page()])
    assert kept.source_page == 1
    assert kept.source_image_id == "page-1"
    assert notice.key_details == [duplicate]
    assert notice.financial_support == [primary]


def test_similar_but_distinct_repair_facts_remain_separate() -> None:
    notice = NoticeData(
        financial_support=[LabeledFact(
            text="Research funding is up to KRW 200,000 per person.",
            source_evidence="연구비 최대 20만원", source_fact_ids=["F001"], source_page=1,
        )],
        key_details=[LabeledFact(
            text="Research funding is KRW 200,000 per person.",
            source_evidence="연구비 20만원", source_fact_ids=["F002"], source_page=1,
        )],
        source_facts=[
            SourceFact(id="F001", kind="funding", source_text="연구비 최대 20만원"),
            SourceFact(id="F002", kind="coverage_repair_funding", source_text="연구비 20만원"),
        ],
    )

    merged = coalesce_exact_repair_duplicates(notice)

    assert len(merged.financial_support) == len(merged.key_details) == 1
    assert merged.financial_support[0].source_fact_ids == ["F001"]
    assert merged.key_details[0].source_fact_ids == ["F002"]


def test_equal_repair_text_on_another_page_is_not_coalesced() -> None:
    notice = NoticeData(
        audience=[LabeledFact(text="Undergraduates may apply.", source_fact_ids=["F001"], source_page=1)],
        key_details=[LabeledFact(text="Undergraduates may apply.", source_fact_ids=["F002"], source_page=2)],
        source_facts=[
            SourceFact(id="F001", kind="eligibility", source_text="학부생 지원 가능"),
            SourceFact(id="F002", kind="coverage_repair_eligibility", source_text="학부생 지원 가능"),
        ],
    )

    merged = coalesce_exact_repair_duplicates(notice)

    assert len(merged.audience) == len(merged.key_details) == 1
