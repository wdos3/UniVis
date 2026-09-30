from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation


_ENGLISH_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]*")
_WRAPPED_PHRASES = (
    re.compile(r"\(([^()]{1,120})\)"),
    re.compile(r'"([^\"]{1,120})"'),
    re.compile(r"“([^”]{1,120})”"),
    re.compile(r"‘([^’]{1,120})’"),
)
_KRW_AMOUNT = re.compile(r"(?<!\d)([\d,]+(?:\.\d+)?)\s*(억|만|천)?\s*원")
_KRW_UNIT = {None: 1, "천": 1_000, "만": 10_000, "억": 100_000_000}
_DISPLAY_NUMBER = re.compile(r"(?<![A-Za-z0-9])\d[\d,]*(?:\.\d+)?(?![A-Za-z0-9])")
_CURRENCY = re.compile(r"\b(?:KRW|won)\b|₩", re.IGNORECASE)
_SOURCE_DATE = re.compile(
    r"(?<!\d)(20\d{2})\s*(?:[./-]|년)\s*(0?[1-9]|1[0-2])\s*"
    r"(?:[./-]|월)\s*(0?[1-9]|[12]\d|3[01])(?:\s*일)?(?!\d)"
)
_SOURCE_MONTH_DAY = re.compile(r"(?<!\d)(0?[1-9]|1[0-2])\s*월\s*(0?[1-9]|[12]\d|3[01])\s*일")
_SOURCE_YEAR = re.compile(r"(?<!\d)(20\d{2})\s*년")
_SOURCE_THRESHOLD = re.compile(r"(?<![A-Za-z0-9])([\d,]+)\s*(?:점\s*)?(?:이상|이하|초과|미만)")
_SOURCE_COUNT_RANGE = re.compile(r"(?<!\d)(\d+)\s*[-~–]\s*(\d+)\s*명")
_SOURCE_ACRONYM = re.compile(r"(?<![A-Za-z0-9])(?:[A-Z]{2,}[A-Z0-9]*|\d+[A-Z]{1,3})(?![A-Za-z0-9])")
_SOURCE_TITLE_TERM = re.compile(r"(?<![A-Za-z])(?:[A-Z][a-z]{2,}\s+)+[A-Z][a-z]{2,}(?![A-Za-z])")
_MONTH_NAMES = (
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
)


def _protected_phrases(source_text: str) -> list[str]:
    """Only explicit quoted/parenthesized phrases are safe to treat as literal."""
    phrases: list[str] = []
    seen: set[tuple[str, ...]] = set()
    for pattern in _WRAPPED_PHRASES:
        for match in pattern.finditer(source_text):
            content = match[1]
            if content.count("\n") > 2 or not content.isascii():
                continue
            words = _ENGLISH_WORD.findall(content)
            key = tuple(word.casefold() for word in words)
            if len(words) < 2 or key in seen:
                continue
            seen.add(key)
            phrases.append(" ".join(words))
    return phrases


def missing_english_literals(source_text: str, detail_text: str) -> list[str]:
    """Find explicit English OCR phrases missing from reader-facing English.

    Spacing, punctuation, and case may differ, but lexical words must remain
    unchanged and in order. This catches plausible yet incorrect expansions
    of source terminology, such as changing "Minimum Value" to "Minimum Viable".
    """
    detail_words = _ENGLISH_WORD.findall(detail_text.casefold())
    missing: list[str] = []
    for phrase in _protected_phrases(source_text):
        words = _ENGLISH_WORD.findall(phrase.casefold())
        if not any(detail_words[index:index + len(words)] == words for index in range(len(detail_words) - len(words) + 1)):
            missing.append(phrase)
    return missing


def _display_numbers(text: str) -> set[Decimal]:
    values: set[Decimal] = set()
    for match in _DISPLAY_NUMBER.finditer(text):
        try:
            values.add(Decimal(match.group().replace(",", "")))
        except InvalidOperation:
            continue
    return values


def _has_month_day(text: str, month: int, day: int) -> bool:
    if re.search(rf"(?<!\d)0?{month}[./-]0?{day}(?!\d)", text):
        return True
    name = _MONTH_NAMES[month - 1]
    abbreviations = (name[:3], name[:4]) if month == 9 else (name[:3],)
    month_pattern = rf"(?:{name}|{'|'.join(abbreviations)})\.?"
    day_pattern = rf"0?{day}(?:st|nd|rd|th)?"
    return bool(
        re.search(rf"\b{month_pattern}\s+{day_pattern}\b", text, re.IGNORECASE)
        or re.search(rf"\b{day_pattern}(?:\s+of)?\s+{month_pattern}\b", text, re.IGNORECASE)
    )


def _has_latin_term(term: str, display_words: set[str]) -> bool:
    word = term.casefold()
    return word in display_words or f"{word}s" in display_words or f"{word}es" in display_words


def missing_source_values(source_text: str, english_text: str) -> list[str]:
    """Conservatively guard exact values before an OCR unit is called represented.

    This is not a semantic translation verifier. It catches values whose absence
    is objectively detectable without assuming that every source digit (such as
    a list number or the "1" in "per person") must appear literally in English.
    """
    missing: list[str] = []
    numbers = _display_numbers(english_text)
    display_words = {word.casefold() for word in re.findall(r"[A-Za-z0-9]+", english_text)}

    for match in _KRW_AMOUNT.finditer(source_text):
        amount = Decimal(match[1].replace(",", "")) * _KRW_UNIT[match[2]]
        if amount not in numbers or not _CURRENCY.search(english_text):
            missing.append(f"KRW {amount:,.0f}")

    dates = {(int(year), int(month), int(day)) for year, month, day in _SOURCE_DATE.findall(source_text)}
    dates.update((None, int(month), int(day)) for month, day in _SOURCE_MONTH_DAY.findall(source_text))
    dates = {
        date for date in dates
        if date[0] is not None or not any(
            year is not None and (month, day) == date[1:]
            for year, month, day in dates
        )
    }
    for year, month, day in sorted(dates, key=lambda value: (value[0] or 0, value[1], value[2])):
        if not _has_month_day(english_text, month, day) or (year and Decimal(year) not in numbers):
            missing.append(f"{year or ''}-{month:02d}-{day:02d}".lstrip("-"))

    for year in _SOURCE_YEAR.findall(source_text):
        if Decimal(year) not in numbers:
            missing.append(year)
    for score in _SOURCE_THRESHOLD.findall(source_text):
        if Decimal(score.replace(",", "")) not in numbers:
            missing.append(score)
    for lower, upper in _SOURCE_COUNT_RANGE.findall(source_text):
        for value in (lower, upper):
            if Decimal(value) not in numbers:
                missing.append(value)

    if source_text.strip().isdigit() and Decimal(source_text.strip()) not in numbers:
        missing.append(source_text.strip())
    for term in _SOURCE_ACRONYM.findall(source_text):
        if term.casefold() not in display_words:
            missing.append(term)
    if re.search(r"[가-힣]", source_text):
        for phrase in _SOURCE_TITLE_TERM.findall(source_text):
            for term in phrase.split():
                if not _has_latin_term(term, display_words):
                    missing.append(term)
    return list(dict.fromkeys(missing))
