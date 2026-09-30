import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { api, ApiError } from './api/client'
import { isBrowserOcrSupported, recognizeImages } from './ocr/browserOcr'
import type { AnalysisResult, NoticeData } from './types'

vi.mock('./api/client', async (importOriginal) => ({
  ...await importOriginal<typeof import('./api/client')>(),
  api: {
    demos: vi.fn(), imageDemos: vi.fn(), demo: vi.fn(), health: vi.fn(), analyzeClientOcr: vi.fn(), upload: vi.fn(), notices: vi.fn(), updateNotice: vi.fn(), reprocessRecoveredText: vi.fn(),
  },
}))
vi.mock('./ocr/browserOcr', () => ({ isBrowserOcrSupported: vi.fn(), recognizeImages: vi.fn() }))

const notice: NoticeData = {
  title: 'Test notice', notice_type: 'Other', audience: [], purpose: '', summary: '',
  actions: [], deadlines: [], required_documents: [], eligibility: [], exceptions: [], warnings: [],
  consequences: [], locations: [], contacts: [], fees: [], financial_support: [], links: [], key_details: [], conditional_groups: [],
  source_language: 'ko', target_language: 'en', ambiguities: [], unverified_items: [], source_facts: [],
  template_overrides: { checklist: null, step_flow: null, timeline: null, decision_tree: null, warning_cards: null, information_cards: null },
}

const imageResult: AnalysisResult = {
  id: 'image-result', created_at: '2026-09-29T00:00:00Z', original_text: '공지사항', recovered_text: '공지사항',
  faithful_translation: 'Notice', simplified_text: 'Notice', provider: 'mock', synthetic: false, korean_detected: true,
  notice, templates: {},
  fidelity: { checks: [], warnings: [], critical_fields_in_source: 0, critical_fields_represented: 0, potentially_missing: [], potentially_invented: [], serious_issue: false },
  source_pages: [{ id: 'page-1', page_number: 1, filename: 'Page 1', media_type: 'application/octet-stream', original_url: '', processed_url: '', width: 1, height: 1, readable: true, quality_issues: [], qr_codes: [] }],
  acquisition: {
    input_type: 'uploaded_image', source_pages: 1, text_extraction_status: 'available', quality_warnings: 0,
    pages_needing_review: 0, critical_facts_needing_review: 0, reconciliation_conflicts: [], ocr_provider: 'browser-ocr-kor-eng',
    translation_provider: 'mock', semantic_provider: 'mock', translation_requests: 0, semantic_requests: 0,
    semantic_input_tokens: 0, semantic_output_tokens: 0, semantic_total_tokens: 0,
    ocr_latency_ms: 1200, translation_latency_ms: 0, semantic_latency_ms: 0, total_latency_ms: 1200,
  },
}

const ocrMetrics = { modelState: 'initialized' as const, detectionMs: 200, recognitionMs: 500, detailPasses: 0, recoveryWarnings: [] }

