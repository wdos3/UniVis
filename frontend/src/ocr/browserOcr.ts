/// <reference types="vite/client" />

import type { OcrResult, OcrResultItem, PaddleOCR } from '@paddleocr/paddleocr-js'
import type { QRCode } from 'jsqr'
import type { BoundingBox, OcrSpan, SourceUnit } from '../types'
import { captureSourceUnits, makeSourceUnit, mergeSourceObservations } from '../ledger/sourceLedger'

type OcrEngine = Awaited<ReturnType<typeof PaddleOCR.create>>
type QrDecoder = typeof import('jsqr').default

interface DecodedQrUrl {
  url: string
  box: BoundingBox
}

interface QrDecodeResult {
  urls: DecodedQrUrl[]
  reachedTimeLimit: boolean
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
// A Promise timeout cannot interrupt synchronous decoding on the main thread.
const QR_SCAN_BUDGET_MS = 1500
// QR work runs alongside PaddleOCR and may add only this much time after OCR finishes.
const QR_EXTRA_WAIT_MS = 1500
const TEXT_DETECTION_MAX_SIDE = 2000
// Adaptive recovery plus one tall-image edge check keeps inference bounded.
const DETAIL_REGION_FRACTION = 0.4
const DETAIL_TEXT_HEIGHT_PX = 24
const DETAIL_CONFIDENCE_THRESHOLD = 0.85
const DETAIL_DETECTION_MAX_SIDE = 2800
const BOTTOM_EDGE_REGION_START = 0.84

export interface BrowserOcrMetrics {
  latencyMs: number
  initializationMs: number
  inferenceMs: number
  modelState: 'initialized' | 'reused'
  detectionMs: number | null
  recognitionMs: number | null
  qrMs?: number | null
  detailPasses: number
  recoveryWarnings: string[]
}

export interface BrowserOcrResult extends BrowserOcrMetrics {
  pages: BrowserOcrPage[]
}

export interface BrowserOcrPage {
  text: string
  spans: OcrSpan[]
  source_units?: SourceUnit[]
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
      throw new Error('Korean OCR could not load its local models.', { cause: error })
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

function pageText(result: OcrResult, page = 1, pass = 'initial'): BrowserOcrPage {
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
  return { text: lines.join('\n'), spans, source_units: captureSourceUnits(result, page, pass) }
}

function preservedPage(page: number): BrowserOcrPage {
  const unit = makeSourceUnit({ page, text: '', order: 0, box: { x: 0, y: 0, width: 1, height: 1 },
    id: `page-${page}-preserved-image`, pass: 'image_fallback' })
  unit.translation_status = 'source_crop'
  unit.english = 'The source page image is preserved; local OCR did not produce a reading.'
  return { text: '', spans: [], source_units: [unit] }
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
  return { text: [page.text, ...additions].filter(Boolean).join('\n'), spans,
    source_units: mergeSourceObservations(page.source_units ?? [], detail.source_units ?? []) }
}

function detailRegion(result: OcrResult): BoundingBox | null {
  const image = result.image
  if (!image?.width || !image.height) return null
  const detectionScale = Math.min(1, TEXT_DETECTION_MAX_SIDE / Math.max(image.width, image.height))
  const candidates = result.items.flatMap((item) => {
    const box = spanBox(item, image)
    if (!item.text.trim() || !box) return []
    const textHeight = box.height * image.height * detectionScale
    const smallText = detectionScale < 1 && textHeight < DETAIL_TEXT_HEIGHT_PX
    const uncertain = Number.isFinite(item.score) && item.score >= 0 && item.score < DETAIL_CONFIDENCE_THRESHOLD
    if (!smallText && !uncertain) return []
    const weight = (smallText ? Math.min(3, DETAIL_TEXT_HEIGHT_PX / textHeight) : 0)
      + (uncertain ? 1 + DETAIL_CONFIDENCE_THRESHOLD - item.score : 0)
    return [{ box, weight }]
  })
  if (!candidates.length) return null
  const wide = image.width > image.height
  let selected: BoundingBox | null = null
  let selectedWeight = 0
  for (const candidate of candidates) {
    const center = wide ? candidate.box.x + candidate.box.width / 2 : candidate.box.y + candidate.box.height / 2
    const candidateLength = wide ? candidate.box.width : candidate.box.height
    const fraction = Math.min(1, Math.max(DETAIL_REGION_FRACTION, candidateLength + 0.04))
    const start = Math.max(0, Math.min(1 - fraction, center - fraction / 2))
    const weight = candidates.reduce((sum, item) => {
      const itemCenter = wide ? item.box.x + item.box.width / 2 : item.box.y + item.box.height / 2
      return itemCenter >= start && itemCenter <= start + fraction ? sum + item.weight : sum
    }, 0)
    if (weight > selectedWeight) {
      selectedWeight = weight
      selected = wide
        ? { x: start, y: 0, width: fraction, height: 1 }
        : { x: 0, y: start, width: 1, height: fraction }
    }
  }
  return selected
}

function detailRegions(result: OcrResult): BoundingBox[] {
  const adaptive = detailRegion(result)
  const regions = adaptive ? [adaptive] : []
  const image = result.image
  if (!image?.width || !image.height || image.height <= TEXT_DETECTION_MAX_SIDE || image.height / image.width < 1.4) {
    return regions
  }
  // Initial detection can omit small edge text entirely, leaving no confidence
  // or box to select. Recheck that blind spot even when a noisier region wins.
  const bottomAlreadyCovered = adaptive && adaptive.x === 0 && adaptive.width === 1
    && adaptive.y <= BOTTOM_EDGE_REGION_START && adaptive.y + adaptive.height >= 1 - Number.EPSILON
  if (!bottomAlreadyCovered) {
    regions.push({ x: 0, y: BOTTOM_EDGE_REGION_START, width: 1, height: 1 - BOTTOM_EDGE_REGION_START })
  }
  return regions
}

async function recognizeDetail(
  file: File, fullResult: OcrResult, engine: OcrEngine, region: BoundingBox,
): Promise<OcrResult> {
  const image = fullResult.image
  if (!image?.width || !image.height) throw new Error('The original OCR result did not retain image coordinates.')
  const bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' })
  try {
    if (bitmap.width !== image.width || bitmap.height !== image.height) {
      throw new Error('The browser image orientation did not match OCR coordinates.')
    }
    const left = Math.floor(bitmap.width * region.x)
    const top = Math.floor(bitmap.height * region.y)
    const width = Math.min(bitmap.width - left, Math.ceil(bitmap.width * region.width))
    const height = Math.min(bitmap.height - top, Math.ceil(bitmap.height * region.height))
    const canvas = new OffscreenCanvas(width, height)
    const context = canvas.getContext('2d')
    if (!context) throw new Error('A detail image could not be prepared.')
    context.filter = 'contrast(1.2)'
    context.drawImage(bitmap, left, top, width, height, 0, 0, width, height)
    const crop = await canvas.convertToBlob({ type: 'image/png' })
    const results = await engine.predict(crop, {
      textDetLimitType: 'max', textDetLimitSideLen: DETAIL_DETECTION_MAX_SIDE,
      textDetThresh: 0.2, textDetBoxThresh: 0.25, textRecScoreThresh: 0,
    })
    if (results.length !== 1) throw new Error('Detail OCR returned an unexpected page count.')
    const result = results[0]
    if (result.image?.width !== width || result.image?.height !== height) {
      throw new Error('Detail OCR returned inconsistent coordinates.')
    }
    return {
      ...result,
      image,
      items: result.items.map((item) => ({ ...item, poly: item.poly?.map(([x, y]) => [x + left, y + top]) })),
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

async function decodeQrUrls(
  file: File, decoderPromise: Promise<QrDecoder | null>, signal: AbortSignal,
): Promise<QrDecodeResult> {
  let bitmap: ImageBitmap | undefined
  const urls = new Map<string, BoundingBox>()
  let reachedTimeLimit = false
  try {
    const decode = await decoderPromise
    if (!decode || signal.aborted) return { urls: [], reachedTimeLimit: signal.aborted }
    bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' })
    if (signal.aborted) return { urls: [], reachedTimeLimit: true }
    const scale = Math.min(1, QR_MAX_IMAGE_SIDE / Math.max(bitmap.width, bitmap.height))
    const width = Math.round(bitmap.width * scale)
    const height = Math.round(bitmap.height * scale)
    if (!width || !height) return { urls: [], reachedTimeLimit: false }
    const context = new OffscreenCanvas(width, height).getContext('2d', { willReadFrequently: true })
    if (!context) return { urls: [], reachedTimeLimit: false }
    context.drawImage(bitmap, 0, 0, width, height)

    const scanStartedAt = performance.now()
    const budgetExhausted = () => {
      if (signal.aborted || performance.now() - scanStartedAt >= QR_SCAN_BUDGET_MS) reachedTimeLimit = true
      return reachedTimeLimit
    }
    for (const top of tileStarts(height)) {
      if (budgetExhausted()) break
      for (const left of tileStarts(width)) {
        if (budgetExhausted()) break
        const tile = context.getImageData(left, top,
          Math.min(QR_TILE_SIZE, width - left), Math.min(QR_TILE_SIZE, height - top))
        for (let count = 0; count < QR_MAX_CODES_PER_TILE; count++) {
          if (budgetExhausted()) break
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
  } catch {
    // QR is best-effort; a later failure does not erase URLs already decoded.
  } finally {
    bitmap?.close()
  }
  return { urls: [...urls].map(([url, box]) => ({ url, box })), reachedTimeLimit }
}

async function qrUrlsWithoutDelayingOcr(
  promise: Promise<QrDecodeResult>, controller: AbortController,
): Promise<QrDecodeResult> {
  let timeout: ReturnType<typeof setTimeout> | undefined
  try {
    return await Promise.race([
      promise,
      new Promise<QrDecodeResult>((resolve) => {
        timeout = setTimeout(() => resolve({ urls: [], reachedTimeLimit: true }), QR_EXTRA_WAIT_MS)
      }),
    ])
  } finally {
    clearTimeout(timeout)
    controller.abort()
  }
}

export async function recognizeImages(
  files: File[],
  onProgress?: (completed: number, total: number) => void,
): Promise<BrowserOcrResult> {
  if (!isBrowserOcrSupported()) {
    onProgress?.(files.length, files.length)
    return { pages: files.map((_, index) => preservedPage(index + 1)), latencyMs: 0, initializationMs: 0, inferenceMs: 0,
      modelState: 'initialized', detectionMs: null, recognitionMs: null, qrMs: null, detailPasses: 0,
      recoveryWarnings: ['Local OCR is unavailable in this browser. Preserved page images remain available for automatic recovery.'] }
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
  let engine: OcrEngine | null = null
  let initializationWarning = ''
  try {
    engine = await getEngine()
  } catch (problem) {
    initializationWarning = problem instanceof Error ? problem.message : 'Local OCR initialization ended.'
  }
  const initializedAt = performance.now()
  const pages: BrowserOcrPage[] = []
  let remainingSpans = 600
  let detectionMs: number | null = 0
  let recognitionMs: number | null = 0
  let qrMs: number | null = 0
  let detailPasses = 0
  const recoveryWarnings: string[] = []
  if (initializationWarning) recoveryWarnings.push(`${initializationWarning} The original page is retained for automatic region recovery.`)

  function recordMetrics(result: OcrResult) {
    detectionMs = detectionMs !== null && Number.isFinite(result.metrics?.detMs) && result.metrics.detMs >= 0
      ? detectionMs + result.metrics.detMs : null
    recognitionMs = recognitionMs !== null && Number.isFinite(result.metrics?.recMs) && result.metrics.recMs >= 0
      ? recognitionMs + result.metrics.recMs : null
  }

  for (const [index, file] of files.entries()) {
    if (!engine) {
      pages.push(preservedPage(index + 1))
      detectionMs = null; recognitionMs = null
      onProgress?.(index + 1, files.length)
      continue
    }
    let result: OcrResult[]
    const qrController = new AbortController()
    const qrStartedAt = performance.now()
    let pageQrMs: number | null = null
    const qrUrlsPromise = decodeQrUrls(file, qrDecoderPromise, qrController.signal).finally(() => {
      pageQrMs = Math.round(performance.now() - qrStartedAt)
    })
    try {
      result = await engine.predict(file, {
        textDetLimitType: 'max',
        textDetLimitSideLen: TEXT_DETECTION_MAX_SIDE,
        // Keep uncertain text for source review; confidence never licenses deletion.
        textRecScoreThresh: 0,
      })
    } catch (error) {
      qrController.abort()
      recoveryWarnings.push(`Page ${index + 1}: local OCR ended (${error instanceof Error ? error.message : 'image decoding failure'}). Its source image is retained for automatic recovery.`)
      pages.push(preservedPage(index + 1))
      detectionMs = null; recognitionMs = null
      onProgress?.(index + 1, files.length)
      continue
    }
    if (result.length !== 1) {
      qrController.abort()
      recoveryWarnings.push(`Page ${index + 1}: OCR returned an unexpected page count. The original page remains available for automatic recovery.`)
      pages.push(preservedPage(index + 1))
      detectionMs = null; recognitionMs = null
      onProgress?.(index + 1, files.length)
      continue
    }
    let page = pageText(result[0], index + 1)
    if (!page.source_units?.length) {
      page = preservedPage(index + 1)
      recoveryWarnings.push(`Page ${index + 1}: no text was recognized locally. Automatic recovery will use the preserved page image.`)
    }
    recordMetrics(result[0])
    for (const region of detailRegions(result[0])) {
      try {
        const detail = await recognizeDetail(file, result[0], engine, region)
        detailPasses += 1
        recordMetrics(detail)
        page = addDetailText(page, pageText(detail, index + 1, `detail-${detailPasses}`))
      } catch {
        const location = region.y === BOTTOM_EDGE_REGION_START && region.height === 1 - BOTTOM_EDGE_REGION_START
          ? 'the lower edge' : 'a small or uncertain text region'
        recoveryWarnings.push(`Page ${index + 1}: ${location} is retained as source evidence after the additional OCR attempt ended.`)
      }
    }
    const qr = await qrUrlsWithoutDelayingOcr(qrUrlsPromise, qrController)
    qrMs = qrMs !== null && pageQrMs !== null ? qrMs + pageQrMs : null
    if (qr.reachedTimeLimit) {
      recoveryWarnings.push(`Page ${index + 1}: QR scan reached its time limit; some code destinations could not be read. Printed text was still analyzed.`)
    }
    if (qr.urls.length) {
      for (const { url, box } of qr.urls) {
        const qrText = `Decoded QR code URL (not opened): ${url}`
        page.text = page.text ? `${page.text}\n${qrText}` : qrText
        if (qrText.length <= 500) page.spans.push({ text: qrText, box })
        if (page.source_units) {
          const unit = makeSourceUnit({ page: index + 1, text: url, box, order: page.source_units.length, pass: 'qr' })
          page.source_units.push({ ...unit, english: `Decoded QR link (not opened): ${url}`, translation_provider: 'local',
            translation_status: 'literal', translation_source_ids: [unit.id] })
        }
      }
    }
    const spans = page.spans.slice(0, Math.min(250, remainingSpans))
    remainingSpans -= spans.length
    pages.push({ text: page.text, spans, source_units: page.source_units })
    onProgress?.(index + 1, files.length)
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
    qrMs,
    detailPasses,
    recoveryWarnings,
  }
}
