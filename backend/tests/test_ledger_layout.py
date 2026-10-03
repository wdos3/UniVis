from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.models import (
    BoundingBox,
    LedgerAnalysisRequest,
    LedgerVisionRegion,
    SourceLedger,
    SourcePoint,
    SourceUnit,
)
from app.services.ledger_layout import build_source_ledger


FIXTURES = Path(__file__).parent / "fixtures"


def unit(
    id: str, text: str, x: float, y: float, width: float = 0.18, height: float = 0.025
) -> SourceUnit:
    return SourceUnit(
        id=id,
        page_number=1,
        image_id="photo-1",
        order=int(y * 1000),
        source_text=text,
        box=BoundingBox(x=x, y=y, width=width, height=height),
    )


def test_table_cells_keep_physical_labels_values_and_repeated_cells() -> None:
    units = [
        unit("a", "TOEIC", 0.1, 0.1),
        unit("b", "TEPS", 0.4, 0.1),
        unit("c", "OPIc", 0.7, 0.1),
        unit("d", "800점 이상", 0.1, 0.15),
        unit("e", "309점 이상", 0.4, 0.15),
        unit("f", "IM3 이상", 0.7, 0.15),
    ]
    ledger = build_source_ledger(units)
    assert {u.id for u in ledger.units} == {u.id for u in units}
    assert [(u.table_row, u.table_column) for u in ledger.units] == [
        (0, 0),
        (0, 1),
        (0, 2),
        (1, 0),
        (1, 1),
        (1, 2),
    ]
    assert all(block.kind == "table_cell" for block in ledger.blocks)


def test_wrapped_negation_attaches_to_condition_without_joining_other_column() -> None:
    units = [
        unit("a", "*휴학생도 참여는 가능하나, 연구비 및", 0.06, 0.2, 0.39),
        unit("b", "활동비 지원 대상에서는 제외", 0.06, 0.231, 0.35),
        unit("c", "1. 스마트 글라스 등 AI Wearable Device", 0.55, 0.2, 0.4),
        unit("d", "의 AIX 발굴과 MVP 연구", 0.55, 0.231, 0.35),
    ]
    ledger = build_source_ledger(units)
    assert any(
        block.unit_ids == ["a", "b"] and block.kind == "condition"
        for block in ledger.blocks
    )
    assert any(block.unit_ids == ["c", "d"] for block in ledger.blocks)
    assert not any(
        set(block.unit_ids) & {"a", "b"} and set(block.unit_ids) & {"c", "d"}
        for block in ledger.blocks
    )


def test_every_observation_survives_geometryless_long_multiline_and_duplicate_text() -> (
    None
):
    units = [
        unit("a", "신청", 0.1, 0.1),
        unit("b", "신청", 0.6, 0.1),
        SourceUnit(
            id="c",
            image_id="photo-1",
            page_number=1,
            order=3,
            source_text="긴 문장\n" * 150,
        ),
        unit("d", "기타", 0.1, 0.3),
    ]
    units[-1].polygon = [
        SourcePoint(x=0.1, y=0.3),
        SourcePoint(x=0.25, y=0.29),
        SourcePoint(x=0.25, y=0.32),
    ]
    ledger = build_source_ledger(units)
    mapped = [id for block in ledger.blocks for id in block.unit_ids]
    assert sorted(mapped) == ["a", "b", "c", "d"]
    assert ledger.units[-1].polygon == units[-1].polygon
    assert ledger.coverage.displayed_unit_ids == []
    assert not ledger.coverage.meaning_checked


