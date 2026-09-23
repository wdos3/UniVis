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
- `OPENAI_MODEL` — defaults to `gpt-4.1-mini`.
- `TRANSLATION_PROVIDER` — defaults to `mymemory`.
- `CORS_ORIGINS` — optional for cross-origin callers; the hosted UI uses
  same-origin API rewrites.

The repository's local runtime installs PaddleOCR and PaddlePaddle from
`backend/requirements.txt`. The Vercel function intentionally leaves those
large native packages out because their bundle exceeds Vercel's 500 MB
function limit. As a result, the hosted branch supports the demos, text/PDF
text flows, translation, and semantic rendering; image OCR remains available
when running the same branch locally (or on a container host). The health
endpoint reports `paddleocr-local-unavailable-on-vercel` instead of claiming
that hosted image OCR is ready. This keeps the public prototype honest while
the deployment architecture is evaluated.
