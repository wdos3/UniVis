from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models import Contact, NoticeData, ReviewState
from app.services.semantic import OpenAISemanticProvider, SourceCorrectionRequired, normalize_notice
from app.services.source_contacts import contact_corrections, unsupported_contacts


FIXTURES = Path(__file__).parent / "fixtures"


def test_raw_sogang_contact_requests_exact_correction_before_semantic_request() -> None:
    fixture = json.loads((FIXTURES / "sogang_research_2026_browser_ocr.json").read_text(encoding="utf-8"))
    source = "[Page 1]\n" + "\n".join(item["text"] for item in fixture["items"])

    class NoRequests:
        async def parse(self, **kwargs):
            raise AssertionError("Damaged contact text must be corrected before using semantic tokens.")

    provider = OpenAISemanticProvider(client=SimpleNamespace(responses=NoRequests()))
    with pytest.raises(SourceCorrectionRequired, match="close-up of the contact line") as exc:
        asyncio.run(provider.analyze(source, "Translation", "en"))

    assert len(exc.value.corrections) == 1
    correction = exc.value.corrections[0]
    assert correction["page"] == 1
    assert correction["line"] == 47
    assert "02.710.25n0" in correction["text"]
    assert "02-710-2500" not in str(exc.value)
    assert "exact digits" in correction["reason"]


def test_corrected_sogang_fixture_has_no_contact_correction_request() -> None:
    source = (FIXTURES / "sogang_research_corrected.txt").read_text(encoding="utf-8")
    assert contact_corrections(source) == []


@pytest.mark.parametrize("damaged", ["02.710.25n0", "02-710-25O0", "02-710-25ㅇ0", "02-710-25?0"])
def test_damaged_phone_correction_retains_page_and_exact_line(damaged: str) -> None:
    corrections = contact_corrections(f"[Page 1]\n프로그램 모집\n[Page 2]\n문의 {damaged}")
    assert corrections[0]["page"] == 2
    assert corrections[0]["line"] == 1
    assert corrections[0]["text"] == f"문의 {damaged}"


def test_contact_correction_does_not_confuse_dates_amounts_or_logo_gibberish() -> None:
    assert contact_corrections("2026.08.24(월)~2026.09.20(일)\n20만원 지원\n부착9입CO임부터") == []
    assert contact_corrections("공고 번호 2026-ABC-0001\n연구과제 2026-A12-1234") == []


@pytest.mark.parametrize(("source", "english", "expected"), [
    ("문의 02.710.2500", "Call 02-710-2500", []),
    ("문의 02-710-2500", "Call +82 2-710-2500", []),
    ("문의 02-710-2500", "Call 02-710-2501", ["02-710-2501"]),
    ("문의 convedu@sogang.ac.kr", "Email convedu@sogang.ac.kr", []),
    ("문의 convedu@sogang.ac.kr", "Email convedu@sogang.edu", ["convedu@sogang.edu"]),
])
def test_contacts_cannot_be_invented_or_altered(source: str, english: str, expected: list[str]) -> None:
    assert unsupported_contacts(source, english) == expected


def test_semantic_email_without_matching_source_evidence_is_cleared() -> None:
    notice = NoticeData(contacts=[Contact(
        email="convedu@sogang.edu", source_evidence="문의 convedu@sogang.ac.kr",
    )])
    contact = normalize_notice(notice).contacts[0]
    assert contact.email == ""
    assert contact.state == ReviewState.NEEDS_REVIEW
    assert "Email address does not match" in contact.details
