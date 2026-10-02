from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from openai.lib._pydantic import to_strict_json_schema
from pydantic import ValidationError

from app.services.english_verification import (
    EnglishSupportDecision,
    EnglishSupportField,
    EnglishSupportResponse,
    EnglishSupportSourceUnit,
    EnglishVerificationProtocolError,
    EnglishVerificationProviderError,
    _EnglishCoverageSupportResponse,
    _EnglishCoverageVerdictResponse,
    _coverage_response_format,
    verify_english_support,
)


class FakeClient:
    def __init__(self, parsed, *, usage=None, error=None, delay=0):
        self.parsed = parsed
        self.usage = usage if usage is not None else SimpleNamespace(input_tokens=81, output_tokens=19, total_tokens=100)
        self.error = error
        self.delay = delay
        self.options = []
        self.calls = []
        self.responses = self

    def with_options(self, **kwargs):
        self.options.append(kwargs)
        return self

    async def parse(self, **kwargs):
        self.calls.append(kwargs)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        parsed = self.parsed(kwargs["text_format"]) if callable(self.parsed) else self.parsed
        return SimpleNamespace(output_parsed=parsed, usage=self.usage)


def _decision(field_id, status="supported", reason=""):
    return EnglishSupportDecision(id=field_id, status=status, reason=reason)


def _response(decisions):
    return EnglishSupportResponse(**{
        f"{status}_ids": [decision.id for decision in decisions if decision.status == status]
        for status in ("supported", "unsupported", "insufficient")
    })


def _run(fields, decisions, *, source="한국어 공고", client=None, **kwargs):
    client = client or FakeClient(_response(decisions))
    result = asyncio.run(verify_english_support(fields, source, client=client, **kwargs))
    return result, client


def test_returns_decisions_in_input_order_without_mutating_fields():
    fields = [
        EnglishSupportField("E001", "A grant is available.", "장학금 지급", 1, "financial_support", "Grant"),
        EnglishSupportField("E002", "All installments require a report.", "2차 지급은 보고서 제출 후", 1, "financial_support"),
        EnglishSupportField("E003", "Noisy invented place", "훼난기", 2, "locations"),
    ]
    result, client = _run(fields, [
        _decision("E003", "insufficient", "The damaged name has no established identity."),
        _decision("E002", "unsupported", "The condition applies only to the later installment."),
        _decision("E001"),
    ])

    assert [decision.id for decision in result.decisions] == ["E001", "E002", "E003"]
    assert result.supported_ids == {"E001"}
    assert result.unsupported_ids == {"E002"}
    assert result.insufficient_ids == {"E003"}
    assert result.rejected_ids == {"E002", "E003"}
    assert fields[1].text == "All installments require a report."
    assert len(client.calls) == result.requests == 1
    assert (result.input_tokens, result.output_tokens, result.total_tokens) == (81, 19, 100)
    assert result.usage_complete is True
    assert client.options == [{"max_retries": 0, "timeout": 45.0}]


def test_sends_exact_final_fields_quotes_pages_and_complete_context():
    source = "[Page 1]\n주거지원 모집\n후기 분납금은 서류 제출 후 지급\n[Page 2]\n별도 동아리 모임\n매주 금요일"
    fields = [
        EnglishSupportField("E1", "Friday housing deadline", "매주 금요일", 2, "key_details", "Schedule"),
        EnglishSupportField("E2", "Unknown University", "Unknown University 주거지원 모집", 1, "title"),
    ]
    result, client = _run(fields, [
        _decision("E1", "unsupported", "The club schedule belongs to a different notice."),
        _decision("E2"),
    ], source=source, layout_context="Page 2: separate bottom poster", model="configured-mini",
       primary_notice_title="Unknown University Housing Support")

    assert result.rejected_ids == {"E1"}
    call = client.calls[0]
    assert call["model"] == "configured-mini"
    assert call["text_format"] is EnglishSupportResponse
    payload = json.loads(call["input"][1]["content"])
    assert payload["source_text"] == source
    assert payload["presentation_scope"] == "All supplied fields appear together as one primary notice digest."
    assert payload["primary_notice_title"] == "Unknown University Housing Support"
    assert payload["spatial_ocr_hints"] == "Page 2: separate bottom poster"
    assert payload["english_fields"][0] == {
        "id": "E1", "text": "Friday housing deadline", "source_quote": "매주 금요일",
        "source_page": 2, "field": "key_details", "label": "Schedule",
    }


