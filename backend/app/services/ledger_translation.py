from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal
from time import perf_counter

import httpx

from app.models import SourceBlock, SourceLedger
from app.services.ledger_ids import derived_id
from app.services.english_literals import (
    missing_source_values,
    unsupported_currency_amounts,
    unsupported_source_dates,
)
from app.services.image_translation import HANGUL, _translate_standalone_threshold
from app.services.source_contacts import (
    email_values,
    phone_values,
    unsupported_contacts,
)
from app.services.translation import (
    LibreTranslateProvider,
    MyMemoryTranslationProvider,
    TranslationError,
    TranslationProvider,
    choose_translation_provider,
    split_utf8_chunks,
)


_MAX_CONCURRENCY = 4
_URL = re.compile(
    r"https?://[^\s<>\"'\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]+", re.IGNORECASE
)
_TIME = re.compile(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)\s*(am|pm)?", re.IGNORECASE)
_KOREAN_TIME = re.compile(
    r"(오전|오후)?\s*(?<!\d)([01]?\d|2[0-3])\s*시(?:\s*([0-5]?\d)\s*분)?"
)
_ENGLISH_TIME = re.compile(r"(?<!\d)(1[0-2]|0?[1-9])\s*(am|pm)\b", re.IGNORECASE)
_KRW = re.compile(r"(?<!\d)([\d,]+(?:\.\d+)?)\s*(억|만|천)?\s*원")
_KRW_MULTIPLIER = {None: 1, "천": 1000, "만": 10000, "억": 100000000}
_EXAM = re.compile(
    r"(?<![A-Za-z])(?:TOEIC\s+Speaking|TOEFL(?:\s*(?:\(\s*)?iBT\s*\)?)?|TOEIC|TEPS|FLEX|OPIc|IELTS)(?![A-Za-z])",
    re.IGNORECASE,
)
_SCORE = re.compile(
    r"(?<![A-Za-z0-9])(?:\d{1,4}(?:\.\d+)?[A-Za-z]{0,2}|IM[123]|IH|AL)(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_NEGATIVE_SOURCE = re.compile(
    r"불가|불허|금지|허용\s*안|허용하지|할\s*수\s*없|하지\s*않|아니[한다며]|제외|미제출|부적격"
)
_NEGATIVE_ENGLISH = re.compile(
    r"\b(?:no|not|cannot|can't|mustn't|without|never|ineligible|except|exclud\w*|prohibit\w*|forbid\w*|disallow\w*|fail\w*\s+to\s+submit)\b",
    re.IGNORECASE,
)
_ELIGIBILITY = (
    (
        r"재학생|재학\s*중",
        r"\benrolled\b|\bcurrently (?:attending|registered)\b",
        "enrolled-student condition",
    ),
    (r"휴학생|휴학\s*중", r"\bleave\b", "leave-of-absence condition"),
    (
        r"졸업\s*예정",
        r"\b(?:expected|expecting|scheduled|prospective|soon)\b.{0,40}\bgraduat\w*\b|\bgraduat\w*\b.{0,40}\b(?:expected|soon)\b",
        "expected-graduation condition",
    ),
)
_SOURCE_CONSTRAINTS = (
    (
        r"학생\s*자율\s*선정\s*주제",
        r"\bstudents?\b.{0,60}\b(?:select\w*|chosen|choos\w*|choice|own|independen\w*|autonom\w*)\b|\b(?:select\w*|chosen|choos\w*|independen\w*|autonom\w*)\b.{0,60}\bstudents?\b",
        "student-selected topic option",
    ),
    (r"(?:^|\n)\s*연구비\s*[:：]", r"\bresearch\b", "research funding category"),
    (
        r"(?:^|\n)\s*활동비\s*[:：]",
        r"\bactivity\b|\bactivities\b",
        "activity funding category",
    ),
    (
        r"제한",
        r"\b(?:restrict\w*|limit\w*|ineligible|not permitted|prohibit\w*|forbid\w*|exclud\w*)\b",
        "restriction",
    ),
    (r"최대", r"\b(?:maximum|up to|at most|no more than|capped at)\b", "maximum limit"),
    (
        r"(?:1\s*)?인당",
        r"\bper[ -](?:person|student|participant|individual|capita)\b|\beach (?:person|student|participant|individual)\b",
        "per-person scope",
    ),
    (r"장학금", r"\bscholarships?\b", "scholarship category"),
    (r"카드\s*결제", r"\bcard\b", "card-payment procedure"),
    (r"필수", r"\b(?:required|must|mandatory|essential)\b", "mandatory condition"),
    (
        r"추첨",
        r"\b(?:lottery|draw|random(?:ly)?|raffle)\b",
        "lottery condition",
    ),
)
_COMPARISONS = (
    (
        "이상",
        r"\b(?:or more|or higher|or above|at least|minimum|not less than)\b|>=|≥",
        "inclusive minimum",
    ),
    (
        "이하",
        r"\b(?:or less|or lower|or below|at most|maximum|no more than|up to)\b|<=|≤",
        "inclusive maximum",
    ),
    (
        "이내",
        r"\b(?:or less|or fewer|at most|maximum|no more than|up to|within)\b|<=|≤",
        "inclusive maximum",
    ),
    (
        "초과",
        r"\b(?:more than|greater than|exceed\w*)\b|(?<![<>=])>(?!=)",
        "exclusive minimum",
    ),
    ("미만", r"\b(?:less than|below|under)\b|(?<![<>=])<(?!=)", "exclusive maximum"),
)
_DIGIT_COMPARISON = re.compile(
    r"([A-Za-z0-9,]+(?:\.[0-9]+)?)[ \t]*(?:점|명|인|개|(?:억|만|천)?\s*원)?[ \t]*(이상|이하|이내|초과|미만)"
)
_DECIMAL_THRESHOLD = re.compile(
    r"(?<![\w.])(\d+\.\d+)\s*(?:점\s*)?(이상|이하|초과|미만)"
)
_NUMBER = re.compile(r"(?<![A-Za-z0-9])\d[\d,]*(?:\.\d+)?(?![A-Za-z0-9])")


