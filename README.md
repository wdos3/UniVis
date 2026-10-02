# VisNotice — Version 2

Version 2 separates the notice pipeline into three replaceable portions:

1. PaddleOCR with the Korean PP-OCRv5 model recovers Korean text—locally in Python/Docker, or in the visitor's browser on the hosted site;
2. MyMemory provides temporary no-key translation (or a configured LibreTranslate instance can replace it);
3. OpenAI extracts typed notice facts from the Korean source and translation, then checks the English output for omitted source details. React renders the result deterministically.

An analysis can make several OpenAI calls: initial structured extraction, English-field repair when needed, a source-line completeness audit, possibly a targeted audit retry, and a bounded final English support check for photos. Photo extraction assigns fact IDs locally from exact quotations and interprets Korean directly; MyMemory remains a separate baseline. Grounded photo candidates are retained internally for final review even when an earlier audit cannot certify them. The review checks each English claim and the complete meaning of each recovered source unit; uncertain candidates are withheld. The response records stage timings, request counts, and available token usage. Version 1 remains unchanged in `../visnotice` apart from its explicit Version 1 branding.

Non-mock photo extraction runs alongside the independent baseline translation.
Targeted photo repairs can quote exact nearby source context to retain
heading/continuation relationships. Explicit printed acronym expansions can be
restored from the field's own quotation; no expansion is inferred from memory.

**Visualizing Korean University Notices for International Students**

VisNotice is a local research prototype that turns a photograph, screenshot, PDF, or Korean text notice into three independently presentable conditions:

- **A — Translation:** faithful English translation;
- **B — Simplified Text:** concise structured English without diagrams or icons;
- **C — Visual Instructions:** deterministic checklists, step flows, timelines, warnings, and information cards.

It is designed to test whether visualization helps international students identify deadlines, eligibility, required actions, documents, exceptions, and contact details. It does not claim that visualization improves comprehension; that requires a user study.

## What works

- rear-camera capture plus JPG, PNG, WEBP, text, and PDF upload (local Python/Docker image API also accepts HEIC/HEIF);
- ordered same-notice image pages, removal/reordering, and a separate replacement upload for testing another notice;
- EXIF correction, conservative enhancement, quality screening, QR detection, and image-PDF rendering;
- PaddleOCR PP-OCRv5 Korean recognition for photographs and image-only PDFs in the local Python/Docker runtime;
- browser-based PaddleOCR for camera and image uploads on the hosted site, with recognized text, bounded text positions, and any locally decoded QR web URLs sent to the application API rather than photo bytes;
- conservative column-aware ordering for browser OCR when positioned text clearly forms two side-by-side sections;
- local best-effort QR URL decoding that never opens links automatically;
- selectable MyMemory or LibreTranslate adapter plus mock translation for demos;
- translation chunking that keeps OCR paragraph/column boundaries and whole lines where the provider's byte limit permits;
- strict Pydantic intermediate representation—models never generate React or HTML;
- English-language field repair and source-line auditing with bounded retries; photo mode withholds uncertain claims and shows supported facts with explicit English verification gaps;
- recorded OCR, translation, semantic, and total latency plus aggregate semantic request/token counts;
- separate semantic extraction, English repair, and completeness-audit timings; device-side model preparation/detection/recognition and latest server-request timing for photos;
- adaptive browser-local recovery for small or uncertain text, plus a lower-edge check on tall photos (at most two additional crops), retaining conflicting readings;
- exact Korean evidence and source-fact IDs on important items;
- deterministic visual-template selection;
- five grounded text demos and seven generated image fixtures across six photo scenarios;
- original-photo display, recovered Korean text correction and retry after a failed photo analysis, and image-backed evidence;
- actionable page/text correction requests for unreadable contacts, unresolved source lines, and incomplete or ambiguous English-test tables;
- manual researcher correction and regeneration without another AI call;
- research sessions with isolated A/B/C conditions, questions, elapsed time, confidence, and local SQLite storage;
- CSV study-data export with comprehension accuracy and critical-information miss rate;
- print-friendly visual output for browser “Save as PDF”;
- explicit unreadable-image, language-detection, missing-key, ambiguity, and no-action states.

## Quick start on Windows

Requirements: Node.js 20+ and Python 3.11+. PaddleOCR and its CPU runtime are installed from `backend/requirements.txt`. The first live image analysis downloads and caches the official lightweight Korean PP-OCRv5 recognition model and mobile detection model; subsequent runs reuse them.

### One-command helper

From PowerShell:

```powershell
cd C:\path\to\visnotice-v2
.\start.ps1 -Install
```

The first run creates `backend/.venv`, installs dependencies, and opens both development servers. Later runs can use `./start.ps1`.

### Run manually

