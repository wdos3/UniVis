# Browser OCR assets

`browserOcr.ts` uses the official Apache-2.0 PaddleOCR.js 0.4.2 SDK, PP-OCRv5 mobile text detection, and its Korean recognition model (which also supports English). Models load lazily from the same origin; no image is uploaded for OCR. The first run downloads approximately 18.4 MB of models plus the ONNX Runtime WASM binary. Subsequent requests can use browser HTTP caching.

The two uncompressed model archives in `frontend/public/models/` were downloaded from PaddlePaddle's official model host on 2026-09-28. Their model metadata declares Apache-2.0; the license copy is in `frontend/public/models/LICENSE`:

| Asset | Source | SHA-256 |
| --- | --- | --- |
| `PP-OCRv5_mobile_det_onnx_infer.tar` | <https://paddle-model-ecology.bj.bcebos.com/paddlex/official_inference_model/paddle3.0.0/PP-OCRv5_mobile_det_onnx_infer.tar> | `781056046c9ed77a15c94681605db6a0f62317c2e9cce6931c71da2478d4bc30` |
| `korean_PP-OCRv5_mobile_rec_onnx_infer.tar` | <https://paddle-model-ecology.bj.bcebos.com/paddlex/official_inference_model/paddle3.0.0/korean_PP-OCRv5_mobile_rec_onnx_infer.tar> | `568ed8b43a260adc9f484d92105e425ea8cddf8ce16940c177bc12864cfb0eb0` |

The PaddleOCR.js worker bundles ONNX Runtime Web 1.24.3, so `package.json`
pins that transitive version. `frontend/public/ort/` contains the matching
standard, JSPI, and JSEP `.mjs`/`.wasm` pairs copied from that installed
package. `browserOcr.ts` passes an absolute same-origin `wasmPaths` URL; a
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
