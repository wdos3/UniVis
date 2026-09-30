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
    expect(result.pages[0].spans.map((span) => span.confidence)).toEqual([1, 0.9])
  })

  it('retains uncertain text and confidence instead of discarding low-score lines', async () => {
    const { recognizeImages } = await moduleUnderTest()
    predict.mockResolvedValue([{ image: { width: 1000, height: 1000 }, items: [
      { text: '기간입C이끼지', score: 0.556, poly: [[10, 10], [200, 10], [200, 40], [10, 40]] },
      { text: '문의 02-710-25n0', score: 0.957, poly: [[10, 50], [200, 50], [200, 90], [10, 90]] },
    ] }])
    const result = await recognizeImages([new File(['x'], 'notice.png')])
    expect(predict).toHaveBeenCalledWith(expect.any(File), expect.objectContaining({ textRecScoreThresh: 0 }))
    expect(result.pages[0].text).toBe('기간입C이끼지\n문의 02-710-25n0')
    expect(result.pages[0].spans.map((span) => span.confidence)).toEqual([0.556, 0.957])
    expect(result.detectionMs).toBeNull()
    expect(result.recognitionMs).toBeNull()
  })

  it('recovers small footer text in a local detail pass and maps it back to the photo', async () => {
    const close = vi.fn()
    vi.stubGlobal('createImageBitmap', vi.fn().mockResolvedValue({ width: 2296, height: 4080, close }))
    const drawImage = vi.fn()
    const crop = new Blob(['local footer pixels'], { type: 'image/png' })
    const convertToBlob = vi.fn().mockResolvedValue(crop)
    class DetailCanvas {
      getContext() { return { drawImage } }
      convertToBlob = convertToBlob
    }
    vi.stubGlobal('OffscreenCanvas', DetailCanvas)
    predict.mockResolvedValueOnce([{ image: { width: 2296, height: 4080 }, metrics: { detMs: 100, recMs: 200 }, items: [
      { text: '모집 대상', score: 0.99, poly: [[100, 100], [700, 100], [700, 180], [100, 180]] },
      { text: '장학금 형태로 지급', score: 0.96, poly: [[100, 3500], [700, 3500], [700, 3580], [100, 3580]] },
      { text: '문의 02-710-25n0', score: 0.95, poly: [[100, 3800], [1200, 3800], [1200, 3880], [100, 3880]] },
    ] }]).mockResolvedValueOnce([{ image: { width: 2296, height: 653 }, metrics: { detMs: 50, recMs: 75 }, items: [
      { text: '장학금 형태로 지급', score: 0.999, poly: [[100, 73], [700, 73], [700, 153], [100, 153]] },
      { text: '문의 02-710-2500 convedu@sogang.ac.kr', score: 0.98, poly: [[100, 373], [1200, 373], [1200, 453], [100, 453]] },
    ] }])
    const { recognizeImages } = await moduleUnderTest()

    const result = await recognizeImages([new File(['private photo'], 'notice.png')])

    expect(predict.mock.calls[1][0]).toBe(crop)
    expect(drawImage).toHaveBeenCalledWith(expect.anything(), 0, 3427, 2296, 653, 0, 0, 2296, 653)
    expect(predict.mock.calls[1][1]).toMatchObject({ textDetLimitSideLen: 2800, textDetThresh: 0.2, textDetBoxThresh: 0.25 })
    expect(result.pages[0].text.split('\n')).toEqual([
      '모집 대상', '장학금 형태로 지급', '문의 02-710-25n0', '문의 02-710-2500 convedu@sogang.ac.kr',
    ])
    expect(result.pages[0].spans[1].confidence).toBe(0.999)
    expect(result.pages[0].spans[3].box.y).toBeCloseTo(3800 / 4080)
    expect(result).toMatchObject({ detailPasses: 1, detectionMs: 150, recognitionMs: 275, recoveryWarnings: [] })
    expect(close).toHaveBeenCalled()
  })

  it('keeps the first reading and reports when small-text recovery cannot complete', async () => {
    vi.stubGlobal('createImageBitmap', vi.fn().mockRejectedValue(new Error('decode failed')))
    predict.mockResolvedValue([{ image: { width: 2000, height: 4000 }, items: [
      { text: '신청 기간', score: 0.99, poly: [[100, 100], [700, 100], [700, 180], [100, 180]] },
    ] }])
    const { recognizeImages } = await moduleUnderTest()
    const result = await recognizeImages([new File(['x'], 'notice.png')])
    expect(result.pages[0].text).toBe('신청 기간')
    expect(result.recoveryWarnings).toEqual([expect.stringContaining('Page 1: small text in the lower part could not be checked')])
    expect(predict).toHaveBeenCalledOnce()
  })

  it('keeps repeated footer text when its positions differ', async () => {
    vi.stubGlobal('createImageBitmap', vi.fn().mockResolvedValue({ width: 1000, height: 4000, close: vi.fn() }))
    class DetailCanvas {
      getContext() { return { drawImage: vi.fn() } }
      async convertToBlob() { return new Blob(['footer'], { type: 'image/png' }) }
    }
    vi.stubGlobal('OffscreenCanvas', DetailCanvas)
    predict.mockResolvedValueOnce([{ image: { width: 1000, height: 4000 }, items: [
      { text: '지원하기', score: 0.99, poly: [[100, 3600], [300, 3600], [300, 3680], [100, 3680]] },
    ] }]).mockResolvedValueOnce([{ image: { width: 1000, height: 640 }, items: [
      { text: '지원하기', score: 0.99, poly: [[100, 240], [300, 240], [300, 320], [100, 320]] },
      { text: '지원하기', score: 0.99, poly: [[100, 400], [300, 400], [300, 480], [100, 480]] },
    ] }])
    const { recognizeImages } = await moduleUnderTest()
    const result = await recognizeImages([new File(['x'], 'notice.png')])
    expect(result.pages[0].text).toBe('지원하기\n지원하기')
    expect(result.pages[0].spans.map((span) => span.box.y)).toEqual([0.9, 0.94])
  })

  it('distinguishes model reuse from the initial load', async () => {
    predict.mockResolvedValue([{ items: [{ text: '공지', score: 1 }] }])
    const { recognizeImages } = await moduleUnderTest()
    const file = new File(['x'], 'notice.png')
    expect((await recognizeImages([file])).modelState).toBe('initialized')
    expect((await recognizeImages([file])).modelState).toBe('reused')
    expect(createEngine).toHaveBeenCalledOnce()
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