@dataclass(frozen=True)
class TranslationChunk:
    id: str
    text: str


@dataclass(frozen=True)
class ChunkTranslation:
    id: str
    text: str = ""
    error: str | None = None
    request_count: int = 1
    usage_complete: bool = True


ChunkTransport = Callable[[list[TranslationChunk]], Awaitable[list[ChunkTranslation]]]


def _clock_values(text: str) -> set[tuple[int, int]]:
    values: set[tuple[int, int]] = set()
    for hour, minute, period in _TIME.findall(text):
        value = int(hour)
        if period:
            value = value % 12 + (12 if period.lower() == "pm" else 0)
        values.add((value, int(minute)))
    for period, hour, minute in _KOREAN_TIME.findall(text):
        value = int(hour)
        if period:
            value = value % 12 + (12 if period == "오후" else 0)
        values.add((value, int(minute or 0)))
    for hour, period in _ENGLISH_TIME.findall(text):
        values.add((int(hour) % 12 + (12 if period.lower() == "pm" else 0), 0))
    return values


def _exam_label(text: str) -> str:
    normalized = re.sub(r"[\s()]", "", text).casefold()
    return {"toeflibt": "toefl ibt", "toeicspeaking": "toeic speaking"}.get(
        normalized, normalized
    )


def _exam_segments(text: str) -> list[tuple[str, str]]:
    labels = list(_EXAM.finditer(text))
    segments = []
    for index, label in enumerate(labels):
        end = labels[index + 1].start() if index + 1 < len(labels) else len(text)
        # Restrict association to the adjacent cell/row, never a later section.
        tail = text[label.end() : min(end, label.end() + 45)]
        name = _exam_label(label.group())
        segments.append((name, tail))
    return segments


def _exam_scores(text: str) -> list[tuple[str, str]]:
    pairs = []
    for name, tail in _exam_segments(text):
        score = _SCORE.search(tail)
        if score:
            pairs.append((name, score.group().casefold()))
    return pairs


