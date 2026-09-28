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
  text to `/api/analyze-client-ocr`; photo bytes and filenames are not sent to
  that endpoint. The server still sends recognized text to the configured
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
- `OPENAI_MODEL` — defaults to `gpt-4o-mini` for the lower-latency semantic path. Set `gpt-4.1-mini` when higher extraction quality is worth the extra latency.
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