Terminal 1:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8001
```

Terminal 2:

```powershell
cd frontend
npm install
npm run dev -- --port 5174
```

Open [http://localhost:5174](http://localhost:5174). API documentation is at [http://localhost:8001/docs](http://localhost:8001/docs).

Docker users may copy `.env.example` to `.env` and run `docker compose up --build`.
Compose starts the API at port 8001 and a separate CPU PaddleOCR service at port
8002. The API sends image pages to that service over the private Compose network,
so the API process does not need to load PaddleOCR itself. The OCR service downloads
the two lightweight Korean/English model files on first use.

### Provisional Vercel deployment

This repository includes a Vercel adapter for the hosted prototype. The
deployment serves the Vite frontend and rewrites the FastAPI routes through
`api/index.py`. Configure `OPENAI_API_KEY` (and any translation settings) in
the Vercel project environment; never commit `.env` or secret values. The
local runtime still uses PaddleOCR, but Vercel intentionally omits its large
native packages because they exceed Vercel's function bundle limit. On the
hosted UI, camera and image files are recognized by PaddleOCR in the browser;
the API receives ordered OCR text, not photo bytes. This requires a capable
browser and a first-load download of the OCR models. The local Python/Docker
image and image-only PDF path remains available. A separate OCR container may
still be configured with `PADDLEOCR_SERVICE_URL` and its token, but is not
required for hosted photo input. Vercel's temporary function filesystem also
means text analyses and SQLite study data are not durable across cold starts.
See [the deployment notes](docs/VERCEL_DEPLOYMENT.md) before treating this
branch as production-ready.

## API configuration

For an optional Arm VM deployment with persistent OCR and API containers, see
[the OCI Always Free guide](docs/OCI_ALWAYS_FREE_DEPLOYMENT.md). The Vercel
site uses browser PaddleOCR for camera and image uploads instead of requiring a VM.

Copy `.env.example` to `.env`. `OPENAI_API_KEY` is required only for arbitrary semantic analysis. Keys are read from the environment, never persisted, returned to the client, or logged.

| Variable | Purpose | Default |
|---|---|---|
| `OPENAI_API_KEY` | Enables live semantic extraction and English completeness checks | unset |
| `OPENAI_MODEL` | Structured-output semantic model | `gpt-4o-mini` |
| `PADDLE_PDX_MODEL_SOURCE` | Paddle model host (`BOS` is the official object-store source) | `BOS` |
| `PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK` | Skip Paddle's extra model-host connectivity probe | `True` |
| `PADDLEOCR_CPU_THREADS` | CPU threads used by local OCR | `8` |
| `PADDLEOCR_ENABLE_MKLDNN` | oneDNN acceleration; disabled by default on Windows for compatibility | platform-dependent |
| `PADDLEOCR_SERVICE_URL` | Optional dedicated OCR container URL; empty uses in-process OCR | unset |
| `PADDLEOCR_SERVICE_TOKEN` | Shared secret for the dedicated OCR container | `local-dev-ocr-token` in Compose |
| `PADDLEOCR_SERVICE_TIMEOUT_SECONDS` | Maximum OCR service request time | `90` |
| `PADDLEOCR_CONTAINER_ENABLE_MKLDNN` | Container oneDNN acceleration toggle; disabled by default for Paddle 3.3 model compatibility | `false` in Compose |
| `TRANSLATION_PROVIDER` | `mymemory` or `libretranslate` | `mymemory` |
| `MYMEMORY_URL` | Temporary no-key translation endpoint | MyMemory public API |
| `LIBRETRANSLATE_URL` | Base URL for a self-hosted replacement | `http://127.0.0.1:5000` |
| `LIBRETRANSLATE_API_KEY` | Optional key required by some LibreTranslate hosts | unset |
| `TRANSLATION_TIMEOUT_SECONDS` | Translation request timeout | `20` |
| `TRANSLATION_CONCURRENCY` | Concurrent MyMemory chunk requests | `4` |
| `CORS_ORIGINS` | Allowed frontend origins | `http://localhost:5174` |
| `VISNOTICE_DB_PATH` | SQLite file path | project `visnotice.db` |
| `VISNOTICE_PUBLIC_MODE` | Disable unauthenticated researcher routes and limit anonymous analyses | unset (automatically enabled on Vercel) |
| `VISNOTICE_ADMIN_TOKEN` | Optional server-side token for researcher routes in public mode | unset |
| `LOG_LEVEL` | Structured development log level | `INFO` |

With no key, the app starts in mock mode and explains that arbitrary real notices cannot be interpreted. Bundled text demos remain available; image demos require a working OCR runtime.

## Typical workflow

1. Select **Take a Photo**, **Upload Image**, **Upload PDF**, or **Paste Korean text**.
2. Preview image pages, add/remove pages, and put them in reading order.
3. Use **Upload another notice** for an independent photo, or **Add another page** for another page of the current notice. Select Auto, Mock, or OpenAI for the semantic step and analyze the notice.
4. For image input, inspect original pages and OCR-recovered Korean text. Local Python/Docker image analysis also reports quality warnings and QR results; the hosted browser route attempts QR URL decoding locally.
5. Inspect Translation, Simplified Text, and Visual Instructions.
6. Turn on **Show source evidence** to compare English items with Korean phrases, fact IDs, and source pages.
7. Photo recovery and audit retries run automatically. The app opens English simplified text first. A **Partial interpretation** status and English source gaps identify withheld details. **Retry English interpretation** reuses the recognized text and positions without repeating OCR or requiring Korean transcription. Source editing is optional; local **Researcher View** also supports structured-data/template corrections.
8. Use **Print / Save PDF** for a clean student-facing export.