def test_raw_sogang_inventory_remains_complete_including_seal() -> None:
    fixture = json.loads(
        (FIXTURES / "sogang_research_2026_browser_ocr.json").read_text(encoding="utf-8")
    )
    width, height = fixture["image"]["width"], fixture["image"]["height"]
    units = [
        unit(
            str(index),
            item["text"],
            item["box"][0] / width,
            item["box"][1] / height,
            (item["box"][2] - item["box"][0]) / width,
            (item["box"][3] - item["box"][1]) / height,
        )
        for index, item in enumerate(fixture["items"])
    ]
    ledger = build_source_ledger(units)
    assert ledger.coverage.source_unit_ids == [u.id for u in units]
    assert sorted(id for block in ledger.blocks for id in block.unit_ids) == sorted(
        u.id for u in units
    )
    assert any("기간입C이끼지" == u.source_text for u in ledger.units)
    assert any(
        "휴학생" in b.source_text and "지원 대상에서는 제외" in b.source_text
        for b in ledger.blocks
    )


def test_request_rejects_unknown_crop_ids_and_remote_images() -> None:
    with pytest.raises(ValidationError, match="inline"):
        LedgerVisionRegion(
            unit_ids=["a"], data_url="https://example.com/private-photo.png"
        )
    crop = LedgerVisionRegion(
        unit_ids=["unknown"], data_url="data:image/jpeg;base64,/9j/"
    )
    with pytest.raises(ValidationError, match="existing"):
        LedgerAnalysisRequest(
            ledger=SourceLedger(units=[unit("a", "text", 0.1, 0.1)]), regions=[crop]
        )


def test_source_ids_cannot_silently_collapse() -> None:
    with pytest.raises(ValidationError, match="unique"):
        build_source_ledger([unit("a", "신청", 0.1, 0.1), unit("a", "신청", 0.1, 0.2)])


def test_synthetic_table_does_not_absorb_adjacent_funding_column() -> None:
    fixture = json.loads(
        (FIXTURES / "ledger_synthetic_layout.json").read_text(encoding="utf-8")
    )
    ledger = build_source_ledger(SourceLedger.model_validate(fixture["ledger"]).units)
    table = {u.id for u in ledger.units if u.table_id}
    assert table == {"toeic-label", "toeic-score", "teps-label", "teps-score"}
    assert any(
        block.unit_ids == ["condition-first", "condition-second"]
        for block in ledger.blocks
    )


def test_actual_kcci_geometry_preserves_wrapped_headers_six_pairs_and_duplicate_observations() -> (
    None
):
    fixture = json.loads(
        (FIXTURES / "kcci_2027_ledger_geometry.json").read_text(encoding="utf-8")
    )
    units = [SourceUnit.model_validate(item) for item in fixture["units"]]
    ledger = build_source_ledger(units)
    cells = [
        block for block in ledger.blocks if block.table_id and "exams" in block.table_id
    ]
    pairs = [
        (
            header.source_text,
            next(
                cell.source_text
                for cell in cells
                if cell.table_row == 1 and cell.table_column == header.table_column
            ),
        )
        for header in cells
        if header.table_row == 0
    ]
    assert pairs == [
        ("TOEIC", "800 이상"),
        ("TEPS", "309 이상"),
        ("FLEX", "2B 이상"),
        ("TOEFL\n(iBT)", "91 이상"),
        ("TOEIC\nSpeaking", "150이상\n150 이상"),
        ("OPIC\nOPIc", "IM3 이상"),
    ]
    assert sorted(id for block in ledger.blocks for id in block.unit_ids) == sorted(
        unit.id for unit in units
    )
    assert any(block.unit_ids == ["kcci-23", "kcci-30"] for block in cells)
    assert any(block.unit_ids == ["kcci-24", "kcci-31"] for block in cells)
    assert not any("3문제" in block.source_text for block in cells)
    assert next(unit for unit in ledger.units if unit.id == "kcci-71").table_id is None


def test_row_oriented_exam_table_retains_label_value_rows() -> None:
    ledger = build_source_ledger(
        [
            unit("a", "TOEIC", 0.1, 0.1),
            unit("b", "800 이상", 0.3, 0.1),
            unit("c", "TEPS", 0.1, 0.15),
            unit("d", "309 이상", 0.3, 0.15),
        ]
    )
    assert [(unit.table_row, unit.table_column) for unit in ledger.units] == [
        (0, 0),
        (0, 1),
        (1, 0),
        (1, 1),
    ]


