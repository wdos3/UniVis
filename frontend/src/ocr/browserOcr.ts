/// <reference types="vite/client" />

import type { OcrResult, OcrResultItem, PaddleOCR } from '@paddleocr/paddleocr-js'
import type { QRCode } from 'jsqr'
import type { BoundingBox, OcrSpan } from '../types'

type OcrEngine = Awaited<ReturnType<typeof PaddleOCR.create>>
type QrDecoder = typeof import('jsqr').default

interface DecodedQrUrl {
  url: string
  box: BoundingBox
}

interface QrBounds {
  left: number
  right: number
  top: number
  bottom: number
}

// A dense QR code in a phone photo was unreadable at 2400px; tiled 3500px kept it legible.
const QR_MAX_IMAGE_SIDE = 3500
const QR_TILE_SIZE = 1000
const QR_TILE_STEP = 800
const QR_MAX_CODES_PER_TILE = 4
// QR work runs alongside PaddleOCR and may add only this much time after OCR finishes.
const QR_EXTRA_WAIT_MS = 1500

export interface BrowserOcrResult {
  pages: BrowserOcrPage[]
  latencyMs: number
  initializationMs: number
  inferenceMs: number
}

export interface BrowserOcrPage {
  text: string
  spans: OcrSpan[]
}

let enginePromise: Promise<OcrEngine> | undefined

export function isBrowserOcrSupported(): boolean {
  if (typeof Worker === 'undefined'
    || typeof WebAssembly === 'undefined'
    || typeof ImageBitmap === 'undefined'
    || typeof createImageBitmap !== 'function'
    || typeof OffscreenCanvas === 'undefined'
    || typeof document === 'undefined'
    || window.location.protocol === 'file:') {
    return false
  }
  try {
    return document.createElement('canvas').getContext('2d') !== null
  } catch {
    return false
  }
}

async function getEngine(): Promise<OcrEngine> {
  if (!enginePromise) {
    enginePromise = import('@paddleocr/paddleocr-js').then(({ PaddleOCR }) => PaddleOCR.create({
      worker: true,
      textDetectionModelName: 'PP-OCRv5_mobile_det',
      textDetectionModelAsset: {
        url: `${import.meta.env.BASE_URL}models/PP-OCRv5_mobile_det_onnx_infer.tar`,
      },
      textRecognitionModelName: 'korean_PP-OCRv5_mobile_rec',
      textRecognitionModelAsset: {
        url: `${import.meta.env.BASE_URL}models/korean_PP-OCRv5_mobile_rec_onnx_infer.tar`,
      },
      textRecognitionBatchSize: 4,
      ortOptions: {
        backend: 'wasm',
        wasmPaths: new URL(`${import.meta.env.BASE_URL}ort/`, window.location.origin).href,
        numThreads: 1,
        simd: true,
      },
    })).catch((error: unknown) => {
      enginePromise = undefined
      throw new Error('Korean OCR could not load its local models. Check your connection and try again.', { cause: error })
    })
  }
  return enginePromise
}

function spanBox(item: OcrResultItem, image: OcrResult['image']): BoundingBox | null {
  if (!item.poly?.length || !image?.width || !image?.height) return null
  const xs = item.poly.map((point) => point[0] / image.width)
  const ys = item.poly.map((point) => point[1] / image.height)
  if (![...xs, ...ys].every(Number.isFinite)) return null
  const x = Math.max(0, Math.min(1, Math.min(...xs)))
  const y = Math.max(0, Math.min(1, Math.min(...ys)))
  const right = Math.max(0, Math.min(1, Math.max(...xs)))
  const bottom = Math.max(0, Math.min(1, Math.max(...ys)))
  if (right <= x || bottom <= y) return null
  return { x, y, width: right - x, height: bottom - y }
}

function pageText(result: OcrResult): BrowserOcrPage {
  const lines: string[] = []
  const spans: BrowserOcrPage['spans'] = []
  for (const item of result.items) {
    const text = item.text.trim()
    if (!text) continue
    lines.push(text)
    const box = spanBox(item, result.image)
    if (box && text.length <= 500 && !text.includes('\n')) spans.push({ text, box })
  }
  return { text: lines.join('\n'), spans }
}

function webUrl(rawValue: string): string | null {
  const value = rawValue.trim()
  if (!value || value.length > 2048 || [...value].some((character) => {
    const code = character.charCodeAt(0)
    return code < 32 || code === 127
  })) return null
  try {
    const parsed = new URL(value)
    if (!['http:', 'https:'].includes(parsed.protocol) || !parsed.hostname || parsed.username || parsed.password) return null
    return value
  } catch {
    return null
  }
}

function tileStarts(length: number): number[] {
  if (length <= QR_TILE_SIZE) return [0]
  const starts: number[] = []
  for (let start = 0; start < length - QR_TILE_SIZE; start += QR_TILE_STEP) starts.push(start)
  starts.push(length - QR_TILE_SIZE)
  return [...new Set(starts)]
}

function qrBounds(code: QRCode): QrBounds | null {
  const corners = [code.location.topLeftCorner, code.location.topRightCorner,
    code.location.bottomLeftCorner, code.location.bottomRightCorner]
  if (!corners.every(({ x, y }) => Number.isFinite(x) && Number.isFinite(y))) return null
  return {
    left: Math.min(...corners.map(({ x }) => x)),
    right: Math.max(...corners.map(({ x }) => x)),
    top: Math.min(...corners.map(({ y }) => y)),
    bottom: Math.max(...corners.map(({ y }) => y)),
  }
}

