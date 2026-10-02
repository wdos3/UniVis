"""Application contracts across synthetic notice types, with injected audits.

These tests exercise coverage, retry, rendering, and source grounding. They do
not establish OCR accuracy or the external model's translation quality.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import re
from types import SimpleNamespace

import pytest

from app.models import BoundingBox, ClientOcrPage, LabeledFact, NoticeData, OcrSpan, SourcePage
from app.services.coverage import audit_coverage
from app.services.coverage_repair import RepairDetail, RepairResponse, repair_coverage
from app.services.extraction.language_scores import add_aligned_language_scores
from app.services.text import simplified_text


FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "cross_notice_contracts.json").read_text(encoding="utf-8"))
CASES = FIXTURE["cases"]


def source_text(case: dict) -> str:
    lines: list[str] = []
    page = None
    for unit in case["units"]:
        if unit["page"] != page:
            page = unit["page"]
            lines.append(f"[Page {page}]")
        lines.append(unit["source"])
    return "\n".join(lines)


def details(case: dict) -> list[RepairDetail]:
    units = audit_coverage(NoticeData(), source_text(case)).units
    return [
        RepairDetail(unit_ids=[unit.id], text=expected["english"], category=expected["category"], certain=True)
        for unit, expected in zip(units, case["units"], strict=True)
    ]


def response(items: list[RepairDetail], *, rejected: list[str] | None = None) -> RepairResponse:
    return RepairResponse(
        represented_unit_ids=[], details=items, decorative=[], unresolved_unit_ids=[],
        unsupported_english_ids=rejected or [],
    )


class AuditReplay:
    def __init__(self, responses: list[RepairResponse]) -> None:
        self.responses = responses
        self.calls: list[dict] = []

    async def parse(self, **kwargs):
        self.calls.append(kwargs)
        assert len(self.calls) <= len(self.responses), "An unexpected extra audit was requested."
        return SimpleNamespace(output_parsed=self.responses[len(self.calls) - 1], usage=None)


def run_replay(case: dict, responses: list[RepairResponse], notice: NoticeData | None = None):
    replay = AuditReplay(responses)
    result = asyncio.run(repair_coverage(
        notice or NoticeData(), source_text(case), client=SimpleNamespace(responses=replay), model="gpt-4o-mini",
    ))
    return result, replay.calls


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_varied_notice_clauses_reach_english_with_their_own_evidence(case: dict) -> None:
    result, calls = run_replay(case, [response(details(case))])

    digest = simplified_text(result.notice)
    assert all(unit["english"] in digest for unit in case["units"])
    assert not re.search(r"[가-힣]", digest)
    assert all(term not in digest.casefold() for term in ("sogang", "convedu", "creative convergence", "200,000"))
    assert audit_coverage(result.notice, source_text(case)).uncovered == []
    displayed = result.notice.key_details + result.notice.financial_support
    assert len(displayed) == len(case["units"])
    for expected in case["units"]:
        item = next(item for item in displayed if item.source_evidence == expected["source"])
        assert item.source_evidence == expected["source"]
        assert item.source_page == expected["page"]
        assert item.source_fact_ids
    prompt = json.loads(calls[0]["input"][1]["content"])
    assert [unit["korean_ocr"] for unit in prompt["source_units"]] == [unit["source"] for unit in case["units"]]
    assert calls[0]["model"] == "gpt-4o-mini"


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_missing_clause_gets_focused_repair_for_each_notice_type(case: dict) -> None:
    expected = details(case)
    omitted = expected[-1]
    result, calls = run_replay(case, [response(expected[:-1]), response([omitted])])

    assert len(calls) == result.requests == 2
    retry = json.loads(calls[1]["input"][1]["content"])
    assert [unit["id"] for unit in retry["source_units"]] == omitted.unit_ids
    assert all(unit["english"] in simplified_text(result.notice) for unit in case["units"])


def test_previous_notice_claims_cannot_survive_a_rejected_english_audit() -> None:
    case = CASES[0]
    contamination = "Sogang research teams receive KRW 200,000 per person through the Convergence Education Center."
    notice = NoticeData(key_details=[LabeledFact(text=contamination, source_evidence=case["units"][0]["source"], source_page=1)])
    expected = details(case)

    result, calls = run_replay(case, [response(expected, rejected=["E001"]), response([expected[0]])], notice)

    assert contamination == notice.key_details[0].text
    assert contamination not in simplified_text(result.notice)
    assert all(unit["english"] in simplified_text(result.notice) for unit in case["units"])
    assert json.loads(calls[0]["input"][1]["content"])["english_fields"]["E001"] == contamination


def test_conditional_registration_dates_are_checked_for_each_student_group() -> None:
    case = next(case for case in CASES if case["id"] == "course_registration")
    expected = details(case)
    swapped = [item.model_copy(deep=True) for item in expected]
    swapped[0].text = "Daon University course registration for new students is on March 6, 2028 from 10:00 to 12:00."
    swapped[1].text = "Course registration for enrolled students is on March 4, 2028 from 14:00 to 16:00."

    result, calls = run_replay(case, [response(swapped), response(expected[:2])])

    assert len(calls) == 2
    retry = json.loads(calls[1]["input"][1]["content"])
    assert {unit["id"] for unit in retry["source_units"]} == {item.unit_ids[0] for item in expected[:2]}
    assert all(unit["english"] in simplified_text(result.notice) for unit in case["units"])


@pytest.mark.parametrize("layout", ["rows", "columns"])
@pytest.mark.parametrize("thresholds", [
    ("735", "277", "3A", "88", "140", "IH"),
    ("910", "342", "1A", "104", "180", "AL"),
])
def test_varied_test_score_pairs_survive_row_and_column_layouts(layout: str, thresholds: tuple[str, ...]) -> None:
    labels = ("TOEIC", "TEPS", "FLEX", "TOEFL (iBT)", "TOEIC Speaking", "OPIc")
    pairs: list[OcrSpan] = []
    for index, (label, threshold) in enumerate(zip(labels, thresholds, strict=True)):
        header_x, header_y = (0.12 + index * 0.14, 0.2) if layout == "columns" else (0.2, 0.15 + index * 0.1)
        score_x, score_y = (header_x, 0.25) if layout == "columns" else (0.6, header_y)
        for text, x, y in ((label, header_x, header_y), (f"{threshold} 이상", score_x, score_y)):
            pairs.append(OcrSpan(text=text, box=BoundingBox(x=x, y=y, width=0.04, height=0.02)))
    # OCR enumeration order is not evidence of which test a score belongs to.
    qualifier = OcrSpan(
        text="영어 성적 중 하나 이상",
        box=BoundingBox(x=0.12 if layout == "columns" else 0.2,
                        y=0.14 if layout == "columns" else 0.09,
                        width=0.82 if layout == "columns" else 0.44, height=0.02),
    )
    spans = [qualifier, *pairs[::2][::-1], *pairs[1::2][::-1]]
    page = ClientOcrPage(text="\n".join(span.text for span in spans), spans=spans)
    source_page = SourcePage(
        id="synthetic-score-page", page_number=1, filename="Synthetic score table", media_type="image/png",
        original_url="", processed_url="", width=1000, height=1000,
    )
    notice = NoticeData()

    count = add_aligned_language_scores(notice, [page], [source_page])

    assert count == 6
    expected = {f"{label}: {threshold} or higher" for label, threshold in zip(labels, thresholds, strict=True)}
    assert expected <= {item.text for item in notice.eligibility}
    assert notice.eligibility[0].text == "Meet at least one of the following English-test score thresholds."
    assert all(item.source_page == 1 and item.bounding_box is not None for item in notice.eligibility[1:])
