# Source ledger verification — October 3, 2026

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

- `backend/.venv/Scripts/python.exe -m pytest backend/tests -q`: 1,044 tests,
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
instruction digest. Final live checks follow the corrective deployment.

## Remaining limits

Unreadable content cannot be invented. Source crops, partial English and literal
values/romanization preserve difficult regions but cannot guarantee their meaning.
MyMemory can mistranslate administrative terms and fragmentary text. Geometry and
candidate checks remain heuristics. The original and recovery evidence remain
inspectable without making Korean correction a prerequisite for receiving output.
Required keys prevent structural omission but cannot prove arbitrary semantic
equivalence. Connected-condition grammar, seal/noise classification, unsupported
paraphrases, and repeated fragments still need broader bilingual evaluation.
Only photos 02 and 06 were exercised here; the other supplied photos and future
images are not certified by these results.

The 10–15 second target has not been established. Cold model downloads and device
OCR can exceed it before API processing starts. Crop vision can add significant
tokens, particularly on `gpt-4o-mini`; actual returned usage must be reported,
including an incomplete-usage flag after failed attempts. Source/display coverage
is independent of semantic acceptance and does not prove that nothing was omitted.

Text/PDF/local Python/older API clients retain their legacy audit behavior. The
new nonblocking ledger is the hosted browser photo path. Extremely large notices,
unsupported image decoders and provider/network failures can leave the English
source view available while semantic instructions remain unfinished.
