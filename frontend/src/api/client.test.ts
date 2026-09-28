import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from './client'

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
    })
  })

  it('shows validation details from malformed OCR text requests', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      detail: [{ msg: 'OCR text is too long' }],
    }), { status: 422, headers: { 'Content-Type': 'application/json' } })))

    await expect(api.analyzeClientOcr([{ text: 'too long' }], 1, 'auto', 'uploaded_image'))
      .rejects.toThrow('OCR text is too long')
  })
})
