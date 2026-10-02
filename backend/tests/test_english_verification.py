from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from openai.lib._pydantic import to_strict_json_schema

from app.services.english_verification import (
    EnglishSupportDecision,
    EnglishSupportField,
    EnglishSupportResponse,
    EnglishVerificationProtocolError,
    EnglishVerificationProviderError,
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
        return SimpleNamespace(output_parsed=self.parsed, usage=self.usage)


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
