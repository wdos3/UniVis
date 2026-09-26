import type { AnalysisResult, DemoSummary, ImageDemoSummary, NoticeData } from '../types'

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, options)
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(body.detail ?? 'The request failed.')
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
  analyzeImages: (files: File[], provider: string, inputType: 'camera_photo' | 'uploaded_image') => {
    const data = new FormData()
    files.forEach((file) => data.append('files', file))
    data.append('provider', provider)
    data.append('target_language', 'en')
    data.append('input_type', inputType)
    return request<AnalysisResult>('/api/analyze-images', { method: 'POST', body: data })
  },
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