def test_wrapped_label_in_row_oriented_table_remains_one_header_cell() -> None:
    units = [
        unit("a", "TOEIC", 0.1, 0.1),
        unit("b", "Speaking", 0.1, 0.13),
        unit("c", "150 이상", 0.35, 0.115),
        unit("d", "TEPS", 0.1, 0.2),
        unit("e", "309 이상", 0.35, 0.2),
    ]
    ledger = build_source_ledger(units)
    assert any(
        block.unit_ids == ["a", "b"]
        and block.table_row == 0
        and block.table_column == 0
        for block in ledger.blocks
    )
    assert [(unit.table_row, unit.table_column) for unit in ledger.units] == [
        (0, 0),
        (0, 0),
        (0, 1),
        (1, 0),
        (1, 1),
    ]


@pytest.mark.parametrize(
    "ambiguous", ["two_headers", "two_values", "missing_suffix", "unknown_suffix"]
)
def test_ambiguous_exam_geometry_retains_physical_cells_without_manufacturing_pairs(
    ambiguous,
) -> None:
    cases = {
        "two_headers": [
            unit("a", "TOEIC", 0.10, 0.1, 0.08),
            unit("b", "TEPS", 0.12, 0.11, 0.08),
            unit("c", "800 이상", 0.11, 0.145, 0.08),
        ],
        "two_values": [
            unit("a", "TOEIC", 0.1, 0.1),
            unit("b", "800 이상", 0.1, 0.15),
            unit("c", "600 이상", 0.1, 0.15),
        ],
        "missing_suffix": [
            unit("a", "TOEIC", 0.1, 0.1),
            unit("b", "150 이상", 0.1, 0.15),
            unit("c", "TOEIC", 0.5, 0.1),
            unit("d", "800 이상", 0.5, 0.15),
        ],
        "unknown_suffix": [
            unit("a", "TOEFL", 0.1, 0.1),
            unit("b", "i8T", 0.1, 0.12),
            unit("c", "91 이상", 0.1, 0.15),
        ],
    }
    ledger = build_source_ledger(cases[ambiguous])
    assert sorted(id for block in ledger.blocks for id in block.unit_ids) == sorted(
        unit.id for unit in ledger.units
    )
    assert not any(unit.table_id for unit in ledger.units)
    assert ledger.coverage.protected_value_gaps
    assert all(block.kind == "caption" for block in ledger.blocks)


def test_unrelated_thresholds_and_essay_question_counts_never_join_score_table() -> (
    None
):
    units = [
        unit("a", "TOEIC", 0.5, 0.1),
        unit("b", "800 이상", 0.5, 0.15),
        unit("c", "TEPS", 0.8, 0.1),
        unit("d", "309 이상", 0.8, 0.15),
        unit("e", "3문제 내외", 0.7, 0.7),
        unit("f", "20만원 이상", 0.1, 0.3),
    ]
    ledger = build_source_ledger(units)
    assert {unit.id for unit in ledger.units if unit.table_id} == {"a", "b", "c", "d"}


def test_client_recovery_metadata_is_reset_and_small_noise_is_caption() -> None:
    units = [
        unit("a", "대", 0.1, 0.1, 0.02),
        unit("b", "지용부착 자용해기", 0.9, 0.1, 0.06),
    ]
    units[0].recovered_source_text = "trusted client claim"
    units[0].recovery_source = "vision"
    units[1].confidence = 0.7
    ledger = build_source_ledger(units)
    assert all(
        unit.recovered_source_text is None and unit.recovery_source is None
        for unit in ledger.units
    )
    assert ledger.blocks[0].kind == "caption"
    assert ledger.blocks[1].kind != "caption"


def test_long_physical_ids_keep_bounded_distinct_layout_identifiers():
    identifiers = ["a" * 128, "a" * 127 + "b"]
    units = [
        unit(identifier, "학생 공지", 0.1, 0.1 + index * 0.3)
        for index, identifier in enumerate(identifiers)
    ]
    result = build_source_ledger(units)
    assert [entry.id for entry in result.units] == identifiers
    assert all(len(block.id) <= 128 for block in result.blocks)
    assert all(len(entry.section_id) <= 128 for entry in result.units)
    assert len({block.id for block in result.blocks}) == len(result.blocks)
    assert [block.id for block in build_source_ledger(units).blocks] == [
        block.id for block in result.blocks
    ]


