# Provisional Vercel deployment

This branch contains the Version 2 prototype and is intentionally separate
from the repository's default branch while the PaddleOCR, MyMemory, and visual
instruction choices are evaluated.

## Architecture

- `frontend/` is built as the Vite static site.
- The project uses Vercel's `Other` framework preset so static frontend files
  are served separately from the file-based Python function in `api/`.
- `api/index.py` exposes the existing FastAPI application as a Vercel Python
  function.
- The hosted camera and image upload path runs PaddleOCR.js with Korean/English
  PP-OCRv5 models in the visitor's browser. It posts per-page recognized
  text and normalized text-box positions to `/api/analyze-client-ocr`; photo
  bytes and filenames are not sent to that endpoint. The browser also makes a
  best-effort local scan for HTTP(S) QR URLs, adding decoded links to the
  recognized text without opening them. The server still sends recognized text
  to the configured translator and semantic provider.
- `vercel.json` rewrites `/api/*`, `/uploads/*`, and `/demo-images/*` to that
  function and serves the React single-page app for other routes.
- The Python function excludes the frontend build tree, tests, and deployment
  documentation from its bundle; frontend assets are served separately.
- The HTML entrypoint is sent with `Cache-Control: no-store` so a browser does
  not retain an old page that references removed hashed assets. The build also
  preserves the two entrypoint asset names from the affected earlier deployment
  while existing browser caches expire.
- Vercel's temporary `/tmp` filesystem is used for prototype uploads and the
  SQLite study store. These values are not durable across cold starts; use a
  managed database/object store before treating this as production storage.

## Environment variables

Configure these in the Vercel project settings (Production and Preview as
appropriate). Never commit `.env` or secret values.

- `OPENAI_API_KEY` — required for real semantic analysis.
- `OPENAI_MODEL` — defaults to `gpt-4o-mini`. Benchmark any replacement on dense, multi-column notices before changing it; a `gpt-4.1-mini` trial here was slower and did not reliably pair exam scores.
- `TRANSLATION_PROVIDER` — defaults to `mymemory`.
- `CORS_ORIGINS` — optional for cross-origin callers; the hosted UI uses
  same-origin API rewrites.
- `PADDLEOCR_SERVICE_URL` — optional HTTPS URL of a separately hosted OCR
  container for direct server-side image routes; not needed for hosted photo UI.
- `PADDLEOCR_SERVICE_TOKEN` — optional server-side shared secret for that container.
- `PADDLEOCR_SERVICE_TIMEOUT_SECONDS` — optional OCR request timeout, default `90`.

The repository's local runtime installs PaddleOCR and PaddlePaddle from
`backend/requirements.txt`. The Vercel function intentionally leaves those
large native packages out because they exceed its function bundle limit.
It also omits server-side OpenCV to stay within the hosted
Python bundle limit; a direct image upload therefore reports that local
quality/QR checks were unavailable. Browser PaddleOCR is the no-container path for camera and image
files. On first use it downloads model/runtime assets, then performs inference
on the visitor's device; performance and browser compatibility must be tested
on intended phones. A direct call to the legacy server-side image endpoints
still requires a separately hosted OCR container. Without one, health may
report `paddleocr-local-unavailable-on-vercel` even while browser OCR works.
The browser never receives the container token. Image-only PDFs are not yet
handled by browser OCR on the hosted site; local Python/Docker OCR supports them.

## Fidelity and latency limits

OCR text order can interleave columns and separate table headers from their
values. Browser OCR therefore sends bounded text-box positions. The API
reorders a clearly positioned two-column band column-first without dropping
lines and can add review-marked, horizontally aligned English-test score pairs.
It leaves sparse or ambiguous layouts alone rather than guessing. MyMemory
translation preserves paragraph and OCR-line boundaries where its byte limit
permits, but its output can still scramble tables.

The English digest is made from structured OpenAI extraction, not from a raw
list of unmatched OCR lines. One or more follow-up calls repair user-facing fields
left in Korean when needed. A separate call then audits recovered source lines
against the English items that cite them and may append grounded English
details; a targeted retry is possible if the first audit cannot classify some
lines. If substantive OCR text still cannot be interpreted, the API rejects the
digest. The hosted UI keeps the source photo and recognized text in memory so
the user can correct OCR and retry without another OCR pass. Funding awarded to
participants is presented separately from applicant fees.

The fidelity percentage measures links among facts the semantic model already
identified; it is not a completeness or translation-accuracy guarantee. The
source-line audit cannot recover text OCR missed, certify English meaning, or
resolve every table. The new follow-up calls also increase tokens and latency.
The 10–15 second end-to-end target is not yet met on a tested dense poster.
Keep human review available for high-stakes eligibility and deadlines, and do
not treat this branch as production-ready.
