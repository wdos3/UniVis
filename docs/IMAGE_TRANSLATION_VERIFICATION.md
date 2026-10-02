# Image translation prototype verification

This is a separate experiment: browser PaddleOCR → positioned Korean text →
machine translation → English painted into the original photo → downloadable
PNG. It bypasses OpenAI extraction, English repair, completeness auditing and
analysis persistence. The existing notice workspace and Version 1 are preserved.

## Provider choice

The existing MyMemory adapter needs no new credentials. Standalone literal
thresholds such as `800 이상` are translated locally with inclusive/exclusive
comparisons and the exact original value; this avoids observed provider-added
currency symbols. Arbitrary prose still uses the configured translation provider.
Latin-only text, numbers and decoded QR URLs stay untouched. Region translations
are deduplicated and outbound connections are bounded to four.

[Papago Image Translation](https://guide.ncloud-docs.com/docs/en/papago-image-translation-use)
offers actual translated-image synthesis, but requires NAVER Cloud credentials
and usage billing. [Google Cloud Translation setup](https://docs.cloud.google.com/translate/docs/setup)
requires billing and an authenticated project despite its monthly free allowance.
Neither account nor billing was created. No undocumented consumer endpoints,
paid OCR container or new dependencies were introduced.

## Automated checks

Focused tests cover comparable versus partial crop readings, continuation
grouping without merging parallel table cells, full-text wrapping, literal URL
preservation, readable-fit failure, safe neighboring paint bounds, retained-source
protection, API ID/source association, partial provider failure, bounded request
input/concurrency, cancellation, replacement-photo stale results, local URL
cleanup and same-selection OCR reuse. Tests explicitly forbid semantic processing
and persistence in the new API route.

Final code checks on October 3, 2026: **909 backend tests** and **127 frontend
tests** passed. Ruff, ESLint, TypeScript and the Vite production build passed;
`git diff --check` passed. Dependency deprecation warnings and existing large
OCR/OpenCV bundle warnings remain. These automated checks are separate from
the actual browser/photo verification below.

## Real-photo checks

The supplied original Sogang creative-research (`_02`) and KCCI hiring (`_06`)
JPEGs were selected through the actual browser file chooser. No corrected Korean
transcription or fixture-based translation was injected. The normal local Vite
frontend and FastAPI server processed browser OCR, the live free translator,
canvas drawing and PNG export. Timings come from the visible stage report; OCR
reuse is reported separately and does not represent a fresh-photo runtime.

Initial placement rejected every axis-aligned box intersection. On Sogang that
left 27 otherwise translated regions original. Safe partitioning of slightly
overlapping adjacent lines improved placement while protecting retained originals.
A broader two-column paragraph grouping heuristic was removed after review
showed that indistinguishable table geometry could merge independent rows.

Complete matching crop readings can differ in leading bullets or crop padding;
those now deduplicate under strong overlap/center checks. Competing printed
numeric/date/time/grade tokens prevent geometry-only deduplication, even if one
reading has higher confidence.

Local browser measurements before the last literal-conflict safeguard:

| Original photo | OCR | Translation | Drawing | Total | English placements | Latin/numeric originals | Other originals |
|---|---:|---:|---:|---:|---:|---:|---:|
| Sogang creative research `_02`, fresh selection | 57.1 s | 10.0 s | 1.1 s | 68.2 s | 31 / 61 | 12 | 18 |
| KCCI hiring `_06`, initial run before final dedup/grouping | 61.4 s | 17.0 s | 1.1 s | 79.5 s | 54 / 102 | 21 | 27 |
| Seoul promotion `_03`, before complete-reading dedup | 60.6 s | 7.6 s | 1.0 s | 69.2 s | 30 / 40 | 3 | 7 |

Sogang's same-photo OCR-reuse run took 13.2 s (12.1 s translation + 1.1 s
drawing), with 49 known outbound translation requests. KCCI's OCR-reuse run
after local threshold translation took 15.2 s (14.0 s translation + 1.2 s
drawing), with 72 known outbound requests. These are repeat runs, not new-photo
timings. PNGs exported through the actual browser download control were confirmed
to retain 2296 × 4080 dimensions and were opened for visual inspection.

The KCCI export retained the six test headers in their original columns and
placed the corresponding thresholds: TOEIC 800, TEPS 309, FLEX 2B, TOEFL iBT 91,
TOEIC Speaking 150 and OPIc IM3, each inclusive. MyMemory had originally returned
`More than 800$`; the local standalone-comparison rule now produces `800 or more`
and preserves the other exact values. This table check does not validate the
English meaning of unrelated hiring requirements.

## Deployment checks

Code commit `d1f6ff2` was pushed only to `prototype/paddleocr-gpt41mini` and
deployed to the existing `univis-v2-prototype` project. Vercel deployment
`dpl_4JCCU4XU4KdSAuMsKHWJxjAWadFt` reached READY and was aliased to
`https://univis-v2-prototype.vercel.app/`. The deployment retained the static Vite
frontend and Python 3.12 API packaging.

Live HTTP checks confirmed: root HTML and the current entry bundle returned 200;
health returned 200 with public mode enabled and the existing `gpt-4o-mini`
semantic model; OCR worker, WASM, QR and preserved legacy entry assets returned
200 with their expected JavaScript/WASM/CSS content types. The protected notices
route still returned 403. The new endpoint returned exact local `800 or more`
and `IM3 or more` results with zero outbound translation requests, and rejected
an extra image field with 422. No credentials were returned or printed.

Both main original photographs completed the actual hosted file chooser →
browser OCR → text-only API → canvas → download flow on this deployment:

| Original photo | OCR | Translation | Drawing | Total | English placements | Latin/numeric originals | Other originals |
|---|---:|---:|---:|---:|---:|---:|---:|
| Sogang creative research `_02` | 35.2 s | 6.6 s | 1.0 s | 42.8 s | 31 / 62 | 12 | 19 |
| KCCI hiring `_06` | 54.5 s | 8.7 s | 1.1 s | 64.3 s | 60 / 98 | 21 | 17 |

These used fresh photo selections, without cached OCR results; the second
photo reused an initialized OCR engine. The Sogang source had 65 positioned
spans and made 50 known translator requests. KCCI had 114 spans and 67 known
translator requests. All six exact inclusive score thresholds were checked in
the hosted region list and exported picture. Its 17 retained Korean regions
comprised 14 overlap conflicts and three unreadable fits. Sogang's 19 were all
overlap conflicts. No provider failures occurred in these two runs. This does
not establish correctness of the translated prose.

Original/translated toggling, PNG download, region inspection, returning to the
existing notice workspace, and reentering the new mode were exercised in the
hosted UI. Exported sample images and browser screenshots are saved locally in
`C:\Users\Lam\Desktop\Coding\UniVis Image Translation Results`; source photos
and these generated images were not committed or uploaded to the API.

## Practical limits

Replacement counts cover selected OCR regions, including seal text, repeated
crop readings, Latin values and QR URL regions. They do not measure character
recall, completeness or English correctness. A detected/translated region may
remain Korean in the exported image when placement conflicts or the complete
English cannot fit readably. The complete source and translation remain available
in the expandable region list.

Actual photos expose wrong administrative vocabulary, fragment translations,
tiny-seal gibberish and OCR-confused characters. Flat color patches can leave
Korean glyph edges and cannot restore patterned artwork. Axis-aligned hulls can
overlap even when tilted text polygons do not. PaddleOCR.js returns polygons;
the existing OCR span contract currently retains their axis-aligned hulls.
Perspective-aware placement is future work, not a verified feature of this
prototype. The approximately 10–15-second fresh-photo target remains unmet.

Supported input is one JPG/PNG/WebP, under 15 MB and 25 megapixels, up to 200
regions and 20,000 recognized characters per translation request. Free-provider
quotas, network availability, browser capabilities and model downloads can still
prevent successful translation. There is no claim that every image translates
completely or that every machine-translated statement is correct.