def validate_protected_values(source: str, english: str) -> list[str]:
    """Detect literal loss and contradictions; this is not a meaning audit."""
    # The shared legacy threshold guard recognizes integers only. Remove its
    # fractional-digit false positives and check whole decimals explicitly.
    legacy_source = _DECIMAL_THRESHOLD.sub(
        lambda match: f"[decimal threshold] {match[2]}", source
    )
    legacy_english = re.sub(r"\bTOEFLiBT\b", "TOEFL iBT", english, flags=re.IGNORECASE)
    issues = [
        f"missing value: {value}"
        for value in missing_source_values(legacy_source, legacy_english)
    ]
    english_numbers = {
        Decimal(match.group().replace(",", "")) for match in _NUMBER.finditer(english)
    }
    for number, _ in _DECIMAL_THRESHOLD.findall(source):
        if Decimal(number) not in english_numbers:
            issues.append(f"missing numeric threshold: {number}")
    issues.extend(
        f"unsupported amount: {value}"
        for value in unsupported_currency_amounts(source, english)
    )
    issues.extend(
        f"unsupported date: {value}"
        for value in unsupported_source_dates(source, english, require_evidence=True)
    )
    issues.extend(
        f"unsupported contact: {value}"
        for value in unsupported_contacts(source, english)
    )
    english_times = _clock_values(english)
    source_times = _clock_values(source)
    for hour, minute in sorted(source_times - english_times):
        issues.append(f"missing time: {hour:02d}:{minute:02d}")
    for hour, minute in sorted(english_times - source_times):
        issues.append(f"unsupported time: {hour:02d}:{minute:02d}")
    for url in _URL.findall(source):
        if url.rstrip(".,;)") not in english:
            issues.append(f"missing URL: {url.rstrip('.,;)')}")
    if _NEGATIVE_SOURCE.search(source) and not _NEGATIVE_ENGLISH.search(english):
        issues.append("missing negation or exclusion")
    for korean, pattern, description in (*_ELIGIBILITY, *_SOURCE_CONSTRAINTS):
        if re.search(korean, source) and not re.search(pattern, english, re.IGNORECASE):
            issues.append(f"missing {description}")
    for match in _DIGIT_COMPARISON.finditer(source):
        korean = match[2]
        pattern, description = next(
            (pattern, label) for word, pattern, label in _COMPARISONS if word == korean
        )
        if not re.search(pattern, english, re.IGNORECASE):
            issues.append(f"missing {description} for {match[1]}")
        if (
            re.fullmatch(r"[\d,.]+", match[1])
            and not _KRW.search(match.group())
            and Decimal(match[1].replace(",", "")) not in english_numbers
        ):
            issues.append(f"missing numeric threshold: {match[1]}")
    english_pairs = set(_exam_scores(english))
    source_exams = {_exam_label(match.group()) for match in _EXAM.finditer(source)}
    english_exams = {_exam_label(match.group()) for match in _EXAM.finditer(english)}
    issues.extend(
        f"unsupported exam name: {name}"
        for name in sorted(english_exams - source_exams)
    )
    for label, score in _exam_scores(source):
        if (label, score) not in english_pairs:
            issues.append(f"missing or changed score pairing: {label} / {score}")
    for label, source_tail in _exam_segments(source):
        comparison = _DIGIT_COMPARISON.search(source_tail)
        if not comparison:
            continue
        matching_tails = [
            tail
            for name, tail in _exam_segments(english)
            if name == label
            and (score := _SCORE.search(tail))
            and score.group().casefold() == comparison[1].casefold()
        ]
        pattern, description = next(
            (pattern, label)
            for word, pattern, label in _COMPARISONS
            if word == comparison[2]
        )
        if not any(re.search(pattern, tail, re.IGNORECASE) for tail in matching_tails):
            issues.append(f"changed threshold direction: {label} / {description}")
    return list(dict.fromkeys(issues))


