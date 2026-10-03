from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from app.models import BoundingBox, OcrCandidate, SourceBlock, SourceLedger, SourceUnit
from app.services import ledger_translation
from app.services.ledger_translation import (
    ChunkTranslation,
    best_effort_english,
    translate_ledger,
    validate_protected_values,
)
from app.services.translation import (
    MyMemoryTranslationProvider,
    TranslationError,
    TranslationProvider,
    TranslationResult,
)


class TestProvider(TranslationProvider):
    __test__ = False
    name = "test-provider"

    def __init__(self, translations: dict[str, str | Exception]) -> None:
        self.translations = translations
        self.calls: list[str] = []
        self.active = 0
        self.max_active = 0

    async def translate(
        self, text: str, source_language: str, target_language: str
    ) -> TranslationResult:
        assert (source_language, target_language) == ("ko", "en")
        assert len(text.encode("utf-8")) <= 480
        self.calls.append(text)
        self.active += 1
        self.max_active = max(self.active, self.max_active)
        try:
            await asyncio.sleep(0)
            value = self.translations[text]
            if isinstance(value, Exception):
                raise value
            return TranslationResult(value, self.name, 1)
        finally:
            self.active -= 1


def make_ledger(*sources: str, grouped: bool = False) -> SourceLedger:
    units = [
        SourceUnit(
            id=f"u{index}",
            page_number=1,
            image_id="image-1",
            order=index,
            source_text=text,
        )
        for index, text in enumerate(sources)
    ]
    blocks = (
        [SourceBlock(id="b0", unit_ids=[unit.id for unit in units])]
        if grouped
        else [
            SourceBlock(id=f"b{index}", unit_ids=[unit.id])
            for index, unit in enumerate(units)
        ]
    )
    return SourceLedger(units=units, blocks=blocks)


def test_unit_and_duplicate_text_associations_survive_provider_deduplication():
    ledger = make_ledger("문의", "지원 방법", "문의")
    provider = TestProvider({"문의": "Contact", "지원 방법": "How to apply"})
    result = asyncio.run(translate_ledger(ledger, provider=provider))
    assert [unit.id for unit in result.units] == ["u0", "u1", "u2"]
    assert [unit.english for unit in result.units] == [
        "Contact",
        "How to apply",
        "Contact",
    ]
    assert [unit.translation_source_ids for unit in result.units] == [
        ["u0"],
        ["u1"],
        ["u2"],
    ]
    assert provider.calls == ["문의", "지원 방법"]
    assert result.metrics.translation_requests == 2
    assert result.coverage.translated_unit_ids == ["u0", "u1", "u2"]
    assert not result.coverage.meaning_checked
    assert result.coverage.displayed_unit_ids == []
    assert ledger.units[0].english == ""


def test_group_translation_covers_every_original_unit_without_replacing_inventory():
    ledger = make_ledger(
        "휴학생도 참여 가능", "연구비 지원 대상에서 제외", grouped=True
    )
    provider = TestProvider(
        {
            "휴학생도 참여 가능\n연구비 지원 대상에서 제외": "Students on leave may participate but are excluded from research funding."
        }
    )
    result = asyncio.run(translate_ledger(ledger, provider=provider))
    assert len(result.units) == 2
    assert result.units[0].english == result.units[1].english
    assert all(unit.translation_source_ids == ["u0", "u1"] for unit in result.units)
    assert (
        result.blocks[0].source_text == "휴학생도 참여 가능\n연구비 지원 대상에서 제외"
    )
    assert result.blocks[0].translation_status == "translated"


def test_chunks_are_reconciled_by_explicit_id_when_responses_are_reordered():
    ledger = make_ledger("문의", "신청 방법")

    async def transport(chunks):
        return [
            ChunkTranslation(chunks[1].id, "How to apply"),
            ChunkTranslation(chunks[0].id, "Contact"),
        ]

    result = asyncio.run(translate_ledger(ledger, translate_chunks=transport))
    assert [unit.english for unit in result.units] == ["Contact", "How to apply"]
    assert result.metrics.usage_complete