@pytest.mark.parametrize("decisions", [
    [],
    [_decision("unknown")],
    [_decision("E1"), _decision("E1")],
    [_decision("E1"), _decision("unknown", "insufficient", "Unknown field.")],
    [_decision("E1"), _decision("E1", "unsupported", "Conflicting classification.")],
])
def test_rejects_incomplete_unknown_or_duplicate_partition_with_known_usage(decisions):
    client = FakeClient(_response(decisions))
    with pytest.raises(EnglishVerificationProtocolError) as caught:
        _run([EnglishSupportField("E1", "Housing application")], decisions, client=client)

    assert caught.value.requests == 1
    assert caught.value.total_tokens == 100
    assert caught.value.usage_complete is True
    assert len(client.calls) == 1


@pytest.mark.parametrize("response,expected", [
    (EnglishSupportResponse(supported_ids=["E1"], unsupported_ids=[], insufficient_ids=[]), {"E1"}),
    (EnglishSupportResponse(supported_ids=["E1", "unknown"], unsupported_ids=[], insufficient_ids=["E2"]), {"E1"}),
    (EnglishSupportResponse(supported_ids=["E1", "E2"], unsupported_ids=["E2"], insufficient_ids=[]), {"E1"}),
    (EnglishSupportResponse(supported_ids=["E1", "E1", "E2"], unsupported_ids=[], insufficient_ids=[]), {"E2"}),
])
def test_partial_review_preserves_only_unique_known_classifications(response, expected):
    fields = [EnglishSupportField("E1", "Apply by the deadline."), EnglishSupportField("E2", "Submit the form.")]
    client = FakeClient(response)
    result, _ = _run(fields, [], client=client, allow_partial=True)
    assert result.supported_ids == expected
    assert result.insufficient_ids == {"E1", "E2"} - expected
    assert result.partition_complete is False
    assert result.requests == 1 and result.total_tokens == 100


def test_rejection_reasons_are_application_owned_without_generated_wording():
    result, _ = _run([
        EnglishSupportField("E1", "A copied fragment"), EnglishSupportField("E2", "Wrong restriction"),
    ], [
        _decision("E1", "insufficient"), _decision("E2", "unsupported"),
    ])
    assert result.decisions[0].reason == "The recovered source does not establish a complete meaning or association."
    assert result.decisions[1].reason == "The English meaning or scope is not supported by the recovered source."


def test_no_parsed_response_is_protocol_error_and_preserves_completed_usage():
    client = FakeClient(None)
    with pytest.raises(EnglishVerificationProtocolError) as caught:
        _run([EnglishSupportField("E1", "Grant")], [], client=client)
    assert caught.value.total_tokens == 100
    assert caught.value.usage_complete is True


def test_provider_failure_is_typed_bounded_and_does_not_invent_token_usage():
    original = RuntimeError("provider unavailable")
    client = FakeClient(None, error=original)
    with pytest.raises(EnglishVerificationProviderError) as caught:
        _run([EnglishSupportField("E1", "Grant")], [], client=client)

    assert caught.value.__cause__ is original
    assert caught.value.requests == len(client.calls) == 1
    assert caught.value.total_tokens == 0
    assert caught.value.usage_complete is False


def test_timeout_cancels_the_only_request_without_retry():
    client = FakeClient(_response([_decision("E1")]), delay=1)
    with pytest.raises(EnglishVerificationProviderError) as caught:
        _run([EnglishSupportField("E1", "Grant")], [], client=client, timeout_seconds=0.01)

    assert isinstance(caught.value.__cause__, TimeoutError)
    assert len(client.calls) == 1
    assert client.options == [{"max_retries": 0, "timeout": 0.01}]


def test_missing_usage_is_explicitly_incomplete_even_with_valid_decisions():
    client = FakeClient(_response([_decision("E1")]), usage=SimpleNamespace())
    result, _ = _run([EnglishSupportField("E1", "Grant")], [], client=client)
    assert result.requests == 1
    assert result.total_tokens == 0
    assert result.usage_complete is False


