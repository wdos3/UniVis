# VisNotice — Version 2

Version 2 separates the notice pipeline into three replaceable portions:

1. local PaddleOCR with the Korean PP-OCRv5 model recovers Korean text without uploading the image;
2. MyMemory provides temporary no-key translation (or a configured LibreTranslate instance can replace it);
3. one OpenAI structured-output request converts the bilingual text into typed visual instructions, which React renders deterministically.

The response records the translation request count and the semantic call's input, output, and total token usage. Version 1 remains unchanged in `../visnotice` apart from its explicit Version 1 branding.

**Visualizing Korean University Notices for International Students**

VisNotice is a local research prototype that turns a photograph, screenshot, PDF, or Korean text notice into three independently presentable conditions:

- **A — Translation:** faithful English translation;
- **B — Simplified Text:** concise structured English without diagrams or icons;
- **C — Visual Instructions:** deterministic checklists, step flows, timelines, warnings, and information cards.

It is designed to test whether visualization helps international students identify deadlines, eligibility, required actions, documents, exceptions, and contact details. It does not claim that visualization improves comprehension; that requires a user study.

## What works

- rear-camera capture plus JPG, PNG, WEBP, HEIC/HEIF, text, and PDF upload;
- ordered multi-image previews, removal, and page reordering;
- EXIF correction, conservative enhancement, quality screening, QR detection, and image-PDF rendering;
- local PaddleOCR PP-OCRv5 Korean recognition for photographs and image-only PDFs; images are not sent to OpenAI;
- selectable MyMemory or LibreTranslate adapter plus mock translation for demos;
- strict Pydantic intermediate representation—models never generate React or HTML;
- exactly one OpenAI semantic request per live analysis;
- recorded OCR, translation, semantic, and total latency plus semantic input/output/total token usage;
- exact Korean evidence and source-fact IDs on important items;
- deterministic visual-template selection;
- five grounded text demos and seven generated image fixtures across six photo scenarios;
- original-photo display, recovered Korean text correction, and image-backed evidence;
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
native packages because they exceed Vercel's function bundle limit. Set
`PADDLEOCR_SERVICE_URL`, `PADDLEOCR_SERVICE_TOKEN`, and
`PADDLEOCR_SERVICE_TIMEOUT_SECONDS` to forward image OCR to the dedicated
container; without them, the hosted prototype remains suitable for demos,
text-file flows, translation, and semantic rendering only. Vercel's temporary
function filesystem also means uploads and SQLite study data are not durable
across cold starts. See [the deployment notes](docs/VERCEL_DEPLOYMENT.md)
before treating this branch as production-ready.

## API configuration

Copy `.env.example` to `.env`. `OPENAI_API_KEY` is required only for arbitrary semantic analysis. Keys are read from the environment, never persisted, returned to the client, or logged.

| Variable | Purpose | Default |
|---|---|---|
| `OPENAI_API_KEY` | Enables the single live semantic call | unset |
| `OPENAI_MODEL` | Structured-output semantic model | `gpt-4.1-mini` |
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
| `CORS_ORIGINS` | Allowed frontend origins | `http://localhost:5174` |
| `VISNOTICE_DB_PATH` | SQLite file path | project `visnotice.db` |
| `LOG_LEVEL` | Structured development log level | `INFO` |

With no key, the app starts in mock mode and explains that arbitrary real notices cannot be interpreted. All bundled text and image demos remain fully functional.

## Typical workflow

1. Select **Take a Photo**, **Upload Image**, **Upload PDF**, or **Paste Korean text**.
2. Preview image pages, add/remove pages, and put them in reading order.
3. Select Auto, Mock, or OpenAI for the semantic step and analyze the notice.
4. For image input, inspect original pages, quality warnings, QR results, and locally recovered Korean text.
5. Inspect Translation, Simplified Text, and Visual Instructions.
6. Turn on **Show source evidence** to compare English items with Korean phrases, fact IDs, and source pages.
7. Correct recovered text or use **Researcher View** for structured-data/template corrections.
8. Use **Print / Save PDF** for a clean student-facing export.

Image-only PDFs are rendered and processed by local OCR. An unreadable source is rejected instead of producing plausible instructions.

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
Image preparation + quality / QR checks
    ↓
Local PaddleOCR PP-OCRv5 Korean, either in-process or in the dedicated OCR container (or embedded PDF/text input)
    ↓
Temporary translation provider (MyMemory or LibreTranslate)
    ↓
One OpenAI semantic structured-output request
    ↓
Strict NoticeData schema + evidence/fidelity coverage
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

Backend tests cover image and multi-image upload, page order, image-only PDFs, EXIF rotation, preprocessing, invalid/oversized images, QR extraction, table preservation, exact-value conflicts, conservative provider failure, recovered-text correction, schema validation, fidelity, and CSV export. Frontend tests cover camera capture markup, ordered previews, template rendering, and evidence disclosure.

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

Generated output can be wrong and must not replace an official university notice. OCR may misread photographs, free machine translation may mistranslate administrative language, and semantic analysis may omit qualifications. Quality detection is heuristic and icons can differ culturally. Images stay local; extracted text is sent to the configured translation service, and the Korean plus translated text is sent to OpenAI for one semantic request. Paddle's model files are fetched on first live use, but notice images are not sent to Paddle. Originals and processed copies are stored locally for evidence review; the prototype has no retention scheduler. It stores processed notices and non-identifying study responses in SQLite and does not collect accounts, names, or participant email addresses.
