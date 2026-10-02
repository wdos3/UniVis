# Architecture

## Design goals

VisNotice separates factual interpretation from presentation. AI providers return typed data, never HTML. React owns the output structure, so Conditions B and C share facts but differ in presentation. Source evidence, page provenance, and internal fact IDs make some omissions and image-reading uncertainty inspectable; they do not prove that an English paraphrase is correct.

## Components

Recovered phone numbers containing unreadable characters and incomplete positioned
English-test tables are rejected before translation/semantic requests. Recovery
errors use HTTP 422 with `code`, `message`, and page/line/text/reason corrections.
The frontend quotes the affected text and can focus its page editor; correction
does not require another OCR pass. Confidence accompanies OCR positions but never
permits deleting source words or certifies a phone number.

The model's extraction schema omits application-owned image coordinates, page IDs,
language settings, and template overrides. The normal public `NoticeData` contract
is restored locally, and source pages are assigned only from matching evidence.
The separate completeness audit still sees every substantive recovered source
unit; repeated cited English is sent once through references to reduce tokens.
Before this audit, primary items and fact quotes absent from the source are
rejected. Valid quotes with unrelated fact IDs are linked to their exact source
evidence and marked for review. The audit must still account for every recovered
source unit; removing an unsupported claim does not license skipping source text.
The same audit checks displayed English claims, including summaries and review
notes. It can reject a model-invented consequence even when its quoted Korean
exists; affected source units then require complete grounded details.
Local wording correction uses evidence-backed glossary terms and explicitly printed
acronym expansions from each field's quotation; it does not replace
whole sentences with translations of a remembered poster. Missing clauses must pass
the independent semantic audit. Invalid audit assignments are removed before a
focused retry; grouped facts are retried together, unknown IDs require broader review,
and repeated invalid responses are never accepted. Strict APIs reject them; opt-in
photo mode withholds affected claims and returns English gaps. There are at most two
audit requests. Partial pruning uses each item's own provenance before coalescing.
Exact dates, amounts, contacts, literal English phrases, recognized source conditions,
and common spending clauses have additional deterministic checks. These checks have bounded
vocabularies and do not prove arbitrary semantic meaning or negation.

### FastAPI backend

`app/main.py` exposes text, image, PDF, browser-OCR text, demo, recovered-text correction, researcher-edit, and study-result endpoints. Pydantic models in `app/models.py` reject extra fields, invalid steps, duplicate fact IDs, and invalid research condition/confidence values.

Three provider boundaries keep acquisition, translation, and semantic interpretation separate:

- `PaddleOcrProvider` runs the lightweight PP-OCRv5 detector and Korean recognizer locally, then assembles ordered page text. `RemotePaddleOcrProvider` sends the same ordered image bytes to the dedicated authenticated OCR container when `PADDLEOCR_SERVICE_URL` is configured. Both providers share the same result contract and preserve page-level warnings.
- `TranslationProvider` performs translation without interpretation. MyMemory is the temporary no-key adapter and splits input below its byte limit, preserving blank paragraph/column boundaries and whole OCR lines where possible; `LibreTranslateProvider` supports a later self-hosted replacement.
- `SemanticProvider` converts Korean OCR plus its machine translation into a strict `NoticeData` response. The live OpenAI provider makes an initial structured-output request, then translates any Korean left in user-facing English fields in one or more batched follow-up calls. Mock providers keep the five synthetic demos local.
- The English completeness service compares distinct substantive recovered source lines with the actual cited English display fields and digest. It can append grounded details to `key_details` or `financial_support`, retry unresolved or malformed source/English-ID classifications once, or reject a result if substantive meaning cannot be accounted for. The resulting calls and tokens are included in semantic metrics. This is a safeguard, not a guarantee of semantic correctness or recovery of text OCR missed.

Image services preserve the uploaded original, apply EXIF orientation, create a mildly enhanced working copy, report heuristic quality issues, and detect QR codes without opening them. Images are not included in the OpenAI request. Overlapping heading and full-page OCR passes improve poster recovery while preserving uncertainty for review.

