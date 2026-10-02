from __future__ import annotations

import re


_HANGUL_RUN = re.compile(r"[가-힣]+")
_LATIN_SOURCE = re.compile(r"[A-Za-z]")
_ENGLISH_TOKEN = re.compile(r"[A-Za-z]+(?:-[A-Za-z]+)*")
_NAME_ROLES = {"title", "contact", "contacts", "location", "locations", "name", "institution", "map", "app", "site"}
_SOURCE_NAME_ROLE = re.compile(
    r"대학교|대학|학교|병원|재단|협회|센터|교육원|연구원|기관|도서관|사무소|위원회|박물관|회사|"
    r"업체명|기관명|상호|이름|성명|명칭|지도|사이트|누리집|주소|위치|담당자|담당부서|문의|연락처|"
    r"앱(?=$|\s|[:：])|어플(?:리케이션)?"
)
_INITIAL = ("g", "kk", "n", "d", "tt", "r", "m", "b", "pp", "s", "ss", "", "j", "jj", "ch", "k", "t", "p", "h")
_VOWEL = ("a", "ae", "ya", "yae", "eo", "e", "yeo", "ye", "o", "wa", "wae", "oe", "yo", "u", "wo", "we", "wi", "yu", "eu", "ui", "i")
_FINAL = ("", "k", "k", "k", "n", "n", "n", "t", "l", "k", "m", "p", "l", "t", "p", "l", "m", "p", "p", "t", "t", "ng", "t", "t", "k", "t", "p", "t")
_UNVERIFIED_PHONETIC_NAME = (
    "A short caption contains a phonetic name whose identity or intended meaning is not established."
)


def _romanized_syllable(character: str) -> str:
    # This deliberately approximates syllables independently. It does not
    # implement assimilation, historical spelling, or full Korean phonology.
    index = ord(character) - 0xAC00
    initial, remainder = divmod(index, 21 * 28)
    vowel, final = divmod(remainder, 28)
    return _INITIAL[initial] + _VOWEL[vowel] + _FINAL[final]


def _matches_adjacent_syllables(token: str, syllables: list[str]) -> bool:
    for start in range(len(syllables) - 1):
        candidate = syllables[start]
        for syllable in syllables[start + 1:]:
            candidate += syllable
            if len(candidate) > len(token):
                break
            if token == candidate or token == candidate + "s":
                return True
    return False


def broken_transliteration_reason(
    source_evidence: str, english_text: str, *, field: str = "", label: str = "",
) -> str | None:
    """Identify uncertain phonetic names in short standalone OCR captions.

    Matching is a risk signal, not proof that an unfamiliar word is corrupted.
    Explicit names, printed Latin words, contextual quotations, and named roles
    are excluded. Complete single-word borrowings are retained; partial borrowed
    terms in mixed translations can still produce conservative false positives.
    No correction or notice-specific vocabulary is inferred here.
    """
    source = source_evidence.strip()
    if not source or len(source) > 20 or len(source.splitlines()) != 1:
        return None
    role, _, embedded_label = field.partition(":")
    if role.strip().casefold() in _NAME_ROLES or (label or embedded_label).strip().casefold() in _NAME_ROLES:
        return None
    if _LATIN_SOURCE.search(source) or _SOURCE_NAME_ROLE.search(source):
        return None
    runs = _HANGUL_RUN.findall(source)
    if not any(len(run) >= 2 for run in runs):
        return None
    tokens = _ENGLISH_TOKEN.findall(english_text)
    if not tokens:
        return None
    syllable_runs = [[_romanized_syllable(character) for character in run] for run in runs]
    whole_caption = "".join(syllable for run in syllable_runs for syllable in run)
    for original_token in tokens:
        token = original_token.replace("-", "").casefold()
        # Established borrowed words are not distinguishable from romanization
        # by decomposition alone. Avoid rejecting a complete unhyphenated word.
        if len(tokens) == 1 and "-" not in original_token and token == whole_caption:
            continue
        if len(token) >= 3 and any(_matches_adjacent_syllables(token, run) for run in syllable_runs):
            return _UNVERIFIED_PHONETIC_NAME
    return None
