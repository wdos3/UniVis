import type { AnalysisResult, ClientOcrPage, DemoSummary, ImageDemoSummary, NoticeData, SourceLedger, SourceUnit } from '../types'

export interface ImageTextTranslation {
  id: string
  source_text: string
  translated_text: string
  status: 'translated' | 'unchanged' | 'failed'
  error?: string | null
}

export interface ImageTextTranslationResult {
  regions: ImageTextTranslation[]
  provider: string
  request_count: number
  latency_ms: number
  metrics_complete: boolean
}

export interface SourceCorrection {
  page: number | null
  line: number | null
  text: string
  reason: string
}

export class ApiError extends Error {
  readonly status: number
  readonly code: string | null
  readonly corrections: SourceCorrection[]

  constructor(message: string, status: number, code: string | null = null, corrections: SourceCorrection[] = []) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.corrections = corrections
  }
}

function sourceCorrections(value: unknown): SourceCorrection[] {
  if (!Array.isArray(value)) return []
  return value.flatMap((item: unknown) => {
    if (!item || typeof item !== 'object' || !('text' in item) || !('reason' in item)
      || typeof item.text !== 'string' || typeof item.reason !== 'string') return []
    const page = 'page' in item && typeof item.page === 'number' && Number.isInteger(item.page) && item.page > 0 ? item.page : null
    const line = 'line' in item && typeof item.line === 'number' && Number.isInteger(item.line) && item.line > 0 ? item.line : null
    return [{ page, line, text: item.text, reason: item.reason }]
  })
}

function errorMessage(body: unknown, fallback: string): string {
  if (!body || typeof body !== 'object' || !('detail' in body)) return fallback
  if (typeof body.detail === 'string') return body.detail
  if (body.detail && typeof body.detail === 'object' && 'message' in body.detail && typeof body.detail.message === 'string') {
    return body.detail.message
  }
  if (Array.isArray(body.detail)) {
    return body.detail.map((item) => item && typeof item === 'object' && 'msg' in item ? String(item.msg) : 'Invalid input').join('; ')
  }
  return fallback
}

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, options)
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null)
    const detail = body && typeof body === 'object' && 'detail' in body ? body.detail : null
    const code = detail && typeof detail === 'object' && 'code' in detail && typeof detail.code === 'string' ? detail.code : null
    const corrections = detail && typeof detail === 'object' && 'corrections' in detail ? sourceCorrections(detail.corrections) : []
    throw new ApiError(errorMessage(body, response.statusText || 'The request failed.'), response.status, code, corrections)
  }
  return response.json() as Promise<T>
}

export const api = {
  translateLedger: (units: SourceUnit[], ocrLatencyMs = 0, layoutLatencyMs = 0, signal?: AbortSignal) => request<SourceLedger>('/api/translate-ledger', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ units, ocr_latency_ms: ocrLatencyMs, layout_latency_ms: layoutLatencyMs }), signal,
  }),
  analyzeLedger: (ledger: SourceLedger, provider: string, inputType: 'camera_photo' | 'uploaded_image',
    regions: { unit_ids: string[]; data_url: string }[] = [], signal?: AbortSignal) => request<AnalysisResult>('/api/analyze-ledger', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ledger, provider, input_type: inputType, regions }), signal,
  }),
  translateImageText: (regions: { id: string; text: string }[], signal?: AbortSignal) => request<ImageTextTranslationResult>('/api/translate-image-text', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ regions, target_language: 'en' }), signal,
  }),
  health: () => request<{ status: string; openai_configured: boolean; default_provider: string; ocr_provider: string; public_mode: boolean }>('/api/health'),
  demos: () => request<DemoSummary[]>('/api/demos'),
  imageDemos: () => request<ImageDemoSummary[]>('/api/image-demos'),
  demo: (id: string) => request<AnalysisResult>(`/api/demos/${id}`),
  analyze: (text: string, provider: string) => request<AnalysisResult>('/api/analyze', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text, provider, target_language: 'en' }),
  }),
  upload: (file: File, provider: string) => {
    const data = new FormData()
    data.append('file', file)
    data.append('provider', provider)
    data.append('target_language', 'en')
    return request<AnalysisResult>('/api/upload', { method: 'POST', body: data })
  },
  analyzeClientOcr: (
    pages: ClientOcrPage[],
    ocrLatencyMs: number,
    provider: string,
    inputType: 'camera_photo' | 'uploaded_image',
  ) => request<AnalysisResult>('/api/analyze-client-ocr', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pages, ocr_latency_ms: ocrLatencyMs, input_type: inputType, provider, target_language: 'en', allow_partial: true }),
  }),
  notices: () => request<AnalysisResult[]>('/api/notices'),
  updateNotice: (id: string, notice: NoticeData) => request<AnalysisResult>(`/api/notices/${id}`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(notice),
  }),
  reprocessRecoveredText: (id: string, text: string, provider: string) => request<AnalysisResult>(`/api/notices/${id}/reprocess-recovered-text`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text, provider }),
  }),
  saveResearch: (payload: object) => request<{ id: number }>('/api/research/results', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }),
}