@pytest.mark.parametrize(
    "failure", ["missing", "duplicate", "empty", "hangul", "error", "foreign"]
)
def test_partial_or_malformed_chunk_responses_preserve_every_unit_with_source_fallback(
    failure,
):
    ledger = make_ledger("문의", "신청 방법")

    async def transport(chunks):
        good = ChunkTranslation(chunks[0].id, "Contact")
        bad = {
            "missing": [],
            "duplicate": [
                ChunkTranslation(chunks[1].id, "How to apply"),
                ChunkTranslation(chunks[1].id, "Apply"),
            ],
            "empty": [ChunkTranslation(chunks[1].id, "")],
            "hangul": [ChunkTranslation(chunks[1].id, "신청 method")],
            "error": [
                ChunkTranslation(
                    chunks[1].id, error="Quota exhausted", usage_complete=False
                )
            ],
            "foreign": [ChunkTranslation("foreign-id", "How to apply")],
        }[failure]
        return [good, *bad]

    result = asyncio.run(translate_ledger(ledger, translate_chunks=transport))
    assert result.units[0].english == "Contact"
    assert result.units[1].translation_status == "source_crop"
    assert result.units[1].english.startswith("Source wording (romanized):")
    assert not ledger_translation.HANGUL.search(result.units[1].english)
    assert result.coverage.source_unit_ids == ["u0", "u1"]
    assert result.coverage.translated_unit_ids == ["u0"]
    assert result.coverage.fallback_unit_ids == ["u1"]
    assert result.coverage.protected_value_gaps


def test_bounded_chunks_keep_successful_reading_and_missing_chunk_source_evidence():
    first, second = "첫 번째 안내 " * 23, "두 번째 안내 " * 23
    ledger = make_ledger(first, second, grouped=True)

    async def transport(chunks):
        assert len(chunks) > 1
        assert all(len(chunk.text.encode("utf-8")) <= 480 for chunk in chunks)
        return [ChunkTranslation(chunks[0].id, "First instructions")]

    result = asyncio.run(translate_ledger(ledger, translate_chunks=transport))
    assert result.blocks[0].english.startswith(
        "Partial English reading: First instructions"
    )
    assert "Source wording (romanized):" in result.blocks[0].english
    assert all(unit.translation_status == "source_crop" for unit in result.units)
    assert all(unit.translation_source_ids == ["u0", "u1"] for unit in result.units)


def test_non_korean_and_literal_threshold_cells_use_no_external_requests():
    ledger = make_ledger(
        "https://example.org/apply", "TOEIC Speaking", "150 이상", "2B 이상", "IM3 이상"
    )
    provider = TestProvider({})
    result = asyncio.run(translate_ledger(ledger, provider=provider))
    assert provider.calls == []
    assert [unit.english for unit in result.units] == [
        "https://example.org/apply",
        "TOEIC Speaking",
        "150 or more",
        "2B or more",
        "IM3 or more",
    ]
    assert result.metrics.translation_requests == 0
    assert all(unit.translation_status == "translated" for unit in result.units)


def test_quota_failure_does_not_prevent_other_units_from_translating():
    ledger = make_ledger("문의", "제출 불가")
    provider = TestProvider(
        {"문의": "Contact", "제출 불가": TranslationError("Quota exhausted")}
    )
    result = asyncio.run(translate_ledger(ledger, provider=provider))
    assert result.units[0].english == "Contact"
    assert result.units[1].translation_status == "source_crop"
    assert result.units[1].source_text == "제출 불가"
    assert result.metrics.translation_requests == 2
    assert not result.metrics.usage_complete


