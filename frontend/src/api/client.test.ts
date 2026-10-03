import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError } from './client'
import { makeSourceUnit, pendingLedger } from '../ledger/sourceLedger'

describe('client-side OCR analysis request', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('sends ledger translation with exact source IDs and spatial evidence without original image bytes', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ units: [], blocks: [] }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    const units = [makeSourceUnit({ page: 1, text: '지원금 100만원', order: 0, id: 'funding', box: { x: .1, y: .5, width: .4, height: .05 } })]
    await api.translateLedger(units, 100, 12)
    expect(fetchMock).toHaveBeenCalledWith('/api/translate-ledger', expect.objectContaining({ method: 'POST' }))
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ units, ocr_latency_ms: 100, layout_latency_ms: 12 })
  })

  it('maps bounded recovery crops to source IDs in the semantic request', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: 'result' }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    const ledger = pendingLedger([makeSourceUnit({ page: 1, text: '문의 02-710-25n0', order: 0, id: 'contact' })])
    const regions = [{ unit_ids: ['contact'], data_url: 'data:image/jpeg;base64,/9j/AA==' }]
    await api.analyzeLedger(ledger, 'auto', 'uploaded_image', regions)
    expect(fetchMock).toHaveBeenCalledWith('/api/analyze-ledger', expect.objectContaining({ method: 'POST' }))
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ ledger, provider: 'auto', input_type: 'uploaded_image', regions })
  })

  it('sends image translation as bounded text regions with cancellation and no image bytes', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ regions: [] }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    const controller = new AbortController()
    await api.translateImageText([{ id: 'R001', text: '신청 기간' }], controller.signal)
    expect(fetchMock).toHaveBeenCalledWith('/api/translate-image-text', expect.objectContaining({ method: 'POST', signal: controller.signal }))
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ regions: [{ id: 'R001', text: '신청 기간' }], target_language: 'en' })
  })

  it('posts ordered OCR text as JSON without files or image bytes', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: 'notice-1' }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetchMock)

    await api.analyzeClientOcr([{ text: '첫 페이지' }, { text: '둘째 페이지' }], 1800, 'auto', 'camera_photo')

    expect(fetchMock).toHaveBeenCalledOnce()
    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/analyze-client-ocr')
    expect(options.method).toBe('POST')
    expect(options.headers).toEqual({ 'Content-Type': 'application/json' })
    expect(JSON.parse(options.body as string)).toEqual({
      pages: [{ text: '첫 페이지' }, { text: '둘째 페이지' }],
      ocr_latency_ms: 1800,
      input_type: 'camera_photo',
      provider: 'auto',
      target_language: 'en',
      allow_partial: true,
    })
  })

  it('shows validation details from malformed OCR text requests', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      detail: [{ msg: 'OCR text is too long' }],
    }), { status: 422, headers: { 'Content-Type': 'application/json' } })))

    await expect(api.analyzeClientOcr([{ text: 'too long' }], 1, 'auto', 'uploaded_image'))
      .rejects.toThrow('OCR text is too long')
  })

  it('preserves actionable source correction details from the completeness gate', async () => {
    const corrections = [{ page: 1, line: 47, text: '문의:02.710.25n0', reason: 'The telephone number contains an unreadable character. Retype it from the photo.' }]
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: {
      code: 'source_correction_required', message: 'Correct the contact number before retrying.', corrections,
    } }), { status: 422, headers: { 'Content-Type': 'application/json' } })))

    const error = await api.analyzeClientOcr([{ text: '문의:02.710.25n0' }], 1, 'auto', 'uploaded_image').catch((problem: unknown) => problem)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 422, code: 'source_correction_required', message: 'Correct the contact number before retrying.', corrections })
  })

  it('discards malformed correction hints without hiding the error message', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: {
      message: 'Review source text.', corrections: [{ text: 42, reason: 'Wrong shape' }, { page: -1, line: '3', text: '원문', reason: 'Check the source.' }],
    } }), { status: 422, headers: { 'Content-Type': 'application/json' } })))
    const error = await api.analyze('원문', 'auto').catch((problem: unknown) => problem)
    expect(error).toMatchObject({ message: 'Review source text.', corrections: [{ page: null, line: null, text: '원문', reason: 'Check the source.' }] })
  })
})
