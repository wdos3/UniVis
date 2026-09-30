# Limitations

## Model and translation error

OCR can corrupt Korean text, a free translator can mistranslate administrative language, and the semantic model can still omit or misclassify facts even when constrained by a schema. Version 2 now uses an initial structured extraction, optional batched English-field repair calls, and a separate completeness audit that may make a targeted retry. These checks consume additional OpenAI tokens and time. A [schema-conforming response can still contain mistakes](https://developers.openai.com/api/docs/guides/structured-outputs); human bilingual review remains necessary.

## Source-fact coverage is structural

The fidelity percentage detects missing and unknown references among facts the model identified. It cannot see facts missing from the model's inventory. A separate check compares recovered OCR lines with the English display fields that cite them; it can add grounded English details, or fail the analysis rather than publish a digest when the source remains unresolved. It cannot prove that the English meaning is correct, detect text that OCR never recovered, or make an ambiguous table pairing reliable. A wrong paraphrase can still cite the right source line. Page links and optional bounding boxes improve auditability but do not establish semantic correctness. Raw unmapped OCR lines are not presented as a substitute for a digest.

## Administrative and legal language

Visa, employment, tuition, and academic-status notices may have legal effects. The prototype must not replace official guidance, university staff, or immigration authorities.

## Photograph and OCR limitations

Image-quality detection is heuristic: it can miss glare, cutoff text, perspective distortion, or a notice that occupies too little of the frame, and it can warn on a usable page. The prototype applies EXIF rotation and mild enhancement but does not provide interactive cropping or full perspective correction.

PaddleOCR is the primary image-text channel. The local Python/Docker route uses full-page and footer-detail passes and marks low-confidence lines for review. PaddleOCR can still confuse similar Hangul glyphs, punctuation, QR-adjacent text, and perspective-distorted lines; neither route guarantees reliable word-level bounding boxes. Page-level evidence is the reliable minimum.

The hosted camera/image path runs PaddleOCR in the visitor's browser. First use
must download the model/runtime assets, and inference depends on the device's
CPU, memory, and browser support; the 10–15 second end-to-end target has not
been met on the tested dense photo. This route sends recovered text and bounded
normalized text positions to the API, not photo bytes. The API only reorders a
clearly positioned two-column section; it leaves sparse tables and ambiguous
layouts alone. The browser also attempts to decode HTTP(S) QR URLs locally, but
this is best-effort and never opens a link automatically. Unlike local
Python/Docker image analysis, the hosted route does not run server-side image
quality checks. A false OCR reading—including a plausible-looking phone
number—may pass with high OCR confidence. Check the original photo against
the recovered text before relying on a result.

## PDF extraction

PyMuPDF handles selectable text but reading order can be wrong in multi-column layouts or tables. Image-only PDFs are rendered into ordered pages and analyzed through local Python/Docker OCR, not the hosted browser-OCR route. On the hosted site, an image-only PDF therefore requires a separately configured OCR container or conversion to image pages first. Password-protected, malformed, and PDFs longer than the prototype page limit may fail. Mock mode can interpret only bundled synthetic image fixtures; arbitrary real notice semantics requires `OPENAI_API_KEY`.

## Long and composite notices

The semantic provider does not implement section-aware chunking and reconciliation. Very long notices may exceed a model limit or lose cross-section context. MyMemory must split text into sub-500-byte queries; the current splitter preserves paragraph/column boundaries and complete OCR lines when they fit but cannot reconstruct table meaning. A long notice can exhaust the public translator's quota or fail partway through. The source-line completeness audit is capped at 120 units. The text API applies a 200,000-character ceiling; visual inputs accept at most 12 pages, 15 MB per image page, and 50 MB total. Provider failures and unverified completeness are surfaced instead of silently bypassed.

## Visual and cultural interpretation

Lucide icons use common conventions, but meaning is not culturally universal. Icons are always paired with labels; user testing is still required. Color is supportive rather than the sole carrier of meaning.

## Simplification loss

Concise language can unintentionally weaken a qualification, remove context, or imply an order. Conditions B and C render the same structured facts but must still be compared with the source, not assumed equivalent. Funding awarded to participants is stored separately from fees they must pay; OCR or semantic errors can still confuse the direction of payment.

## Evaluation bias

The five text demos and seven image pages are synthetic and authored to fit the schema. They cannot estimate performance on real notices. Familiarity, English ability, device, camera quality, visual literacy, notice difficulty, and question design may confound study outcomes.

The included answer scorer is intentionally simple and can misclassify synonymous or partially correct answers. Formal studies need pre-registered scoring rules and human adjudication.

## Privacy and deployment

SQLite and source-image storage have no user-account authentication or encryption. The hosted UI's browser-OCR camera/image path keeps photos on the visitor's device and persists only recognized text/results server-side. The local Python/Docker image API still stores originals and processed copies under `data/uploads` (or the cloud data volume) until manually removed; there is no retention scheduler. Public mode disables global notice browsing, editing, reprocessing, and study CSV export without a server-side administrator token, but stored results and any images uploaded through the legacy API still need protection. Do not submit private notices to the public deployment. OCR text is sent to the configured translation service and Korean plus translated text is sent to the semantic provider. Researchers must assess both providers' terms and institutional data-handling requirements before using sensitive material.

## Deferred work

- interactive crop and perspective correction;
- stronger document detection, deskewing, and Korean OCR confidence scoring;
- replacement of the temporary public translator with a controlled service;
- robust semantic chunking/reconciliation for very long notices and dense tables;
- URL ingestion;
- PNG or server-generated PDF export;
- non-English target languages;
- graphical decision-tree branching beyond conditional cards/tables;
- post-comparison preference survey and counterbalancing logic;
- configurable retention, production authentication, encryption, migration tooling, and deployment hardening.
