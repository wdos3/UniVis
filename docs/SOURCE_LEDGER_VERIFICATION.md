# Source ledger verification — October 4, 2026

This report distinguishes physical-source retention, displayed-ID coverage,
literal/condition checks, semantic output and actual photo runs. None of the
counts certifies complete comprehension, OCR recall or linguistic accuracy.

## Implementation

The browser captures source observations before the older flattening/span limits.
IDs, source Korean, normalized polygons/boxes, page/order, alternate readings,
blocks/sections/table cells, English/status/provider, output references and display
destinations remain in an independent ledger. Candidate/vision transcription is
separate from original OCR. Translation chunks reconcile by explicit ID. Failed
chunks retain a source-linked English/crop fallback rather than deleting units.

The main photo UI displays translated blocks before semantic processing. Structured
semantic output is checked against source references and protected values, with
bounded targeted repair and source-backed replacements. Source crops remain local
except for optional bounded recovery input; API keys and original image files are
never exposed to the client. Recovery crop bytes are absent from stored results.
The existing Vite static frontend/Python 3.12 API packaging is preserved.

## Development evidence

- Entry branch: `prototype/paddleocr-gpt41mini`; working tree clean before the plan update.
- Entry HEAD: `b7a9470`; prior live code: `d1f6ff2`.
- Direct entry checks: deployed root HTTP 200; `/api/health` configured OpenAI,
  MyMemory and `gpt-4o-mini`, public mode, browser OCR path.
- Initial in-progress backend checks: 908 passed, one exact-response expectation
  needed the additive `source_unit_ids` field. After integration: 959 passed.
- Frontend integration checks reported 151 passing tests, ESLint and type/build
  checks. Final release checks are recorded below after all changes.

The first **actual local Sogang photo** run captured 63 physical units. It took
43.156 s OCR, 8.206 s translation, 27.365 s semantic, approximately 79.7 s in the
browser. Two semantic requests consumed 87,355 input / 1,657 output / 89,012 total
tokens. Only 11 source IDs had accepted semantic output; fallback views retained
the remaining inventory. Its semantic organization and title were inadequate.
This is failed-development evidence, not a passing release test.

That run exposed a detached restriction continuation, score-table/prose confusion,
crop selection favoring seal noise, expensive high-detail crop input, and overly
strict source-ID partitioning/validation. Regression checks now protect these
cases, including six KCCI score pairs and the separate essay-question count.

## Release checks and measured runs

Automated checks (repository root unless noted):

- `backend/.venv/Scripts/python.exe -m pytest backend/tests -q`: 1,068 tests,
  including source retention, chunk reconciliation, omission/repair, source-ID
  shifts, incorrect thresholds, enrollment/funding conditions, crop isolation,
  uncertain-source display, and both real-poster geometry fixtures.
- `ruff check backend`; `ruff format --check` on the four ledger modules and four
  ledger test modules: passed. `git diff --check`: passed.
- In `frontend`, `npm.cmd test -- --reporter=dot`: 159 tests in 17 files passed.
  `npm.cmd run lint` and `npm.cmd run build`: passed. Build includes TypeScript
  and Version 1 asset preservation. Existing OpenCV browser-module and large
  chunk warnings remain.

These are behavior/fixture checks, not evidence of universal OCR recall or
linguistic correctness. Complete corrected Sogang text is tested separately from
raw OCR; six KCCI score pairs and its essay-stage count are checked explicitly.

Measured development runs, all using configured `gpt-4o-mini`:

| Input/run | OCR | MT | Semantic | Calls | Input/output/total semantic tokens | Measured elapsed |
| --- | ---: | ---: | ---: | ---: | --- | ---: |
| Sogang actual local photo, before final per-unit guards | 42.359 s | 7.4 s | 27.0 s | 2 | total 32,291 | browser 78.4 s |
| Sogang recorded OCR, reordered inventory | excluded | 11.791 s | 23.632 s | 2 | 11,292 / 1,434 / 12,726 | API stages 36.051 s |
| KCCI recorded OCR, reordered inventory | excluded | 15.884 s | 25.712 s | 1 | 16,278 / 1,442 / 17,720 | API stages 42.318 s |
| Sogang actual image-translation mode | 47.3 s | 7.3 s request wait | none | 0 | none | browser 56.4 s, drawing 1.8 s |

