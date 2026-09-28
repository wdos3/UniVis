import type { AnalysisResult, DemoSummary, ImageDemoSummary, NoticeData } from '../types'

function errorMessage(body: unknown, fallback: string): string {
  if (!body || typeof body !== 'object' || !('detail' in body)) return fallback
  if (typeof body.detail === 'string') return body.detail
  if (Array.isArray(body.detail)) {
    return body.detail.map((item) => item && typeof item === 'object' && 'msg' in item ? String(item.msg) : 'Invalid input').join('; ')
  }
  return fallback
}

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, options)
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null)
    throw new Error(errorMessage(body, response.statusText || 'The request failed.'))
  }
  return response.json() as Promise<T>
}

export const api = {
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
    pages: { text: string }[],
    ocrLatencyMs: number,
    provider: string,
    inputType: 'camera_photo' | 'uploaded_image',
  ) => request<AnalysisResult>('/api/analyze-client-ocr', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pages, ocr_latency_ms: ocrLatencyMs, input_type: inputType, provider, target_language: 'en' }),
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