def test_empty_input_needs_no_source_no_credentials_and_no_provider_call(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = asyncio.run(verify_english_support([], ""))
    assert result.decisions == ()
    assert result.requests == result.total_tokens == 0
    assert result.usage_complete is True


@pytest.mark.parametrize("fields,source", [
    ([EnglishSupportField("E1", "Grant"), EnglishSupportField("E1", "Other grant")], "source"),
    ([EnglishSupportField("", "Grant")], "source"),
    ([EnglishSupportField(" E1", "Grant")], "source"),
    ([EnglishSupportField("E1", " ")], "source"),
    ([EnglishSupportField("E1", "Grant")], " "),
    ([EnglishSupportField("E1", "Grant", source_page=0)], "source"),
])
def test_invalid_input_is_rejected_before_external_calls(fields, source):
    client = FakeClient(None)
    with pytest.raises(ValueError):
        _run(fields, [], source=source, client=client)
    assert client.calls == client.options == []


def test_no_credentials_error_has_no_failed_request_or_unknown_cost(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(EnglishVerificationProviderError) as caught:
        asyncio.run(verify_english_support([EnglishSupportField("E1", "Grant")], "장학금"))
    assert caught.value.requests == 0
    assert caught.value.usage_complete is True


def test_schema_is_strict_and_has_no_generated_replacement_fields():
    schema = to_strict_json_schema(EnglishSupportResponse)
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"supported_ids", "unsupported_ids", "insufficient_ids"}
    assert all(value["type"] == "array" and value["items"]["type"] == "string" for value in schema["properties"].values())


def _coverage_response(*, supported=("E1",), covered=(), unresolved=()):
    return _EnglishCoverageSupportResponse(
        supported_ids=list(supported), unsupported_ids=[], insufficient_ids=[],
        covered_source_unit_ids=list(covered), unresolved_source_unit_ids=list(unresolved),
    )


def test_source_coverage_sends_compact_exact_units_and_preserves_spatial_context():
    units = [
        EnglishSupportSourceUnit("U1", "납부 기간", 2, 4),
        EnglishSupportSourceUnit("U2", "3차 지급은 확인 후", 2, 5),
    ]
    client = FakeClient(_coverage_response(covered=["U1"], unresolved=["U2"]))
    result, _ = _run(
        [EnglishSupportField("E1", "Payment period.", "납부 기간", 2)], [],
        source="Redundant original source", client=client, source_units=units,
        layout_context="Page 2: separate table", primary_notice_title="Funding notice",
    )

    assert result.fully_covered_source_ids == {"U1"}
    assert result.unverified_source_ids == {"U2"}
    assert result.source_partition_complete is True
    call = client.calls[0]
    assert issubclass(call["text_format"], _EnglishCoverageVerdictResponse)
    payload = json.loads(call["input"][1]["content"])
    assert "source_text" not in payload
    assert payload["source_units"] == {
        "U1": {"text": "납부 기간", "page": 2, "line": 4},
        "U2": {"text": "3차 지급은 확인 후", "page": 2, "line": 5},
    }
    assert payload["spatial_ocr_hints"] == "Page 2: separate table"
    assert payload["primary_notice_title"] == "Funding notice"
    assert result.requests == len(client.calls) == 1 and result.total_tokens == 100


@pytest.mark.parametrize("covered,unresolved", [
    ([], []),
    (["U1"], []),
    (["U1", "U2", "unknown"], []),
    (["U1", "U1"], ["U2"]),
    (["U1", "U2"], ["U2"]),
])
def test_strict_source_coverage_rejects_incomplete_unknown_or_conflicting_partition(covered, unresolved):
    client = FakeClient(_coverage_response(covered=covered, unresolved=unresolved))
    with pytest.raises(EnglishVerificationProtocolError) as caught:
        _run([EnglishSupportField("E1", "Funding detail")], [], client=client, source_units=[
            EnglishSupportSourceUnit("U1", "장학금"), EnglishSupportSourceUnit("U2", "신청 서류"),
        ])
    assert caught.value.requests == 1
    assert caught.value.total_tokens == 100 and caught.value.usage_complete is True


@pytest.mark.parametrize("covered,unresolved,expected", [
    (["U1"], [], {"U1"}),
    (["U1", "unknown"], ["U2"], {"U1"}),
    (["U1", "U2"], ["U2"], {"U1"}),
    (["U1", "U1", "U2"], [], {"U2"}),
])
def test_partial_source_coverage_certifies_only_unique_known_ids(covered, unresolved, expected):
    client = FakeClient(_coverage_response(covered=covered, unresolved=unresolved))
    result, _ = _run([EnglishSupportField("E1", "Funding detail")], [], client=client, source_units=[
        EnglishSupportSourceUnit("U1", "장학금"), EnglishSupportSourceUnit("U2", "신청 서류"),
    ], allow_partial=True)
    assert result.fully_covered_source_ids == expected
    assert result.unverified_source_ids == {"U1", "U2"} - expected
    assert result.source_partition_complete is False
    assert "unknown" not in result.fully_covered_source_ids


def test_source_coverage_cannot_be_certified_without_supported_final_english():
    parsed = _coverage_response(supported=(), covered=["U1"])
    parsed.unsupported_ids = ["E1"]
    result, _ = _run([EnglishSupportField("E1", "Wrong instruction")], [], client=FakeClient(parsed),
                     source_units=[EnglishSupportSourceUnit("U1", "원문 조건")])
    assert result.fully_covered_source_ids == set()
    assert result.unverified_source_ids == {"U1"}
    assert result.source_partition_complete is True


@pytest.mark.parametrize("allow_partial", [False, True])
def test_missing_source_classification_is_never_treated_as_coverage(allow_partial):
    client = FakeClient(_response([_decision("E1")]))
    args = ([EnglishSupportField("E1", "Funding detail")], [])
    kwargs = {"client": client, "source_units": [EnglishSupportSourceUnit("U1", "장학금")],
              "allow_partial": allow_partial}
    if not allow_partial:
        with pytest.raises(EnglishVerificationProtocolError):
            _run(*args, **kwargs)
    else:
        result, _ = _run(*args, **kwargs)
        assert result.supported_ids == {"E1"}
        assert result.fully_covered_source_ids == set()
        assert result.unverified_source_ids == {"U1"}
        assert result.source_partition_complete is False


def test_no_english_output_locally_marks_all_source_units_unverified_without_a_call():
    client = FakeClient(None)
    result, _ = _run([], [], source="", client=client, source_units=[
        EnglishSupportSourceUnit("U1", "읽을 수 있는 조건"), EnglishSupportSourceUnit("U2", "손상된 원문"),
    ])
    assert result.unverified_source_ids == {"U1", "U2"}
    assert result.fully_covered_source_ids == set()
    assert result.source_partition_complete is True
    assert result.requests == 0 and client.calls == []


def test_default_three_list_mode_does_not_claim_source_completeness():
    result, client = _run([EnglishSupportField("E1", "Funding")], [_decision("E1")])
    assert result.source_partition_complete is False
    assert result.fully_covered_source_ids == result.unverified_source_ids == frozenset()
    assert client.calls[0]["text_format"] is EnglishSupportResponse


@pytest.mark.parametrize("units", [
    [EnglishSupportSourceUnit("", "원문")],
    [EnglishSupportSourceUnit(" U1", "원문")],
    [EnglishSupportSourceUnit("U1", "원문"), EnglishSupportSourceUnit("U1", "다른 원문")],
    [EnglishSupportSourceUnit("U1", " ")],
    [EnglishSupportSourceUnit("U1", "원문", page=0)],
    [EnglishSupportSourceUnit("U1", "원문", line=0)],
])
def test_invalid_source_units_fail_before_provider_calls(units):
    client = FakeClient(None)
    with pytest.raises(ValueError):
        _run([EnglishSupportField("E1", "Funding")], [], client=client, source_units=units)
    assert client.options == client.calls == []


def test_extended_schema_requires_both_source_id_lists_without_replacement_text():
    schema = to_strict_json_schema(_EnglishCoverageSupportResponse)
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {
        "supported_ids", "unsupported_ids", "insufficient_ids",
        "covered_source_unit_ids", "unresolved_source_unit_ids",
    }
    assert all(value["type"] == "array" and value["items"]["type"] == "string" for value in schema["properties"].values())


def test_required_verdict_maps_return_complete_independent_partitions_in_one_call():
    fields = [EnglishSupportField("E1", "Supported meaning"), EnglishSupportField("E2", "Wrong scope")]
    units = [EnglishSupportSourceUnit("U1", "원문 의미"), EnglishSupportSourceUnit("U2", "다른 조건")]
    client = FakeClient(lambda response_format: response_format(
        english_verdicts={"E2": "unsupported", "E1": "supported"},
        source_verdicts={"U2": "unresolved", "U1": "covered"},
    ))
    result, _ = _run(fields, [], client=client, source_units=units)

    assert result.supported_ids == {"E1"}
    assert result.unsupported_ids == {"E2"}
    assert [decision.id for decision in result.decisions] == ["E1", "E2"]
    assert result.fully_covered_source_ids == {"U1"}
    assert result.unverified_source_ids == {"U2"}
    assert result.partition_complete is result.source_partition_complete is True
    assert result.requests == len(client.calls) == 1 and result.total_tokens == 100
    prompt = client.calls[0]["input"][0]["content"]
    assert "english_verdicts and source_verdicts objects" in prompt
    assert "Unsupported or insufficient English fields can NEVER establish source coverage" in prompt


def test_unit_schema_requires_each_opaque_id_once_with_only_allowed_verdicts():
    fields = [EnglishSupportField("E.001", "A meaning"), EnglishSupportField("model_config", "Another meaning")]
    units = [EnglishSupportSourceUnit("P001-L0028", "원문"), EnglishSupportSourceUnit("source:id", "계속")]
    response_format = _coverage_response_format(fields, units)
    schema = to_strict_json_schema(response_format)
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"english_verdicts", "source_verdicts"}
    definitions = schema["$defs"]
    english = definitions["RequiredEnglishVerdicts"]
    source = definitions["RequiredSourceVerdicts"]
    assert english["additionalProperties"] is source["additionalProperties"] is False
    assert set(english["required"]) == set(english["properties"]) == {field.id for field in fields}
    assert set(source["required"]) == set(source["properties"]) == {unit.id for unit in units}
    assert all(set(field["enum"]) == {"supported", "unsupported", "insufficient"}
               for field in english["properties"].values())
    assert all(set(unit["enum"]) == {"covered", "unresolved"} for unit in source["properties"].values())

    client = FakeClient(lambda model: model(
        english_verdicts={"model_config": "insufficient", "E.001": "supported"},
        source_verdicts={"source:id": "unresolved", "P001-L0028": "covered"},
    ))
    result, _ = _run(fields, [], client=client, source_units=units)
    assert result.insufficient_ids == {"model_config"}
    assert result.fully_covered_source_ids == {"P001-L0028"}