def test_translation_unavailable_returns_all_units_without_korean_in_english(
    monkeypatch,
):
    def unavailable(mock):
        raise TranslationError("Not configured")

    monkeypatch.setattr(ledger_translation, "choose_translation_provider", unavailable)
    result = asyncio.run(
        translate_ledger(make_ledger("지원 방법", "연구비 20만원", "문의 02-710-2500"))
    )
    assert len(result.units) == 3
    assert all(unit.translation_status == "source_crop" for unit in result.units)
    assert all(
        unit.english and not ledger_translation.HANGUL.search(unit.english)
        for unit in result.units
    )
    assert "KRW 200,000" in result.units[1].english
    assert "02-710-2500" in result.units[2].english
    assert not result.metrics.usage_complete


@pytest.mark.parametrize(
    ("source", "english", "issue"),
    [
        ("기한 2026.09.20 18:00", "Deadline September 20, 2026", "missing time"),
        ("신청 https://example.org/apply?y=2026", "Apply online", "missing URL"),
        ("중복 참여 불허", "Duplicate participation is allowed", "negation"),
        ("휴학생 참여 가능", "Students may participate", "leave-of-absence"),
        ("학부 재학생", "Undergraduates", "enrolled-student"),
        ("20만원 이하", "KRW 200,000 or more", "inclusive maximum"),
        ("800 미만", "800 or less", "exclusive maximum"),
        ("연구비 20만원", "Research funding KRW 300,000", "amount"),
        ("문의 02-710-2500", "Contact 02-710-2501", "contact"),
        (
            "TOEIC 800 이상\nTEPS 309 이상",
            "TOEIC 309 or more\nTEPS 800 or more",
            "pairing",
        ),
    ],
)
def test_generic_protected_value_guards_reject_losses_and_contradictions(
    source, english, issue
):
    assert any(
        issue in problem for problem in validate_protected_values(source, english)
    )


def test_exact_dates_amounts_contacts_times_and_eligibility_can_change_presentation():
    source = "재학생 및 휴학생 신청: 2026.09.20 오후 6시, 1인당 최대 20만원. 문의 02-710-2500 / convedu@sogang.ac.kr https://example.org/apply"
    english = "Enrolled students and students on leave: September 20, 2026, 18:00. Up to KRW 200,000 per person. Contact 02-710-2500 / convedu@sogang.ac.kr https://example.org/apply"
    assert validate_protected_values(source, english) == []


def test_kcci_six_exam_score_pairings_and_thresholds_are_protected():
    source = "\n".join(
        [
            "TOEIC: 800 이상",
            "TEPS: 309 이상",
            "FLEX: 2B 이상",
            "TOEFL (iBT): 91 이상",
            "TOEIC Speaking: 150 이상",
            "OPIc: IM3 이상",
        ]
    )
    english = "\n".join(
        [
            "TOEIC: 800 or more",
            "TEPS: 309 or more",
            "FLEX: 2B or more",
            "TOEFL iBT: 91 or more",
            "TOEIC Speaking: 150 or more",
            "OPIc: IM3 or more",
        ]
    )
    assert validate_protected_values(source, english) == []
    missing_pair = validate_protected_values(
        source, english.replace("TOEFL iBT: 91 or more", "TOEFL iBT: 309 or more")
    )
    assert any("toefl ibt / 91" in issue for issue in missing_pair)
    directions = validate_protected_values(
        source, english.replace("TEPS: 309 or more", "TEPS: 309 or less")
    )
    assert any("changed threshold direction: teps" in issue for issue in directions)


def test_wrong_protected_values_are_not_kept_as_partial_english_claims():
    provider = TestProvider({"연구비 20만원": "Research funding KRW 300,000"})
    result = asyncio.run(
        translate_ledger(make_ledger("연구비 20만원"), provider=provider)
    )
    assert "KRW 300,000" not in result.units[0].english
    assert "KRW 200,000" in result.units[0].english
    assert result.units[0].translation_status == "source_crop"


