from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from openai import OpenAIError

from app.models import (
    BoundingBox,
    LedgerMetrics,
    LedgerVisionRegion,
    SourceBlock,
    SourceLedger,
    SourceUnit,
)
from app.services.ledger_semantic import (
    LedgerSemanticItem,
    LedgerSemanticResponse,
    analyze_ledger,
)
from app.services.ledger_translation import best_effort_english
from app.services.text import simplified_text


FIXTURES = Path(__file__).parent / "fixtures"
USAGE = SimpleNamespace(input_tokens=100, output_tokens=40, total_tokens=140)


class Responses:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    async def parse(self, **kwargs):
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        if isinstance(response, tuple):
            parsed, usage = response
        else:
            parsed, usage = response, USAGE
        if isinstance(parsed, LedgerSemanticResponse):
            # The test catalog uses U1..Un. The transport sends compact U000..
            # aliases and required block keys; model citations are not trusted.
            source = json.loads(kwargs["input"][1]["content"][0]["text"])
            blocks = {}
            for block in source["blocks"]:
                ids = [f"U{int(alias[1:]) + 1}" for alias in block["unit_ids"]]
                matches = [item for item in parsed.items if item.source_unit_ids == ids]
                if len(matches) == 1:
                    match = matches[0]
                    blocks[block["id"]] = dict(
                        kind=match.kind,
                        translations={alias: match.text for alias in block["unit_ids"]},
                        recoveries=[],
                    )
            parsed = {"required_blocks": blocks}
        if isinstance(parsed, dict) and "required_blocks" in parsed:
            blocks = parsed["required_blocks"]
            parsed = {
                "unit_translations": {
                    alias: text
                    for block in blocks.values()
                    for alias, text in block["translations"].items()
                },
                "block_kinds": {
                    alias: block["kind"] for alias, block in blocks.items()
                },
                "recoveries": [
                    entry
                    for block in blocks.values()
                    for entry in block.get("recoveries", [])
                ],
            }
        return SimpleNamespace(output_parsed=parsed, usage=usage)


def ledger(pairs: list[tuple[str, str]], *, grouped: bool = False) -> SourceLedger:
    units = [
        SourceUnit(
            id=f"U{index}",
            page_number=1,
            image_id="image-1",
            order=index,
            source_text=source,
            english=english,
            translation_status="translated",
            translation_provider="fixture",
            translation_source_ids=[f"U{index}"],
            block_id="B1" if grouped else f"B{index}",
            section_id="section-1",
        )
        for index, (source, english) in enumerate(pairs, 1)
    ]
    if grouped:
        blocks = [
            SourceBlock(
                id="B1",
                unit_ids=[unit.id for unit in units],
                source_text="\n".join(source for source, _ in pairs),
                english=" ".join(english for _, english in pairs),
                translation_status="translated",
                section_id="section-1",
            )
        ]
    else:
        blocks = [
            SourceBlock(
                id=unit.block_id,
                unit_ids=[unit.id],
                source_text=unit.source_text,
                english=unit.english,
                translation_status="translated",
                section_id=unit.section_id,
            )
            for unit in units
        ]
    return SourceLedger(units=units, blocks=blocks)


def item(
    ids: list[str], text: str, kind: str = "detail", heading: str = ""
) -> LedgerSemanticItem:
    return LedgerSemanticItem(
        kind=kind, heading=heading, text=text, source_unit_ids=ids
    )


def run(source: SourceLedger, responses: Responses, **kwargs):
    return asyncio.run(
        analyze_ledger(source, client=SimpleNamespace(responses=responses), **kwargs)
    )


def payload(call: dict) -> dict:
    data = json.loads(call["input"][1]["content"][0]["text"])
    data["target_ids"] = [f"U{int(unit['id'][1:]) + 1}" for unit in data["units"]]
    return data


def assert_survives(outcome) -> None:
    ids = {unit.id for unit in outcome.ledger.units}
    assert set(outcome.ledger.coverage.source_unit_ids) == ids
    assert (
        set(outcome.ledger.coverage.semantic_unit_ids)
        | set(outcome.ledger.coverage.fallback_unit_ids)
        == ids
    )
    assert all(unit.semantic_refs for unit in outcome.ledger.units)
    assert all(unit.display_destinations == [] for unit in outcome.ledger.units)
    assert outcome.ledger.coverage.displayed_unit_ids == []
    assert outcome.ledger.coverage.meaning_checked is False
    assert not any(
        "가" <= character <= "힣" for character in simplified_text(outcome.notice)
    )