@pytest.mark.parametrize("english,source", [
    ({}, {"U1": "covered"}),
    ({"E1": "supported"}, {}),
    ({"E1": "supported", "unknown": "supported"}, {"U1": "covered"}),
    ({"E1": "supported"}, {"U1": "covered", "unknown": "covered"}),
    ({"E1": "covered"}, {"U1": "covered"}),
    ({"E1": "supported"}, {"U1": "supported"}),
    ({"E1": ["supported", "unsupported"]}, {"U1": "covered"}),
    ({"E1": "supported"}, {"U1": ["covered", "unresolved"]}),
])
def test_required_unit_schema_cannot_omit_invent_or_conflict_verdicts(english, source):
    response_format = _coverage_response_format(
        [EnglishSupportField("E1", "English meaning")], [EnglishSupportSourceUnit("U1", "원문 의미")],
    )
    with pytest.raises(ValidationError):
        response_format(english_verdicts=english, source_verdicts=source)


def test_required_map_coverage_cannot_come_from_rejected_english():
    client = FakeClient(lambda model: model(
        english_verdicts={"E1": "insufficient"}, source_verdicts={"U1": "covered"},
    ))
    result, _ = _run([EnglishSupportField("E1", "Unverified association")], [], client=client,
                     source_units=[EnglishSupportSourceUnit("U1", "원문")])
    assert result.partition_complete is result.source_partition_complete is True
    assert result.fully_covered_source_ids == set()
    assert result.unverified_source_ids == {"U1"}


def test_required_maps_with_no_source_units_keep_source_text_and_no_false_coverage():
    client = FakeClient(lambda model: model(english_verdicts={"E1": "supported"}, source_verdicts={}))
    result, _ = _run([EnglishSupportField("E1", "A title")], [], client=client, source_units=[], source="공지 제목")
    payload = json.loads(client.calls[0]["input"][1]["content"])
    assert payload["source_text"] == "공지 제목" and payload["source_units"] == {}
    assert result.partition_complete is result.source_partition_complete is True
    assert result.fully_covered_source_ids == result.unverified_source_ids == frozenset()


def test_unit_schema_ids_do_not_leak_between_independent_requests():
    first = _coverage_response_format([EnglishSupportField("E1", "First")], [EnglishSupportSourceUnit("U1", "첫째")])
    second = _coverage_response_format([EnglishSupportField("E2", "Second")], [EnglishSupportSourceUnit("U2", "둘째")])
    with pytest.raises(ValidationError):
        second(english_verdicts={"E1": "supported"}, source_verdicts={"U1": "covered"})
    assert first(english_verdicts={"E1": "supported"}, source_verdicts={"U1": "covered"})
    assert second(english_verdicts={"E2": "supported"}, source_verdicts={"U2": "covered"})
