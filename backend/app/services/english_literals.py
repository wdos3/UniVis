from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from app.services.source_contacts import email_values, phone_values


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
_ENGLISH_CURRENCY_AMOUNT = re.compile(
    r"(?:\bKRW\s*|₩\s*)([\d,]+(?:\.\d+)?)|([\d,]+(?:\.\d+)?)\s*(?:KRW\b|won\b)", re.IGNORECASE,
)
_SOURCE_DATE = re.compile(
    r"(?<!\d)(20\d{2})\s*(?:[./-]|년)\s*(0?[1-9]|1[0-2])\s*"
    r"(?:[./-]|월)\s*(0?[1-9]|[12]\d|3[01])(?:\s*일)?(?!\d)"
)
_SOURCE_MONTH_DAY = re.compile(r"(?<!\d)(0?[1-9]|1[0-2])\s*월\s*(0?[1-9]|[12]\d|3[01])\s*일")
_ABBREVIATED_MONTH_DAY = re.compile(
    r"(?<![\d./])(0?[1-9]|1[0-2])\s*[./]\s*(0?[1-9]|[12]\d|3[01])(?![\d./])"
)
_CALENDAR_WEEKDAY = re.compile(
    r"\s*\(\s*(?:[월화수목금토일]|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s*\)",
    re.IGNORECASE,
)
_DATE_LABEL = re.compile(
    r"(?:신청|접수|모집|등록|납부|행사)?\s*(?:기간|일시|일자|날짜|마감|일정|기한)\s*[:：|]?\s*$"
)
_BARE_DATE_RANGE = re.compile(
    r"\s*(?:0?[1-9]|1[0-2])\s*[./]\s*(?:0?[1-9]|[12]\d|3[01])\s*"
    r"[~～–—]\s*(?:0?[1-9]|1[0-2])\s*[./]\s*(?:0?[1-9]|[12]\d|3[01])\s*"
)
_SOURCE_YEAR = re.compile(r"(?<!\d)(20\d{2})\s*년")
_SOURCE_THRESHOLD = re.compile(r"(?<![A-Za-z0-9])([\d,]+)\s*(?:점\s*)?(?:이상|이하|초과|미만)")
_SOURCE_COUNT_RANGE = re.compile(r"(?<!\d)(\d+)\s*[-~–]\s*(\d+)\s*명")
_SOURCE_ACRONYM = re.compile(r"(?<![A-Za-z0-9])(?:[A-Z]{2,}[A-Z0-9]*|\d+[A-Z]{1,3})(?![A-Za-z0-9])")
_SOURCE_TITLE_TERM = re.compile(r"(?<![A-Za-z])(?:[A-Z][a-z]{2,}\s+)+[A-Z][a-z]{2,}(?![A-Za-z])")
_MONTH_NAMES = (
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
)
_MONTH_NUMBERS = {
    spelling: number
    for number, name in enumerate(_MONTH_NAMES, start=1)
    for spelling in (name, name[:3], *(("sept",) if number == 9 else ()))
}
_ENGLISH_MONTH = "|".join(sorted(_MONTH_NUMBERS, key=len, reverse=True))
_ENGLISH_NAMED_DATE = re.compile(
    rf"\b({_ENGLISH_MONTH})\.?\s+(0?[1-9]|[12]\d|3[01])(?:st|nd|rd|th)?"
    r"(?:\s*,?\s*(20\d{2}))?(?!\d)", re.IGNORECASE,
)
_ENGLISH_DAY_MONTH = re.compile(
    rf"(?<!\d)(0?[1-9]|[12]\d|3[01])(?:st|nd|rd|th)?\s+(?:of\s+)?"
    rf"({_ENGLISH_MONTH})\.?(?:\s*,?\s*(20\d{{2}}))?\b", re.IGNORECASE,
)
_ENGLISH_DATE_LABEL = re.compile(
    r"\b(?:dates?|deadlines?|period|schedule|opens?|closes?|starts?|ends?|due)"
    r"(?:\s+(?:is|are|on|from|at|by|between))?\s*[:：|]?\s*$"
    r"|\b(?:apply|applications?|register|registration)\s+(?:by|until|from|on)\s*$"
    r"|^\s*(?:from|until|through|by|on|between)\s*$",
    re.IGNORECASE,
)
_ENGLISH_NUMERIC_MONTH_DAY = re.compile(
    r"(?<![\d./])(0?[1-9]|1[0-2])\s*[./]\s*(0?[1-9]|[12]\d|3[01])(?!\d|[./]\d)"
)
_DATE_CONTEXT_SUFFIX = re.compile(
    r"\s*(?:is\s+(?:the\s+)?)?(?:deadline|date|마감|일시|일자|기한)\b", re.IGNORECASE,
)
_DATE_RANGE_LINK = re.compile(
    rf"(?:{_CALENDAR_WEEKDAY.pattern})?\s*(?:[~～–—-]|to|through|until)\s*", re.IGNORECASE,
)
_SOURCE_INSTALLMENT = re.compile(
    r"(?P<number>[1-9]\d*)\s*(?:회\s*차|차|번째)\s*"
    r"(?:지원금|장학금|보조금|활동비|연구비|분할금|지급|입금|교부|수령)"
)
_INSTALLMENT_CONDITION_CUE = re.compile(
    r"한하여|한해|경우에만|때만|(?:제출|확인|검증|완료|승인|통과)\s*(?:후|시)"
)
_ORDINAL_WORDS = {
    1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth", 6: "sixth",
    7: "seventh", 8: "eighth", 9: "ninth", 10: "tenth", 11: "eleventh", 12: "twelfth",
}
_INSTALLMENT_NOUN = r"(?:instal(?:l)?ment|payment|disbursement|transfer|tranche)"
_SPENDING_RULES = (
    (r"기자재", r"\b(?:equipment|instruments?|apparatus|devices?)\b", "equipment"),
    (r"구입", r"\b(?:purchas\w*|buy\w*|bought|acquir\w*)\b", "purchase"),
    (r"대여", r"\b(?:rent\w*|hir\w*|borrow\w*|leas\w*)\b", "rental"),
    (r"재료비", r"\b(?:materials?|supplies)\b", "materials"),
    (r"도서", r"\bbooks?\b", "books"),
    (r"인쇄", r"\bprint\w*\b", "printing"),
    (r"카드\s*결제", r"\bcard\b", "card payment"),
    (r"방문", r"\bvisit\w*\b|\bin[ -]person\b|\bgo(?:ing)? to\b", "in-person visit"),
)
_SOURCE_CONDITIONS = (
    (r"프로그램\s*내\s*중복\s*(?:참여|신청)", r"\b(?:within|in|for)\s+(?:the\s+)?(?:same\s+|this\s+|single\s+)?program\b|\b(?:same|this|single)\s+program\b", "duplicate participation within the same program"),
    (r"비교과\s*통합\s*관리", r"\bextracurricular\b", "extracurricular system scope"),
    (r"연구지도\s*를\s*받는", r"\bresearch (?:supervision|guidance)\b|\bsupervised research\b", "receiving research supervision"),
    (r"휴학생[^\n]*연구비\s*및\s*활동비[^\n]*제외", r"\bresearch\b", "research funding exclusion"),
    (r"휴학생[^\n]*연구비\s*및\s*활동비[^\n]*제외", r"\bactivity\b", "activity allowance exclusion"),
    (r"학부\s*재학생", r"\benrolled\b|\bcurrently attending\b|\bregistered undergraduate", "enrolled undergraduates"),
    (r"교내", r"\b(?:on[ -]campus|campus|internal|university[ -]wide)\b|\bwithin (?:the |this |our )?(?:university|institution|school)\b|\b(?:at|from|by|of) (?:the|this|our|same) (?:university|institution|school)\b", "on-campus scope"),
    (r"동일", r"\b(?:same|identical)\b", "same topic"),
    (r"유사", r"\b(?:similar|comparable)\b", "similar topic"),
    (r"연구\s*주제[^\n]*지원\s*을\s*받는", r"\b(?:supported|funded)\b|\b(?:receiv(?:e[sd]?|ing)|get(?:s|ting)?|got|obtain(?:s|ed|ing)?)\b(?:\W+\w+){0,4}?\W+(?:support|funding|funds|grants?)\b|\bin receipt of (?:support|funding)\b", "receiving support qualification"),
    (r"최대", r"\b(?:up to|max(?:imum)?|at most|no more than|capped at|limit(?:ed)? to)\b", "maximum limit"),
    (r"1\s*인당", r"\b(?:per[ -](?:person|student|participant|individual|capita)|each (?:person|student|participant|individual))\b", "per-person amount"),
    (r"장학금", r"\bscholarships?\b", "scholarship payment"),
    (r"불허(?!\s*하지)", r"\b(?:no|not allowed|not permitted|prohibit\w*|forbid\w*|disallow\w*|cannot|may not)\b", "not allowed"),
    (r"지원\s*대상(?:에서는|에서)?\s*제외", r"\b(?:exclud\w*|not eligible|ineligible|not (?:be |receive |receiving )|cannot receive|without)\b", "exclusion from support"),
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
    unchanged and in order. This catches plausible yet incorrect substitutions
    in printed terminology without defining notice-specific translations.
    """
    detail_words = _ENGLISH_WORD.findall(detail_text.casefold())
    missing: list[str] = []
    for phrase in _protected_phrases(source_text):
        words = _ENGLISH_WORD.findall(phrase.casefold())
        if not any(detail_words[index:index + len(words)] == words for index in range(len(detail_words) - len(words) + 1)):
            missing.append(phrase)
    return missing


def missing_spending_rules(source_text: str, english_text: str) -> list[str]:
    """Guard common legible spending clauses that numerical checks cannot see.

    This is a narrow omission check, not a general translation verifier. The
    independent semantic audit still checks conditions and combined meaning.
    """
    missing = [
        meaning for source, english, meaning in _SPENDING_RULES
        if re.search(source, source_text) and not re.search(english, english_text, re.IGNORECASE)
    ]
    if (
        re.search(r"방문[^\n]{0,60}카드\s*결제", source_text)
        and not re.search(r"가능|선택|자율", source_text)
        and re.search(r"\b(?:can|may|optional(?:ly)?)\b", english_text, re.IGNORECASE)
    ):
        missing.append("prescribed in-person card-payment procedure")
    return missing


def missing_source_conditions(source_text: str, english_text: str) -> list[str]:
    """Check explicit scope, limits, payment categories, and exclusion wording.

    Only these recognized source conditions are checked locally; the audit
    remains responsible for their relationships and the rest of the meaning.
    """
    missing = [
        meaning for source, english, meaning in _SOURCE_CONDITIONS
        if re.search(source, source_text) and not re.search(english, english_text, re.IGNORECASE)
    ]
    missing.extend(_missing_installment_scope(source_text, english_text))
    return missing


def _missing_installment_scope(source_text: str, english_text: str) -> list[str]:
    """A condition for a numbered payment must retain that payment's identity.

    A total such as "three installments" does not establish which installment
    has a prerequisite. Match only explicit payment labels near a source
    condition; the semantic audit still verifies the prerequisite's meaning.
    """
    labels = list(_SOURCE_INSTALLMENT.finditer(source_text))
    conditional_orders: set[int] = set()
    for condition in _INSTALLMENT_CONDITION_CUE.finditer(source_text):
        nearby = [
            (max(label.start() - condition.end(), condition.start() - label.end(), 0), label)
            for label in labels
        ]
        if not nearby:
            continue
        distance, label = min(nearby, key=lambda pair: pair[0])
        if distance <= 80:
            conditional_orders.add(int(label["number"]))
    missing: list[str] = []
    for number in sorted(conditional_orders):
        ordinal = rf"(?:{_ORDINAL_WORDS.get(number, str(number))}|{number}(?:st|nd|rd|th)?)"
        label = (
            rf"\b{ordinal}\s+(?:(?:support|grant|scholarship|funding)\s+){{0,2}}{_INSTALLMENT_NOUN}\b"
            rf"|\b{_INSTALLMENT_NOUN}\s*(?:(?:number|no\.?|#)\s*)?{ordinal}\b"
        )
        if not re.search(label, english_text, re.IGNORECASE):
            missing.append(f"condition applying to installment {number}")
    return missing


def _display_numbers(text: str) -> set[Decimal]:
    values: set[Decimal] = set()
    for match in _DISPLAY_NUMBER.finditer(text):
        try:
            values.add(Decimal(match.group().replace(",", "")))
        except InvalidOperation:
            continue
    # A dotted calendar date otherwise becomes the decimal "2026.08" plus
    # "24", hiding its explicit year from the exact-date safeguard.
    values.update(Decimal(year) for year, _, _ in _SOURCE_DATE.findall(text))
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


def _contextual_month_days(
    text: str, date_pattern: re.Pattern[str], label_pattern: re.Pattern[str],
) -> set[tuple[None, int, int]]:
    """A decimal needs its own calendar cue or a direct link to a dated endpoint."""
    dates: set[tuple[None, int, int]] = set()
    for line in text.splitlines():
        pending = list(date_pattern.finditer(line))
        anchors = [
            (match.start(), match.end())
            for pattern in (_SOURCE_DATE, _SOURCE_MONTH_DAY, _ENGLISH_NAMED_DATE, _ENGLISH_DAY_MONTH)
            for match in pattern.finditer(line)
        ]
        bare_range = bool(_BARE_DATE_RANGE.fullmatch(line))
        # A cue at the final endpoint can establish the preceding range too.
        while pending:
            remaining = []
            for match in pending:
                linked = any(
                    (end <= match.start() and _DATE_RANGE_LINK.fullmatch(line[end:match.start()]))
                    or (match.end() <= start and _DATE_RANGE_LINK.fullmatch(line[match.end():start]))
                    for start, end in anchors
                )
                if (
                    bare_range or linked or label_pattern.search(line[:match.start()])
                    or _CALENDAR_WEEKDAY.match(line[match.end():])
                    or _DATE_CONTEXT_SUFFIX.match(line[match.end():])
                ):
                    dates.add((None, int(match[1]), int(match[2])))
                    anchors.append((match.start(), match.end()))
                else:
                    remaining.append(match)
            if len(remaining) == len(pending):
                break
            pending = remaining
    return dates


def _abbreviated_source_dates(source_text: str) -> set[tuple[None, int, int]]:
    """Recognize calendar context without treating every decimal as a date.

    Notice ranges commonly print the year only at the first endpoint. The
    abbreviated endpoint still needs its own month/day in English, but a bare
    range cannot establish a year. Weekdays and adjacent date labels also make
    an abbreviated date distinguishable from prices or software versions.
    """
    return _contextual_month_days(source_text, _ABBREVIATED_MONTH_DAY, _DATE_LABEL)


def _source_calendar_dates(source_text: str) -> set[tuple[int | None, int, int]]:
    dates = {(int(year), int(month), int(day)) for year, month, day in _SOURCE_DATE.findall(source_text)}
    dates.update((None, int(month), int(day)) for month, day in _SOURCE_MONTH_DAY.findall(source_text))
    dates.update(_abbreviated_source_dates(source_text))
    return {
        value for value in dates
        if value[0] is not None or not any(
            year is not None and (month, day) == value[1:]
            for year, month, day in dates
        )
    }


def _explicit_calendar_dates(text: str) -> set[tuple[int | None, int, int]]:
    dates = _source_calendar_dates(text)
    for month, day, year in _ENGLISH_NAMED_DATE.findall(text):
        dates.add((int(year) if year else None, _MONTH_NUMBERS[month.casefold()], int(day)))
    for day, month, year in _ENGLISH_DAY_MONTH.findall(text):
        dates.add((int(year) if year else None, _MONTH_NUMBERS[month.casefold()], int(day)))
    dates.update(_contextual_month_days(text, _ENGLISH_NUMERIC_MONTH_DAY, _ENGLISH_DATE_LABEL))
    dated_month_days = {(month, day) for year, month, day in dates if year is not None}
    return {value for value in dates if value[0] is not None or value[1:] not in dated_month_days}


def unsupported_source_dates(
    source_evidence: str, english_text: str, *, require_evidence: bool = False,
) -> list[str]:
    """Find explicit English dates that conflict with this field's calendar evidence.

    A valid endpoint may represent only part of a quoted range. Missing dates
    are a completeness concern, not a contradiction. An abbreviated source
    date cannot establish a year, which may legitimately come from context.
    require_evidence also rejects a new date when no source date was recognized.
    """
    source_dates = _explicit_calendar_dates(source_evidence)
    if not source_dates and not require_evidence:
        return []
    unsupported = []
    for year, month, day in sorted(_explicit_calendar_dates(english_text), key=lambda value: (value[0] or 0, value[1], value[2])):
        if not any(
            (source_month, source_day) == (month, day)
            and (year is None or source_year is None or source_year == year)
            for source_year, source_month, source_day in source_dates
        ):
            unsupported.append(f"{year or ''}-{month:02d}-{day:02d}".lstrip("-"))
    return unsupported


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

    dates = _source_calendar_dates(source_text)
    for year, month, day in sorted(dates, key=lambda value: (value[0] or 0, value[1], value[2])):
        if not _has_month_day(english_text, month, day) or (year and Decimal(year) not in numbers):
            missing.append(f"{year or ''}-{month:02d}-{day:02d}".lstrip("-"))

    for year in _SOURCE_YEAR.findall(source_text):
        if Decimal(year) not in numbers:
            missing.append(year)
    for score in _SOURCE_THRESHOLD.findall(source_text):
        if Decimal(score.replace(",", "")) not in numbers:
            missing.append(score)
    display_phones = phone_values(english_text)
    for digits, printed in phone_values(source_text).items():
        if digits not in display_phones:
            missing.append(f"phone {printed}")
    missing.extend(f"email {email}" for email in sorted(email_values(source_text) - email_values(english_text)))
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


def unsupported_currency_amounts(source_evidence: str, english_text: str) -> list[str]:
    """A monetary claim needs its amount in this item's actual quotation."""
    quoted_amounts = {
        Decimal(match[1].replace(",", "")) * _KRW_UNIT[match[2]]
        for match in _KRW_AMOUNT.finditer(source_evidence)
    }
    quoted_amounts.update(
        Decimal((match[1] or match[2]).replace(",", ""))
        for match in _ENGLISH_CURRENCY_AMOUNT.finditer(source_evidence)
    )
    unsupported = []
    for match in _ENGLISH_CURRENCY_AMOUNT.finditer(english_text):
        amount = Decimal((match[1] or match[2]).replace(",", ""))
        if amount not in quoted_amounts:
            unsupported.append(f"KRW {amount:,.0f}")
    return list(dict.fromkeys(unsupported))