def test_complete_result_uses_one_request_and_configured_model(monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o-mini")
    source = ledger(
        [
            ("신청 마감 2026.09.20 18:00", "Apply by September 20, 2026 at 18:00."),
            ("학생 행사", "Student event."),
        ]
    )
    source.metrics = LedgerMetrics(
        ocr_ms=50, translation_ms=60, semantic_requests=9, input_tokens=900
    )
    responses = Responses(
        LedgerSemanticResponse(
            items=[item([unit.id], unit.english) for unit in source.units]
        )
    )
    outcome = run(source, responses)
    assert len(responses.calls) == 1
    assert responses.calls[0]["model"] == "gpt-4o-mini"
    assert outcome.ledger.metrics.semantic_requests == 1
    assert outcome.ledger.metrics.input_tokens == 100
    assert outcome.ledger.metrics.output_tokens == 40
    assert outcome.ledger.metrics.total_tokens == 140
    assert (
        outcome.ledger.metrics.ocr_ms == 50
        and outcome.ledger.metrics.translation_ms == 60
    )
    assert source.metrics.input_tokens == 900
    assert source.units[0].semantic_refs == []
    assert_survives(outcome)


def test_omitted_unit_has_targeted_repair_and_english_fallback_if_retry_omits_it():
    source = ledger(
        [
            ("학생 행사", "Student event."),
            ("문의 test@example.com", "Contact test@example.com."),
        ]
    )
    responses = Responses(
        LedgerSemanticResponse(items=[item(["U1"], "Student event.")]),
        LedgerSemanticResponse(),
    )
    outcome = run(source, responses)
    assert payload(responses.calls[1])["target_ids"] == ["U2"]
    assert outcome.ledger.coverage.semantic_unit_ids == ["U1"]
    assert outcome.ledger.coverage.fallback_unit_ids == ["U2"]
    assert "test@example.com" in simplified_text(outcome.notice)
    assert "could not be verified" not in simplified_text(outcome.notice)
    assert_survives(outcome)


@pytest.mark.parametrize(
    "bad_item",
    [
        item(["U1"], "Funding is KRW 999,000."),
        item(["U1", "missing"], "Funding is KRW 200,000."),
        item(["U1", "U1"], "Funding is KRW 200,000."),
        item(["U1"], "연구비 is KRW 200,000."),
    ],
)
def test_rejected_generated_item_is_replaced_using_same_source_ids(bad_item):
    source = ledger([("연구비 20만원", "Research funding is KRW 200,000.")])
    responses = Responses(
        LedgerSemanticResponse(items=[bad_item]), LedgerSemanticResponse()
    )
    outcome = run(source, responses)
    assert payload(responses.calls[1])["target_ids"] == ["U1"]
    assert "999,000" not in simplified_text(outcome.notice)
    assert "KRW 200,000" in simplified_text(outcome.notice)
    assert outcome.notice.key_details[0].source_unit_ids == ["U1"]
    assert outcome.ledger.coverage.fallback_unit_ids == ["U1"]
    assert_survives(outcome)


def test_duplicate_source_assignments_do_not_drop_a_conflicting_unit():
    source = ledger([("학생 행사", "Student event.")])
    responses = Responses(
        LedgerSemanticResponse(
            items=[item(["U1"], "Student event."), item(["U1"], "A different event.")]
        ),
        LedgerSemanticResponse(),
    )
    outcome = run(source, responses)
    assert "A different event" not in simplified_text(outcome.notice)
    assert "Student event" in simplified_text(outcome.notice)
    assert_survives(outcome)


def test_targeted_repair_does_not_rewrite_previously_accepted_units():
    source = ledger(
        [
            ("학생 행사", "Student event."),
            ("신청 마감 2026.09.20", "Apply by September 20, 2026."),
        ]
    )
    responses = Responses(
        LedgerSemanticResponse(items=[item(["U1"], "Student event.")]),
        LedgerSemanticResponse(
            items=[item(["U1", "U2"], "Different event; apply September 20, 2026.")]
        ),
    )
    outcome = run(source, responses)
    assert "Different event" not in simplified_text(outcome.notice)
    assert "Student event" in simplified_text(outcome.notice)
    assert_survives(outcome)


def test_no_blocks_and_partial_blocks_still_retain_every_source_unit():
    source = ledger([("학생 행사", "Student event."), ("온라인 신청", "Apply online.")])
    source.blocks = source.blocks[:1]
    outcome = asyncio.run(analyze_ledger(source, provider="mock"))
    assert "Apply online" in simplified_text(outcome.notice)
    assert_survives(outcome)
    source.blocks = []
    assert_survives(asyncio.run(analyze_ledger(source, provider="mock")))


def test_source_crop_and_romanized_values_remain_when_no_english_can_be_established():
    source = ledger([("흐릿한 문의 02.710.25n0", "")])
    source.units[0].translation_status = "source_crop"
    source.blocks[0].translation_status = "source_crop"
    outcome = run(source, Responses(OpenAIError("Service unavailable")))
    assert "Source wording (romanized)" not in simplified_text(outcome.notice)
    assert "Source wording (romanized)" in outcome.ledger.units[0].english
    assert "25n0" in outcome.ledger.units[0].english
    assert "02-710-2500" not in simplified_text(outcome.notice)
    assert outcome.ledger.metrics.semantic_requests == 1
    assert outcome.ledger.metrics.input_tokens is None
    assert outcome.ledger.metrics.output_tokens is None
    assert outcome.ledger.metrics.total_tokens is None
    assert outcome.ledger.metrics.usage_complete is False
    assert_survives(outcome)


def test_failed_retry_keeps_known_token_totals_and_marks_unknown_usage():
    source = ledger([("학생 행사", "Student event.")])
    outcome = run(
        source, Responses(LedgerSemanticResponse(), OpenAIError("Retry unavailable"))
    )
    assert outcome.ledger.metrics.semantic_requests == 2
    assert outcome.ledger.metrics.total_tokens == 140
    assert outcome.ledger.metrics.usage_complete is False
    assert_survives(outcome)


def test_success_without_usage_is_unknown_not_zero():
    source = ledger([("학생 행사", "Student event.")])
    outcome = run(
        source,
        Responses(
            (LedgerSemanticResponse(items=[item(["U1"], "Student event.")]), None)
        ),
    )
    assert outcome.ledger.metrics.total_tokens is None
    assert outcome.ledger.metrics.usage_complete is False


def test_valid_pending_translation_repair_updates_unit_and_block():
    source = ledger([("온라인 신청", "")])
    source.units[0].translation_status = "pending"
    source.blocks[0].translation_status = "pending"
    response = LedgerSemanticResponse(items=[item(["U1"], "Apply online.")])
    outcome = run(source, Responses(response))
    assert outcome.ledger.units[0].english == "Apply online."
    assert outcome.ledger.units[0].translation_status == "translated"
    assert outcome.ledger.blocks[0].english == "Apply online."
    assert outcome.ledger.blocks[0].translation_status == "translated"
    assert_survives(outcome)


def test_accepted_semantic_item_can_supply_missing_unit_translation_without_extra_request():
    source = ledger([("온라인 신청", "")])
    source.units[0].translation_status = "literal"
    source.blocks[0].translation_status = "literal"
    outcome = run(
        source, Responses(LedgerSemanticResponse(items=[item(["U1"], "Apply online.")]))
    )
    assert outcome.ledger.units[0].english == "Apply online."
    assert outcome.ledger.blocks[0].english == "Apply online."
    assert outcome.ledger.coverage.translated_unit_ids == ["U1"]
    assert outcome.ledger.metrics.semantic_requests == 1


def test_invalid_translation_repair_cannot_change_the_source_or_invent_an_amount():
    source = ledger([("지원금 20만원", "")])
    source.units[0].translation_status = "literal"
    response = LedgerSemanticResponse(items=[item(["U1"], "Funding is KRW 900,000.")])
    outcome = run(source, Responses(response, LedgerSemanticResponse()))
    assert outcome.ledger.units[0].source_text == "지원금 20만원"
    assert "900,000" not in simplified_text(outcome.notice)
    assert "KRW 200,000" in outcome.ledger.units[0].english
    assert_survives(outcome)


def test_spatial_table_pairings_override_flattened_header_order():
    source = ledger(
        [
            ("TOEIC", "TOEIC"),
            ("TEPS", "TEPS"),
            ("800 이상", "800 or higher"),
            ("309 이상", "309 or higher"),
        ],
        grouped=True,
    )
    for index, unit in enumerate(source.units):
        unit.table_id = "scores"
        unit.table_row = index // 2
        unit.table_column = index % 2
    source.blocks[0].table_id = "scores"
    source.blocks[0].english = "TOEIC: 800 or higher; TEPS: 309 or higher."
    bad = item(
        ["U1", "U2", "U3", "U4"], "TOEIC: 309 or higher; TEPS: 800 or higher.", "table"
    )
    good = item(
        ["U1", "U2", "U3", "U4"], "TOEIC: 800 or higher; TEPS: 309 or higher.", "table"
    )
    responses = Responses(
        LedgerSemanticResponse(items=[bad]), LedgerSemanticResponse(items=[good])
    )
    outcome = run(source, responses)
    assert "TOEIC\n800 or more\nTEPS\n309 or more" in simplified_text(outcome.notice)
    assert len(responses.calls) == 1
    assert outcome.ledger.coverage.fallback_unit_ids == []
    assert_survives(outcome)


def test_actual_score_geometry_uses_literal_cells_despite_model_alias_shift():
    from app.services.ledger_layout import build_source_ledger
    from app.services.ledger_translation import validate_protected_values

    fixture = json.loads(
        (FIXTURES / "kcci_2027_ledger_geometry.json").read_text(encoding="utf-8")
    )
    source = build_source_ledger(
        [SourceUnit.model_validate(value) for value in fixture["units"]]
    )
    source = build_source_ledger([unit for unit in source.units if unit.table_id])
    # The real model shifted labels and thresholds by one key. All these
    # standalone cells are deterministically readable from the source itself.
    translations = {f"U{index:03d}": "Above 999" for index in range(len(source.units))}
    from app.services.ledger_semantic import _catalog

    kinds = {
        alias: "table" if block.table_id else "detail"
        for alias, block in _catalog(source).items()
    }
    for index, unit in enumerate(source.units):
        if "논술" in unit.source_text:
            translations[f"U{index:03d}"] = "Essay: economics/current affairs."
        elif "3문제" in unit.source_text:
            translations[f"U{index:03d}"] = "Approximately 3 questions."
    responses = Responses(
        {"unit_translations": translations, "block_kinds": kinds, "recoveries": []}
    )
    outcome = run(source, responses)
    table = next(item for item in outcome.notice.key_details if "TOEIC" in item.text)
    assert (
        validate_protected_values(
            "TOEIC 800 이상; TEPS 309 이상; FLEX 2B 이상; TOEFL iBT 91 이상; TOEIC Speaking 150 이상; OPIc IM3 이상",
            table.text,
        )
        == []
    )
    assert "999" not in table.text
    assert len(responses.calls) == 1
    assert_survives(outcome)


def test_essay_question_count_cannot_move_to_english_score_test():
    source = ledger(
        [
            ("TOEIC: 800 이상", "TOEIC: 800 or higher."),
            (
                "논술: 경제/시사 분야 3문제 내외",
                "Essay: approximately 3 questions on economics/current affairs.",
            ),
        ],
        grouped=True,
    )
    bad = item(["U1", "U2"], "TOEIC: 800 or higher; approximately 3 questions.")
    good = item(
        ["U1", "U2"],
        "TOEIC: 800 or higher. Essay: approximately 3 questions on economics/current affairs.",
    )
    outcome = run(
        source,
        Responses(
            LedgerSemanticResponse(items=[bad]), LedgerSemanticResponse(items=[good])
        ),
    )
    assert "Essay: approximately 3 questions" in simplified_text(outcome.notice)
    assert outcome.ledger.coverage.fallback_unit_ids == []


def test_multi_line_negation_amount_time_and_contact_survive_filter_rejection():
    source = ledger(
        [
            ("휴학생도 참여 가능하나", "Students on leave may participate,"),
            (
                "연구비 및 활동비 지원 대상 제외",
                "but are excluded from research funding and activity allowances.",
            ),
            (
                "연구비 최대 20만원; 활동비 10만원",
                "Research funding: up to KRW 200,000; activity allowance: KRW 100,000.",
            ),
            (
                "마감 2026.09.20 18:00; 문의 help@example.com",
                "Deadline: September 20, 2026 at 18:00; contact help@example.com.",
            ),
        ],
        grouped=True,
    )
    bad = item(
        [unit.id for unit in source.units],
        "All students receive KRW 200,000; apply by September 20, 2026.",
    )
    outcome = run(
        source, Responses(LedgerSemanticResponse(items=[bad]), LedgerSemanticResponse())
    )
    digest = simplified_text(outcome.notice)
    assert "Students on leave may participate" in digest
    assert "excluded" in digest
    assert "100,000" in digest and "18:00" in digest and "help@example.com" in digest
    assert_survives(outcome)


SOGANG_ENGLISH = [
    "2026 second-semester Creative Convergence Free Research participant recruitment.",
    "Application period: August 24, 2026 to September 20, 2026.",
    "Submit the application form, research plan, and consent to collection and use of personal information via the extracurricular integrated management system (S Plus).",
    "Currently enrolled undergraduate students in the second semester of 2026.",
    "Students on leave may participate but are excluded from research funding and activity allowances.",
    "Teams of 2 to 5 undergraduate students.",
    "Students and teams receiving support from other on-campus programs for the same or similar research topic have restricted participation.",
    "Duplicate participation within the same program is not allowed.",
    "Research topic 1: designated topics proposed by the Institute for Convergence Education.",
    "Designated topic 1: discover AIX and develop MVP (Minimum Value Prototyping) for AI Wearable Device such as smart glasses.",
    'Designated topic 2: develop AI functions matching the motto "AI is Everywhere".',
    "Designated topic 3: research and development of fundamental AI technology.",
    "Designated topic 4: Robot research and development.",
    "Check the announcement for the detailed topics.",
    "Research topic 2: a topic independently chosen by students.",
    "Research funding: up to KRW 200,000 per person.",
    "Research funding can pay for equipment purchase and rental, materials, books, and printing.",
    "Visit the Institute for Convergence Education in person to pay by card.",
    "Activity allowance: KRW 200,000 per person.",
    "Costs outside the categories covered by research funding are paid as a scholarship.",
    "Contact the Convergence Education Innovation Team: 02-710-2500; convedu@sogang.ac.kr.",
]


def test_full_sogang_corrected_fixture_survives_semantic_omissions():
    lines = [
        line
        for line in (FIXTURES / "sogang_research_corrected.txt")
        .read_text(encoding="utf-8")
        .splitlines()
        if line and not line.startswith("[Page")
    ]
    assert len(lines) == len(SOGANG_ENGLISH)
    source = ledger(list(zip(lines, SOGANG_ENGLISH, strict=True)))
    outcome = run(
        source,
        Responses(
            LedgerSemanticResponse(items=[item(["U1"], SOGANG_ENGLISH[0], "heading")]),
            LedgerSemanticResponse(),
        ),
    )
    digest = simplified_text(outcome.notice)
    for phrase in (
        "application form, research plan",
        "Students on leave",
        "2 to 5",
        "same or similar",
        "Duplicate participation",
        "Minimum Value Prototyping",
        "AI is Everywhere",
        "fundamental AI",
        "Robot",
        "independently chosen",
        "equipment purchase and rental",
        "printing",
        "pay by card",
        "scholarship",
        "convedu@sogang.ac.kr",
    ):
        assert phrase in digest
    assert len(outcome.ledger.units) == 21
    assert len(outcome.ledger.coverage.fallback_unit_ids) == 20
    assert_survives(outcome)


def test_raw_sogang_fixture_retains_seal_observations_and_corrupted_phone_evidence():
    raw = json.loads(
        (FIXTURES / "sogang_research_2026_browser_ocr.json").read_text(encoding="utf-8")
    )
    source = ledger(
        [(entry["text"], best_effort_english(entry["text"])) for entry in raw["items"]]
    )
    for unit in source.units:
        unit.translation_status = "literal"
    outcome = run(source, Responses(OpenAIError("Service unavailable")))
    assert len(outcome.ledger.units) == len(raw["items"])
    assert [unit.source_text for unit in outcome.ledger.units] == [
        entry["text"] for entry in raw["items"]
    ]
    assert "2500" not in simplified_text(outcome.notice)
    assert "25n0" in "\n".join(unit.english for unit in outcome.ledger.units)
    assert_survives(outcome)


def test_kcci_fixture_retains_six_score_pairs_and_essay_scope_after_empty_output():
    source_text = (FIXTURES / "kcci_2027_corrected.txt").read_text(encoding="utf-8")
    required = [
        ("TOEIC: 800 이상", "TOEIC: 800 or higher."),
        ("TEPS: 309 이상", "TEPS: 309 or higher."),
        ("FLEX: 2B 이상", "FLEX: 2B or higher."),
        ("TOEFL (iBT): 91 이상", "TOEFL iBT: 91 or higher."),
        ("TOEIC Speaking: 150 이상", "TOEIC Speaking: 150 or higher."),
        ("OPIc: IM3 이상", "OPIc: IM3 or higher."),
        (
            "03 논술시험: 11. 2(월) 오후; 논술: 경제/시사 분야 3문제 내외",
            "Essay examination: November 2 in the afternoon; approximately 3 questions on economics/current affairs.",
        ),
        (
            "접수방법: 인터넷 접수; 방문, 우편, 이메일 접수 불가",
            "Apply online; in-person, postal, and email applications are not accepted.",
        ),
        (
            "졸업(예정)증명서, 성적증명서, 어학 성적표 및 자격증 등 서류는 면접전형 시 제출",
            "Submit graduation or expected-graduation certificates, transcripts, language-score reports, qualifications and other documents at the interview stage.",
        ),
        (
            "근무형식: 최종 합격 이후 3개월간 수습기간을 통해 업무 평가 실시 후 정규직 전환",
            "After final selection, performance is assessed during a 3-month probationary period before conversion to permanent employment.",
        ),
    ]
    assert all(korean in source_text for korean, _ in required)
    source = ledger(required)
    outcome = run(source, Responses(LedgerSemanticResponse(), LedgerSemanticResponse()))
    digest = simplified_text(outcome.notice)
    for english in (
        "TOEIC: 800",
        "TEPS: 309",
        "FLEX: 2B",
        "TOEFL iBT: 91",
        "TOEIC Speaking: 150",
        "OPIc: IM3",
        "approximately 3 questions",
        "not accepted",
        "expected-graduation",
        "3-month probationary",
    ):
        assert english in digest
    assert_survives(outcome)


def test_recovery_crop_is_bound_to_known_target_ids_and_small_crops_use_low_detail():
    source = ledger([("학생 행사", "Student event.")])
    source.units[0].box = BoundingBox(x=0.1, y=0.1, width=0.2, height=0.2)
    region = LedgerVisionRegion(
        unit_ids=["U1"], data_url="data:image/png;base64,iVBORw0KGgo="
    )
    responses = Responses(
        LedgerSemanticResponse(items=[item(["U1"], "Student event.")])
    )
    run(source, responses, regions=[region])
    content = responses.calls[0]["input"][1]["content"]
    assert content[1]["text"].endswith("U000")
    assert content[2]["detail"] == "low"
    assert content[2]["image_url"] == region.data_url


def test_no_provider_key_returns_translations_without_creating_a_provider(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    source = ledger([("학생 행사", "Student event.")])
    outcome = asyncio.run(analyze_ledger(source))
    assert outcome.ledger.metrics.semantic_requests == 0
    assert outcome.ledger.metrics.total_tokens == 0
    assert "Student event" in simplified_text(outcome.notice)
    assert_survives(outcome)


def test_required_unit_translations_preserve_each_wrapped_condition_fragment():
    source = ledger(
        [
            ("휴학생도 참여는 가능하나, 연구비 및", "Reading aid."),
            ("활동비 지원 대상에서는 제외", "Reading aid."),
            ("2~5명의 학부생으로 구성된 팀 단위", "Reading aid."),
        ],
        grouped=True,
    )
    english = [
        "Students on leave may participate, but are excluded from research funding",
        "and activity allowance support.",
        "Teams must consist of 2 to 5 undergraduate students.",
    ]
    response = {
        "required_blocks": {
            "B000": {
                "kind": "eligibility",
                "translations": dict(
                    zip(["U000", "U001", "U002"], english, strict=True)
                ),
                "recoveries": [],
            }
        }
    }
    calls = Responses(response)
    result = run(source, calls)
    assert len(calls.calls) == 1
    assert [unit.english for unit in result.ledger.units] == english
    assert all(unit.translation_source_ids == [unit.id] for unit in result.ledger.units)
    assert result.ledger.coverage.fallback_unit_ids == []
    schema = calls.calls[0]["text_format"].model_json_schema()
    translations = next(
        value for key, value in schema["$defs"].items() if key.endswith("Translations")
    )
    assert set(translations["required"]) == {"U000", "U001", "U002"}
    assert_survives(result)


def test_missing_nested_translation_retries_the_complete_connected_block():
    source = ledger(
        [
            ("온라인 신청", "Apply online."),
            ("문의 office@example.org", "Contact office@example.org."),
        ],
        grouped=True,
    )
    partial = {
        "required_blocks": {
            "B000": {
                "kind": "detail",
                "translations": {"U000": "Apply online."},
                "recoveries": [],
            }
        }
    }
    complete = {
        "required_blocks": {
            "B000": {
                "kind": "detail",
                "translations": {
                    "U000": "Apply online.",
                    "U001": "Contact office@example.org.",
                },
                "recoveries": [],
            }
        }
    }
    calls = Responses(partial, complete)
    result = run(source, calls)
    assert payload(calls.calls[1])["target_ids"] == ["U1", "U2"]
    assert result.ledger.coverage.fallback_unit_ids == []
    assert_survives(result)


def test_explicit_unreadable_caption_keeps_crop_without_repeating_noise():
    source = ledger([("ㄱㅁ ㅂㄷ", "An invented instruction.")])
    source.blocks[0].kind = "caption"
    response = {
        "required_blocks": {
            "B000": {"kind": "detail", "translations": {"U000": ""}, "recoveries": []}
        }
    }
    calls = Responses(response)
    result = run(source, calls)
    assert len(calls.calls) == 1
    assert result.ledger.units[0].translation_status == "source_crop"
    assert "invented instruction" not in simplified_text(result.notice)
    assert result.ledger.coverage.fallback_unit_ids == ["U1"]
    assert_survives(result)


def test_complete_observed_phone_candidate_is_recovered_without_guessing():
    from app.models import OcrCandidate

    source = ledger([("문의 02.710.25n0 | office@example.org", "")])
    candidate = "문의 02.710.2500 | office@example.org"
    source.units[0].alternatives = [OcrCandidate(text=candidate, confidence=0.99)]
    source.units[0].translation_status = "source_crop"
    calls = Responses(
        {
            "required_blocks": {
                "B000": {
                    "kind": "contact",
                    "translations": {
                        "U000": "Contact 02-710-2500; office@example.org."
                    },
                    "recoveries": [],
                }
            }
        }
    )
    result = run(source, calls)
    assert result.ledger.units[0].source_text == source.units[0].source_text
    assert result.ledger.units[0].recovered_source_text == candidate
    assert result.ledger.units[0].recovery_source == "ocr_candidate"
    assert "2500" in simplified_text(result.notice)
    assert len(calls.calls) == 1
    assert_survives(result)


def test_higher_confidence_conflicting_date_cannot_override_original():
    from app.models import OcrCandidate

    source = ledger([("마감 2026.09.20", "Deadline September 20, 2026.")])
    source.units[0].confidence = 0.7
    source.units[0].alternatives = [
        OcrCandidate(text="마감 2026.09.28", confidence=0.99)
    ]
    response = {
        "required_blocks": {
            "B000": {
                "kind": "deadline",
                "translations": {"U000": "Deadline September 20, 2026."},
                "recoveries": [],
            }
        }
    }
    result = run(source, Responses(response))
    assert result.ledger.units[0].recovered_source_text is None
    assert result.notice.deadlines[0].date == "2026.09.20"
    assert "September 28" not in simplified_text(result.notice)


def test_client_claimed_recovery_and_display_counts_are_not_trusted():
    source = ledger([("온라인 신청", "Apply online.")])
    source.units[0].recovered_source_text = "장학금 900만원"
    source.units[0].recovery_source = "vision"
    source.units[0].display_destinations = ["translated_image"]
    calls = Responses(
        {
            "required_blocks": {
                "B000": {
                    "kind": "action",
                    "translations": {"U000": "Apply online."},
                    "recoveries": [],
                }
            }
        }
    )
    result = run(source, calls)
    assert payload(calls.calls[0])["units"][0]["source"] == "온라인 신청"
    assert result.ledger.units[0].recovered_source_text is None
    assert_survives(result)


def test_invalid_recovery_cannot_replace_source_or_retry_valid_english():
    source = ledger([("문의 02-123-4567", "Contact 02-123-4567.")])
    response = {
        "required_blocks": {
            "B000": {
                "kind": "contact",
                "translations": {"U000": "Contact 02-123-4567."},
                "recoveries": [
                    {
                        "source_unit_id": "U000",
                        "recovered_source_text": "Contact 02-123-9999",
                        "method": "ocr_candidate",
                    }
                ],
            }
        }
    }
    calls = Responses(response)
    result = run(source, calls)
    assert len(calls.calls) == 1
    assert result.ledger.units[0].recovered_source_text is None
    assert "9999" not in simplified_text(result.notice)
    assert_survives(result)


def test_repair_of_a_legible_empty_unit_replaces_its_entire_block():
    source = ledger(
        [("학생 행사", "Student event."), ("온라인 신청", "Apply online.")],
        grouped=True,
    )
    first = {
        "unit_translations": {"U000": "Student event.", "U001": ""},
        "block_kinds": {"B000": "detail"},
        "recoveries": [],
    }
    second = {
        "unit_translations": {"U000": "Student event.", "U001": "Apply online."},
        "block_kinds": {"B000": "detail"},
        "recoveries": [],
    }
    calls = Responses(first, second)
    result = run(source, calls)
    assert payload(calls.calls[1])["target_ids"] == ["U1", "U2"]
    assert result.ledger.coverage.fallback_unit_ids == []
    assert_survives(result)


def test_abbreviated_deadline_range_keeps_both_printed_endpoints():
    source = ledger(
        [
            (
                "접수기간 2026.9.14(월)~9.30(수)18:00",
                "Apply from 2026.9.14 to 9.30 at 18:00.",
            )
        ]
    )
    result = run(
        source,
        Responses(
            {
                "unit_translations": {
                    "U000": "Application period: 2026.9.14 to 9.30 at 18:00."
                },
                "block_kinds": {"B000": "deadline"},
                "recoveries": [],
            }
        ),
    )
    assert result.notice.deadlines[0].date == "2026.9.14 – 9.30"
    assert result.notice.deadlines[0].time == "18:00"


@pytest.mark.parametrize(
    "source, english, destination",
    [
        (
            "입사지원서 내용이 허위일 경우 합격 및 입사 취소",
            "False application information will result in cancellation of acceptance and employment.",
            "consequences",
        ),
        (
            "자기소개서에 출신학교 기재 금지",
            "It is prohibited to name your school in the personal statement.",
            "warnings",
        ),
        ("근무장소 | 서울", "Work location: Seoul.", "locations"),
        (
            "근무형식 | 3개월 수습기간 후 정규직 전환",
            "Work arrangement: conversion to permanent employment after a 3-month probationary period.",
            "key_details",
        ),
        (
            "2027년 2월 졸업예정자",
            "Applicants expecting to graduate in February 2027.",
            "eligibility",
        ),
    ],
)
def test_readable_employment_conditions_keep_their_roles_despite_wrong_model_label(
    source, english, destination
):
    outcome = run(
        ledger([(source, english)]),
        Responses(LedgerSemanticResponse(items=[item(["U1"], english, "document")])),
    )
    assert len(getattr(outcome.notice, destination)) == 1
    assert outcome.notice.required_documents == []


def test_a_large_english_logo_does_not_replace_the_korean_notice_title():
    source = ledger(
        [("KCGI", "KCGI"), ("신입직원 채용", "Recruitment of New Employees")]
    )
    for unit, height in zip(source.units, [0.1, 0.05], strict=True):
        unit.box = BoundingBox(x=0.1, y=0.1, width=0.4, height=height)
    for block in source.blocks:
        block.kind = "heading"
    outcome = run(
        source,
        Responses(
            LedgerSemanticResponse(
                items=[
                    item(["U1"], "KCGI", "heading"),
                    item(["U2"], "Recruitment of New Employees", "heading"),
                ]
            )
        ),
    )
    assert outcome.notice.title == "Recruitment of New Employees"


def test_a_complete_block_cannot_hide_topics_swapped_between_source_ids():
    source = ledger(
        [
            ("4. Robot 관련 연구 개발", "Robot research and development."),
            ("2. 학생 자율 선정 주제", "Student-selected topics."),
        ],
        grouped=True,
    )
    bad = {
        "unit_translations": {
            "U000": "Student-selected topics.",
            "U001": "Robot research and development.",
        },
        "block_kinds": {"B000": "detail"},
        "recoveries": [],
    }
    good = {
        "unit_translations": {
            "U000": "4. Robot research and development.",
            "U001": "2. Student-selected topics.",
        },
        "block_kinds": {"B000": "detail"},
        "recoveries": [],
    }
    calls = Responses(bad, good)
    outcome = run(source, calls)
    assert len(calls.calls) == 2
    assert outcome.ledger.units[0].english == "4. Robot research and development."
    assert outcome.ledger.coverage.fallback_unit_ids == []


def test_funding_categories_cannot_swap_even_when_their_amounts_are_identical():
    source = ledger([("연구비:1인당 최대 20만원", ""), ("활동비:1인당 20만원", "")])
    calls = Responses(
        {
            "unit_translations": {
                "U000": "Activity funding: KRW 200,000.",
                "U001": "Research funding: KRW 200,000.",
            },
            "block_kinds": {"B000": "funding", "B001": "funding"},
            "recoveries": [],
        }
    )
    outcome = run(source, calls)
    assert "Research funding: up to KRW 200,000 per person." in simplified_text(
        outcome.notice
    )
    assert "Activity funding: KRW 200,000 per person." in simplified_text(
        outcome.notice
    )
    assert len(calls.calls) == 1


def test_card_payment_at_the_center_cannot_become_an_either_or_choice():
    source = ledger(
        [("융합교육원에 방문하여 카드결제", "Visit the center and pay by card.")]
    )
    calls = Responses(
        LedgerSemanticResponse(
            items=[
                item(
                    ["U1"],
                    "Payments can be made in person or by card at the center.",
                    "funding",
                )
            ]
        ),
        LedgerSemanticResponse(
            items=[item(["U1"], "Visit the center and pay by card.", "funding")]
        ),
    )
    outcome = run(source, calls)
    assert len(calls.calls) == 2
    assert "or by card" not in simplified_text(outcome.notice)
    assert "Visit the center and pay by card." in simplified_text(outcome.notice)


def test_fluent_semantic_english_does_not_hide_an_unrecovered_uncertain_source_crop():
    source = ledger([("학생 행사", "Student event.")])
    source.units[0].confidence = 0.7
    outcome = run(
        source,
        Responses(LedgerSemanticResponse(items=[item(["U1"], "Student event.")])),
    )
    assert outcome.ledger.units[0].english == "Student event."
    assert outcome.ledger.units[0].translation_status == "source_crop"
    assert outcome.ledger.coverage.semantic_unit_ids == ["U1"]
    assert outcome.ledger.coverage.fallback_unit_ids == ["U1"]
    assert outcome.ledger.coverage.translated_unit_ids == []


def test_unreadable_stamp_cannot_invent_a_calendar_date_or_be_dumped_into_instructions():
    source = ledger([("기간입C이끼지", best_effort_english("기간입C이끼지"))])
    source.units[0].translation_status = "source_crop"
    source.blocks[0].translation_status = "source_crop"
    response = LedgerSemanticResponse(items=[item(["U1"], "Until September 16")])
    outcome = run(source, Responses(response, response))
    assert "September 16" not in simplified_text(outcome.notice)
    assert "romanized" not in simplified_text(outcome.notice)
    assert outcome.ledger.units[0].source_text == "기간입C이끼지"
    assert outcome.ledger.units[0].english == best_effort_english("기간입C이끼지")
    assert outcome.ledger.units[0].semantic_refs == ["translation_view"]


def test_partial_machine_reading_with_romanization_stays_beside_its_source_crop():
    partial = (
        "Partial English reading: Attachment 9 From CO\n"
        "Source wording (romanized): buchak9ipCOimbuteo"
    )
    source = ledger([("부착9입CO임부터", partial)])
    source.units[0].translation_status = "source_crop"
    source.blocks[0].translation_status = "source_crop"
    outcome = run(source, Responses(OpenAIError("Provider unavailable")))
    assert "Attachment 9" not in simplified_text(outcome.notice)
    assert "romanized" not in simplified_text(outcome.notice)
    assert outcome.ledger.units[0].english == partial
    assert outcome.ledger.units[0].semantic_refs == ["translation_view"]
    assert_survives(outcome)


def test_clear_enrollment_and_team_cells_survive_incorrect_model_translations():
    source = ledger(
        [
            ("가상대학교 학부 재학생(휴학생 참가 가능)", ""),
            ("개인 또는 팀(3인 이내) 참가 가능", ""),
        ],
        grouped=True,
    )
    calls = Responses(
        {
            "unit_translations": {"U000": "Students.", "U001": "Teams of 5 people."},
            "block_kinds": {"B000": "eligibility"},
            "recoveries": [],
        }
    )
    outcome = run(source, calls)
    digest = simplified_text(outcome.notice)
    assert "Currently enrolled undergraduate students" in digest
    assert "Students on leave may participate" in digest
    assert "teams of up to 3 people" in digest
    assert "5 people" not in digest
    assert len(calls.calls) == 1
    assert outcome.ledger.coverage.semantic_unit_ids == ["U1", "U2"]


def test_numeric_stamp_dates_cannot_hide_inside_an_otherwise_readable_block():
    source = ledger(
        [
            ("기간입C이끼지", best_effort_english("기간입C이끼지")),
            ("학생문화처", "Student Cultural Office"),
            ("UNIV", "UNIV"),
            ("9입입부터", best_effort_english("9입입부터")),
        ],
        grouped=True,
    )
    bad = {
        "unit_translations": {
            "U000": "Until 9/16",
            "U001": "Student Cultural Office",
            "U002": "UNIV",
            "U003": "from 9/10",
        },
        "block_kinds": {"B000": "document"},
        "recoveries": [],
    }
    outcome = run(source, Responses(bad, bad))
    digest = simplified_text(outcome.notice)
    assert "9/16" not in digest and "9/10" not in digest
    assert "romanized" not in digest
    assert_survives(outcome)