The recorded-OCR rows reuse earlier actual photo observations; they are **not**
fresh photo-to-output runs. All shown successful provider usage is complete.
A separate 45-second provider timeout returned source fallback with unavailable
semantic usage; zero tokens were not inferred for that failed request.

The image-translation run painted 26 of 63 physical units and displayed all 63
source IDs in English/crop sidecars. The rendered translated image and original
toggle were checked. The browser's PNG download completion was not confirmed.
Original Korean can remain in the exported image where safe fitting fails; the
sidecar is necessary for those units. This is not full Google/Papago replacement
quality.

The final reordered Sogang replay retained dates/documents, enrollment, leave and
funding exclusion, 2–5 members, duplicate-support restrictions, four designated
research topics plus student-selected topics, both funding amounts and spending/
card/scholarship rules, and the observed phone/email. Some sentence fragments are
awkward and seal noise can still receive poor English. The fresh preceding photo
run failed topic/funding alignment and motivated the final per-unit guards; it is
not counted as a passing fidelity run. The KCCI replay retains the six thresholds
and binds the approximately-three-question essay note to its spatial stage grid.
Its raw OCR says economic/social topics; a different corrected fixture says
economic/current-affairs topics. The system does not overwrite that conflict from
a remembered transcription.

Initial live release: `802826725f2c0457c684e741e2df4b0298e1d227`, linked project
`univis-v2-prototype`, deployment `dpl_7ykYKU79PnbrRNS2GoHAThc3CPQw` READY.
The root and health endpoint returned 200; health confirms `source-ledger-v1`,
OpenAI configured, `gpt-4o-mini`, MyMemory and public mode. JavaScript/CSS,
worker, bundled ORT WASM, QR chunk, both OCR model archives and public ORT WASM
returned 200 with appropriate content types. Python 3.12 and existing static/
file-based API packaging were confirmed in the Vercel build.

A live KCCI geometry-fixture round trip returned HTTP 200 from both new routes,
retained all 20 source IDs with English fields, and used mock semantic mode
(zero OpenAI calls). This verifies API packaging/retention, not model accuracy.

The initial fresh hosted Sogang photo returned English and all requested topic/
funding values in 69.4 s: OCR 47.5 s, MT 5.2 s / 34 requests, semantic 14.0 s /
two calls / 26,170 total tokens. Seal noise generated an unsupported September
date, so this is **failed fidelity evidence**. Four new regressions now require
date evidence even when a region has no recognized date, and keep opaque
romanized/crop fallbacks in the source view rather than dumping them into the
instruction digest.

The corrective deployment `cdd2fcf4f449f99214eb94c8d35e88d88b428830`
(`dpl_DRWa2MtYnzjayCf26UzeykMrQF7d`) was READY on the existing alias. Its
health endpoint returned HTTP 200 with the same configured model and ledger path.
Five actual supplied photos were then exercised on that hosted code:

| Photo | Source / translated / fallback / displayed IDs | OCR / MT / semantic | Requests | Input / output / total tokens | Browser elapsed |
| --- | --- | --- | ---: | --- | ---: |
| 02, creative research | 63 / 49 / 14 / 63 | 40.1 / 5.2 / 27.0 s | 2 | 29,079 / 1,299 / 30,378 | 75.2 s |
| 06, KCCI hiring | 99 / 86 / 13 / 99 | 48.0 / 7.5 / 24.7 s | 2 | 31,606 / 1,805 / 33,411 | 83.6 s |
| 03, Seoul promotion | 40 / 34 / 6 / 40 | 28.7 / 9.7 / 15.1 s | 1 | 18,649 / 669 / 19,318 | 55.4 s |
| 01, undergraduate research support | 46 / 25 / 21 / 46 | 25.4 / 5.5 / 13.3 s | 2 | 25,602 / 886 / 26,488 | 46.3 s |
| 04, campus video contest | 76 / 47 / 29 / 76 | 32.2 / 6.5 / 25.4 s | 2 | 27,296 / 1,688 / 28,984 | 66.7 s |

