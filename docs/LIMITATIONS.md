# Limitations

## Model and translation error

OCR can corrupt Korean text, a free translator can mistranslate administrative language, and the semantic model can still omit or misclassify facts even when constrained by a schema. Version 2 deliberately uses one semantic call; the structural fidelity report is deterministic, not an independent semantic guarantee. Human bilingual review remains necessary.

## Source-fact coverage is structural

Coverage detects missing and unknown fact references. It does not prove that an English statement correctly represents the Korean evidence. A wrong paraphrase can still point to the right fact ID. Page links and optional bounding boxes improve auditability but do not establish semantic correctness.

## Administrative and legal language

Visa, employment, tuition, and academic-status notices may have legal effects. The prototype must not replace official guidance, university staff, or immigration authorities.

## Photograph and OCR limitations

Image-quality detection is heuristic: it can miss glare, cutoff text, perspective distortion, or a notice that occupies too little of the frame, and it can warn on a usable page. The prototype applies EXIF rotation and mild enhancement but does not provide interactive cropping or full perspective correction.

PaddleOCR is the primary image-text channel and runs locally with the lightweight PP-OCRv5 Korean recognizer. The first live image analysis needs network access to download the official model weights. PaddleOCR can still confuse similar Hangul glyphs, punctuation, QR-adjacent text, and perspective-distorted lines. Version 2 uses full-page and footer-detail passes and marks low-confidence lines for review; it does not claim reliable word-level bounding boxes. Page-level evidence is the reliable minimum.

The hosted camera/image path runs PaddleOCR in the visitor's browser. First use
must download the model/runtime assets, and inference depends on the device's
CPU, memory, and browser support; the 10–15 second target is not guaranteed.
This browser path currently sends OCR text to the API without the server's
image-quality and QR checks or bounding boxes. Check the original photo against
the recovered text before relying on a result.

## PDF extraction

PyMuPDF handles selectable text but reading order can be wrong in multi-column layouts or tables. Image-only PDFs are rendered into ordered pages and analyzed through local Python/Docker OCR, not the hosted browser-OCR route. On the hosted site, an image-only PDF therefore requires a separately configured OCR container or conversion to image pages first. Password-protected, malformed, and PDFs longer than the prototype page limit may fail. Mock mode can interpret only bundled synthetic image fixtures; arbitrary real notice semantics requires `OPENAI_API_KEY`.

## Long and composite notices

The semantic provider does not implement section-aware chunking and reconciliation. Very long notices may exceed a model limit or lose cross-section context. MyMemory must split text into sub-500-byte queries, so a long notice can exhaust its public quota or fail partway through. The text API applies a 200,000-character ceiling; visual inputs accept at most 12 pages, 15 MB per image page, and 50 MB total. Provider failures are surfaced.

## Visual and cultural interpretation

Lucide icons use common conventions, but meaning is not culturally universal. Icons are always paired with labels; user testing is still required. Color is supportive rather than the sole carrier of meaning.

## Simplification loss

Concise language can unintentionally weaken a qualification, remove context, or imply an order. Conditions B and C must therefore be audited against source evidence, not assumed equivalent.

## Evaluation bias

The five text demos and seven image pages are synthetic and authored to fit the schema. They cannot estimate performance on real notices. Familiarity, English ability, device, camera quality, visual literacy, notice difficulty, and question design may confound study outcomes.

The included answer scorer is intentionally simple and can misclassify synonymous or partially correct answers. Formal studies need pre-registered scoring rules and human adjudication.

## Privacy and deployment

SQLite and source-image storage have no user-account authentication or encryption. The hosted UI's browser-OCR camera/image path keeps photos on the visitor's device and persists only recognized text/results server-side. The local Python/Docker image API still stores originals and processed copies under `data/uploads` (or the cloud data volume) until manually removed; there is no retention scheduler. Public mode disables global notice browsing, editing, reprocessing, and study CSV export without a server-side administrator token, but stored results and any images uploaded through the legacy API still need protection. Do not submit private notices to the public deployment. OCR text is sent to the configured translation service and Korean plus translated text is sent to the semantic provider. Researchers must assess both providers' terms and institutional data-handling requirements before using sensitive material.

## Deferred work

- interactive crop and perspective correction;
- stronger document detection, deskewing, and Korean OCR confidence scoring;
- replacement of the temporary public translator with a controlled service;
- robust chunking/reconciliation for very long notices;
- URL ingestion;
- PNG or server-generated PDF export;
- non-English target languages;
- graphical decision-tree branching beyond conditional cards/tables;
- post-comparison preference survey and counterbalancing logic;
- configurable retention, production authentication, encryption, migration tooling, and deployment hardening.