For hosted camera and image uploads, the frontend instead runs PaddleOCR.js
locally in the browser and posts per-page recognized text with bounded text
positions to `/api/analyze-client-ocr`. It also attempts to decode HTTP(S) QR
URLs locally without opening them; decoded URLs become source text and remain
subject to evidence review. The endpoint rejects image data and filenames,
validates page and text limits, and applies the public analysis rate limit.
Before translation, it reorders a clearly positioned two-column band
column-first, retaining every OCR line; sparse or ambiguous layouts remain in
their original order. It then passes the text through the same translation,
semantic, and completeness pipeline. It records page-level provenance and OCR
timing, but no image bytes are persisted by this path. Source photos remain in
browser memory for the current session.

PDF extraction uses PyMuPDF. Selectable text bypasses OCR; image-only PDFs render ordered pages and use local OCR. Password-protected, malformed, unreadable, and over-limit files return explicit errors.

### Fidelity and template services

Each critical source fact is assigned `F001`, `F002`, and so on. Grounded output elements reference one or more IDs. `calculate_fidelity` compares critical IDs against represented IDs and flags missing or unknown references. It also surfaces ambiguity, reconciliation conflicts, unreadable pages, and provider-validation warnings. This percentage covers AI-identified facts only; the independent source-line audit checks a different failure mode. Neither check can certify the underlying translation.

Template selection is deterministic:

| Data condition | Template |
|---|---|
| documents or eligibility | checklist |
| two or more actions | step flow |
| two or more dates | timeline |
| per-group dates or rules | decision/table treatment |
| warnings, exceptions, consequences | warning card |
| location, contact, applicant fee, or funding awarded to participants | information card |

### React frontend

`ImageInputPanel` makes camera capture and image upload primary actions and maintains ordered multi-page previews. If semantic analysis fails after browser OCR, it displays the recognized text beside the source pages for correction and retry without another OCR pass. `OriginalImageView` presents source pages, quality warnings, QR results, and editable recovered Korean text in local administrative mode. On the hosted browser-OCR path, local object URLs show the user's source photo without uploading it. `VisualInstructions` composes reusable semantic sections, including a distinct financial-support card, and can disclose the supporting source page in a modal. Lucide icons always appear with text.

The same `AnalysisResult` drives the Original, Translation, Simplified, and Visual tabs. Research Mode reveals only one condition. Researcher View allows schema-level manual correction and calls the backend to validate and regenerate derived output without an AI call.

### Persistence

SQLite stores complete processed-notice snapshots and research results. For the
local Python/Docker image API, originals and processed working images are stored
under `data/uploads/{analysis_id}` for evidence review. Browser-OCR analyses
store text/results but no photos. The default database file is local and can be
redirected using `VISNOTICE_DB_PATH`. CSV output escapes spreadsheet-formula
prefixes in participant IDs. The prototype does not implement automatic
retention or deletion.

## Data flow

```text
Camera photo / image pages / PDF / Korean text
        |
        +-- local image/visual PDF --> preserve original pages
        |                              EXIF + enhancement + quality + QR
        |                              PaddleOCR in-process or OCR container
        |
        +-- hosted camera/image ----> browser PaddleOCR (Korean PP-OCRv5)
        |                              best-effort local QR URL decode
        |                              send text + positions, keep photos local
        |
        +-- selectable text ------> Korean detection
                                    |
                                    v
                            optional browser-OCR column ordering
                                    |
                                    v
                            TranslationProvider
                              MyMemory (temporary)
                              or LibreTranslate
                                    |
                                    v
                            SemanticProvider
                              structured OpenAI extraction
                              optional English-field repair
                                    |
                                    v
                            source-line completeness audit
                              optional targeted retry
                              add grounded English detail or fail
                                    |
                                    v
                            photo final English support check
                              one bounded classification request
                              withhold unsupported final wording
                              recover literal score pairs as printed tables
                                    |
                                    v
                            NoticeData validation
                              + fidelity/coverage report
                              + deterministic templates
                              + SQLite snapshot
                                    |
                                    v
                            React A / B / C renderers
```