def _romanize(text: str) -> str:
    # Revised-Romanization syllable decomposition preserves OCR spelling rather
    # than guessing a word. Pronunciation assimilation is deliberately omitted.
    initials = (
        "g",
        "kk",
        "n",
        "d",
        "tt",
        "r",
        "m",
        "b",
        "pp",
        "s",
        "ss",
        "",
        "j",
        "jj",
        "ch",
        "k",
        "t",
        "p",
        "h",
    )
    vowels = (
        "a",
        "ae",
        "ya",
        "yae",
        "eo",
        "e",
        "yeo",
        "ye",
        "o",
        "wa",
        "wae",
        "oe",
        "yo",
        "u",
        "wo",
        "we",
        "wi",
        "yu",
        "eu",
        "ui",
        "i",
    )
    finals = (
        "",
        "k",
        "kk",
        "ks",
        "n",
        "nj",
        "nh",
        "t",
        "l",
        "lk",
        "lm",
        "lp",
        "ls",
        "lt",
        "lp",
        "lh",
        "m",
        "p",
        "ps",
        "t",
        "t",
        "ng",
        "t",
        "t",
        "k",
        "t",
        "p",
        "h",
    )
    result = []
    for character in text:
        code = ord(character) - 0xAC00
        if 0 <= code <= 11171:
            result.append(
                initials[code // 588] + vowels[(code % 588) // 28] + finals[code % 28]
            )
        elif HANGUL.fullmatch(character):
            result.append(f"[character U+{ord(character):04X}]")
        else:
            result.append(character)
    return "".join(result)


def _literal_values(source: str) -> list[str]:
    values = []
    for match in _KRW.finditer(source):
        amount = Decimal(match[1].replace(",", "")) * _KRW_MULTIPLIER[match[2]]
        values.append(f"KRW {amount:,.0f}")
    values.extend(
        f"{hour:02d}:{minute:02d}" for hour, minute in sorted(_clock_values(source))
    )
    values.extend(phone_values(source).values())
    values.extend(sorted(email_values(source)))
    values.extend(url.rstrip(".,;)") for url in _URL.findall(source))
    values.extend(
        f"{label.upper()} {score.upper()}" for label, score in _exam_scores(source)
    )
    # Include exact printed numeric dates and ranges in addition to normalized
    # amounts/times. No year, digit, or lower/upper endpoint is inferred.
    values.extend(
        re.findall(r"(?<![A-Za-z0-9])\d[\d.,:/~–— -]*\d(?![A-Za-z0-9])", source)
    )
    for match in _DIGIT_COMPARISON.finditer(source):
        label = next(label for word, _, label in _COMPARISONS if word == match[2])
        values.append(f"{label}: {match[1]}")
    if _NEGATIVE_SOURCE.search(source):
        values.append("restriction/exclusion marker present")
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))


def literal_translation(source: str) -> str | None:
    """Translate only whole, unambiguous cells without a provider."""
    threshold = _translate_standalone_threshold(source)
    if threshold:
        return threshold
    funding = re.fullmatch(
        r"\s*(연구비|활동비)\s*[:：]\s*1\s*인당\s*(최대\s*)?([\d,]+(?:\.\d+)?)\s*(억|만|천)?원\s*",
        source,
    )
    if funding:
        amount = Decimal(funding[3].replace(",", "")) * _KRW_MULTIPLIER[funding[4]]
        category = "Research funding" if funding[1] == "연구비" else "Activity funding"
        return (
            f"{category}: {'up to ' if funding[2] else ''}KRW {amount:,.0f} per person."
        )
    if re.fullmatch(
        r"\s*[*·•-]?\s*프로그램\s*내\s*중복\s*참여\s*(?:불허|불가|금지)\s*[.]?\s*",
        source,
    ):
        return "Duplicate participation within the same program is not allowed."
    enrolled = re.fullmatch(
        r"\s*(?:(20\d{2})\s*학년도\s*)?(?:([12])\s*학기\s*)?학부\s*재학생\s*", source
    )
    if enrolled:
        text = "Currently enrolled undergraduate students"
        if enrolled[2]:
            text += f" in the {'first' if enrolled[2] == '1' else 'second'} semester"
        if enrolled[1]:
            text += f" of the {enrolled[1]} academic year"
        return text + "."
    university_enrolled = re.fullmatch(
        r"\s*([가-힣]{1,30})대학교\s*학부\s*재학생\s*"
        r"(?:\(\s*휴학생\s*(?:참가|참여)\s*가능\s*\))?\s*",
        source,
    )
    if university_enrolled:
        # The source establishes the institution and condition, but not its
        # official English name. Label the deterministic name transcription.
        name = _romanize(university_enrolled[1]).capitalize()
        text = f"Currently enrolled undergraduate students at {name} University (name transliterated)."
        if "휴학생" in source:
            text += " Students on leave may participate."
        return text
    team = re.fullmatch(
        r"\s*개인\s*또는\s*팀\s*\(\s*(\d+)\s*(?:인|명)\s*이내\s*\)\s*"
        r"(?:참가|참여)\s*가능\s*",
        source,
    )
    if team:
        return f"Individuals or teams of up to {team[1]} people may participate."
    supported_participants = re.fullmatch(
        r"\s*지원\s*을?\s*받는\s*(학생\s*및\s*팀|학생|팀)\s*(?:은|는)\s*"
        r"참여\s*(?:가\s*)?제한\s*[.]?\s*",
        source,
    )
    if supported_participants:
        audience = {
            "학생및팀": "Students and teams",
            "학생": "Students",
            "팀": "Teams",
        }[re.sub(r"\s+", "", supported_participants[1])]
        return f"{audience} receiving support are restricted from participation."
    return None


