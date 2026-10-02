import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError } from './client'

describe('client-side OCR analysis request', () => {
  afterEach(() => vi.unstubAllGlobals())

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