These are measured photo flows, not blanket fidelity passes. The unsupported
September date disappeared from photo 02; the application dates/documents,
enrollment, leave exclusion, 2–5 members, duplicate restrictions, all topic options,
both KRW 200,000 funding categories, spending/card/scholarship rules and contact
values were visible. Its wrapped leave sentence remained awkward and partial
stamp readings still leaked into the digest. Photo 06 retained the six thresholds
(800, 309, 2B, 91, 150 and IM3), essay question count with the essay stage,
application restrictions, documents and employment conditions; repeated fragments
and decorative text remained. Photo 03 retained its dates, budget-exhaustion
condition, 5% cashback, KRW 50,000 monthly cap and KRW 5,000 lottery reward.
Photo 01 retained its research supervision, documents, dates, KRW 300,000 amount,
two installments and final-report requirement for the second installment, but
detached a restriction continuation. Photo 04 retained the prize amounts and
format/attendance dates but lost their award-category associations in the digest;
its enrollment/leave/team eligibility remained only as romanization/crops. Clipped
neighboring poster text was mixed into its additional details. These failures
motivated the next bounded correction, rather than being counted as successes.

Additional hosted image-translation testing on photo 03 placed 27/40 units,
retained the source view, and took 39.2 s OCR + 7.7 s translation + 1.8 s drawing
= 48.7 s overall, with 33 known MT requests and no semantic call. The rendered
image and original toggle were visually checked. PNG download completion again
could not be confirmed in the in-app browser. MyMemory omitted the survey lottery
condition, prompting a deterministic check that prevents that partial reading
from being painted as a guaranteed reward.

The follow-up correction keeps partial/romanized readings in the crop view even
when preceded by an English fragment, attaches wide paragraph continuations at
their left origin, recognizes Korean-labeled numeric prize grids, protects
inclusive team limits and lottery conditions, and translates only whole explicit
enrollment/team clauses locally. Institution names in the local enrollment
fallback are labeled as transliterations rather than asserted official English
names. An observed 15-unit prize/adjacent-paragraph geometry fixture protects award/amount columns and table boundaries;
its confidence is unavailable and is not invented. Final hosted checks for this
correction are recorded below after deployment.

On `af6034e8047143483cbcecb2031a51b75713aad8`, the repeated actual photo 04
showed enrollment, leave permission and teams of up to three, and restored both
award columns. It retained 76 source/display IDs, with 50 translated and 26
fallback units; OCR 38.8 s, MT 6.3 s and semantic 15.0 s, one request with
22,855 input / 1,071 output / 23,926 total tokens. The table incorrectly absorbed
the adjacent ceremony paragraphs. The expanded observed fixture reproduced this
failure before the boundary fix and passed afterward. The fix rejects a paragraph
spanning multiple column anchors and trims a trailing label with no values;
those units remain in ordinary source blocks.

The photo 01 repeat on `af6034e` still detached its restriction (46 source and
display IDs, 25 translated, 22 fallback; these dimensions can overlap). OCR
40.4 s, MT 5.0 s, semantic 19.3 s, two requests, 26,130 input / 1,218 output /
27,348 total tokens. The earlier wide-column fix alone did not solve this case.
Retained crop geometry exposed an inflated axis-aligned height on tilted prose
and a side label between its two lines. A three-unit observed fixture now checks
the complete connected restriction with that label kept separate. Polygon-side
text-height estimation and short-lived paragraphs tracked at horizontal anchors
avoid the split without joining across a same-anchor section heading. Synthetic
tilt and section-boundary tests protect those additional mechanics; the observed
fixture does not invent confidence or polygons absent from the rendered DOM.

The photo 02 repeat on `2f74513` retained the required substantive details and
63 displayed source IDs (48 translated / 15 fallback), at 39.6 s OCR, 4.4 s MT,
16.6 s semantic, 63.3 s measured browser elapsed, two requests and 25,059 input /
1,261 output / 26,320 total tokens. It still stamp dates unsupported by accepted transcription as `Until
9/16` and `from 9/10`, rather than written month names. This is another failed
fidelity run. Date recognition now covers standalone date prepositions with
numeric month/day formats. A four-unit regression prevents a readable neighboring
office/logo block from hiding those unsupported dates.

Detailed OCR profiling of the earlier actual photo 04 run showed model reuse,
14.5 s detection, 16.1 s recognition, two extra small-text checks and 1.7 s QR
work in parallel, for 32.2 s acquisition. This confirms that substantial OCR
latency persists after initialization; it is not solely a cold-download delay.