describe('App browser OCR', () => {
  afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

  beforeEach(() => {
    vi.mocked(api.demos).mockResolvedValue([{ id: 'demo', title: 'Synthetic notice', category: 'Example', original_text: '공지', questions: [] }])
    vi.mocked(api.imageDemos).mockResolvedValue([])
    vi.mocked(isBrowserOcrSupported).mockReturnValue(true)
  })

  it('keeps text and synthetic notices available in unsupported browsers', async () => {
    vi.mocked(isBrowserOcrSupported).mockReturnValue(false)
    vi.mocked(api.health).mockResolvedValue({ status: 'ok', openai_configured: false, default_provider: 'mock', ocr_provider: 'paddleocr-local-unavailable-on-vercel', public_mode: true })
    render(<App />)

    expect(await screen.findByText('Photo analysis is unavailable in this browser.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Take a Photo/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /Upload text-based PDF or TXT/i })).toBeEnabled()
    expect(await screen.findByRole('button', { name: /Synthetic notice/ })).toBeEnabled()
    expect(screen.queryByRole('button', { name: 'Researcher View' })).not.toBeInTheDocument()

    fireEvent.change(screen.getByPlaceholderText('공지사항의 한국어 텍스트를 여기에 붙여넣으세요…'), { target: { value: '공지' } })
    expect(screen.getByRole('button', { name: 'Generate instructions' })).toBeEnabled()
  })

  it('enables local photo OCR even when hosted PaddleOCR is absent', async () => {
    vi.mocked(api.health).mockResolvedValue({ status: 'ok', openai_configured: true, default_provider: 'openai', ocr_provider: 'paddleocr-local-unavailable-on-vercel', public_mode: false })
    render(<App />)

    expect(await screen.findByRole('button', { name: 'Researcher View' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Take a Photo/i })).toBeEnabled()
    expect(screen.getByRole('button', { name: /Upload Image/i })).toBeEnabled()
    expect(screen.getByRole('button', { name: /Upload text-based PDF or TXT/i })).toBeEnabled()
  })

  it('sends recognized text without image bytes and keeps image URLs local', async () => {
    vi.mocked(api.health).mockResolvedValue({ status: 'ok', openai_configured: false, default_provider: 'mock', ocr_provider: 'paddleocr-local-unavailable-on-vercel', public_mode: true })
    vi.mocked(recognizeImages).mockResolvedValue({ pages: [{ text: '공지사항 신청 방법', spans: [] }], latencyMs: 1200, initializationMs: 500, inferenceMs: 700, ...ocrMetrics })
    vi.mocked(api.analyzeClientOcr).mockResolvedValue(imageResult)
    const createUrl = vi.fn().mockReturnValueOnce('blob:draft').mockReturnValueOnce('blob:result')
    const revokeUrl = vi.fn()
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createUrl })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: revokeUrl })

    const { container, unmount } = render(<App />)
    await screen.findByText('Photos are read on your device.')
    const file = new File(['private photo bytes'], 'notice.png', { type: 'image/png' })
    fireEvent.change(container.querySelector('input[multiple]')!, { target: { files: [file] } })
    fireEvent.click(screen.getByRole('button', { name: 'Analyze notice photo' }))

    await waitFor(() => expect(api.analyzeClientOcr).toHaveBeenCalledWith([{ text: '공지사항 신청 방법', spans: [] }], 1200, 'auto', 'uploaded_image'))
    expect(recognizeImages).toHaveBeenCalledWith([file], expect.any(Function))
    expect(screen.getByAltText('Original notice page 1')).toHaveAttribute('src', 'blob:result')
    expect(screen.getByRole('textbox', { name: '' })).toHaveValue('공지사항 신청 방법')
    expect(createUrl).toHaveBeenCalledWith(file)
    unmount()
    expect(revokeUrl).toHaveBeenCalledWith('blob:draft')
    expect(revokeUrl).toHaveBeenCalledWith('blob:result')
  })

  it('does not attach photo A to saved notice B when a researcher switches results', async () => {
    const savedResult: AnalysisResult = {
      ...imageResult,
      id: 'saved-B',
      notice: { ...notice, title: 'Saved B' },
      source_pages: [{ ...imageResult.source_pages[0], id: 'saved-B-page', original_url: '', processed_url: '' }],
    }
    vi.mocked(api.health).mockResolvedValue({ status: 'ok', openai_configured: false, default_provider: 'mock', ocr_provider: 'paddleocr-local-unavailable-on-vercel', public_mode: false })
    vi.mocked(recognizeImages).mockResolvedValue({ pages: [{ text: '공지사항 신청 방법', spans: [] }], latencyMs: 1200, initializationMs: 500, inferenceMs: 700, ...ocrMetrics })
    vi.mocked(api.analyzeClientOcr).mockResolvedValue(imageResult)
    vi.mocked(api.notices).mockResolvedValue([savedResult])
    vi.mocked(api.updateNotice).mockResolvedValue(savedResult)
    vi.mocked(api.reprocessRecoveredText).mockResolvedValue(imageResult)
    const revokeUrl = vi.fn()
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn().mockReturnValueOnce('blob:draft-A').mockReturnValueOnce('blob:result-A') })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: revokeUrl })

    const { container } = render(<App />)
    await screen.findByText('Photos are read on your device.')
    fireEvent.change(container.querySelector('input[multiple]')!, { target: { files: [new File(['A'], 'photo-A.png', { type: 'image/png' })] } })
    fireEvent.click(screen.getByRole('button', { name: 'Analyze notice photo' }))
    expect(await screen.findByAltText('Original notice page 1')).toHaveAttribute('src', 'blob:result-A')

    fireEvent.click(screen.getByRole('button', { name: 'Edit recovered text' }))
    fireEvent.click(screen.getByRole('button', { name: 'Save & regenerate outputs' }))
    await waitFor(() => expect(api.reprocessRecoveredText).toHaveBeenCalledWith('image-result', '공지사항', 'auto'))
    await screen.findByRole('button', { name: 'Edit recovered text' })
    expect(screen.getByAltText('Original notice page 1')).toHaveAttribute('src', 'blob:result-A')
    expect(revokeUrl).not.toHaveBeenCalledWith('blob:result-A')

    fireEvent.click(screen.getByRole('button', { name: 'Researcher View' }))
    fireEvent.click(await screen.findByRole('button', { name: /Saved B/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Validate & regenerate' }))
    await waitFor(() => expect(api.updateNotice).toHaveBeenCalledWith('saved-B', savedResult.notice))
    fireEvent.click(screen.getByRole('button', { name: 'Back to workspace' }))

    expect(screen.getByText('This photo was kept on the original device and is no longer available here.')).toBeInTheDocument()
    expect(screen.queryByAltText('Original notice page 1')).not.toBeInTheDocument()
    expect(revokeUrl).toHaveBeenCalledWith('blob:result-A')
    expect(revokeUrl).not.toHaveBeenCalledWith('blob:draft-A')
  })

  it('does not assign text-demo comprehension questions to an unanalyzed image demo', async () => {
    vi.mocked(api.demos).mockResolvedValue([{
      id: 'text-demo', title: 'Synthetic notice', category: 'Example', original_text: '공지',
      questions: [{ id: 'q1', prompt: 'Which deadline?', expected_answer: 'Monday', critical_fact_id: null }],
    }])
    vi.mocked(api.demo).mockResolvedValue({ ...imageResult, source_pages: [], synthetic: true })
    vi.mocked(api.imageDemos).mockResolvedValue([{ id: 'image-demo', title: 'Image demo', description: 'Poster image', page_urls: ['/demo-images/poster.png'] }])
    vi.mocked(api.health).mockResolvedValue({ status: 'ok', openai_configured: false, default_provider: 'mock', ocr_provider: 'paddleocr-local-unavailable-on-vercel', public_mode: true })
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn().mockReturnValue('blob:demo') })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(new Blob(['image'], { type: 'image/png' }), { status: 200 })))

    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: /Synthetic notice/ }))
    expect(await screen.findByRole('button', { name: /Open Research Mode/ })).toBeEnabled()
    fireEvent.click(screen.getByRole('button', { name: /Image demo/ }))
    await screen.findByText('poster.png')
    expect(screen.queryByRole('button', { name: /Open Research Mode/ })).not.toBeInTheDocument()
  })

  it('does not leave a previous result visible when mock image OCR cannot be interpreted', async () => {
    vi.mocked(api.health).mockResolvedValue({ status: 'ok', openai_configured: false, default_provider: 'mock', ocr_provider: 'paddleocr-local-unavailable-on-vercel', public_mode: true })
    vi.mocked(api.demo).mockResolvedValue({ ...imageResult, source_pages: [], synthetic: true })
    vi.mocked(recognizeImages).mockResolvedValue({ pages: [{ text: '공지사항 다른 날짜', spans: [] }], latencyMs: 1200, initializationMs: 500, inferenceMs: 700, ...ocrMetrics })
    vi.mocked(api.analyzeClientOcr).mockRejectedValue(new Error('Mock mode requires exact synthetic notice OCR.'))
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn().mockReturnValue('blob:draft') })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() })

    const { container } = render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: /Synthetic notice/ }))
    expect(await screen.findByRole('heading', { level: 2, name: 'Test notice' })).toBeInTheDocument()
    fireEvent.change(container.querySelector('input[multiple]')!, { target: { files: [new File(['B'], 'photo-B.png', { type: 'image/png' })] } })
    fireEvent.click(screen.getByRole('button', { name: 'Analyze notice photo' }))

    expect(await screen.findByText('Mock mode requires exact synthetic notice OCR.')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { level: 2, name: 'Test notice' })).not.toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: '' })).toHaveValue('공지사항 다른 날짜')
  })

  it('retries in-place OCR corrections with their positions and keeps the local photo', async () => {
    vi.mocked(api.health).mockResolvedValue({ status: 'ok', openai_configured: true, default_provider: 'openai', ocr_provider: 'paddleocr-local-unavailable-on-vercel', public_mode: false })
    const recoveredPage = { text: '지원 마감', spans: [{ text: '지원 마감', box: { x: 0.1, y: 0.2, width: 0.3, height: 0.1 } }] }
    vi.mocked(recognizeImages).mockResolvedValue({ pages: [recoveredPage], latencyMs: 1200, initializationMs: 500, inferenceMs: 700, ...ocrMetrics })
    vi.mocked(api.analyzeClientOcr).mockRejectedValueOnce(new Error('Coverage check could not resolve all details.')).mockResolvedValueOnce(imageResult)
    const createUrl = vi.fn().mockReturnValueOnce('blob:draft').mockReturnValueOnce('blob:result')
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createUrl })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() })

    const { container } = render(<App />)
    await screen.findByText('Photos are read on your device.')
    const file = new File(['photo bytes'], 'notice.png', { type: 'image/png' })
    fireEvent.change(container.querySelector('input[multiple]')!, { target: { files: [file] } })
    fireEvent.click(screen.getByRole('button', { name: 'Analyze notice photo' }))

    expect(await screen.findByText('Coverage check could not resolve all details.')).toBeInTheDocument()
    expect(screen.getByText('Review recognized text before retrying')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open page photo' })).toHaveAttribute('href', 'blob:draft')
    expect(screen.getByPlaceholderText('공지사항의 한국어 텍스트를 여기에 붙여넣으세요…')).toBeDisabled()
    expect(screen.getByText(/Photo correction is active above/)).toBeInTheDocument()
    fireEvent.change(screen.getByRole('textbox', { name: /Page 1 recognized text/i }), { target: { value: '지원 마감 9월 30일' } })
    fireEvent.click(screen.getByRole('button', { name: 'Retry analysis with corrected text' }))

    await waitFor(() => expect(api.analyzeClientOcr).toHaveBeenLastCalledWith(
      [{ text: '지원 마감 9월 30일', spans: [{ text: '지원 마감 9월 30일', box: recoveredPage.spans[0].box }] }], 1200, 'auto', 'uploaded_image',
    ))
    expect(recognizeImages).toHaveBeenCalledTimes(1)
    expect(await screen.findByAltText('Original notice page 1')).toHaveAttribute('src', 'blob:result')
    expect(createUrl).toHaveBeenCalledWith(file)
    expect(screen.queryByText('Review recognized text before retrying')).not.toBeInTheDocument()
    expect(screen.getByPlaceholderText('공지사항의 한국어 텍스트를 여기에 붙여넣으세요…')).toBeEnabled()
  })

  it('shows structured correction requests and keeps retries on the photo path', async () => {
    vi.mocked(api.health).mockResolvedValue({ status: 'ok', openai_configured: true, default_provider: 'openai', ocr_provider: 'paddleocr-local-unavailable-on-vercel', public_mode: true })
    vi.mocked(recognizeImages).mockResolvedValue({ pages: [{ text: '문의:02.710.25n0', spans: [] }], latencyMs: 1200, initializationMs: 500, inferenceMs: 700, ...ocrMetrics })
    vi.mocked(api.analyzeClientOcr).mockRejectedValueOnce(new ApiError('Correct the unreadable contact.', 422, 'source_correction_required', [{
      page: 1, line: 47, text: '문의:02.710.25n0', reason: 'Retype the telephone number from the footer.',
    }]))
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn().mockReturnValue('blob:photo') })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() })
    const { container } = render(<App />)
    await screen.findByText('Photos are read on your device.')
    fireEvent.change(container.querySelector('input[multiple]')!, { target: { files: [new File(['photo'], 'notice.png', { type: 'image/png' })] } })
    fireEvent.click(screen.getByRole('button', { name: 'Analyze notice photo' }))
    expect(await screen.findByText('Retype the telephone number from the footer.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Generate instructions' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Retry analysis with corrected text' })).toBeEnabled()
    expect(screen.queryByRole('heading', { name: 'Test notice' })).not.toBeInTheDocument()
  })

  it('retains photo corrections after a failed document upload and clears them after a successful one', async () => {
    const documentResult: AnalysisResult = {
      ...imageResult, id: 'document-result', original_text: '새 문서 공지사항', recovered_text: '새 문서 공지사항',
      notice: { ...notice, title: 'Document notice' }, source_pages: [],
      acquisition: { ...imageResult.acquisition, input_type: 'pdf_text', source_pages: 0 },
    }
    vi.mocked(api.health).mockResolvedValue({ status: 'ok', openai_configured: true, default_provider: 'openai', ocr_provider: 'paddleocr-local-unavailable-on-vercel', public_mode: true })
    vi.mocked(recognizeImages).mockResolvedValue({ pages: [{ text: '문의:02.710.25n0', spans: [] }], latencyMs: 1200, initializationMs: 500, inferenceMs: 700, ...ocrMetrics })
    vi.mocked(api.analyzeClientOcr).mockRejectedValueOnce(new ApiError('Correct the contact line.', 422, 'source_correction_required', [{
      page: 1, line: 47, text: '문의:02.710.25n0', reason: 'Retype the telephone number from the photo.',
    }]))
    vi.mocked(api.upload).mockRejectedValueOnce(new Error('Document upload failed.')).mockResolvedValueOnce(documentResult)
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn().mockReturnValue('blob:photo') })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() })
    const { container } = render(<App />)
    await screen.findByText('Photos are read on your device.')
    fireEvent.change(container.querySelector('input[multiple]')!, { target: { files: [new File(['photo'], 'notice.png', { type: 'image/png' })] } })
    fireEvent.click(screen.getByRole('button', { name: 'Analyze notice photo' }))
    await screen.findByText('Retype the telephone number from the photo.')

    const document = new File(['document'], 'notice.pdf', { type: 'application/pdf' })
    const documentInput = container.querySelector('input[accept=".pdf,.txt"]')!
    fireEvent.change(documentInput, { target: { files: [document] } })
    expect(await screen.findByText('Document upload failed.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry analysis with corrected text' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Generate instructions' })).toBeDisabled()

    fireEvent.change(documentInput, { target: { files: [document] } })
    await screen.findByRole('heading', { level: 2, name: 'Document notice' })
    expect(screen.queryByText('Retype the telephone number from the photo.')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Retry analysis with corrected text' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Generate instructions' })).toBeEnabled()
    expect(screen.getByPlaceholderText('공지사항의 한국어 텍스트를 여기에 붙여넣으세요…')).toHaveValue('새 문서 공지사항')
    expect(screen.getByPlaceholderText('공지사항의 한국어 텍스트를 여기에 붙여넣으세요…')).toBeEnabled()
    expect(api.upload).toHaveBeenLastCalledWith(document, 'auto')
    expect(api.analyzeClientOcr).toHaveBeenCalledOnce()
  })

  it.each([
    ['첫째 항목\n새 항목\n둘째 항목', true],
    ['둘째 항목\n첫째 항목', false],
  ])('keeps positions only for ordered unchanged lines: %s', async (corrected, keepPositions) => {
    vi.mocked(api.health).mockResolvedValue({ status: 'ok', openai_configured: true, default_provider: 'openai', ocr_provider: 'paddleocr-local-unavailable-on-vercel', public_mode: false })
    vi.mocked(recognizeImages).mockResolvedValue({
      pages: [{ text: '첫째 항목\n둘째 항목', spans: [
        { text: '첫째 항목', box: { x: 0.1, y: 0.2, width: 0.2, height: 0.1 } },
        { text: '둘째 항목', box: { x: 0.1, y: 0.4, width: 0.2, height: 0.1 } },
      ] }],
      latencyMs: 1200, initializationMs: 500, inferenceMs: 700, ...ocrMetrics,
    })
    vi.mocked(api.analyzeClientOcr).mockRejectedValueOnce(new Error('Review OCR lines.')).mockResolvedValueOnce(imageResult)
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn().mockReturnValue('blob:photo') })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() })

    const { container } = render(<App />)
    await screen.findByText('Photos are read on your device.')
    fireEvent.change(container.querySelector('input[multiple]')!, { target: { files: [new File(['photo'], 'notice.png', { type: 'image/png' })] } })
    fireEvent.click(screen.getByRole('button', { name: 'Analyze notice photo' }))
    expect(await screen.findByText('Review OCR lines.')).toBeInTheDocument()
    fireEvent.change(screen.getByRole('textbox', { name: /Page 1 recognized text/i }), { target: { value: corrected } })
    fireEvent.click(screen.getByRole('button', { name: 'Retry analysis with corrected text' }))

    await waitFor(() => expect(api.analyzeClientOcr).toHaveBeenLastCalledWith(
      [{ text: corrected, spans: keepPositions ? [
        { text: '첫째 항목', box: { x: 0.1, y: 0.2, width: 0.2, height: 0.1 } },
        { text: '둘째 항목', box: { x: 0.1, y: 0.4, width: 0.2, height: 0.1 } },
      ] : [] }], 1200, 'auto', 'uploaded_image',
    ))
  })

  it('ignores an in-flight response after the selected images change', async () => {
    vi.mocked(api.health).mockResolvedValue({ status: 'ok', openai_configured: true, default_provider: 'openai', ocr_provider: 'paddleocr-local-unavailable-on-vercel', public_mode: false })
    vi.mocked(recognizeImages).mockResolvedValue({ pages: [{ text: '첫 번째 공지', spans: [] }], latencyMs: 1200, initializationMs: 500, inferenceMs: 700, ...ocrMetrics })
    let resolveAnalysis!: (value: AnalysisResult) => void
    vi.mocked(api.analyzeClientOcr).mockReturnValue(new Promise((resolve) => { resolveAnalysis = resolve }))
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn().mockReturnValueOnce('blob:first').mockReturnValueOnce('blob:second') })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() })

    const { container } = render(<App />)
    await screen.findByText('Photos are read on your device.')
    const imageInput = container.querySelector('input[multiple]')!
    fireEvent.change(imageInput, { target: { files: [new File(['A'], 'first.png', { type: 'image/png' })] } })
    fireEvent.click(screen.getByRole('button', { name: 'Analyze notice photo' }))
    await waitFor(() => expect(api.analyzeClientOcr).toHaveBeenCalledOnce())
    fireEvent.change(imageInput, { target: { files: [new File(['B'], 'second.png', { type: 'image/png' })] } })
    resolveAnalysis(imageResult)

    await waitFor(() => expect(screen.getByRole('button', { name: 'Analyze 2 pages as one notice' })).toBeEnabled())
    expect(screen.queryByRole('heading', { level: 2, name: 'Test notice' })).not.toBeInTheDocument()
    expect(screen.queryByAltText('Original notice page 1')).not.toBeInTheDocument()
    expect(screen.queryByText('Review recognized text before retrying')).not.toBeInTheDocument()
    expect(screen.getByText('second.png')).toBeInTheDocument()
  })

  it('clears an analyzed result when its selected photo is removed', async () => {
    vi.mocked(api.health).mockResolvedValue({ status: 'ok', openai_configured: true, default_provider: 'openai', ocr_provider: 'paddleocr-local-unavailable-on-vercel', public_mode: false })
    vi.mocked(recognizeImages).mockResolvedValue({ pages: [{ text: '지원 마감', spans: [] }], latencyMs: 1200, initializationMs: 500, inferenceMs: 700, ...ocrMetrics })
    vi.mocked(api.analyzeClientOcr).mockResolvedValue(imageResult)
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn().mockReturnValueOnce('blob:draft').mockReturnValueOnce('blob:result') })
    const revokeUrl = vi.fn()
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: revokeUrl })

    const { container } = render(<App />)
    await screen.findByText('Photos are read on your device.')
    fireEvent.change(container.querySelector('input[multiple]')!, { target: { files: [new File(['photo'], 'notice.png', { type: 'image/png' })] } })
    fireEvent.click(screen.getByRole('button', { name: 'Analyze notice photo' }))
    expect(await screen.findByRole('heading', { level: 2, name: 'Test notice' })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Remove page 1' }))
    expect(screen.queryByRole('heading', { level: 2, name: 'Test notice' })).not.toBeInTheDocument()
    expect(revokeUrl).toHaveBeenCalledWith('blob:result')
  })
})