def test_alternate_ocr_negations_and_scores_remain_visible_as_conflicts():
    ledger = make_ledger("TOEIC 800 이상", "참여 불가")
    ledger.units[0].alternatives = [OcrCandidate(text="TOEIC 600 이상")]
    ledger.units[1].alternatives = [OcrCandidate(text="참여 가능")]
    provider = TestProvider(
        {
            "TOEIC 800 이상": "TOEIC 800 or more",
            "참여 불가": "Participation is not allowed",
        }
    )
    result = asyncio.run(translate_ledger(ledger, provider=provider))
    assert len(result.units) == 2
    assert [candidate.text for candidate in result.units[0].alternatives] == [
        "TOEIC 600 이상"
    ]
    assert any(
        "u0: OCR candidates disagree" in issue
        for issue in result.coverage.protected_value_gaps
    )
    assert any(
        "u1: OCR candidates disagree" in issue
        for issue in result.coverage.protected_value_gaps
    )


def test_provider_concurrency_is_bounded_and_unknown_errors_are_not_hidden():
    sources = [f"항목 {index}" for index in range(12)]
    provider = TestProvider(
        {source: f"Item {index}" for index, source in enumerate(sources)}
    )
    asyncio.run(translate_ledger(make_ledger(*sources), provider=provider))
    assert provider.max_active == 4
    assert provider.active == 0
    with pytest.raises(RuntimeError, match="programming failure"):
        asyncio.run(
            translate_ledger(
                make_ledger("문의"),
                provider=TestProvider({"문의": RuntimeError("programming failure")}),
            )
        )


def test_real_provider_chunks_share_pool_and_never_silently_concatenate_missing_response():
    active_clients = []

    def handle(request):
        active_clients.append(request.url.params["q"])
        return httpx.Response(
            200,
            json={"responseStatus": 200, "responseData": {"translatedText": "Contact"}},
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            return await translate_ledger(
                make_ledger("문의", "문의"),
                provider=MyMemoryTranslationProvider(client),
            )

    result = asyncio.run(run())
    assert active_clients == ["문의"]
    assert result.metrics.translation_requests == 1
    assert [unit.english for unit in result.units] == ["Contact", "Contact"]


@pytest.mark.parametrize(
    "source",
    [
        "",
        "800 이상",
        "ㄱㅅ 2026",
        "지원 불가 20만원 18:00",
        "문의 convedu@sogang.ac.kr",
        "https://example.org",
    ],
)
def test_source_fallback_never_leaks_korean_characters_or_invents_digits(source):
    fallback = best_effort_english(source)
    assert fallback
    assert not ledger_translation.HANGUL.search(fallback)
    if "20만원" in source:
        assert "KRW 200,000" in fallback


def test_synthetic_fixture_has_source_ids_for_columns_table_conditions_contacts_and_noise():
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "ledger_synthetic_layout.json").read_text(
            encoding="utf-8"
        )
    )
    ledger = SourceLedger.model_validate(fixture["ledger"])

    async def failed(chunks):
        return []

    result = asyncio.run(translate_ledger(ledger, translate_chunks=failed))
    assert [unit.id for unit in result.units] == [unit.id for unit in ledger.units]
    assert len({unit.id for unit in result.units}) == len(result.units)
    assert all(unit.english and unit.translation_source_ids for unit in result.units)
    assert {block.kind for block in result.blocks} >= {
        "heading",
        "table_cell",
        "condition",
        "caption",
    }
    assert not result.coverage.meaning_checked


def test_geometryless_or_empty_units_get_source_linked_fallback_even_without_blocks():
    ledger = SourceLedger(
        units=[
            SourceUnit(
                id="blank", page_number=1, image_id="photo", order=0, source_text=""
            ),
            SourceUnit(
                id="unpositioned",
                page_number=1,
                image_id="photo",
                order=1,
                source_text="문의",
            ),
        ]
    )
    result = asyncio.run(
        translate_ledger(ledger, provider=TestProvider({"문의": "Contact"}))
    )
    assert result.units[0].english == "Image detail: see the original crop."
    assert result.units[0].translation_status == "source_crop"
    assert result.units[1].english == "Contact"
    assert [block.unit_ids for block in result.blocks] == [["blank"], ["unpositioned"]]
    assert result.units[0].translation_source_ids == ["blank"]


