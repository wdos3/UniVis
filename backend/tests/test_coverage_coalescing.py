from __future__ import annotations

import pytest

from app.models import BoundingBox, LabeledFact, NoticeData, ReviewState, SourceFact, SourcePage
from app.services.coverage import audit_coverage
from app.services.coverage_coalescing import coalesce_exact_repair_duplicates
from app.services.extraction.reconciliation import add_page_provenance, evidence_matches_page
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


def test_exact_primary_repeat_with_same_evidence_is_merged_in_same_section() -> None:
    text = "Activity allowance: KRW 200,000 per person"
    evidence = "활동비: 1인당 20만원"
    notice = NoticeData(
        financial_support=[
            LabeledFact(text=text, source_evidence=evidence, source_fact_ids=["F001"], source_page=1),
            LabeledFact(text=text, source_evidence=evidence, source_fact_ids=["F002"], source_page=1),
        ],
        source_facts=[
            SourceFact(id="F001", kind="funding", source_text=evidence),
            SourceFact(id="F002", kind="funding", source_text=evidence),
        ],
    )

    merged = coalesce_exact_repair_duplicates(notice)

    assert len(merged.financial_support) == 1
    assert merged.financial_support[0].source_fact_ids == ["F001", "F002"]
    assert len(merged.source_facts) == 2
    assert len(notice.financial_support) == 2


def test_same_primary_text_from_distinct_source_lines_remains_separate() -> None:
    notice = NoticeData(financial_support=[
        LabeledFact(text="Funding available", source_evidence="연구비 지원", source_fact_ids=["F001"], source_page=1),
        LabeledFact(text="Funding available", source_evidence="활동비 지원", source_fact_ids=["F002"], source_page=1),
    ])

    merged = coalesce_exact_repair_duplicates(notice)

    assert len(merged.financial_support) == 2


@pytest.mark.parametrize("full_quote_first", [False, True])
def test_contained_partial_quote_keeps_the_exact_full_source_quote(full_quote_first: bool) -> None:
    partial = "비용은 장학금 형태로 지급"
    full = "연구비로 지원되는 항목 외의 비용은 장학금 형태로 지급"
    first, second = (full, partial) if full_quote_first else (partial, full)
    text = "Costs outside research-funded categories are paid as scholarships."
    notice = NoticeData(
        financial_support=[LabeledFact(
            text=text, source_evidence=first, source_fact_ids=["F001"], source_page=1,
        )],
        key_details=[LabeledFact(
            text=text, source_evidence=second, source_fact_ids=["F002"], source_page=1,
        )],
        source_facts=[
            SourceFact(id="F001", kind="funding", source_text=first),
            SourceFact(id="F002", kind="coverage_repair_funding", source_text=second),
        ],
    )

    merged = coalesce_exact_repair_duplicates(notice)

    kept = merged.financial_support[0]
    assert merged.key_details == []
    assert kept.source_evidence == full
    assert kept.source_fact_ids == ["F001", "F002"]
    assert [fact.source_text for fact in merged.source_facts] == [first, second]
    assert evidence_matches_page(kept.source_evidence, full)
    assert audit_coverage(merged, full).uncovered == []
    add_page_provenance(merged, [full], [_source_page()])
    assert kept.source_page == 1
    assert kept.source_image_id == "page-1"


def test_contained_quote_removal_preserves_disjoint_source_lines_and_fact_ids() -> None:
    partial = "비용은 장학금 형태로 지급"
    full = "연구비로 지원되는 항목 외의 비용은 장학금 형태로 지급"
    disjoint = "연구비는 카드결제"
    source = full + "\n문의: 융합교육혁신팀\n" + disjoint
    text = "Other costs are paid as scholarships; research expenses are paid by card."
    notice = NoticeData(
        financial_support=[LabeledFact(
            text=text, source_evidence=partial, source_fact_ids=["F001"], source_page=1,
        )],
        key_details=[LabeledFact(
            text=text, source_evidence=full + "\n" + disjoint, source_fact_ids=["F002"], source_page=1,
        )],
        source_facts=[
            SourceFact(id="F001", kind="funding", source_text=partial),
            SourceFact(id="F002", kind="coverage_repair_funding", source_text=full + "\n" + disjoint),
        ],
    )

    merged = coalesce_exact_repair_duplicates(notice)

    kept = merged.financial_support[0]
    assert kept.source_evidence == full + "\n" + disjoint
    assert kept.source_fact_ids == ["F001", "F002"]
    assert len(merged.source_facts) == 2
    assert evidence_matches_page(kept.source_evidence, source)


def test_contained_quote_on_another_page_retains_both_items_and_citations() -> None:
    partial = "비용은 장학금 형태로 지급"
    full = "연구비로 지원되는 항목 외의 비용은 장학금 형태로 지급"
    text = "Costs outside research-funded categories are paid as scholarships."
    notice = NoticeData(
        financial_support=[LabeledFact(
            text=text, source_evidence=partial, source_fact_ids=["F001"], source_page=1,
        )],
        key_details=[LabeledFact(
            text=text, source_evidence=full, source_fact_ids=["F002"], source_page=2,
        )],
        source_facts=[
            SourceFact(id="F001", kind="funding", source_text=partial, source_page=1),
            SourceFact(id="F002", kind="coverage_repair_funding", source_text=full, source_page=2),
        ],
    )

    merged = coalesce_exact_repair_duplicates(notice)

    assert merged.financial_support[0].source_evidence == partial
    assert merged.financial_support[0].source_fact_ids == ["F001"]
    assert merged.key_details[0].source_evidence == full
    assert merged.key_details[0].source_fact_ids == ["F002"]
    assert [fact.source_page for fact in merged.source_facts] == [1, 2]
