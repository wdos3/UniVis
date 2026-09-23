# Container deployment

The public Vercel function does not include PaddlePaddle or PaddleOCR because
the native runtime is larger than the serverless-function bundle limit. The
repository therefore includes a dedicated CPU OCR service that can run beside
the API on any Docker-capable host.

## Local Compose

```powershell
Copy-Item .env.example .env
docker compose up --build
```

The services are:

- `ocr`: PaddleOCR at `http://localhost:8002`, with an internal `/ocr` endpoint
  and `/health` endpoint;
- `backend`: the lean FastAPI application at `http://localhost:8001` (it does
  not install PaddleOCR; image OCR is delegated to `ocr`);
- `frontend`: the React application at `http://localhost:5174`.

Compose gives the backend the internal URL `http://ocr:8000`. The shared
`PADDLEOCR_SERVICE_TOKEN` protects the OCR endpoint even on a shared Docker
network. Do not use the example token for a public deployment.

## Connecting Vercel to a hosted OCR container

1. Build and publish `ocr_service/Dockerfile` to a container host. The API
   image uses `backend/Dockerfile.api` and intentionally excludes PaddleOCR.
2. Configure the container's `PADDLEOCR_SERVICE_TOKEN` to a long random secret.
3. Restrict the container's ingress if the host supports private networking.
   Otherwise expose HTTPS and keep the token enabled.
4. Add these Vercel server-side environment variables:

   - `PADDLEOCR_SERVICE_URL=https://your-ocr-host.example.com`
   - `PADDLEOCR_SERVICE_TOKEN=<the same random secret>`
   - `PADDLEOCR_SERVICE_TIMEOUT_SECONDS=90`

The browser never receives the OCR URL or token. Vercel's existing
`/api/analyze-images` route uploads the image to the API, and the API forwards
the image bytes to the OCR container. Translation and semantic analysis remain
in the existing pipeline.

## Service contract

`POST /ocr` accepts one or more multipart `files` fields. It returns:

```json
{
  "text": "[Page 1]\n...",
  "page_texts": ["..."],
  "provider": "paddleocr-ppocrv5-korean-local",
  "status": "available",
  "warnings": []
}
```

The service accepts the same prototype limits as the main API: at most 12
pages, 15 MB per page, and 50 MB total. It loads the detector and Korean
recognizer once per container process and reuses them for subsequent requests.

## Fallback behavior

If `PADDLEOCR_SERVICE_URL` is empty, the API uses the existing in-process
`PaddleOcrProvider`. This keeps the Windows development workflow unchanged.
When the URL is configured, failures are surfaced as actionable OCR errors;
the API does not silently send the image to OpenAI.
