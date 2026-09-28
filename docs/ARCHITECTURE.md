# Architecture

## Design goals

VisNotice separates factual interpretation from presentation. AI providers return typed data, never HTML. React owns the output structure, so Conditions B and C share facts but differ in presentation. Source evidence, page provenance, and internal fact IDs make omissions and image-reading uncertainty inspectable.

## Components

### FastAPI backend

`app/main.py` exposes text, image, PDF, browser-OCR text, demo, recovered-text correction, researcher-edit, and study-result endpoints. Pydantic models in `app/models.py` reject extra fields, invalid steps, duplicate fact IDs, and invalid research condition/confidence values.

Three provider boundaries keep acquisition, translation, and semantic interpretation separate:

- `PaddleOcrProvider` runs the lightweight PP-OCRv5 detector and Korean recognizer locally, then assembles ordered page text. `RemotePaddleOcrProvider` sends the same ordered image bytes to the dedicated authenticated OCR container when `PADDLEOCR_SERVICE_URL` is configured. Both providers share the same result contract and preserve page-level warnings.
- `TranslationProvider` performs translation without interpretation. MyMemory is the temporary no-key adapter and uses byte-bounded requests; `LibreTranslateProvider` supports a later self-hosted replacement.
- `SemanticProvider` converts Korean OCR plus its machine translation into one strict `NoticeData` response. The live OpenAI provider makes exactly one structured-output request. Mock providers keep the five synthetic demos local.

Image services preserve the uploaded original, apply EXIF orientation, create a mildly enhanced working copy, report heuristic quality issues, and detect QR codes without opening them. Images are not included in the OpenAI request. Overlapping heading and full-page OCR passes improve poster recovery while preserving uncertainty for review.

For hosted camera and image uploads, the frontend instead runs PaddleOCR.js
locally in the browser and posts ordered per-page recognized text to
`/api/analyze-client-ocr`. That endpoint rejects image data and filenames,
validates page and text limits, applies the public analysis rate limit, and
passes the text through the same translation and semantic pipeline once. It
records page-level provenance and OCR timing, but no image bytes are persisted
by this path. Source photos remain in browser memory for the current session.

PDF extraction uses PyMuPDF. Selectable text bypasses OCR; image-only PDFs render ordered pages and use local OCR. Password-protected, malformed, unreadable, and over-limit files return explicit errors.

### Fidelity and template services

Each critical source fact is assigned `F001`, `F002`, and so on. Grounded output elements reference one or more IDs. `calculate_fidelity` compares critical IDs against represented IDs and flags missing or unknown references. It also surfaces ambiguity, reconciliation conflicts, unreadable pages, and provider-validation warnings.

Template selection is deterministic:

| Data condition | Template |
|---|---|
| documents or eligibility | checklist |
| two or more actions | step flow |
| two or more dates | timeline |
| per-group dates or rules | decision/table treatment |
| warnings, exceptions, consequences | warning card |
| location, contact, fee | information card |

### React frontend

`ImageInputPanel` makes camera capture and image upload primary actions and maintains ordered multi-page previews. `OriginalImageView` presents source pages, quality warnings, QR results, and editable recovered Korean text. On the hosted browser-OCR path, local object URLs show the user's source photo without uploading it. `VisualInstructions` composes reusable semantic sections and can disclose the supporting source page in a modal. Lucide icons always appear with text.

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
        |                              send ordered text, keep photos local
        |
        +-- selectable text ------> Korean detection
                                    |
                                    v
                            TranslationProvider
                              MyMemory (temporary)
                              or LibreTranslate
                                    |
                                    v
                            SemanticProvider
                              one structured OpenAI call
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

The text API accepts at most 200,000 characters and still relies on translation-service quotas and the semantic model context window. MyMemory input is split below its 500-byte query limit, which can consume multiple free requests for one notice. Local image input is limited to 12 ordered pages, 15 MB per page, and 50 MB total; the browser-OCR text endpoint permits 12 pages, 20,000 characters per page, and 50,000 total. Production work should replace the temporary public translator and add section-aware semantic chunking with cross-page source-fact reconciliation.
