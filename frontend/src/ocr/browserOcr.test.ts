import { beforeEach, describe, expect, it, vi } from 'vitest'

const { createEngine, predict } = vi.hoisted(() => ({
  createEngine: vi.fn(),
  predict: vi.fn(),
}))

vi.mock('@paddleocr/paddleocr-js', () => ({
  PaddleOCR: { create: createEngine },
}))

async function moduleUnderTest() {
  vi.resetModules()
  return import('./browserOcr')
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.stubGlobal('Worker', class {})
  vi.stubGlobal('ImageBitmap', class {})
  vi.stubGlobal('createImageBitmap', vi.fn())
  vi.stubGlobal('OffscreenCanvas', class {})
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({} as CanvasRenderingContext2D)
  createEngine.mockResolvedValue({ predict })
})

describe('browser OCR', () => {
  it('reports unsupported browsers without worker/image bitmap APIs', async () => {
    const { isBrowserOcrSupported, recognizeImages } = await moduleUnderTest()
    expect(isBrowserOcrSupported()).toBe(true)
    vi.stubGlobal('createImageBitmap', undefined)
    expect(isBrowserOcrSupported()).toBe(false)
    await expect(recognizeImages([new File(['x'], 'notice.png')])).rejects.toThrow('cannot run local OCR')
  })

  it('uses local Korean and detection models and preserves page order', async () => {
    const { recognizeImages } = await moduleUnderTest()
    predict
      .mockResolvedValueOnce([{ items: [{ text: '  모집 대상 ', score: 0.98 }, { text: '2026년', score: 0.95 }] }])
      .mockResolvedValueOnce([{ items: [{ text: ' 신청 기간 ', score: 0.98 }] }])
    const progress = vi.fn()

    const result = await recognizeImages(
      [new File(['a'], 'first.png'), new File(['b'], 'second.png')],
      progress,
    )

    expect(createEngine).toHaveBeenCalledWith(expect.objectContaining({
      worker: true,
      textDetectionModelName: 'PP-OCRv5_mobile_det',
      textRecognitionModelName: 'korean_PP-OCRv5_mobile_rec',
      textDetectionModelAsset: { url: '/models/PP-OCRv5_mobile_det_onnx_infer.tar' },
      textRecognitionModelAsset: { url: '/models/korean_PP-OCRv5_mobile_rec_onnx_infer.tar' },
      ortOptions: expect.objectContaining({ backend: 'wasm', numThreads: 1 }),
    }))
    expect(createEngine.mock.calls[0][0].ortOptions).toHaveProperty(
      'wasmPaths', new URL('/ort/', window.location.origin).href,
    )
    expect(predict).toHaveBeenCalledTimes(2)
    expect(result.pages).toEqual([{ text: '모집 대상\n2026년', spans: [] }, { text: '신청 기간', spans: [] }])
    expect(result.latencyMs).toBeGreaterThanOrEqual(0)
    expect(progress.mock.calls).toEqual([[0, 2], [1, 2], [2, 2]])
  })

  it('retains normalized OCR positions for table reconstruction', async () => {
    const { recognizeImages } = await moduleUnderTest()
    predict.mockResolvedValue([{ image: { width: 1000, height: 2000 }, items: [
      { text: 'TOEIC', score: 1, poly: [[100, 200], [200, 200], [200, 240], [100, 240]] },
      { text: '800 이상', score: 0.9, poly: [[100, 300], [200, 300], [200, 340], [100, 340]] },
    ] }])

    const result = await recognizeImages([new File(['x'], 'table.png')])

    expect(result.pages[0].text).toBe('TOEIC\n800 이상')
    expect(result.pages[0].spans.map((span) => span.text)).toEqual(['TOEIC', '800 이상'])
    expect(result.pages[0].spans[0].box.x).toBeCloseTo(0.1)
    expect(result.pages[0].spans[0].box.y).toBeCloseTo(0.1)
    expect(result.pages[0].spans[1].box.y).toBeCloseTo(0.15)
  })

  it('rejects blank OCR results', async () => {
    const { recognizeImages } = await moduleUnderTest()
    predict.mockResolvedValue([{ items: [{ text: '   ', score: 0.1 }] }])
    await expect(recognizeImages([new File(['x'], 'blank.png')])).rejects.toThrow('No text was recognized')
  })

  it('wraps an image decoding or inference failure with the page number', async () => {
    const { recognizeImages } = await moduleUnderTest()
    predict.mockRejectedValue(new Error('decode failed'))
    await expect(recognizeImages([new File(['x'], 'bad.heic')])).rejects.toThrow('Could not read image 1')
  })

  it('can retry model initialization after a transient failure', async () => {
    const { recognizeImages } = await moduleUnderTest()
    createEngine.mockRejectedValueOnce(new Error('network')).mockResolvedValueOnce({ predict })
    predict.mockResolvedValue([{ items: [{ text: 'ok', score: 1 }] }])
    const files = [new File(['x'], 'notice.png')]

    await expect(recognizeImages(files)).rejects.toThrow('could not load its local models')
    await expect(recognizeImages(files)).resolves.toMatchObject({ pages: [{ text: 'ok' }] })
    expect(createEngine).toHaveBeenCalledTimes(2)
  })
})
