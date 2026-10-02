# Version 2 recovery verification

Report date: October 1, 2026 (Asia/Seoul); the local measurements and replay below were
recorded on September 30.

This report records checks of the existing Version 2 implementation on
`prototype/paddleocr-gpt41mini`. Version 1 and `main` are outside this change. It is a
verification record, not a claim that OCR or semantic interpretation has no omissions.
The final hosted release and measurements are recorded in the table and final results
below. The intervening local comparison is retained as historical evidence, explicitly
separate from the final hosted responses. Availability correction: the earlier search missed the KCCI original in stored
uploads. The user subsequently supplied a folder containing five real photos,
including both primary regressions. Historical "unavailable" rows below describe
that earlier incomplete search, not the current inventory. See
[V2_GENERALIZATION_VERIFICATION.md](V2_GENERALIZATION_VERIFICATION.md) for the
current broader implementation and photo checks.

## Final verification record

| Check | Final artifact or measurement | Status |
|---|---|---|
| Reviewed runtime commit | `b23a74c9100490791795f5fd3664b7d63bd1eebc`; pushed only to `prototype/paddleocr-gpt41mini` | Reviewed and deployed; final report is a subsequent documentation commit |
| Backend regression tests and Ruff | Final validation: 308 backend tests and Ruff passed | Passed local checks |
| Frontend regression tests, lint, and build | Final validation: 53 tests across 8 files, ESLint, TypeScript, and Vite production build passed | Passed local checks |
| Corrected Sogang text through the local API | `final-audited-local-corrected.json`, HTTP 200; 49.161 s request wall time | Measured local response; final wording reviewed through replay |
| Final source-grounded wording replay | `final-wording-replay.json`, created at 23:59:18 on September 30, 2026 (Asia/Seoul) | All 21 substantive lines compared; no new API/provider/OCR calls |
| Corrected Sogang text through the final hosted API | HTTP 200; 27.818 s; final-b23-hosted-corrected.json | 21-line requested-meaning review; 31/31 displayed citations match; no Hangul display fields |
| All 21 corrected Sogang source lines against the latest reviewed local English digest | Manual comparison below against `final-wording-replay.json` | Requested substantive requirements matched; bounded review |
| Raw browser-OCR fixture correction request | HTTP 422 in 674 ms; exact page 1, physical line 48 damaged contact correction before external calls | Historical OCR replay; no fresh primary image inference |
| Browser image upload, OCR, correction retry, and local photo retention | Hosted UI analysis completed after correction and a further provider retry; 41.9 s measured OCR plus latest server request, three semantic calls, 7,235 tokens | Different actual undergraduate research-support poster; corrected retry verified |
| Actual primary Sogang poster photo through the complete hosted flow | Source photo unavailable during this review | Unavailable; corrected text and recorded OCR fixtures only |
| Actual Korea Chamber of Commerce hiring photo | Source photo unavailable during this review | Unavailable; synthetic table regression tests only |
| Linked Vercel deployment and usable application | `dpl_CCE2V6HVeWT78kxt3bdwhnt9xsyw`; existing alias unchanged | Ready; final endpoint/asset checks recorded below |

## Final hosted release verification

Runtime commit: `b23a74c9100490791795f5fd3664b7d63bd1eebc`, experimental branch
`prototype/paddleocr-gpt41mini`. No merge into `main`, Version 1 rewrite, new paid OCR
container, dependency, or deployment configuration change was made.

The final Ready deployment is `dpl_CCE2V6HVeWT78kxt3bdwhnt9xsyw`:
<https://univis-v2-prototype-9da2n54as-opcleaver0-6769s-projects.vercel.app/>. The
linked alias remains <https://univis-v2-prototype.vercel.app/>. Inspection confirmed
static frontend assets and a 41.65 MB Python API function in `iad1`. `framework: null`,
explicit frontend build/install, function exclusions, and Python 3.12 are unchanged. The
live model remains `gpt-4o-mini`, with temporary MyMemory translation and browser
PaddleOCR; recognized text is sent to the API, while hosted photo bytes stay in the
browser.

Commands run from the repository root:

```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend/tests -q
ruff check backend/app backend/tests backend/scripts
npm.cmd --prefix frontend test
npm.cmd --prefix frontend run lint
npm.cmd --prefix frontend run build
git diff --check
```

Results: 308 backend tests, 53 frontend tests across 8 files, Ruff, ESLint, TypeScript,
Vite production build, and diff checks passed. The final Vercel deployment also
completed the TypeScript/Vite build. Existing OpenCV externalization/large OCR-WASM
chunk warnings and backend dependency deprecations were nonfatal. Diff review covered
correction state, optional document conditions, exact-value/negation guards, page
provenance, contained and disjoint citations, table ambiguity, and provider errors.
Tracked environment files remain examples; the frontend build key-pattern scan found no
key-shaped strings. This is a focused scan, not a security audit.

The frontend tests/lint/build were completed on September 30; frontend source was
unchanged in the subsequent backend-only commits. The final deployment rebuilt the same
frontend asset hashes on October 1.

### Final primary fixture measurements and review

Final hosted artifact: `final-b23-hosted-corrected.json`. HTTP 200 at 14:43:14 KST on
October 1. Request wall time 27.818 s; API total 26.870 s; translation 1.373 s,
extraction 14.476 s, English repair 0 s, audit 10.972 s; semantic total 25.448 s. Four
translation requests and three semantic calls used 6,633 input plus 2,303 output tokens
(8,936 total). The profile was run with:

```powershell
.\backend\.venv\Scripts\python.exe backend/scripts/profile_notice.py --text backend/tests/fixtures/sogang_research_corrected.txt --base-url https://univis-v2-prototype.vercel.app --output C:\Users\Lam\AppData\Local\Temp\univis-verification\final-b23-hosted-corrected.json
```

Independent bilingual comparison retained the requested substantive meanings across all
21 source lines; all 31 displayed grounded quotations and all 30 source-fact quotations
matched the fixture, with nonempty evidence and no Hangul display fields. Fidelity
recorded 29/29 identified critical facts linked, no warnings, unknown references,
missing/invented flags, or unmapped lines; these are structural checks, not universal
completeness proof. This separately checks all 21 substantive fixture lines listed in
the historical comparison table: exact dates, enrolled/leave status, 2–5-person teams,
all duplicate-support qualifications, all designated and student-selected topics, both
distinct funding categories, spending/card visit and scholarship payment rules, all
three documents/S Plus, and exact contacts. Mandatory announcement checking and core AI
technology wording were retained. This final digest omits the printed weekday names
while preserving both exact dates and their range; the source evidence retains the
weekdays. It repeats some funding/eligibility/application statements, and copied
application details retain pipe separators. The local replay above has no final-run
timing.

A preceding hosted run at `078980e` took 32.436 seconds, with 1.333 seconds translation,
20.744 seconds extraction, 0 English repair, and 9.320 seconds audit; 4 translation
requests, 3 semantic calls, 9,504 tokens (6,399 input, 3,105 output). Review caught one
invalid composite citation, consisting of a partial quote plus its containing full
quote, and it was fixed before this release. Earlier reviewed hosted candidates took
30.785, 33.307, and 40.054 seconds. These are single runs with variable
provider/network/audit behavior; they do not establish a reliable speedup. The 10–15
second target is unmet. Semantic substage times are already included in semantic time.

A `d35e215` candidate returned HTTP 502 after 30.667 seconds because the audit repair
omitted book purchases. The final release expands the existing exact complete
spending-clause correction to retain every cited category locally; modified
clauses/additional exclusions still go through the generic audit. That failed candidate
is not counted as a successful benchmark.

### Final raw OCR replay and actual-photo retry

`final-b23-hosted-raw.json`: HTTP 422 in 674 ms. The request quotes page 1, physical
line 48, including `02.710.25n0`, and asks for exact digits from the original or a
close-up. It does not infer `2500`. This check replays historical OCR/positions, not a
new primary photo-recognition pass.