Image-only PDFs are rendered and processed by local Python/Docker OCR; the hosted
site's browser OCR currently handles camera and image files, not image-only PDFs.
An unreadable source yields an English unavailable state in photo mode. It does not produce plausible guessed instructions. Text/document APIs retain strict verification failures.

## Research Mode

Load a synthetic demo and open Research Mode. Enter a non-identifying participant code, select Condition A, B, or C, and start. Only the chosen condition is shown. Submission records:

- participant code and notice ID;
- condition;
- start, finish, and duration;
- answers and correctness;
- confidence from 1–5.

Use **Export Study Results CSV** after submission, or open `/api/research/results.csv`. The CSV includes comprehension accuracy and critical-information miss rate. Answer matching in the prototype is deliberately simple; a researcher should review scoring before analysis.

## Architecture

```text
Photo(s) / screenshot / PDF / text
    ↓
Local image preparation + PaddleOCR PP-OCRv5 Korean (Python/Docker), or
browser PaddleOCR for hosted camera/image input (or embedded PDF/text input)
    ↓
Conservative column-aware ordering for positioned browser OCR
    ↓
Temporary translation provider (MyMemory or LibreTranslate)
    ↓
OpenAI structured extraction + English-field repair when needed
    ↓
Source-line completeness audit and possible targeted retry
    ↓
Strict NoticeData schema + evidence/fidelity checks, or an explicit failure
    ↓
Deterministic React templates
    ↓
Translation / Simplified / Visual conditions
```

See [Architecture](docs/ARCHITECTURE.md), [Research design](docs/RESEARCH_DESIGN.md), [Information schema](docs/INFORMATION_SCHEMA.md), and [Limitations](docs/LIMITATIONS.md).

## Tests

```powershell
cd backend
.\.venv\Scripts\python -m pytest

cd ..\frontend
npm test
npm run build
```

Backend tests cover image and multi-image upload, browser-OCR text ingestion,
conservative column ordering, page provenance, image-only PDFs, EXIF rotation,
preprocessing, invalid/oversized images, QR extraction, table preservation,
translation chunking, English-field and source-line checks, conservative provider
failure, recovered-text correction, schema validation, fidelity, and CSV export.
Frontend tests cover camera capture markup, ordered previews, browser OCR and QR
integration, correction/retry, local-only evidence previews, template rendering,
and evidence disclosure.

For repeatable live API profiling of a public fixture (this sends recognized
notice text to the configured translation and semantic services):

```powershell
& .\backend\.venv\Scripts\python.exe backend\scripts\profile_notice.py --text backend\tests\fixtures\sogang_research_corrected.txt --output "$env:TEMP\univis-corrected-profile.json"
```

Use `--browser-ocr backend\tests\fixtures\sogang_research_2026_browser_ocr.json`
to replay positioned OCR. That reuses recorded OCR timing; it does **not** run
new photo inference. See [measured verification](docs/V2_RECOVERY_VERIFICATION.md)
for the distinction between fixture, photo, and deployment checks.

## Repository map

```text
visnotice-v2/
├── backend/app/          FastAPI routes, schemas, providers, fidelity, storage
├── ocr_service/          Standalone PaddleOCR container image and dependencies
├── backend/tests/        API, schema, PDF, fidelity, and export tests
├── frontend/src/         React workspace, visual templates, research/admin views
├── demo_data/            Demo-data guidance
├── docs/                 Architecture, study design, schema, limitations
├── .env.example
├── docker-compose.yml
├── .dockerignore
└── start.ps1
```

## Safety and limitations

Generated output can be wrong and must not replace an official university notice. OCR may misread photographs, free machine translation may mistranslate administrative language, and even a schema-valid semantic analysis may omit or misclassify facts. The completeness audit compares recovered source lines with the English digest and rejects results it cannot confidently account for, but it cannot detect text OCR never recovered or prove the English meaning is correct. Quality detection is heuristic and icons can differ culturally. The hosted camera/image path keeps photo bytes in the browser and sends recognized text, positions, and any decoded QR URLs to the application API. The local Python/Docker image path still uploads and stores originals for evidence review. Neither path sends images to OpenAI. Extracted text is sent to the configured translation service; Korean source text and its translation are sent to OpenAI for analysis, with follow-up checks when needed. These calls add cost and latency; the 10–15 second end-to-end target is not yet met. The prototype has no retention scheduler. It stores processed notices and study responses in SQLite and does not collect account credentials, names, or participant email addresses. Do not submit private notices to the public deployment.
