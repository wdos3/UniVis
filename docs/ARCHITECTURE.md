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
Exact dates, amounts, contacts, literal English phrases, research-support scope,
and common spending clauses have additional deterministic checks. These checks have bounded
vocabularies and do not prove arbitrary semantic meaning or negation.

### FastAPI backend

`app/main.py` exposes text, image, PDF, browser-OCR text, demo, recovered-text correction, researcher-edit, and study-result endpoints. Pydantic models in `app/models.py` reject extra fields, invalid steps, duplicate fact IDs, and invalid research condition/confidence values.

Three provider boundaries keep acquisition, translation, and semantic interpretation separate:

- `PaddleOcrProvider` runs the lightweight PP-OCRv5 detector and Korean recognizer locally, then assembles ordered page text. `RemotePaddleOcrProvider` sends the same ordered image bytes to the dedicated authenticated OCR container when `PADDLEOCR_SERVICE_URL` is configured. Both providers share the same result contract and preserve page-level warnings.
- `TranslationProvider` performs translation without interpretation. MyMemory is the temporary no-key adapter and splits input below its byte limit, preserving blank paragraph/column boundaries and whole OCR lines where possible; `LibreTranslateProvider` supports a later self-hosted replacement.
- `SemanticProvider` converts Korean OCR plus its machine translation into a strict `NoticeData` response. The live OpenAI provider makes an initial structured-output request, then translates any Korean left in user-facing English fields in one or more batched follow-up calls. Mock providers keep the five synthetic demos local.
- The English completeness service compares distinct substantive recovered source lines with the actual cited English display fields and digest. It can append grounded details to `key_details` or `financial_support`, retry unresolved audit classifications once, or reject a result if substantive meaning cannot be accounted for. The resulting calls and tokens are included in semantic metrics. This is a safeguard, not a guarantee of semantic correctness or recovery of text OCR missed.

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
