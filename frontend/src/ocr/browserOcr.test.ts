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
    const fallback = await recognizeImages([new File(['x'], 'notice.png')])
    expect(fallback.pages[0].source_units?.[0].translation_status).toBe('source_crop')
    expect(fallback.recoveryWarnings[0]).toContain('Local OCR is unavailable')
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
    expect(result.pages.map(({ text, spans }) => ({ text, spans }))).toEqual([{ text: '모집 대상\n2026년', spans: [] }, { text: '신청 기간', spans: [] }])
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

  it('recovers a small text cluster in a local detail pass and maps it back to the photo', async () => {
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
      { text: '장학금 형태로 지급', score: 0.96, poly: [[100, 3500], [700, 3500], [700, 3524], [100, 3524]] },
      { text: '문의 02-710-25n0', score: 0.95, poly: [[100, 3800], [1200, 3800], [1200, 3824], [100, 3824]] },
    ] }]).mockResolvedValueOnce([{ image: { width: 2296, height: 1632 }, metrics: { detMs: 50, recMs: 75 }, items: [
      { text: '장학금 형태로 지급', score: 0.999, poly: [[100, 1052], [700, 1052], [700, 1076], [100, 1076]] },
      { text: '문의 02-710-2500 convedu@sogang.ac.kr', score: 0.98, poly: [[100, 1352], [1200, 1352], [1200, 1376], [100, 1376]] },
    ] }])
    const { recognizeImages } = await moduleUnderTest()

    const result = await recognizeImages([new File(['private photo'], 'notice.png')])

    expect(predict).toHaveBeenCalledTimes(2)
    expect(predict.mock.calls[1][0]).toBe(crop)
    expect(drawImage).toHaveBeenCalledWith(expect.anything(), 0, 2448, 2296, 1632, 0, 0, 2296, 1632)
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
      { text: '신청 기간', score: 0.99, poly: [[100, 100], [700, 100], [700, 124], [100, 124]] },
    ] }])
    const { recognizeImages } = await moduleUnderTest()
    const result = await recognizeImages([new File(['x'], 'notice.png')])
    expect(result.pages[0].text).toBe('신청 기간')
    expect(result.recoveryWarnings).toEqual([
      expect.stringContaining('Page 1: a small or uncertain text region is retained as source evidence'),
      expect.stringContaining('Page 1: the lower edge is retained as source evidence'),
    ])
    expect(predict).toHaveBeenCalledOnce()
  })

  it('keeps repeated text when its positions differ', async () => {
    vi.stubGlobal('createImageBitmap', vi.fn().mockResolvedValue({ width: 1000, height: 4000, close: vi.fn() }))
    class DetailCanvas {
      getContext() { return { drawImage: vi.fn() } }
      async convertToBlob() { return new Blob(['footer'], { type: 'image/png' }) }
    }
    vi.stubGlobal('OffscreenCanvas', DetailCanvas)
    predict.mockResolvedValueOnce([{ image: { width: 1000, height: 4000 }, items: [
      { text: '지원하기', score: 0.99, poly: [[100, 3600], [300, 3600], [300, 3624], [100, 3624]] },
    ] }]).mockResolvedValueOnce([{ image: { width: 1000, height: 1600 }, items: [
      { text: '지원하기', score: 0.99, poly: [[100, 1200], [300, 1200], [300, 1224], [100, 1224]] },
      { text: '지원하기', score: 0.99, poly: [[100, 1360], [300, 1360], [300, 1384], [100, 1384]] },
    ] }])
    const { recognizeImages } = await moduleUnderTest()
    const result = await recognizeImages([new File(['x'], 'notice.png')])
    expect(result.pages[0].text).toBe('지원하기\n지원하기')
    expect(result.pages[0].spans.map((span) => span.box.y)).toEqual([0.9, 0.94])
  })

  it.each([
    { name: 'portrait top', width: 2400, height: 3200, x: 100, y: 80, score: 0.99 },
    { name: 'square middle', width: 3000, height: 3000, x: 100, y: 1500, score: 0.99 },
    { name: 'landscape right', width: 4000, height: 1200, x: 3500, y: 100, score: 0.99 },
    { name: 'small uncertain image', width: 800, height: 600, x: 200, y: 100, score: 0.4 },
  ])('checks a $name region without a fixed footer assumption', async ({ width, height, x, y, score }) => {
    const drawImage = vi.fn()
    const close = vi.fn()
    const crop = new Blob(['local detail'], { type: 'image/png' })
    class DetailCanvas {
      getContext() { return { drawImage } }
      async convertToBlob() { return crop }
    }
    vi.stubGlobal('OffscreenCanvas', DetailCanvas)
    vi.stubGlobal('createImageBitmap', vi.fn().mockResolvedValue({ width, height, close }))
    const poly = [[x, y], [x + 100, y], [x + 100, y + 16], [x, y + 16]]
    predict.mockResolvedValueOnce([{ image: { width, height }, items: [
      { text: '신청 조건', score, poly },
      { text: '다른 내용', score: 1, poly: [[0, height - 100], [200, height - 100], [200, height - 40], [0, height - 40]] },
    ] }]).mockImplementationOnce(() => {
      const [, left, top, cropWidth, cropHeight] = drawImage.mock.calls.find((call) => call.length === 9)! as [unknown, number, number, number, number]
      return [{ image: { width: cropWidth, height: cropHeight }, items: [{
        text: '신청 조건을 확인하세요', score: 0.97, poly: poly.map(([pointX, pointY]) => [pointX - left, pointY - top]),
      }] }]
    })
    const { recognizeImages } = await moduleUnderTest()

    const result = await recognizeImages([new File(['private photo'], 'varied.png')])

    expect(predict).toHaveBeenCalledTimes(2)
    expect(predict.mock.calls[1][0]).toBe(crop)
    const [, left, top, regionWidth, regionHeight] = drawImage.mock.calls.find((call) => call.length === 9)! as [unknown, number, number, number, number]
    expect(left).toBeLessThanOrEqual(x)
    expect(top).toBeLessThanOrEqual(y)
    expect(left + regionWidth).toBeGreaterThanOrEqual(x + 100)
    expect(top + regionHeight).toBeGreaterThanOrEqual(y + 16)
    expect(result.pages[0].text).toBe('신청 조건\n다른 내용\n신청 조건을 확인하세요')
    expect(result.pages[0].spans[2].box.x).toBeCloseTo(x / width)
    expect(result.pages[0].spans[2].box.y).toBeCloseTo(y / height)
    expect(result.detailPasses).toBe(1)
    expect(result.recoveryWarnings).toEqual([])
    expect(close).toHaveBeenCalled()
  })

  it('does not add recovery inference for large, clear text', async () => {
    predict.mockResolvedValue([{ image: { width: 4000, height: 2000 }, items: [{
      text: '공지사항', score: 0.99, poly: [[100, 100], [1000, 100], [1000, 220], [100, 220]],
    }] }])
    const { recognizeImages } = await moduleUnderTest()
    const result = await recognizeImages([new File(['image'], 'wide.png')])
    expect(predict).toHaveBeenCalledOnce()
    expect(result.detailPasses).toBe(0)
    expect(result.recoveryWarnings).toEqual([])
  })

  it('checks a tall image edge that the initial detection missed when top uncertainty wins', async () => {
    const drawImage = vi.fn()
    vi.stubGlobal('createImageBitmap', vi.fn().mockResolvedValue({ width: 2000, height: 4000, close: vi.fn() }))
    class DetailCanvas {
      getContext() { return { drawImage } }
      async convertToBlob() { return new Blob(['local crop']) }
    }
    vi.stubGlobal('OffscreenCanvas', DetailCanvas)
    predict.mockResolvedValueOnce([{ image: { width: 2000, height: 4000 }, items: [
      { text: '읽기 어려운 작은 글자', score: 0.4, poly: [[100, 100], [400, 100], [400, 124], [100, 124]] },
      { text: '신청 안내', score: 0.99, poly: [[100, 1000], [900, 1000], [900, 1200], [100, 1200]] },
    ] }]).mockResolvedValueOnce([{ image: { width: 2000, height: 1600 }, items: [
      { text: '읽기 어려운 작은 글자', score: 0.8, poly: [[100, 100], [400, 100], [400, 124], [100, 124]] },
    ] }]).mockResolvedValueOnce([{ image: { width: 2000, height: 640 }, items: [
      { text: '문의 02-123-4567', score: 0.98, poly: [[100, 400], [900, 400], [900, 430], [100, 430]] },
    ] }])
    const { recognizeImages } = await moduleUnderTest()

    const result = await recognizeImages([new File(['private photo'], 'tall.png')])

    expect(predict).toHaveBeenCalledTimes(3)
    expect(drawImage.mock.calls.filter((call) => call.length === 9)).toEqual([
      [expect.anything(), 0, 0, 2000, 1600, 0, 0, 2000, 1600],
      [expect.anything(), 0, 3360, 2000, 640, 0, 0, 2000, 640],
    ])
    expect(result.pages[0].text).toBe('읽기 어려운 작은 글자\n신청 안내\n문의 02-123-4567')
    expect(result.pages[0].spans[0].confidence).toBe(0.8)
    expect(result.pages[0].spans[2].box.y).toBeCloseTo(3760 / 4000)
    expect(result.detailPasses).toBe(2)
    expect(result.recoveryWarnings).toEqual([])
  })

  it('checks an undetected tall-image edge even when no adaptive candidate exists', async () => {
    const drawImage = vi.fn()
    vi.stubGlobal('createImageBitmap', vi.fn().mockResolvedValue({ width: 1000, height: 4000, close: vi.fn() }))
    class DetailCanvas {
      getContext() { return { drawImage } }
      async convertToBlob() { return new Blob(['local edge']) }
    }
    vi.stubGlobal('OffscreenCanvas', DetailCanvas)
    predict.mockResolvedValueOnce([{ image: { width: 1000, height: 4000 }, items: [{
      text: '행사 안내', score: 0.99, poly: [[100, 100], [900, 100], [900, 300], [100, 300]],
    }] }]).mockResolvedValueOnce([{ image: { width: 1000, height: 640 }, items: [{
      text: '준비물 학생증', score: 0.98, poly: [[100, 400], [900, 400], [900, 440], [100, 440]],
    }] }])
    const { recognizeImages } = await moduleUnderTest()
    const result = await recognizeImages([new File(['image'], 'event.png')])
    expect(predict).toHaveBeenCalledTimes(2)
    expect(result.pages[0].text).toBe('행사 안내\n준비물 학생증')
    expect(result.detailPasses).toBe(1)
    expect(result.recoveryWarnings).toEqual([])
  })

  it('still checks the edge after an adaptive crop fails', async () => {
    vi.stubGlobal('createImageBitmap', vi.fn().mockResolvedValue({ width: 1000, height: 4000, close: vi.fn() }))
    class DetailCanvas {
      height: number
      constructor(_width: number, height: number) { this.height = height }
      getContext() { return { drawImage: vi.fn() } }
      async convertToBlob() {
        if (this.height === 1600) throw new Error('adaptive crop failed')
        return new Blob(['edge'])
      }
    }
    vi.stubGlobal('OffscreenCanvas', DetailCanvas)
    predict.mockResolvedValueOnce([{ image: { width: 1000, height: 4000 }, items: [{
      text: '작은 글자', score: 0.4, poly: [[100, 100], [400, 100], [400, 124], [100, 124]],
    }] }]).mockResolvedValueOnce([{ image: { width: 1000, height: 640 }, items: [{
      text: '문의 02-123-4567', score: 0.98, poly: [[100, 400], [900, 400], [900, 440], [100, 440]],
    }] }])
    const { recognizeImages } = await moduleUnderTest()
    const result = await recognizeImages([new File(['image'], 'tall.png')])
    expect(result.pages[0].text).toBe('작은 글자\n문의 02-123-4567')
    expect(result.detailPasses).toBe(1)
    expect(result.recoveryWarnings).toEqual([expect.stringContaining('a small or uncertain text region is retained as source evidence')])
    expect(predict).toHaveBeenCalledTimes(2)
  })

  it('keeps a wide uncertain line inside its recovery crop', async () => {
    const drawImage = vi.fn()
    vi.stubGlobal('createImageBitmap', vi.fn().mockResolvedValue({ width: 1200, height: 600, close: vi.fn() }))
    class DetailCanvas {
      getContext() { return { drawImage } }
      async convertToBlob() { return new Blob(['local crop']) }
    }
    vi.stubGlobal('OffscreenCanvas', DetailCanvas)
    predict.mockResolvedValueOnce([{ image: { width: 1200, height: 600 }, items: [{
      text: '자세한 신청 조건이 있는 긴 문장', score: 0.5, poly: [[50, 100], [1150, 100], [1150, 140], [50, 140]],
    }] }]).mockImplementationOnce(() => {
      const [, , , width, height] = drawImage.mock.calls.find((call) => call.length === 9)! as [unknown, number, number, number, number]
      return [{ image: { width, height }, items: [] }]
    })
    const { recognizeImages } = await moduleUnderTest()
    const result = await recognizeImages([new File(['image'], 'wide-line.png')])
    const [, left, , width] = drawImage.mock.calls.find((call) => call.length === 9)! as [unknown, number, number, number]
    expect(left).toBeLessThanOrEqual(50)
    expect(left + width).toBeGreaterThanOrEqual(1150)
    expect(result.pages[0].text).toBe('자세한 신청 조건이 있는 긴 문장')
    expect(result.detailPasses).toBe(1)
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
    expect(result.pages[0].source_units?.slice(1).map((unit) => unit.source_text)).toEqual([
      'https://m.site.naver.com/2eoT9', 'https://splus.sogang.ac.kr/ko/module/eco/program/view/443',
    ])
    expect(result.pages[0].source_units?.[1].english).toBe('Decoded QR link (not opened): https://m.site.naver.com/2eoT9')
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

  it('bounds tiled QR work and keeps URLs decoded before the scan budget expires', async () => {
    let elapsed = 0
    const clock = vi.spyOn(performance, 'now').mockImplementation(() => elapsed)
    const getImageData = vi.fn((_x: number, _y: number, width: number, height: number) => ({
      width, height, data: new Uint8ClampedArray(width * height * 4),
    }))
    class LocalCanvas {
      getContext() { return { drawImage: vi.fn(), getImageData } }
    }
    vi.stubGlobal('OffscreenCanvas', LocalCanvas)
    vi.stubGlobal('createImageBitmap', vi.fn().mockResolvedValue({ width: 2500, height: 2000, close: vi.fn() }))
    decodeQr.mockImplementation(() => {
      elapsed += 900
      return { data: `https://example.com/notice-${decodeQr.mock.calls.length}`, location: {
        topLeftCorner: { x: 50, y: 50 }, topRightCorner: { x: 90, y: 50 },
        bottomLeftCorner: { x: 50, y: 90 }, bottomRightCorner: { x: 90, y: 90 },
      } }
    })
    predict.mockResolvedValue([{ items: [{ text: '신청 안내', score: 1 }] }])
    try {
      const { recognizeImages } = await moduleUnderTest()
      const result = await recognizeImages([new File(['image'], 'many-tiles.png')])

      expect(decodeQr).toHaveBeenCalledTimes(2)
      expect(getImageData).toHaveBeenCalledOnce()
      expect(result.pages[0].text).toBe('신청 안내\n'
        + 'Decoded QR code URL (not opened): https://example.com/notice-1\n'
        + 'Decoded QR code URL (not opened): https://example.com/notice-2')
      expect(result.qrMs).toBe(1800)
      expect(result.recoveryWarnings).toEqual([expect.stringContaining('QR scan reached its time limit')])
      expect(predict).toHaveBeenCalledOnce()
    } finally {
      clock.mockRestore()
    }
  })

  it('checks remaining QR budget after preparing a tile before calling the decoder', async () => {
    let elapsed = 0
    const clock = vi.spyOn(performance, 'now').mockImplementation(() => elapsed)
    const getImageData = vi.fn((_x: number, _y: number, width: number, height: number) => {
      elapsed += 1600
      return { width, height, data: new Uint8ClampedArray(width * height * 4) }
    })
    class LocalCanvas {
      getContext() { return { drawImage: vi.fn(), getImageData } }
    }
    vi.stubGlobal('OffscreenCanvas', LocalCanvas)
    vi.stubGlobal('createImageBitmap', vi.fn().mockResolvedValue({ width: 2500, height: 2000, close: vi.fn() }))
    predict.mockResolvedValue([{ items: [{ text: '모집 기간', score: 1 }] }])
    try {
      const { recognizeImages } = await moduleUnderTest()
      const result = await recognizeImages([new File(['image'], 'many-tiles.png')])

      expect(getImageData).toHaveBeenCalledOnce()
      expect(decodeQr).not.toHaveBeenCalled()
      expect(result.pages[0].text).toBe('모집 기간')
      expect(result.qrMs).toBe(1600)
      expect(result.recoveryWarnings).toEqual([expect.stringContaining('Printed text was still analyzed')])
    } finally {
      clock.mockRestore()
    }
  })

  it('retains a decoded URL if a later QR decoding attempt fails', async () => {
    decodeQr.mockReturnValueOnce({ data: 'https://example.com/apply', location: {
      topLeftCorner: { x: 50, y: 50 }, topRightCorner: { x: 90, y: 50 },
      bottomLeftCorner: { x: 50, y: 90 }, bottomRightCorner: { x: 90, y: 90 },
    } }).mockImplementationOnce(() => { throw new Error('decoder failed later') })
    vi.stubGlobal('createImageBitmap', vi.fn().mockResolvedValue({ width: 300, height: 400, close: vi.fn() }))
    class LocalCanvas {
      getContext() { return { drawImage: vi.fn(), getImageData: () => ({
        width: 300, height: 400, data: new Uint8ClampedArray(300 * 400 * 4),
      }) } }
    }
    vi.stubGlobal('OffscreenCanvas', LocalCanvas)
    predict.mockResolvedValue([{ items: [{ text: '신청 방법', score: 1 }] }])
    const { recognizeImages } = await moduleUnderTest()

    const result = await recognizeImages([new File(['image'], 'notice.png')])

    expect(result.pages[0].text).toBe('신청 방법\nDecoded QR code URL (not opened): https://example.com/apply')
    expect(decodeQr).toHaveBeenCalledTimes(2)
    expect(result.recoveryWarnings).toEqual([])
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
      expect(result.qrMs).toBeNull()
      expect(result.recoveryWarnings).toEqual([expect.stringContaining('QR scan reached its time limit')])
    } finally {
      vi.useRealTimers()
    }
  })

  it('does not start late QR scanning after its post-OCR wait ends', async () => {
    let resolveBitmap!: (bitmap: ImageBitmap) => void
    vi.stubGlobal('createImageBitmap', vi.fn().mockReturnValue(new Promise<ImageBitmap>((resolve) => { resolveBitmap = resolve })))
    const getContext = vi.fn()
    class LocalCanvas { getContext = getContext }
    vi.stubGlobal('OffscreenCanvas', LocalCanvas)
    predict.mockResolvedValue([{ items: [{ text: '신청 안내', score: 1 }] }])
    const { recognizeImages } = await moduleUnderTest()
    vi.useFakeTimers()
    try {
      const resultPromise = recognizeImages([new File(['image'], 'notice.png')])
      await vi.advanceTimersByTimeAsync(2000)
      const result = await resultPromise
      const close = vi.fn()
      resolveBitmap({ width: 300, height: 400, close } as unknown as ImageBitmap)
      await vi.advanceTimersByTimeAsync(0)

      expect(result.qrMs).toBeNull()
      expect(result.recoveryWarnings).toEqual([expect.stringContaining('QR scan reached its time limit')])
      expect(result.pages[0].text).toBe('신청 안내')
      expect(getContext).not.toHaveBeenCalled()
      expect(decodeQr).not.toHaveBeenCalled()
      expect(close).toHaveBeenCalledOnce()
    } finally {
      vi.useRealTimers()
    }
  })

  it('returns blank pages and measured OCR work for the consumer to show an English unavailable result', async () => {
    const { recognizeImages } = await moduleUnderTest()
    predict.mockResolvedValueOnce([{ image: { width: 1000, height: 1000 }, items: [{
      text: '   ', score: 0.1, poly: [[100, 100], [300, 100], [300, 140], [100, 140]],
    }], metrics: { detMs: 20, recMs: 40 } }])
      .mockResolvedValueOnce([{ image: { width: 800, height: 600 }, items: [], metrics: { detMs: 15, recMs: 0 } }])
    const progress = vi.fn()

    const result = await recognizeImages([new File(['x'], 'blank.png'), new File(['y'], 'another-blank.png')], progress)

    expect(result.pages.map(({ text, spans }) => ({ text, spans }))).toEqual([{ text: '', spans: [] }, { text: '', spans: [] }])
    expect(result).toMatchObject({ modelState: 'initialized', detectionMs: 35, recognitionMs: 40, detailPasses: 0 })
    expect(result.latencyMs).toBeGreaterThanOrEqual(0)
    expect(result.initializationMs).toBeGreaterThanOrEqual(0)
    expect(result.inferenceMs).toBeGreaterThanOrEqual(0)
    expect(result.qrMs).toBeGreaterThanOrEqual(0)
    expect(progress.mock.calls).toEqual([[0, 2], [1, 2], [2, 2]])
    expect(predict).toHaveBeenCalledTimes(2)
  })

  it('wraps an image decoding or inference failure with the page number', async () => {
    const { recognizeImages } = await moduleUnderTest()
    predict.mockRejectedValue(new Error('decode failed'))
    const result = await recognizeImages([new File(['x'], 'bad.heic')])
    expect(result.pages[0].source_units?.[0]).toMatchObject({ source_text: '', translation_status: 'source_crop', box: { x: 0, y: 0, width: 1, height: 1 } })
    expect(result.recoveryWarnings[0]).toContain('decode failed')
  })

  it('can retry model initialization after a transient failure', async () => {
    const { recognizeImages } = await moduleUnderTest()
    createEngine.mockRejectedValueOnce(new Error('network')).mockResolvedValueOnce({ predict })
    predict.mockResolvedValue([{ items: [{ text: 'ok', score: 1 }] }])
    const files = [new File(['x'], 'notice.png')]

    const fallback = await recognizeImages(files)
    expect(fallback.pages[0].source_units?.[0].translation_status).toBe('source_crop')
    expect(fallback.recoveryWarnings[0]).toContain('could not load its local models')
    await expect(recognizeImages(files)).resolves.toMatchObject({ pages: [{ text: 'ok' }] })
    expect(createEngine).toHaveBeenCalledTimes(2)
  })
})
