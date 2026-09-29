# Provisional Vercel deployment

This branch contains the Version 2 prototype and is intentionally separate
from the repository's default branch while the PaddleOCR, MyMemory, and visual
instruction choices are evaluated.

## Architecture

- `frontend/` is built as the Vite static site.
- `api/index.py` exposes the existing FastAPI application as a Vercel Python
  function.
- The hosted camera and image upload path runs PaddleOCR.js with Korean/English
  PP-OCRv5 models in the visitor's browser. It posts only ordered recognized
  text and normalized text-box positions to `/api/analyze-client-ocr`; photo
  bytes and filenames are not sent to that endpoint. The server still sends recognized text to the configured
  translator and semantic provider.
- `vercel.json` rewrites `/api/*`, `/uploads/*`, and `/demo-images/*` to that
  function and serves the React single-page app for other routes.
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
large native packages out because their bundle exceeds Vercel's 500 MB
function limit. Browser PaddleOCR is the no-container path for camera and image
files. On first use it downloads model/runtime assets, then performs inference
on the visitor's device; performance and browser compatibility must be tested
on intended phones. A direct call to the legacy server-side image endpoints
still requires a separately hosted OCR container. Without one, health may
report `paddleocr-local-unavailable-on-vercel` even while browser OCR works.
The browser never receives the container token. Image-only PDFs are not yet
handled by browser OCR on the hosted site; local Python/Docker OCR supports them.

## Fidelity and latency limits

OCR text order can interleave columns and separate table headers from their
values. Browser OCR therefore sends bounded text-box positions, and the API
reconstructs clearly aligned English-test score pairs without trusting the
machine translation's reading order. These pairs are flagged for review.
The fidelity percentage measures links among facts the semantic model already
identified; the review panel separately lists OCR lines not mapped to output.
It is not a guarantee that all source facts were extracted. On a dense
recruitment poster, both `gpt-4o-mini` and a trial of `gpt-4.1-mini` omitted
some prose; the latter also mispaired exam scores and exceeded the interactive
latency target. Keep human review available for high-stakes eligibility and
deadline information.
