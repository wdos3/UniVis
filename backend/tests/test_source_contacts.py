from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models import Contact, NoticeData, ReviewState
from app.services.semantic import OpenAISemanticProvider, SourceCorrectionRequired, normalize_notice
from app.services.source_contacts import contact_corrections, email_values, phone_values, unsupported_contacts


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


@pytest.mark.parametrize("source", [
    "PDF 파일을 grants@example.edu로 제출",
    "문의grants@example.edu에게 연락",
    "grants@example.edu(장학팀)",
])
def test_korean_labels_and_particles_do_not_hide_printed_email(source: str) -> None:
    assert email_values(source) == {"grants@example.edu"}
    assert unsupported_contacts(source, "Send documents to grants@example.edu.") == []


@pytest.mark.parametrize("source", [
    "문의(02.710.2500 |convedu@sogang.ac.kr)",
    "문의02.710.2500|convedu@sogang.ac.kr로 연락",
    "02-710-2500|convedu@sogang.ac.kr",
    "전화(+82 2-710-2500)|convedu@sogang.ac.kr",
    "|convedu@sogang.ac.kr|",
    "문의|convedu@sogang.ac.kr에게 연락",
    "문의 | convedu@sogang.ac.kr | 장학팀",
])
def test_notice_pipe_separators_do_not_become_part_of_the_email(source: str) -> None:
    assert email_values(source) == {"convedu@sogang.ac.kr"}
    assert unsupported_contacts(source, "Email convedu@sogang.ac.kr.") == []


@pytest.mark.parametrize("address", [
    "research.team+2029@example.edu", "student-grants@example.edu",
    "grants_team@example.edu", "first|last@example.edu", "a!b@example.edu",
])
def test_address_punctuation_is_preserved_inside_notice_delimiters(address: str) -> None:
    assert email_values(f"문의|{address}|장학팀") == {address}
    assert unsupported_contacts(f"문의|{address}", f"Email {address}.") == []


def test_pipe_between_two_emails_keeps_both_complete_addresses() -> None:
    assert email_values("grants@example.edu|admin@example.edu") == {
        "grants@example.edu", "admin@example.edu",
    }


def test_contact_normalization_accepts_a_correct_email_after_the_source_pipe() -> None:
    notice = NoticeData(contacts=[Contact(
        email="convedu@sogang.ac.kr", source_evidence="문의(02.710.2500 |convedu@sogang.ac.kr)",
    )])
    assert normalize_notice(notice).contacts[0].email == "convedu@sogang.ac.kr"


@pytest.mark.parametrize("source", ["grants@example.edu9", "grants@example.edu_", "grants@example.edu@other.org",
                                     "grants@example.edu.au2", "grants@example.edu.au-z"])
def test_email_does_not_accept_a_partial_latin_address(source: str) -> None:
    assert "grants@example.edu" not in email_values(source)


@pytest.mark.parametrize("source", ["문의02-123-4567로 연락", "02-123-4567에 전화", "전화(+82 2-123-4567)"])
def test_korean_labels_and_particles_do_not_hide_phone_digits(source: str) -> None:
    assert "021234567" in phone_values(source)
    assert unsupported_contacts(source, "Call 02-123-4567.") == []


def test_damaged_contact_with_korean_particle_still_requires_correction() -> None:
    corrections = contact_corrections("문의02-123-45O7로 연락")
    assert len(corrections) == 1
    assert "02-123-45O7" in corrections[0]["reason"]


@pytest.mark.parametrize("source", ["총사업비1000000000원", "문서번호1234567890", "2026090712", "예산1.000.000.000원"])
def test_long_numbers_without_contact_shape_or_cue_are_not_phones(source: str) -> None:
    assert phone_values(source) == {}


@pytest.mark.parametrize("source", ["전화1234567890", "문의021234567로 연락"])
def test_explicit_bare_phone_numbers_remain_available(source: str) -> None:
    assert phone_values(source)