The different actual undergraduate research-support photo was uploaded through the
hosted image UI. OCR recovered 477 characters including the phone/email footer and
performed one additional lower-page check. Seal fragments and conflicting readings
remained visible for correction. A visually checked 409-character transcription removed
confirmed seal/duplicate noise and joined the continuous heading and clauses. The final
corrected retry used `/api/analyze-client-ocr` without repeating OCR. Hosted UI analysis
completed after correction and a further provider retry; 41.9 s measured OCR plus latest
server request, three semantic calls, 7,235 tokens.

OCR preparation (model reused) 0.0 s, detection 4.9 s, recognition 7.1 s, image/QR
inference 12.6 s, one footer check; latest server/network 29.3 s. API pipeline 41.7 s;
translation 1.2 s and 3 requests, semantic 27.9 s and 3 calls, 7,235 tokens, one page,
11 facts needing review. Preparation reused an initialized model, so this is not a
cold-download benchmark. Detection/recognition are components of inference. The UI total
excludes editing and earlier failed requests. The preceding raw attempt took 45.7
seconds (12.6 seconds OCR, 33.1 seconds server/network) and failed its targeted audit. A
user's complete session including that failed request and correction therefore takes
longer than the successful-retry total.

The first corrected request on the final release also failed safely with inconsistent
provider coverage: its UI total was 38.7 seconds, including the same 12.6 seconds OCR,
so the failed server request was approximately 26.1 seconds. An unchanged corrected-text
retry succeeded. The raw attempt, failed corrected request, and successful retry
together used approximately 101.1 seconds of measured OCR/request work, excluding
editing, idle/deployment waits, and preceding experiments. The reported 41.9 seconds is
not the full session.

Independent bilingual comparison retained all 11 meaningful corrected source-line
meanings in both English and visual output. All 22 visible visual quotations (15
distinct) were nonempty and matched the corrected source, and neither English nor visual
body contained Hangul with source evidence hidden. Fidelity linked 14/14 identified
critical facts; that is a structural count. The 11 meaningful corrected source lines
were compared with simplified English and deterministic visual cards: recognized courses
**and research supervision**, course confirmation, maximum KRW 300,000/person, two
installments with the second only after a final report, all four mandatory documents/S
Plus, September 7–October 5, 2026 (Mondays), same-research support/participation
restriction, announcement/apply labels, exact contacts. `지원금` is support funds;
scholarship status is not added. The original image retained a local browser `blob:`
URL. Source evidence is available for review.

Final UI evidence artifacts are `final-b23-photo-ui.txt`,
`final-b23-photo-visual-ui.txt`, and `final-b23-photo-visual-evidence-ui.txt`.
Screenshots `final-hosted-photo.png` and `final-hosted-visual-cards.png` show the actual
hosted result/timing and required-document cards. Remaining photo presentation caveats
include repeated facts and redundant consent-form wording in an action item. Photo
extraction/audit substage and input/output token breakdowns were not separately captured
from the UI; the text profile above records these backend substages.

### Site usability and remaining evidence limits

Root, /api/health, /api/demos, /api/image-demos, current JS/CSS, OCR worker, WASM
runtime, QR module, and both legacy entrypoint aliases returned HTTP 200; the live
health response confirmed Version 2, gpt-4o-mini, MyMemory, and public mode. Results are
saved in final-b23-health.json. Public global notice browsing remains protected with
HTTP 403. The old entrypoint names are cache-compatibility aliases, not proof of a
separate Version 1 runtime check. Version 1 and `main` were preserved by branch
isolation.

Measurement JSON, corrected photo text, UI snapshots, and screenshots are retained
locally in `C:\Users\Lam\AppData\Local\Temp\univis-verification`. They contain public
notice text, not credentials. The primary and KCCI photos need fresh end-to-end checks
when available. Synthetic six-test score pairing is verified by regression tests;
original hiring thresholds remain unverified. Remaining limits are seal noise, provider
audit failures, temporary translation quality/quota, device/download variability,
ambiguous dense layouts, repeated facts/awkward title wording, and the unmet latency
target. Structural fidelity percentages cannot prove universal completeness or
translation accuracy.

Final evidence artifact SHA-256 values:

| Artifact | SHA-256 |
|---|---|
| `final-b23-hosted-corrected.json` | `11B5F99A45A1FD7F4191587EB656F7D65C4D82772C9F0783963F3321F925CE6A` |
| `final-b23-photo-ui.txt` | `46B855AFBECDAD290E78D3BAA10487771B1BCE43B073D2D1F5F70BA34E3F5B2F` |

## Historical local evidence used for the Sogang review

The source was `backend/tests/fixtures/sogang_research_corrected.txt`: 21 substantive
lines, excluding the `[Page 1]` marker. The latest reviewed output was
`result.simplified_text` and its structured fields in the local verification artifact
`final-wording-replay.json`, created at 23:59:18 on September 30, 2026 (Asia/Seoul). The
replay applies `normalize_notice` and `simplified_text` to
`final-audited-local-corrected.json`, measured at 23:44:38 that day. It does not rerun
OCR, translation, semantic extraction, or the audit. Its inherited request and
acquisition timings describe the measured source response, not the replay or a fresh
request against the final code.

The following table records this latest local comparison and its caveats. “Local
observed” means the indicated wording appeared in this artifact; it is not a
certification of arbitrary translation accuracy or of the photo flow. A source line
being cited does not establish that its complete meaning survived translation. Any
replacement artifact needs a fresh review.

| Source line | Korean source and required meaning | Latest local digest evidence or defect | Review status |
|---|---|---|---|
| 1 | `2026학년도 2학기 창의융합 자유연구 참가자 모집`: recruitment for the second-semester 2026 creative convergence research program | Year, semester, and recruitment purpose appeared. “Creative Convergence Free Study” remains awkward title wording for `자유연구`; it makes no explicit fee claim. | Local observed; wording caveat |
| 2 | `신청 기간: 2026.08.24(월) ~ 2026.09.20(일)`: August 24, 2026 (Monday), through September 20, 2026 (Sunday) | Both exact dates appeared as separate start/end deadlines and together in application details. No hour was added. The digest omits the printed weekday names; they remain in the cited source and preliminary translation. | Exact dates matched; weekday-display caveat |
| 3 | `신청 방법: 지원서, 연구계획서, 개인정보 수집 및 이용 동의서를 비교과통합관리시스템(S Plus)로 제출`: submit all three documents through S Plus | Application form, research plan, and personal information collection/use consent form are submitted through S Plus. “Required items:” is used for the documents. | Local observed |
| 4 | `모집 대상: 2026학년도 2학기 학부 재학생`: undergraduates enrolled for semester 2 of 2026 | An eligibility detail explicitly retained “undergraduate students enrolled in the second semester of the 2026 academic year.” | Local observed |
| 5 | `휴학생도 참여는 가능하나 연구비 및 활동비 지원 대상에서는 제외`: leave-of-absence students may participate but receive neither research nor activity funding | “Students on leave can also participate but are not eligible for research and activity expenses.” The exact leave-of-absence clause is cited. | Local observed |
| 6 | `2~5명의 학부생으로 구성된 팀 단위`: a team consists of 2–5 undergraduates | “Teams consisting of 2 to 5 undergraduate students are required.” | Local observed |
| 7 | `교내 타 프로그램에서 동일하거나 유사한 연구 주제로 지원을 받는 학생 및 팀은 참여 제한`: participation restriction for students and teams receiving support from other on-campus programs for the same or a similar research topic | “Students and teams receiving support from other on-campus programs for the same or similar research topics are restricted from participation.” All four qualifications are retained. | Local observed |
| 8 | `프로그램 내 중복 참여 불허`: duplicate participation within this program is prohibited | “Duplicate participation in the program is not allowed.” | Local observed |
| 9 | `연구 주제 1: 융합교육원 제시 주제(지정 주제)`: the first topic category consists of designated topics proposed by the Convergence Education Center | “Research Topic 1: Designated theme as presented by the Convergence Education Center.” | Local observed |
| 10 | `지정 주제 1: 스마트 글라스 등 AI Wearable Device의 AIX 발굴과 MVP(Minimum Value Prototyping)`: AI wearable devices such as smart glasses, AIX discovery, and MVP with the printed expansion | AIX, AI wearable devices, smart glasses, MVP, and the exact words “Minimum Value Prototyping” appeared. | Local observed |
| 11 | `지정 주제 2: "AI is Everywhere"의 모토에 맞는 AI 기능 개발`: develop AI features consistent with the printed motto | Development of AI functions in line with “AI is Everywhere” appeared. | Local observed |
| 12 | `지정 주제 3: AI 원천 기술 연구 개발`: research and development of core/fundamental AI technologies | “Research and development of core AI technologies.” | Local observed |
| 13 | `지정 주제 4: Robot 관련 연구 개발`: robot-related research and development | “Research and development related to robots.” | Local observed |
| 14 | `세부 주제는 공고 확인 필수`: checking the announcement for detailed topics is mandatory | “Detailed themes must be checked in the announcement,” citing this exact source line. | Local observed |
| 15 | `연구 주제 2: 학생 자율 선정 주제`: the second category permits student-selected topics | “Research Topic 2: Self-selected topics by students.” | Local observed |
| 16 | `연구비: 1인당 최대 20만원`: research funding is capped at KRW 200,000 per person | “Research funding of up to 200,000 KRW per person.” | Local observed |
| 17 | `연구비는 기자재 구입 및 대여, 재료비, 도서 구입 및 인쇄비로 사용 가능`: eligible research spending includes equipment purchase and rental, material costs, book purchases, and printing | “Research expenses may cover equipment purchase or rental, material costs, book purchases, and printing costs.” The purchase/rental verbs apply to equipment. | Local observed |
| 18 | `연구비는 융합교육원에 방문하여 카드결제`: visit the Convergence Education Center to make card payments for research expenses | “Research expenses must be paid by card at the Convergence Education Center, requiring an in-person visit.” The rule covers expenses, including rentals. | Local observed |
| 19 | `활동비: 1인당 20만원`: activity allowance is KRW 200,000 per person | “Activity allowance of 200,000 KRW per person,” without adding “up to.” | Local observed |
| 20 | `연구비로 지원되는 항목 외의 비용은 장학금 형태로 지급`: costs outside the research-funded categories are paid as a scholarship | “Costs not covered by research funding will be provided in the form of scholarships.” | Local observed |
| 21 | `문의: 융합교육혁신팀 (02-710-2500 \| convedu@sogang.ac.kr)`: contact team, exact phone, and exact email | Convergence Education Innovation Team, `02-710-2500`, and `convedu@sogang.ac.kr` appeared with matching cited source text. | Local observed |

