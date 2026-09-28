/// <reference types="vite/client" />

import type { OcrResult, PaddleOCR } from '@paddleocr/paddleocr-js'

type OcrEngine = Awaited<ReturnType<typeof PaddleOCR.create>>

export interface BrowserOcrResult {
  pages: { text: string }[]
  latencyMs: number
  initializationMs: number
  inferenceMs: number
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

function pageText(result: OcrResult): string {
  return result.items
    .map((item) => item.text.trim())
    .filter(Boolean)
    .join('\n')
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
  const engine = await getEngine()
  const initializedAt = performance.now()
  const pages: { text: string }[] = []

  for (const [index, file] of files.entries()) {
    let result: OcrResult[]
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
    pages.push({ text: pageText(result[0]) })
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
