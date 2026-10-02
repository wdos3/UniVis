from __future__ import annotations

import pytest

from app.services.source_fragments import broken_transliteration_reason


@pytest.mark.parametrize("source,english", [
    ("숫불고기집", "Sutbul Meat Restaurant"),
    ("목여탕", "Mokyeo Bathhouse"),
    ("성울", "Seong-ul"),
    ("도서신청", "Doseo Requests"),
    ("미리납부", "Miri Payment"),
    ("가을학기", "Gaeul Semester"),
    ("무료급식", "Muryo Meals"),
    ("우리동네", "Uri Neighborhood"),
])
def test_detects_phonetic_fragments_instead_of_interpreted_captions(source, english):
    reason = broken_transliteration_reason(source, english, field="key_details", label="Topic or option")
    assert reason is not None
    assert "phonetic name" in reason
    assert source not in reason


@pytest.mark.parametrize("source,english", [
    ("숫불고기집", "Charcoal barbecue restaurant"),
    ("목여탕", "Bathhouse"),
    ("도서신청", "Book request"),
    ("가을학기", "Autumn semester"),
    ("무료급식", "Free meals"),
    ("우리동네", "Our neighborhood"),
    ("기말시험", "Final exam"),
    ("베이", "Being prepared"),
    ("김치", "Kimchi"),
    ("김치", "Gimchi"),
    ("라면", "Ramyeon"),
    ("떡볶이", "Tteokbokki"),
])
def test_preserves_translated_captions_complete_borrowings_and_ordinary_english(source, english):
    assert broken_transliteration_reason(source, english) is None


@pytest.mark.parametrize("field,label", [
    ("title", ""),
    ("contacts", ""),
    ("locations", ""),
    ("key_details", "Contact"),
    ("key_details: Location", ""),
    ("key_details", "Institution"),
])
def test_preserves_explicit_named_roles(field, label):
    assert broken_transliteration_reason("성울", "Seong-ul", field=field, label=label) is None


@pytest.mark.parametrize("source,english", [
    ("미리대학교", "Miri University"),
    ("미리센터", "Miri Center"),
    ("미리지도", "Miri Map"),
    ("미리 앱", "Miri App"),
    ("미리사이트", "Miri Site"),
    ("이름: 미리", "Miri"),
    ("MIRI 학습자료", "Miri Learning Materials"),
    ("숫불고기집 SUTBUL", "Sutbul Restaurant"),
    ("업체명\n목여탕", "Mokyeo Bathhouse"),
    ("도서신청\n신청방법", "Doseo Requests"),
])
def test_preserves_printed_names_legible_roles_and_multiline_context(source, english):
    assert broken_transliteration_reason(source, english) is None


def test_partial_borrowed_terms_are_an_explicit_conservative_boundary():
    # No dictionary-free syllable match can tell whether a mixed rendering is
    # a genuine established borrowing or an invented name for damaged OCR.
    assert broken_transliteration_reason("라면국", "Ramyeon Soup") is not None


@pytest.mark.parametrize("source,english", [
    ("미", "Mi Payment"),
    ("", "Name"),
    ("*", "Name"),
    ("2026", "2026"),
    ("도서신청" * 6, "Doseo Requests"),
])
def test_guard_stays_within_short_hangul_caption_scope(source, english):
    assert broken_transliteration_reason(source, english) is None
