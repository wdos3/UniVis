import { beforeEach, describe, expect, it, vi } from 'vitest'

const { createEngine, predict, decodeQr } = vi.hoisted(() => ({
  createEngine: vi.fn(),
  predict: vi.fn(),
  decodeQr: vi.fn(),
}))

vi.mock('@paddleocr/paddleocr-js', () => ({
  PaddleOCR: { create: createEngine },
}))
vi.mock('jsqr', () => ({ default: decodeQr }))

async function moduleUnderTest() {
  vi.resetModules()
  return import('./browserOcr')
}

beforeEach(() => {
  vi.resetAllMocks()
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

  it('appends multiple locally decoded web URLs from one image without opening them', async () => {
    const code = (data: string, x: number) => ({ data, location: {
      topLeftCorner: { x, y: 50 }, topRightCorner: { x: x + 40, y: 50 },
      bottomLeftCorner: { x, y: 90 }, bottomRightCorner: { x: x + 40, y: 90 },
    } })
    decodeQr.mockReturnValueOnce(code('https://m.site.naver.com/2eoT9', 50))
      .mockReturnValueOnce(code('https://splus.sogang.ac.kr/ko/module/eco/program/view/443', 150))
      .mockReturnValueOnce(code('javascript:alert(1)', 250))
      .mockReturnValue(null)
    const close = vi.fn()
    const createBitmap = vi.fn().mockResolvedValue({ width: 300, height: 400, close })
    const drawImage = vi.fn()
    const getImageData = vi.fn((_x: number, _y: number, width: number, height: number) => ({
      width, height, data: new Uint8ClampedArray(width * height * 4),
    }))
    class LocalCanvas {
      getContext() { return { drawImage, getImageData } }
    }
    vi.stubGlobal('OffscreenCanvas', LocalCanvas)
    vi.stubGlobal('createImageBitmap', createBitmap)
    predict.mockResolvedValue([{ image: { width: 300, height: 400 }, items: [{
      text: '지원 방법', score: 1, poly: [[0, 0], [120, 0], [120, 40], [0, 40]],
    }] }])
    const { recognizeImages } = await moduleUnderTest()
    const file = new File(['image'], 'notice.png')

    const result = await recognizeImages([file])

    expect(result.pages[0].text).toBe('지원 방법\n'
      + 'Decoded QR code URL (not opened): https://m.site.naver.com/2eoT9\n'
      + 'Decoded QR code URL (not opened): https://splus.sogang.ac.kr/ko/module/eco/program/view/443')
    expect(result.pages[0].spans.map((span) => span.text)).toEqual([
      '지원 방법',
      'Decoded QR code URL (not opened): https://m.site.naver.com/2eoT9',
      'Decoded QR code URL (not opened): https://splus.sogang.ac.kr/ko/module/eco/program/view/443',
    ])
    expect(result.pages[0].spans[1].box.x).toBeCloseTo(50 / 300)
    expect(result.pages[0].spans[1].box.y).toBeCloseTo(50 / 400)
    expect(result.pages[0].spans[2].box.x).toBeCloseTo(150 / 300)
    expect(result.pages[0].text.split('\n')).toHaveLength(result.pages[0].spans.length)
    expect(createBitmap).toHaveBeenCalledWith(file, { imageOrientation: 'from-image' })
    expect(drawImage).toHaveBeenCalledTimes(1)
    expect(decodeQr).toHaveBeenCalledTimes(4)
    expect(close).toHaveBeenCalledTimes(1)
  })

  it('keeps text OCR usable when QR decoding fails', async () => {
    decodeQr.mockImplementation(() => { throw new Error('decoder failed') })
    const close = vi.fn()
    const createBitmap = vi.fn().mockResolvedValue({ width: 300, height: 400, close })
    class LocalCanvas {
      getContext() { return { drawImage: vi.fn(), getImageData: () => ({
        width: 300, height: 400, data: new Uint8ClampedArray(300 * 400 * 4),
      }) } }
    }
    vi.stubGlobal('OffscreenCanvas', LocalCanvas)
    vi.stubGlobal('createImageBitmap', createBitmap)
    predict.mockResolvedValue([{ items: [{ text: '모집 기간', score: 1 }] }])
    const { recognizeImages } = await moduleUnderTest()

    const result = await recognizeImages([new File(['x'], 'notice.png')])

    expect(result.pages[0].text).toBe('모집 기간')
    expect(close).toHaveBeenCalledTimes(1)
  })

  it('rejects unsafe or malformed decoded destinations', async () => {
    const code = (data: string) => ({ data, location: {
      topLeftCorner: { x: 50, y: 50 }, topRightCorner: { x: 90, y: 50 },
      bottomLeftCorner: { x: 50, y: 90 }, bottomRightCorner: { x: 90, y: 90 },
    } })
    decodeQr.mockReturnValueOnce(code('https://user:secret@example.com/private'))
      .mockReturnValueOnce(code('https://example.com/line\nbreak'))
      .mockReturnValueOnce(code('file:///C:/private'))
      .mockReturnValue(null)
    vi.stubGlobal('createImageBitmap', vi.fn().mockResolvedValue({ width: 300, height: 400, close: vi.fn() }))
    class LocalCanvas {
      getContext() { return { drawImage: vi.fn(), getImageData: () => ({
        width: 300, height: 400, data: new Uint8ClampedArray(300 * 400 * 4),
      }) } }
    }
    vi.stubGlobal('OffscreenCanvas', LocalCanvas)
    predict.mockResolvedValue([{ items: [{ text: '연구 주제', score: 1 }] }])
    const { recognizeImages } = await moduleUnderTest()

    const result = await recognizeImages([new File(['x'], 'notice.png')])

    expect(result.pages[0].text).toBe('연구 주제')
  })

  it('limits any additional wait for a slow QR decoder', async () => {
    vi.stubGlobal('createImageBitmap', vi.fn().mockReturnValue(new Promise(() => {})))
    predict.mockResolvedValue([{ items: [{ text: '신청 기간', score: 1 }] }])
    const { recognizeImages } = await moduleUnderTest()
    vi.useFakeTimers()
    try {
      const resultPromise = recognizeImages([new File(['x'], 'notice.png')])
      await vi.advanceTimersByTimeAsync(2000)
      const result = await resultPromise
      expect(result.pages[0].text).toBe('신청 기간')
    } finally {
      vi.useRealTimers()
    }
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