The latest reviewed simplified digest contained no Hangul. All 31 displayed
evidence-bearing items and 31 source facts had nonempty evidence matching the source
under `evidence_matches_page`. The inherited fidelity report recorded 27 identified
critical facts represented and no unmapped source lines. These checks establish evidence
presence and the reported structural coverage; the manual comparison above separately
assesses meaning for this fixture. They do not prove universal completeness.

Earlier candidate reviews found omitted restriction qualifications, unsupported Korean
citations, an invented disqualification consequence, misleading funding wording, and a
missing explicit enrollment qualification. Those defects are absent from this replay and
are covered by focused guards/tests. The latest digest still repeats the two funding
amounts, places designated topic 1 after the other topics, and uses the awkward title
“Free Study.” The preliminary MyMemory translation still contains “Leaving students”; it
is a reading aid, and the reviewed simplified/structured output correctly uses “Students
on leave.”

## Actual-photo and synthetic-evidence boundaries

The raw browser-OCR fixture
`backend/tests/fixtures/sogang_research_2026_browser_ocr.json` contains positioned text
recovered in an earlier browser run. It includes seal fragments and the damaged contact
string `02.710.25n0`. Exercising that JSON can verify API ingestion, layout ordering,
early correction requests, and semantic handling. It cannot measure a new
image-recognition pass, verify text that OCR missed, or establish the correct unreadable
digits from the photo. The corrected text fixture is supplied transcription evidence,
not an image-derived certainty claim.

No copy of the primary Sogang creative-convergence source photo or the earlier Korea
Chamber of Commerce hiring photo was available in the repository fixtures during this
review. A different actual Sogang undergraduate research-support poster was available
and exercised separately, as recorded below. Any generated image-demo exercise must
likewise be reported separately from these real-poster regressions. The two missing
regression photos require fresh end-to-end checks when they become available.