function maskQr(image: ImageData, bounds: QrBounds): void {
  const left = Math.max(0, Math.floor(bounds.left - 15))
  const right = Math.min(image.width, Math.ceil(bounds.right + 15))
  const top = Math.max(0, Math.floor(bounds.top - 15))
  const bottom = Math.min(image.height, Math.ceil(bounds.bottom + 15))
  for (let y = top; y < bottom; y++) {
    for (let x = left; x < right; x++) {
      const pixel = (y * image.width + x) * 4
      image.data[pixel] = 255
      image.data[pixel + 1] = 255
      image.data[pixel + 2] = 255
      image.data[pixel + 3] = 255
    }
  }
}

async function decodeQrUrls(file: File, decoderPromise: Promise<QrDecoder | null>): Promise<DecodedQrUrl[]> {
  let bitmap: ImageBitmap | undefined
  try {
    const decode = await decoderPromise
    if (!decode) return []
    bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' })
    const scale = Math.min(1, QR_MAX_IMAGE_SIDE / Math.max(bitmap.width, bitmap.height))
    const width = Math.round(bitmap.width * scale)
    const height = Math.round(bitmap.height * scale)
    if (!width || !height) return []
    const context = new OffscreenCanvas(width, height).getContext('2d', { willReadFrequently: true })
    if (!context) return []
    context.drawImage(bitmap, 0, 0, width, height)

    const urls = new Map<string, BoundingBox>()
    for (const top of tileStarts(height)) {
      for (const left of tileStarts(width)) {
        const tile = context.getImageData(left, top,
          Math.min(QR_TILE_SIZE, width - left), Math.min(QR_TILE_SIZE, height - top))
        for (let count = 0; count < QR_MAX_CODES_PER_TILE; count++) {
          const code = decode(tile.data, tile.width, tile.height, { inversionAttempts: 'dontInvert' })
          if (!code) break
          const url = webUrl(code.data)
          const bounds = qrBounds(code)
          if (!bounds) break
          const x = Math.max(0, (left + bounds.left) / width)
          const y = Math.max(0, (top + bounds.top) / height)
          const right = Math.min(1, (left + bounds.right) / width)
          const bottom = Math.min(1, (top + bounds.bottom) / height)
          if (url && right > x && bottom > y && !urls.has(url)) {
            urls.set(url, { x, y, width: right - x, height: bottom - y })
          }
          maskQr(tile, bounds)
        }
      }
    }
    return [...urls].map(([url, box]) => ({ url, box }))
  } catch {
    // QR decoding is best-effort. The image still gets its normal OCR result.
    return []
  } finally {
    bitmap?.close()
  }
}

async function qrUrlsWithoutDelayingOcr(promise: Promise<DecodedQrUrl[]>): Promise<DecodedQrUrl[]> {
  let timeout: ReturnType<typeof setTimeout> | undefined
  try {
    return await Promise.race([
      promise,
      new Promise<DecodedQrUrl[]>((resolve) => {
        timeout = setTimeout(() => resolve([]), QR_EXTRA_WAIT_MS)
      }),
    ])
  } finally {
    clearTimeout(timeout)
  }
}

export async function recognizeImages(
  files: File[],
  onProgress?: (completed: number, total: number) => void,
): Promise<BrowserOcrResult> {
  if (!isBrowserOcrSupported()) {
    throw new Error('This browser cannot run local OCR. Use a recent browser with WebAssembly and image bitmap support.')
  }
  if (files.length === 0) {
    throw new Error('Choose at least one image to analyze.')
  }

  const startedAt = performance.now()
  onProgress?.(0, files.length)
  const qrDecoderPromise: Promise<QrDecoder | null> = import('jsqr')
    .then(({ default: decoder }) => decoder)
    .catch(() => null)
  const engine = await getEngine()
  const initializedAt = performance.now()
  const pages: BrowserOcrPage[] = []
  let remainingSpans = 600

  for (const [index, file] of files.entries()) {
    let result: OcrResult[]
    const qrUrlsPromise = decodeQrUrls(file, qrDecoderPromise)
    try {
      result = await engine.predict(file, {
        textDetLimitType: 'max',
        textDetLimitSideLen: 2000,
      })
    } catch (error) {
      throw new Error(`Could not read image ${index + 1}. Use a JPEG, PNG, or WebP image supported by this browser.`, { cause: error })
    }
    if (result.length !== 1) {
      throw new Error(`OCR returned ${result.length} pages for image ${index + 1}; expected one.`)
    }
    const page = pageText(result[0])
    const qrUrls = await qrUrlsWithoutDelayingOcr(qrUrlsPromise)
    if (qrUrls.length) {
      for (const { url, box } of qrUrls) {
        const qrText = `Decoded QR code URL (not opened): ${url}`
        page.text = page.text ? `${page.text}\n${qrText}` : qrText
        if (qrText.length <= 500) page.spans.push({ text: qrText, box })
      }
    }
    const spans = page.spans.slice(0, Math.min(250, remainingSpans))
    remainingSpans -= spans.length
    pages.push({ text: page.text, spans })
    onProgress?.(index + 1, files.length)
  }

  if (pages.every((page) => page.text.length === 0)) {
    throw new Error('No text was recognized in these images. Try a sharper, well-lit photo.')
  }

  const finishedAt = performance.now()
  return {
    pages,
    latencyMs: Math.round(finishedAt - startedAt),
    initializationMs: Math.round(initializedAt - startedAt),
    inferenceMs: Math.round(finishedAt - initializedAt),
  }
}