def best_effort_english(source: str) -> str:
    """A labeled source fallback, never a claim that unreadable meaning is known."""
    if not source.strip():
        return "Image detail: see the original crop."
    if not HANGUL.search(source):
        return source.strip()
    literal = literal_translation(source)
    if literal:
        return literal
    text = f"Source wording (romanized): {_romanize(source).strip()}"
    literals = _literal_values(source)
    if literals:
        text += "\nPrinted values: " + "; ".join(literals)
    return text


async def _provider_chunks(
    provider: TranslationProvider, chunks: list[TranslationChunk]
) -> list[ChunkTranslation]:
    semaphore = asyncio.Semaphore(_MAX_CONCURRENCY)

    async def translate(chunk: TranslationChunk) -> ChunkTranslation:
        async with semaphore:
            try:
                result = await provider.translate(chunk.text, "ko", "en")
            except TranslationError as exc:
                return ChunkTranslation(chunk.id, error=str(exc), usage_complete=False)
            return ChunkTranslation(
                chunk.id, text=result.text, request_count=result.request_count
            )

    tasks = [asyncio.create_task(translate(chunk)) for chunk in chunks]
    try:
        return await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def _with_session(
    provider: TranslationProvider, chunks: list[TranslationChunk]
) -> list[ChunkTranslation]:
    if (
        isinstance(provider, (MyMemoryTranslationProvider, LibreTranslateProvider))
        and provider.client is None
    ):
        limits = httpx.Limits(
            max_connections=_MAX_CONCURRENCY, max_keepalive_connections=_MAX_CONCURRENCY
        )
        async with httpx.AsyncClient(limits=limits) as client:
            provider.client = client
            try:
                return await _provider_chunks(provider, chunks)
            finally:
                provider.client = None
    return await _provider_chunks(provider, chunks)


def _candidate_gaps(ledger: SourceLedger) -> dict[str, str]:
    gaps = {}
    for unit in ledger.units:
        for candidate in unit.alternatives:
            if candidate.text == unit.source_text:
                continue
            # Both directions matter: a candidate can add a value or erase a
            # prohibition. English validation of Korean alone is inappropriate.
            primary = _literal_values(unit.source_text)
            alternate = _literal_values(candidate.text)
            if primary != alternate or bool(
                _NEGATIVE_SOURCE.search(unit.source_text)
            ) != bool(_NEGATIVE_SOURCE.search(candidate.text)):
                gaps[unit.id] = (
                    f"{unit.id}: OCR candidates disagree on protected values or negation"
                )
                break
            if (
                re.sub(r"\s+", "", candidate.text).casefold()
                != re.sub(r"\s+", "", unit.source_text).casefold()
            ):
                gaps[unit.id] = f"{unit.id}: OCR candidates have different wording"
    return gaps