@pytest.mark.parametrize(
    ("source", "english"),
    [
        ("50만원 이하", "KRW 500,000 or lower"),
        ("50만원 미만", "Less than KRW 500,000"),
        ("TOEFL (iBT): 91 이상", "TOEFL iBT: 91 or higher"),
        ("신청 18시 30분", "Apply by 6:30 pm"),
    ],
)
def test_valid_currency_thresholds_and_clock_notation_are_preserved(source, english):
    assert validate_protected_values(source, english) == []


@pytest.mark.parametrize(
    ("source", "english", "issue"),
    [
        ("시작 09:00", "Starts at 09:00 and 10:00", "unsupported time: 10:00"),
        (
            "신청 2026.10.20",
            "Apply on October 20, 2026 at 18:00",
            "unsupported time: 18:00",
        ),
        ("TOEIC", "TOEIC Speaking", "unsupported exam name: toeic speaking"),
        ("TOEFL", "TOEFL iBT", "unsupported exam name: toefl ibt"),
        ("TOEIC Speaking", "TOEIC", "unsupported exam name: toeic"),
        ("IELTS 7.0 이상", "IELTS 7.5 or higher", "pairing"),
    ],
)
def test_added_times_and_changed_exam_labels_are_rejected(source, english, issue):
    assert any(
        issue in problem for problem in validate_protected_values(source, english)
    )


@pytest.mark.parametrize(
    ("source", "english"),
    [
        ("수업 09:00", "Class at 9:00 am"),
        ("TOEFL (iBT) 91 이상", "TOEFLiBT 91 or higher"),
        ("IELTS 7.0 이상", "IELTS 7.0 or higher"),
    ],
)
def test_equivalent_clocks_exam_names_and_decimal_scores_are_allowed(source, english):
    assert validate_protected_values(source, english) == []


def test_fluent_machine_translation_of_uncertain_ocr_remains_source_crop_reading_aid():
    ledger = make_ledger("지용부착 자용해기")
    ledger.units[0].confidence = 0.7
    ledger.units[0].box = BoundingBox(x=0.9, y=0.1, width=0.05, height=0.02)
    provider = TestProvider(
        {"지용부착 자용해기": "Self-solving machine with liposuction adhesion"}
    )
    result = asyncio.run(translate_ledger(ledger, provider=provider))
    assert result.units[0].translation_status == "source_crop"
    assert result.units[0].english.startswith("Partial English reading:")
    assert "Source wording (romanized):" in result.units[0].english
    assert result.coverage.translated_unit_ids == []
    assert result.coverage.fallback_unit_ids == ["u0"]


def test_conflicting_high_confidence_wording_is_not_promoted_to_established_translation():
    ledger = make_ledger("문의")
    ledger.units[0].confidence = 0.99
    ledger.units[0].alternatives = [OcrCandidate(text="문예", confidence=0.97)]
    result = asyncio.run(
        translate_ledger(ledger, provider=TestProvider({"문의": "Contact"}))
    )
    assert result.units[0].translation_status == "source_crop"
    assert any(
        "different wording" in issue for issue in result.coverage.protected_value_gaps
    )


def test_long_orphan_id_keeps_original_mapping_with_bounded_block_id():
    source_id = "a" * 128
    source = SourceLedger(
        units=[
            SourceUnit(
                id=source_id,
                page_number=1,
                image_id="page",
                order=0,
                source_text="English text",
            )
        ]
    )
    result = asyncio.run(translate_ledger(source, provider=TestProvider({})))
    assert result.units[0].id == source_id
    assert result.units[0].translation_source_ids == [source_id]
    assert result.blocks[0].unit_ids == [source_id]
    assert len(result.blocks[0].id) <= 128


