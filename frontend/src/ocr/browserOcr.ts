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
const TEXT_DETECTION_MAX_SIDE = 2000
// Small angled footer text needs a less restrictive detector than a full poster.
const DETAIL_REGION_START = 0.84
const DETAIL_DETECTION_MAX_SIDE = 2800

export interface BrowserOcrMetrics {
  latencyMs: number
  initializationMs: number
  inferenceMs: number
  modelState: 'initialized' | 'reused'
  detectionMs: number | null
  recognitionMs: number | null
  detailPasses: number
  recoveryWarnings: string[]
}

export interface BrowserOcrResult extends BrowserOcrMetrics {
  pages: BrowserOcrPage[]
}

export interface BrowserOcrPage {
  text: string
  spans: OcrSpan[]
}

let enginePromise: Promise<OcrEngine> | undefined
let engineReady = false

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
    })).then((engine) => {
      engineReady = true
      return engine
    }).catch((error: unknown) => {
      enginePromise = undefined
      engineReady = false
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
    if (box && text.length <= 500 && !text.includes('\n')) {
      const confidence = Number.isFinite(item.score) && item.score >= 0 && item.score <= 1 ? item.score : undefined
      spans.push({ text, box, ...(confidence !== undefined ? { confidence } : {}) })
    }
  }
  return { text: lines.join('\n'), spans }
}

function sameTextRegion(left: OcrSpan, right: OcrSpan): boolean {
  if (left.text !== right.text) return false
  const overlapWidth = Math.max(0, Math.min(left.box.x + left.box.width, right.box.x + right.box.width) - Math.max(left.box.x, right.box.x))
  const overlapHeight = Math.max(0, Math.min(left.box.y + left.box.height, right.box.y + right.box.height) - Math.max(left.box.y, right.box.y))
  const smallerArea = Math.min(left.box.width * left.box.height, right.box.width * right.box.height)
  return overlapWidth * overlapHeight >= smallerArea * 0.35
}

function addDetailText(page: BrowserOcrPage, detail: BrowserOcrPage): BrowserOcrPage {
  const spans = [...page.spans]
  const additions: string[] = []
  const detailLines = detail.text.split('\n')
  const spansByText = new Map<string, OcrSpan[]>()
  const lineCounts = new Map<string, number>()
  detailLines.forEach((text) => lineCounts.set(text, (lineCounts.get(text) ?? 0) + 1))
  detail.spans.forEach((span) => spansByText.set(span.text, [...(spansByText.get(span.text) ?? []), span]))
  const fullyPositionedTexts = new Set([...spansByText]
    .filter(([text, textSpans]) => textSpans.length === lineCounts.get(text))
    .map(([text]) => text))
  for (const text of detailLines) {
    const span = fullyPositionedTexts.has(text) ? spansByText.get(text)?.shift() : undefined
    const previousIndex = span ? spans.findIndex((candidate) => sameTextRegion(candidate, span)) : -1
    if (previousIndex >= 0 && span) {
      if ((span.confidence ?? 0) > (spans[previousIndex].confidence ?? 0)) spans[previousIndex] = span
      continue
    }
    // Different readings of an overlapping line remain evidence for correction.
    additions.push(text)
    if (span) spans.push(span)
  }
  return { text: [page.text, ...additions].filter(Boolean).join('\n'), spans }
}

async function recognizeFooter(file: File, fullResult: OcrResult, engine: OcrEngine): Promise<OcrResult | null> {
  const image = fullResult.image
  if (!image?.width || !image.height || image.height <= TEXT_DETECTION_MAX_SIDE || image.height / image.width < 1.4) return null
  const bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' })
  try {
    if (bitmap.width !== image.width || bitmap.height !== image.height) {
      throw new Error('The browser image orientation did not match OCR coordinates.')
    }
    const top = Math.floor(bitmap.height * DETAIL_REGION_START)
    const height = bitmap.height - top
    const canvas = new OffscreenCanvas(bitmap.width, height)
    const context = canvas.getContext('2d')
    if (!context) throw new Error('A detail image could not be prepared.')
    context.filter = 'contrast(1.2)'
    context.drawImage(bitmap, 0, top, bitmap.width, height, 0, 0, bitmap.width, height)
    const crop = await canvas.convertToBlob({ type: 'image/png' })
    const results = await engine.predict(crop, {
      textDetLimitType: 'max', textDetLimitSideLen: DETAIL_DETECTION_MAX_SIDE,
      textDetThresh: 0.2, textDetBoxThresh: 0.25, textRecScoreThresh: 0,
    })
    if (results.length !== 1) throw new Error('Detail OCR returned an unexpected page count.')
    const result = results[0]
    if (result.image?.width !== bitmap.width || result.image?.height !== height) {
      throw new Error('Detail OCR returned inconsistent coordinates.')
    }
    return {
      ...result,
      image,
      items: result.items.map((item) => ({ ...item, poly: item.poly?.map(([x, y]) => [x, y + top]) })),
    }
  } finally {
    bitmap.close()
  }
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
  const modelState = engineReady ? 'reused' : 'initialized'
  onProgress?.(0, files.length)
  const qrDecoderPromise: Promise<QrDecoder | null> = import('jsqr')
    .then(({ default: decoder }) => decoder)
    .catch(() => null)
  const engine = await getEngine()
  const initializedAt = performance.now()
  const pages: BrowserOcrPage[] = []
  let remainingSpans = 600
  let detectionMs: number | null = 0
  let recognitionMs: number | null = 0
  let detailPasses = 0
  const recoveryWarnings: string[] = []

  function recordMetrics(result: OcrResult) {
    detectionMs = detectionMs !== null && Number.isFinite(result.metrics?.detMs) && result.metrics.detMs >= 0
      ? detectionMs + result.metrics.detMs : null
    recognitionMs = recognitionMs !== null && Number.isFinite(result.metrics?.recMs) && result.metrics.recMs >= 0
      ? recognitionMs + result.metrics.recMs : null
  }

  for (const [index, file] of files.entries()) {
    let result: OcrResult[]
    const qrUrlsPromise = decodeQrUrls(file, qrDecoderPromise)
    try {
      result = await engine.predict(file, {
        textDetLimitType: 'max',
        textDetLimitSideLen: TEXT_DETECTION_MAX_SIDE,
        // Keep uncertain text for source review; confidence never licenses deletion.
        textRecScoreThresh: 0,
      })
    } catch (error) {
      throw new Error(`Could not read image ${index + 1}. Use a JPEG, PNG, or WebP image supported by this browser.`, { cause: error })
    }
    if (result.length !== 1) {
      throw new Error(`OCR returned ${result.length} pages for image ${index + 1}; expected one.`)
    }
    let page = pageText(result[0])
    recordMetrics(result[0])
    try {
      const detail = await recognizeFooter(file, result[0], engine)
      if (detail) {
        detailPasses += 1
        recordMetrics(detail)
        page = addDetailText(page, pageText(detail))
      }
    } catch {
      recoveryWarnings.push(`Page ${index + 1}: small text in the lower part could not be checked. Compare the footer with the photo, especially contact details, before relying on the result.`)
    }
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
    modelState,
    detectionMs: detectionMs === null ? null : Math.round(detectionMs),
    recognitionMs: recognitionMs === null ? null : Math.round(recognitionMs),
    detailPasses,
    recoveryWarnings,
  }
}