async def translate_ledger(
    ledger: SourceLedger,
    *,
    provider: TranslationProvider | None = None,
    translate_chunks: ChunkTransport | None = None,
) -> SourceLedger:
    """Translate explicit source groups and reconcile every labeled chunk."""
    started = perf_counter()
    result = ledger.model_copy(deep=True)
    units = {unit.id: unit for unit in result.units}
    mapped = {unit_id for block in result.blocks for unit_id in block.unit_ids}
    for unit in result.units:
        if unit.id not in mapped:
            block_id = derived_id("source", unit.id)
            result.blocks.append(
                SourceBlock(
                    id=block_id,
                    unit_ids=[unit.id],
                    source_text=unit.source_text,
                    section_id=unit.section_id,
                )
            )
            unit.block_id = block_id

    chunk_by_text: dict[str, TranslationChunk] = {}
    block_chunks: dict[str, list[TranslationChunk]] = {}
    local: dict[str, str] = {}
    for block in result.blocks:
        # Source units are authoritative; client/model joined text is a view.
        block.source_text = "\n".join(
            units[unit_id].source_text for unit_id in block.unit_ids
        )
        if not HANGUL.search(block.source_text):
            local[block.id] = block.source_text.strip() or best_effort_english("")
            continue
        literal = literal_translation(block.source_text)
        if literal:
            local[block.id] = literal
            continue
        chunks = []
        for text in split_utf8_chunks(block.source_text):
            if text not in chunk_by_text:
                chunk_by_text[text] = TranslationChunk(
                    id=f"chunk-{len(chunk_by_text)}", text=text
                )
            chunks.append(chunk_by_text[text])
        block_chunks[block.id] = chunks

    responses: list[ChunkTranslation] = []
    provider_name = "local"
    if chunk_by_text:
        if translate_chunks:
            provider_name = provider.name if provider else "chunk-transport"
            try:
                responses = await translate_chunks(list(chunk_by_text.values()))
            except TranslationError:
                result.metrics.usage_complete = False
        else:
            try:
                provider = provider or choose_translation_provider(mock=False)
            except TranslationError:
                result.metrics.usage_complete = False
                provider_name = "unavailable"
            else:
                provider_name = provider.name
                responses = await _with_session(provider, list(chunk_by_text.values()))

    validation_started = perf_counter()
    expected_ids = {chunk.id for chunk in chunk_by_text.values()}
    responses_by_id: dict[str, list[ChunkTranslation]] = {}
    for response in responses:
        responses_by_id.setdefault(response.id, []).append(response)
    if set(responses_by_id) != expected_ids or any(
        len(items) != 1 for items in responses_by_id.values()
    ):
        result.metrics.usage_complete = False
    result.metrics.translation_requests += sum(
        response.request_count for response in responses
    )
    result.metrics.usage_complete &= all(
        response.usage_complete for response in responses
    )
    candidate_gaps = _candidate_gaps(result)
    gaps = list(candidate_gaps.values())
    for block in result.blocks:
        issues: list[str] = []
        if block.id in local:
            english = local[block.id]
            status = "translated" if block.source_text.strip() else "source_crop"
            block_provider = "local"
        else:
            pieces = []
            for chunk in block_chunks[block.id]:
                items = responses_by_id.get(chunk.id, [])
                if (
                    len(items) != 1
                    or items[0].error
                    or not items[0].text.strip()
                    or HANGUL.search(items[0].text)
                ):
                    issues.append(f"incomplete translation chunk {chunk.id}")
                    continue
                chunk_issues = validate_protected_values(chunk.text, items[0].text)
                if chunk_issues:
                    issues.extend(chunk_issues)
                else:
                    pieces.append(items[0].text.strip())
            english = "\n".join(pieces)
            if not issues:
                combined_issues = validate_protected_values(block.source_text, english)
                if combined_issues:
                    # A cross-chunk contradiction invalidates the combined
                    # reading, even if each fragment looked plausible alone.
                    english = ""
                    issues.extend(combined_issues)
            if issues:
                # Retain successful chunks as a partial reading alongside the
                # complete source fallback, with all original unit IDs intact.
                fallback = best_effort_english(block.source_text)
                english = (
                    f"Partial English reading: {english}\n{fallback}"
                    if english
                    else fallback
                )
            status = "source_crop" if issues else "translated"
            block_provider = provider_name
        risky_units = [
            units[unit_id]
            for unit_id in block.unit_ids
            if unit_id in candidate_gaps
            or (
                units[unit_id].confidence is not None
                and units[unit_id].confidence < 0.85
            )
            or any(
                gap.startswith(f"{unit_id}: ambiguous English-test geometry")
                for gap in result.coverage.protected_value_gaps
            )
        ]
        if risky_units and status == "translated":
            # Fluent machine translation cannot establish what damaged OCR
            # actually said. Preserve it only as a labeled reading aid.
            english = f"Partial English reading: {english}\n{best_effort_english(block.source_text)}"
            status = "source_crop"
            gaps.extend(
                f"{unit.id}: low-confidence or conflicting source reading"
                for unit in risky_units
            )
        block.english = english
        block.translation_status = status
        for unit_id in block.unit_ids:
            unit = units[unit_id]
            unit.english = english
            unit.translation_provider = block_provider
            unit.translation_status = status
            unit.translation_source_ids = list(block.unit_ids)
        gaps.extend(f"{block.id}: {issue}" for issue in issues)

    result.coverage.source_unit_ids = [unit.id for unit in result.units]
    result.coverage.translated_unit_ids = [
        unit.id for unit in result.units if unit.translation_status == "translated"
    ]
    result.coverage.fallback_unit_ids = [
        unit.id
        for unit in result.units
        if unit.translation_status in {"literal", "source_crop"}
    ]
    result.coverage.protected_value_gaps = list(
        dict.fromkeys([*result.coverage.protected_value_gaps, *gaps])
    )
    result.coverage.meaning_checked = False
    validation_ms = round((perf_counter() - validation_started) * 1000)
    result.metrics.validation_ms += validation_ms
    result.metrics.translation_ms += max(
        0, round((perf_counter() - started) * 1000) - validation_ms
    )
    return result