`backend/tests/test_language_scores.py` has a synthetic positioned six-column oracle
that asserts these test/threshold pairs: TOEIC 800, TEPS 309, FLEX 2B, TOEFL iBT 91,
TOEIC Speaking 150, and OPIc IM3, each with the source “or higher” qualifier. This is
evidence that the implementation retains the specified pairings and their evidence, not
independent verification of the original hiring poster's printed values. Additional
geometry tests cover row tables, missing scores, ambiguous headers, reused score values,
lost/garbled test subtitles, conflicting duplicate TOEIC labels, and one-digit decimal
IELTS thresholds. An ambiguous name/value relation requires correction rather than
guessing a score or silently retaining a partial table.

## Historical single-run measurements

These figures are earlier single runs, not final benchmarks or repeated-trial latency
estimates. They do not certify the latest output, measure the missing real-photo flow,
or establish attainment of the 10–15 second target.

| Earlier run | Request wall time | Aggregate semantic tokens | Scope |
|---|---:|---:|---|
| Hosted corrected-text baseline | 42.269 s | 10,776 | Earlier hosted API run; browser OCR not included |
| Preliminary local corrected-text run | 36.736 s | 7,918 | `final-local-corrected.json`, before final restriction/card wording guards; browser OCR not included |

The preliminary local run recorded 4 translation requests and 3 semantic requests. Its
stage timings were translation 2.314 s, extraction 22.208 s, English-field repair 0 s,
and coverage 11.034 s. Its server-reported total was 36.191 s; the external request wall
time was 36.736 s. Semantic time includes extraction, any English-field repair, and
coverage; those substage values must not be added again to the semantic total. Comparing
one hosted run with one local run cannot isolate the effect of the code changes from
provider, network, or deployment variability.

## Latest measured local corrected-text run and wording replay

`final-audited-local-corrected.json` returned HTTP 200 at 23:44:38 on September 30, 2026
(Asia/Seoul). Request wall time was 49.161 s; the API's total was 48.921 s. Recorded
stages were translation 2.137 s, extraction 31.775 s, English-field repair 0 s, and
completeness audit 14.701 s. It used 4 translation requests and 3 semantic requests,
with 6,460 input tokens, 2,521 output tokens, and 8,981 total semantic tokens.

The final wording guards were then applied without provider calls to create
`final-wording-replay.json`. This replay was reviewed above, but it has no new request
latency or token measurement. Comparing the measured local request with the earlier
hosted baseline shows fewer tokens in that single comparison (8,981 versus 10,776),
while wall time increased (49.161 versus 42.269 s). There is no demonstrated latency
improvement or attainment of the 10–15 second target. Both requests exclude browser OCR
and are single runs on different deployment contexts.

## Historical local different-poster browser exercise

An actual Sogang undergraduate research-support poster was exercised through browser OCR
and the local API. This is **not** the primary “2026학년도 2학기 창의융합 자유연구 참가자 모집” poster.

Browser OCR took 27.249 s and recovered 477 characters, including the phone and email.
The earlier 408-character reading lacked that footer. Rounded browser substages were
preparation 5.9 s, detection 10.6 s, recognition 8.3 s, and image inference 21.4 s.
Detection and recognition are components of inference and must not be added to it again.

The raw recovered text failed with HTTP 502 because seal noise remained uninterpretable.
A manual recovered-text correction and retry succeeded without rerunning OCR. The
reported combined OCR plus latest server-request time was 65.603 s, with the latest
server request approximately 38.4 s. It used 3 semantic requests, 7,478 semantic tokens,
and 3 translation requests. Editing time is excluded from the reported total. The
original photo remained available locally in the browser for evidence review; the API
received text and positions.

These observations verify that this different-photo flow can recover footer text and
complete a corrected retry. They do not establish the primary poster's OCR accuracy, the
KCCI table values, unchanged hosted deployment behavior, or universal completeness. The
raw seal-noise failure also remains a concrete limitation rather than a successful
uncorrected-photo analysis.