The next actual photo 02 run on `3f5e834` removed those unsupported month/day
dates, but reversed a clear support restriction: it said participating students
could not receive support instead of saying support recipients could not
participate. It retained 63 source/display IDs (46 translated / 17 fallback),
with 40.5 s OCR, 5.7 s MT, 15.9 s semantic and 65.4 s browser elapsed. Two
requests used 28,692 input / 1,375 output / 30,067 total tokens. This is another
failed meaning check despite full displayed-ID coverage. A whole-clause local
translation and a direction check now protect this general restriction pattern;
tests cover both a local replacement and a targeted semantic repair of a longer
clause. Exceptions appended to the source prevent the local template from
matching, so it cannot silently erase extra conditions.

On `751f5147100d55f50a4892a141444c3c7bc8f214`, actual photo 02 showed the
correct restriction direction and no fabricated month/day stamp dates. It took
42.8 s OCR, 5.6 s MT, 18.9 s semantic, 69.7 s browser elapsed and two semantic
requests (29,630 input / 1,380 output / 31,010 total tokens). All 63 source IDs
were displayed; 43 translated and 23 fallback IDs overlap where source uncertainty
remains. However, the complete leave/funding clause stayed in romanization/crops
after both readings failed, and was absent from the digest. A full-match local
translation now handles that complete clause across connected units. The same
shared English and source-ID set remain in the source view while uncertainty
crops stay available. A regression simulates two incorrect provider readings
and checks both leave participation and both funding exclusions in the digest.

The next photo 02 run on `698c4b3` displayed the leave clause and correct support
restriction, all topics, application/document details, funding/payment rules and
contacts. It retained 63 source/display IDs (51 translated / 12 fallback), with
37.1 s OCR, 15.9 s MT, 17.1 s semantic and two calls (28,481 input / 1,388 output /
29,869 total tokens). The accepted leave translation was grammatically incomplete
across its two units. Whole-clause source translations now replace that wording
even when the provider output passes protected-value checks, with one shared
English text and the complete source-ID set. A test protects this accepted-output
case independently of the failed-provider fallback case. Seal noise still produces
unhelpful English in additional details; those IDs remain crop-linked and are not
evidence of verified meaning.

Actual photo 02 on `fbf1de4` showed the complete, consistent leave/funding clause
and correct participation restriction, but stamp dates unsupported by accepted transcription reappeared as
English vision "transcriptions." This bypassed the ordinary translation-date
guard by changing the effective source. The run retained 63 source/display IDs
(49 translated / 14 fallback), with 37.5 s OCR, 8.4 s MT, 25.3 s semantic, 73.9 s browser elapsed and
two calls (30,354 input / 1,484 output / 31,838 total tokens). It is a failed
fidelity run. Vision recovery now rejects an English-only replacement for Korean
source; the prompt explicitly requires original-language transcription. Tests
protect rejection of this date laundering and preserve legitimate attached-crop
Korean recovery. This contract check cannot prove every native-language vision
reading correct.

## Remaining limits

Unreadable content cannot be invented. Source crops, partial English and literal
values/romanization preserve difficult regions but cannot guarantee their meaning.
MyMemory can mistranslate administrative terms and fragmentary text. Geometry and
candidate checks remain heuristics. The original and recovery evidence remain
inspectable without making Korean correction a prerequisite for receiving output.
Required keys prevent structural omission but cannot prove arbitrary semantic
equivalence. Connected-condition grammar, seal/noise classification, unsupported
paraphrases, and repeated fragments still need broader bilingual evaluation.
All five supplied photos were exercised, but future images and arbitrary semantic
accuracy are not certified by these results. The broader runs above exposed real
layout and wording failures despite full displayed-ID retention.

The 10–15 second target has not been established. Cold model downloads and device
OCR can exceed it before API processing starts. Crop vision can add significant
tokens, particularly on `gpt-4o-mini`; actual returned usage must be reported,
including an incomplete-usage flag after failed attempts. Source/display coverage
is independent of semantic acceptance and does not prove that nothing was omitted.

Text/PDF/local Python/older API clients retain their legacy audit behavior. The
new nonblocking ledger is the hosted browser photo path. Extremely large notices,
unsupported image decoders and provider/network failures can leave the English
source view available while semantic instructions remain unfinished.