@pytest.mark.parametrize(
    "source, expected",
    [
        ("학부 재학생", "Currently enrolled undergraduate students."),
        (
            "2028학년도 1학기 학부 재학생",
            "Currently enrolled undergraduate students in the first semester of the 2028 academic year.",
        ),
        (
            "2026학년도 2학기 학부 재학생",
            "Currently enrolled undergraduate students in the second semester of the 2026 academic year.",
        ),
    ],
)
def test_exact_enrollment_label_has_complete_literal_fallback(source, expected):
    assert best_effort_english(source) == expected
    assert validate_protected_values(source, expected) == []


def test_enrollment_literal_does_not_swallow_an_attached_exception():
    source = "학부 재학생, 휴학생은 지원 제외"
    assert best_effort_english(source).startswith("Source wording (romanized)")


@pytest.mark.parametrize("minimum", ["or more", "or higher", "or above"])
def test_duplicate_crop_observations_do_not_hide_the_matching_exam_threshold(minimum):
    assert (
        validate_protected_values("OPIC\nOPIc\nIM3 이상", f"OPIC\nOPIc\nIM3 {minimum}")
        == []
    )


def test_an_inclusive_exam_minimum_cannot_be_replaced_by_strictly_more_than():
    issues = validate_protected_values("TOEIC 800 이상", "TOEIC: more than 800")
    assert "changed threshold direction: toeic / inclusive minimum" in issues


def test_a_duplicate_label_with_a_different_score_cannot_supply_the_comparator():
    issues = validate_protected_values(
        "TOEIC 800 이상", "TOEIC 800; TOEIC 309 or higher"
    )
    assert "changed threshold direction: toeic / inclusive minimum" in issues


@pytest.mark.parametrize(
    "source, english",
    [
        ("연구비:1인당 최대 20만원", "Research funding: up to KRW 200,000 per person."),
        ("활동비:1인당 20만원", "Activity funding: KRW 200,000 per person."),
        ("연구비:1인당 최대 2.5만원", "Research funding: up to KRW 25,000 per person."),
    ],
)
def test_standalone_funding_categories_and_amounts_have_deterministic_english(
    source, english
):
    assert ledger_translation.literal_translation(source) == english
    assert validate_protected_values(source, english) == []


@pytest.mark.parametrize(
    "english",
    [
        "Until September 16",
        "From September 10, 2026",
        "Deadline: 9.16",
        "Until 9/16",
        "from 9/10",
        "From 9.10",
    ],
)
def test_calendar_dates_need_evidence_even_when_ocr_contains_no_date(english):
    assert any(
        issue.startswith("unsupported date:")
        for issue in validate_protected_values("기간입C이끼지", english)
    )


@pytest.mark.parametrize("maximum", [3, 5, 12])
def test_complete_individual_or_team_condition_has_an_exact_local_translation(maximum):
    source = f"개인 또는 팀({maximum}인 이내) 참가 가능"
    english = f"Individuals or teams of up to {maximum} people may participate."
    assert ledger_translation.literal_translation(source) == english
    assert validate_protected_values(source, english) == []
    assert validate_protected_values(source, english.replace("up to ", ""))
    assert validate_protected_values(source, english.replace(str(maximum), "99"))


def test_institution_enrollment_and_allowed_leave_keep_their_conditions():
    source = "가상대학교 학부 재학생(휴학생 참가 가능)"
    english = ledger_translation.literal_translation(source)
    assert english == (
        "Currently enrolled undergraduate students at Gasang University (name transliterated). "
        "Students on leave may participate."
    )
    assert validate_protected_values(source, english) == []
    assert ledger_translation.literal_translation(source + ", 단 지원금 제외") is None


def test_a_survey_lottery_cannot_be_translated_as_a_guaranteed_reward():
    source = "만족도 조사 참여 시 추첨을 통해 5,000원 상품권 지급"
    assert "missing lottery condition" in validate_protected_values(
        source, "Participants in the satisfaction survey receive a KRW 5,000 voucher."
    )
    assert (
        validate_protected_values(
            source,
            "Participants in the satisfaction survey receive a KRW 5,000 voucher through a lottery.",
        )
        == []
    )
