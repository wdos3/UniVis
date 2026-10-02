# Browser OCR assets

`browserOcr.ts` uses the official Apache-2.0 PaddleOCR.js 0.4.2 SDK, PP-OCRv5 mobile text detection, and its Korean recognition model (which also supports English). Models load lazily from the same origin; no image is uploaded for OCR. The first run downloads approximately 18.4 MB of models plus the ONNX Runtime WASM binary. Subsequent requests can use browser HTTP caching.

The two uncompressed model archives in `frontend/public/models/` were downloaded from PaddlePaddle's official model host on 2026-09-28. Their model metadata declares Apache-2.0; the license copy is in `frontend/public/models/LICENSE`:

| Asset | Source | SHA-256 |
| --- | --- | --- |
| `PP-OCRv5_mobile_det_onnx_infer.tar` | <https://paddle-model-ecology.bj.bcebos.com/paddlex/official_inference_model/paddle3.0.0/PP-OCRv5_mobile_det_onnx_infer.tar> | `781056046c9ed77a15c94681605db6a0f62317c2e9cce6931c71da2478d4bc30` |
| `korean_PP-OCRv5_mobile_rec_onnx_infer.tar` | <https://paddle-model-ecology.bj.bcebos.com/paddlex/official_inference_model/paddle3.0.0/korean_PP-OCRv5_mobile_rec_onnx_infer.tar> | `568ed8b43a260adc9f484d92105e425ea8cddf8ce16940c177bc12864cfb0eb0` |

The PaddleOCR.js worker bundles ONNX Runtime Web 1.24.3, so `package.json`
pins that transitive version. `frontend/public/ort/` contains the matching
JSEP `.mjs`/`.wasm` pair copied from that installed package. The pinned
PaddleOCR.js worker always loads this pair for its WASM backend. `browserOcr.ts` passes an absolute same-origin `wasmPaths` URL; a
relative `/ort/` URL caused Vite development-mode module import failures,
while omitting `wasmPaths` fetched runtime code from a third-party CDN. Keep
the pinned package and copied files version-matched when upgrading. The copied
runtime is MIT licensed; its notice is in `frontend/public/ort/LICENSE`.

The browser SDK uses a worker and single-threaded WASM. Image decoding depends
on `createImageBitmap` and `OffscreenCanvas`; JPEG, PNG, and WebP are the
intended inputs. HEIC/HEIF availability varies by browser. Model initialization
and image inference are separate costs; measure both on representative devices
before claiming an interactive latency target. A Korean/English synthetic
fixture succeeded in headless Chrome and Edge on 2026-09-29: about 4.6–5.1 s
for cold OCR and 2.5–2.8 s warm on this development machine. Those times do
not include network transfer, translation, or the semantic model.

Each image can get an additional local OCR pass over a small or
uncertain text cluster. Selection uses recognition confidence and text height
after full-image downscaling, across the whole image rather than a fixed footer.
Overlapping bands along the long axis support portrait, square, and landscape
layouts; the selected band is normally 40% of that axis and expands when needed
to include its target line. Downscaled tall images (height over 2000 pixels and
height/width at least 1.4) also recheck their lower 16% unless the adaptive crop
already covers that entire edge. Initial detection can omit small edge text
without returning confidence or coordinates; this bounded fallback addresses
that blind spot even when uncertainty elsewhere wins the adaptive selection.
An image gets at most two extra OCR crops. These crops use a 2800-pixel detector limit, mild local
contrast, and lower detection thresholds. The crop uses the browser's EXIF-oriented bitmap, and its boxes
are mapped back to the full photo. Duplicate readings are removed only when
their text matches exactly and their boxes overlap substantially; differing
readings remain available for reconciliation or manual correction. This bounded
recovery cannot guarantee that all undetected text or every uncertain region is
recovered. Extra passes cost time. Clear text skips the adaptive crop, while a
downscaled tall image can still receive its edge check. A failed crop preserves
other readings and leaves an explicit photo-review warning.

OCR spans retain bounded SDK confidence scores, including low-confidence
readings. These scores are hints, not calibrated correctness probabilities;
a high-scoring line can still contain an incorrect telephone digit. Text is
never filtered by confidence. The UI reports model initialization versus reuse,
total detection and recognition times (including the detail pass), local OCR
with QR work, and the latest server-request wall time including network. The
displayed processing total excludes time spent editing and prior failed
requests. These browser timings belong to the current session and are not
persisted as server measurements.

For photo analysis, the browser sends recognized text and bounded normalized
text-box coordinates to the API, never the image pixels or filename. The API
uses these coordinates to reorder only a substantial, unambiguous
two-column section column-first, preserving every OCR line and a blank boundary
for translation chunking. It can also add aligned English-test score pairs with
a review warning because OCR and geometry can still be wrong. Sparse tables
and missing coordinate hints are not forcibly reordered; the raw text remains
complete when the coordinate hint limit is reached. The semantic stage audits
recovered source lines against the English display fields after structured
extraction and any needed English-field repair. This can require additional
OpenAI calls and still cannot certify semantic accuracy or recover text OCR
missed. The photo UI requests an explicitly labeled partial English
interpretation when some source sections remain unreadable: supported facts
stay visible, unsafe claims are withheld, and English verification gaps identify
the affected sections. Users can retry or upload a clearer photo without typing
Korean. Strict API requests still reject an incomplete digest.

An image with no recognized text still returns its empty page and measured OCR
work to the photo flow. The API can then show an English unavailable result and
clearer-photo guidance instead of interrupting the browser before that response.
Unsupported browsers, invalid image decoding, and model/inference failures
remain errors; blank OCR does not create inferred facts.

Structured correction errors identify source text and a specific reason for
review. The user can select the indicated reading in its retained page text and
retry without running OCR again. Unchanged, uniquely matched lines retain their
positions when other lines are added or removed. In-place corrected lines can
keep approximate boxes but lose their old OCR confidence. Reordering source
lines clears position hints; ambiguous duplicate lines do not get guessed boxes.

The image tray contains pages of one notice, in their selected order. Use
**Upload another notice** to replace that tray when testing an independent
notice. Its previous image URLs and analysis result are cleared, and the next
request contains only the replacement notice's recognized text. **Add another
page** keeps the current notice and appends its next page. Independent notices
are not silently combined into one semantic result.

The browser also scans the image locally for HTTP(S) QR-code URLs with a
bundled decoder. Decoding is best-effort and may miss a code when the photo is
blurred, the code is small, or the scan exceeds its time budget. The tiled scan
checks a 1.5-second wall budget before each tile and decoder call. A synchronous
tile operation cannot be interrupted and can overshoot that budget; additional
tiles/codes then stop. URLs already decoded remain available, including when a
later decoder attempt fails. The separate 1.5-second wait after OCR limits
pending preparation; a bitmap that completes after that wait is closed without
starting another scan. A time-limit warning identifies potentially unread QR
destinations while confirming that printed text still follows the OCR path.
Decoded URLs are included in the text sent to the API;
no URL is opened automatically.

`qrMs` reports observed QR preparation and scanning wall time across the
selected images. It runs alongside OCR, so it must not be added to the processing
total. A null value means at least one QR task had not completed when the bounded
post-OCR wait ended. It does not certify that every tile or QR code was scanned.
