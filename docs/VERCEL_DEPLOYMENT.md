# Provisional Vercel deployment

This branch contains the Version 2 prototype and is intentionally separate
from the repository's default branch while the PaddleOCR, MyMemory, and visual
instruction choices are evaluated.

## Architecture

- `frontend/` is built as the Vite static site.
- `api/index.py` exposes the existing FastAPI application as a Vercel Python
  function.
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
- `PADDLEOCR_SERVICE_URL` — HTTPS URL of the separately hosted OCR container.
- `PADDLEOCR_SERVICE_TOKEN` — server-side shared secret for that container.
- `PADDLEOCR_SERVICE_TIMEOUT_SECONDS` — OCR request timeout, default `90`.

The repository's local runtime installs PaddleOCR and PaddlePaddle from
`backend/requirements.txt`. The Vercel function intentionally leaves those
large native packages out because their bundle exceeds Vercel's 500 MB
function limit. Configure the three `PADDLEOCR_SERVICE_*` variables above to
enable image OCR from a separately hosted Docker service. Without that URL,
the health endpoint reports `paddleocr-local-unavailable-on-vercel` and image
OCR remains unavailable on Vercel. The browser never receives the container
token; the FastAPI function forwards image bytes server-side.