## Long notices

The text API accepts at most 200,000 characters and still relies on translation-service quotas and the semantic model context window. MyMemory input is split below its 500-byte query limit, which can consume multiple free requests for one notice. The completeness audit currently caps recovered source units at 120 and can make an additional model request; beyond that limit or when text remains ambiguous, the API returns an error instead of publishing a digest. Local image input is limited to 12 ordered pages, 15 MB per page, and 50 MB total; the browser-OCR text endpoint permits 12 pages, 20,000 characters per page, and 50,000 total. Production work should replace the temporary public translator and add section-aware semantic chunking with cross-page source-fact reconciliation.

## Photo continuity and partial interpretation

The photo UI opts into `allow_partial=true`; the API default remains strict. This
is a reporting/recovery choice, not a different semantic model. Preflagged damaged
contacts and ambiguous score-table tokens cannot become guessed facts. After at most
two audits, valid independent facts may be presented with an explicit partial status,
source-unit count, and English page/line gaps. Unsafe dependent primary claims and
free context are withheld. Raw Korean remains in the Original/evidence views, not
in the English digest as an unmapped-line substitute.

Photo extraction uses a compact schema: exact quoted evidence remains model output,
while fact IDs are assigned locally. Identical quotes on the same page share IDs,
preserving separate document checklist items. The MyMemory baseline is displayed
separately and is omitted from photo semantic prompts. In non-mock photo mode,
baseline translation and Korean-source extraction run concurrently. Their measured
durations are independent; the pipeline wall time does not add the overlap twice.
Unexpected stage errors cancel and join the sibling request. Strict text/document
and mock processing still forwards the completed translation to extraction.
The final support check
classifies the actual final English after all repairs, without writing replacements.
Provider-generated review prose is replaced by application-owned English gaps.
Unassociated table cells and short generic captions are withheld; this conservative
check can also withhold legible information. Positioned English-score pairs can be
restored as explicitly printed table rows with applicability unverified; geometry
does not independently establish eligibility. SDK automatic retries are disabled
and production model requests use a 45-second timeout. The final check's measured
latency is separate from coverage latency; neither stage is added twice to totals.

A failed translator can be bypassed for interpretation from Korean source text,
while the baseline translation is explicitly unavailable. Provider failures or input
too long to verify can produce an English unavailable state with no factual
instructions. `metrics_complete=false` distinguishes partial call/token accounting
from fully measured responses. Local photos remain available; none of these paths
requires the user to transcribe Korean. Input limits, rate limits, unsupported
browsers, connectivity failures, and legibility limits still exist.

Coverage repair keeps its safe partial-result contract and a separate internal
candidate notice. Only the photo orchestrator passes these candidates to the
mandatory final support review; they are never serialized as unchecked output.
Known rejections, blocked OCR and invented quotations remain excluded. Local
presentation rules and direct date/amount contradiction checks run before the
review, so its source-completeness verdict describes the same English that can
be shown. Supported wording for one clause does not certify the whole source
unit. Final source certification also requires surviving citations and collective
value, condition, spending and printed-English-phrase checks. A supported complete
replacement can clear an earlier gap; a discarded incorrect candidate does not
permanently force a partial status.

The photo review response uses required keyed enum verdicts for every supplied
English field and source unit, preventing omissions and duplicate IDs in a valid
structured response. This changes response bookkeeping, not the model or its
evidence criteria. The existing three-list response remains the contract when
the independent verifier is called without source units.

Targeted repairs always require complete details. Photo retries receive nearby,
same-page, unblocked source units as read-only context, allowing a continuation to
quote its heading without counting that heading as another repaired target.
Target assignments remain exactly once; context IDs are validated separately and
their exact text is included in the final review's quotation. Context does not
establish semantic correctness or allow a dependent claim to bypass review.