def test_actual_kcci_stage_grid_preserves_dates_and_essay_question_scope():
    data = json.loads(
        (FIXTURES / "kcci_2027_stages_geometry.json").read_text(encoding="utf-8")
    )
    source = [SourceUnit.model_validate(value) for value in data["units"]]
    result = build_source_ledger(source)
    ids = [unit.id for unit in result.units]
    assert ids == [unit.id for unit in source]
    assert sorted(
        unit_id for block in result.blocks for unit_id in block.unit_ids
    ) == sorted(ids)
    by_text = {unit.source_text: unit for unit in result.units}
    essay = by_text["논술시험"]
    count = by_text["3문제 내외"]
    assert essay.table_id is not None
    assert (count.table_id, count.table_column) == (essay.table_id, essay.table_column)
    assert (by_text["18:00"].table_id, by_text["18:00"].table_column) == (
        by_text["서류접수"].table_id,
        by_text["서류접수"].table_column,
    )
    assert by_text["온라인 진행"].table_column == by_text["인적성검사"].table_column
    assert by_text["11.20(금)"].table_column == by_text["실무면접"].table_column
    SourceLedger.model_validate(result.model_dump())


def test_low_confidence_cannot_turn_a_complete_topic_into_a_discardable_caption():
    observation = unit("topic", "4. Robot 관련 연구 개발", 0.1, 0.1)
    observation.confidence = 0.7
    result = build_source_ledger([observation])
    assert result.blocks[0].kind != "caption"
    assert result.blocks[0].source_text == observation.source_text


def test_wide_paragraph_line_keeps_its_shorter_attached_restriction():
    units = [
        unit("title", "연구활동 지원 프로그램", 0.06, 0.04, 0.88, 0.06),
        unit("left-a", "왼쪽 열의 독립적인 문장", 0.06, 0.2, 0.39),
        unit("right-a", "오른쪽 열의 독립적인 문장", 0.55, 0.2, 0.4),
        unit("left-b", "왼쪽 열의 이어지는 설명", 0.06, 0.231, 0.39),
        unit("right-b", "오른쪽 열의 이어지는 설명", 0.55, 0.231, 0.4),
        unit(
            "condition-a",
            "다른 프로그램에서 지원하는 과제와 동일한 연구를",
            0.06,
            0.4,
            0.88,
        ),
        unit("condition-b", "수행하는 경우 지원 및 참여 제한", 0.06, 0.431, 0.39),
    ]
    result = build_source_ledger(units)
    assert any(
        block.unit_ids == ["condition-a", "condition-b"] for block in result.blocks
    )
    assert any(block.unit_ids == ["left-a", "left-b"] for block in result.blocks)
    assert any(block.unit_ids == ["right-a", "right-b"] for block in result.blocks)
    assert result.blocks[0].unit_ids == ["title"]


def test_actual_contest_prize_grid_keeps_categories_counts_and_amounts_together():
    fixture = json.loads(
        (FIXTURES / "campus_video_prizes_geometry.json").read_text(encoding="utf-8")
    )
    result = build_source_ledger(
        [SourceUnit.model_validate(value) for value in fixture["units"]]
    )
    by_text = {unit.source_text: unit for unit in result.units}
    for label, values in (
        ("최우수상", ["1작품", "팀100만원", "개인 50만원"]),
        ("우수상", ["3작품", "팀50만원", "개인 25만원"]),
    ):
        header = by_text[label]
        assert header.table_id is not None
        assert all(
            (by_text[value].table_id, by_text[value].table_column)
            == (header.table_id, header.table_column)
            for value in values
        )
    assert by_text["최우수상"].table_column != by_text["우수상"].table_column
    assert len({unit.id for unit in result.units}) == 11
