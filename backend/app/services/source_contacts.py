from __future__ import annotations

import re


_PHONE = re.compile(
    r"(?<![A-Za-z0-9_])(?:\+\d{1,3}[. -]?)?\(?\d{1,4}\)?[. -]?\d{3,4}[. -]?\d{4}(?![A-Za-z0-9_])"
)
_PHONE_CANDIDATE = re.compile(
    r"(?<![A-Za-z0-9_])(?:\+\d{1,3}[. -]?)?\(?\d[\dA-Za-z가-힣\u3130-\u318f?]{1,3}\)?[. -]"
    r"[\dA-Za-z가-힣\u3130-\u318f?]{3,4}[. -][\dA-Za-z가-힣\u3130-\u318f?]{4}(?![A-Za-z0-9_])"
)
# Korean labels and grammatical particles often directly adjoin a contact.
# ASCII token boundaries reject partial Latin addresses without rejecting them.
_EMAIL = re.compile(r"(?<![A-Za-z0-9_@])[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![A-Za-z0-9_@-]|\.[A-Za-z0-9_-])")
_PAGE_MARKER = re.compile(r"^\[Page (\d+)\]$")
_CONTACT_CUE = re.compile(r"문의|전화|연락|\b(?:phone|tel|contact)\b", re.IGNORECASE)


def phone_digits(value: str) -> str | None:
    if not re.fullmatch(r"\+?[\d().\s-]{7,}", value):
        return None
    digits = re.sub(r"\D", "", value)
    if not 9 <= len(digits) <= 15:
        return None
    if value.strip().startswith("+82") and digits.startswith("82"):
        return f"0{digits[2:]}"
    return digits


def phone_values(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for candidate in _PHONE.finditer(text):
        printed = candidate.group()
        digits = phone_digits(printed)
        if digits is None or re.match(r"\s*(?:억|만|천)?원", text[candidate.end():]):
            continue
        if printed.isdigit() and not (
            (printed.startswith("0") and len(printed) in (9, 10, 11))
            or _CONTACT_CUE.search(text[max(0, candidate.start() - 12):candidate.start()])
        ):
            continue
        values[digits] = printed
    return values


def email_values(text: str) -> set[str]:
    return {match.group().casefold() for match in _EMAIL.finditer(text)}


def contact_corrections(source_text: str) -> list[dict]:
    """Flag contact-shaped OCR containing letters where digits are required.

    The shape is intentionally narrow: ordinary dates and amounts are not
    phone numbers, and uncertain characters are never repaired by guessing.
    """
    corrections: list[dict] = []
    page = 1
    line_number = 0
    for raw_line in source_text.splitlines():
        line = raw_line.strip()
        marker = _PAGE_MARKER.fullmatch(line)
        if marker:
            page = int(marker[1])
            line_number = 0
            continue
        line_number += 1
        damaged = [
            match.group() for match in _PHONE_CANDIDATE.finditer(line)
            if len(re.findall(r"\d", match.group())) >= 7
            and re.search(r"[A-Za-z가-힣\u3130-\u318f?]", match.group())
            and (_CONTACT_CUE.search(line) or re.match(r"\(?0\d{1,3}[.) -]", match.group()))
        ]
        if damaged:
            corrections.append({
                "page": page,
                "line": line_number,
                "text": line,
                "reason": "The phone number contains unreadable OCR characters: " + ", ".join(damaged)
                + ". Read the exact digits from the photo or upload a close-up of the contact line.",
            })
    return corrections


def unsupported_contacts(source_text: str, english_text: str) -> list[str]:
    source_phones = phone_values(source_text)
    extra = [value for digits, value in phone_values(english_text).items() if digits not in source_phones]
    extra.extend(sorted(email_values(english_text) - email_values(source_text)))
    return extra
