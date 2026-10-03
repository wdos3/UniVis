import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { api } from './api/client'
import { recognizeImages } from './ocr/browserOcr'
import { makeSourceUnit, pendingLedger } from './ledger/sourceLedger'
import type { AnalysisResult } from './types'

vi.mock('./api/client', async (importOriginal) => ({ ...await importOriginal<typeof import('./api/client')>(),
  api: { demos: vi.fn(), imageDemos: vi.fn(), health: vi.fn(), translateLedger: vi.fn(), analyzeLedger: vi.fn(), analyzeClientOcr: vi.fn() } }))
vi.mock('./ocr/browserOcr', () => ({ isBrowserOcrSupported: () => true, recognizeImages: vi.fn() }))
vi.mock('./ledger/crops', () => ({ recoveryCrops: async () => [] }))

const unit = makeSourceUnit({ page: 1, text: '재학생 신청 가능', order: 0, id: 'eligible', box: { x: .1, y: .2, width: .5, height: .03 }, confidence: .99 })
const ledger = pendingLedger([{ ...unit, english: 'Enrolled students may apply.', translation_status: 'translated', translation_source_ids: ['eligible'] }])
const ocr = { pages: [{ text: unit.source_text, spans: [], source_units: [unit] }], latencyMs: 20, initializationMs: 0, inferenceMs: 20,
  modelState: 'reused' as const, detectionMs: 10, recognitionMs: 10, detailPasses: 0, recoveryWarnings: [] }

function addPhoto(container: HTMLElement, name = 'notice.png') {
  fireEvent.change(container.querySelector('input[multiple]')!, { target: { files: [new File(['image'], name, { type: 'image/png' })] } })
}

describe('progressive source ledger photo flow', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.demos).mockResolvedValue([]); vi.mocked(api.imageDemos).mockResolvedValue([])
    vi.mocked(api.health).mockResolvedValue({ status: 'ok', openai_configured: true, default_provider: 'openai', ocr_provider: 'browser', public_mode: true })
    vi.mocked(recognizeImages).mockResolvedValue(ocr)
    vi.mocked(api.translateLedger).mockResolvedValue(ledger)
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn().mockImplementation(() => `blob:${Math.random()}`) })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() })
  })
  afterEach(() => { cleanup(); vi.restoreAllMocks() })

  it('shows source translation before semantic completion and keeps it after a semantic failure', async () => {
    let fail!: (error: Error) => void
    vi.mocked(api.analyzeLedger).mockReturnValue(new Promise((_resolve, reject) => { fail = reject }))
    const { container } = render(<App />)
    await screen.findByText('Photos are read on your device.')
    addPhoto(container); fireEvent.click(screen.getByRole('button', { name: 'Analyze notice photo' }))
    expect(await screen.findByText('Enrolled students may apply.')).toBeVisible()
    await waitFor(() => expect(api.analyzeLedger).toHaveBeenCalledOnce())
    expect(api.analyzeClientOcr).not.toHaveBeenCalled()
    expect(api.translateLedger).toHaveBeenCalledWith([expect.objectContaining({ id: 'eligible', image_id: expect.any(String) })], 20, 0, undefined)
    await act(async () => fail(new Error('Provider connection ended')))
    expect(screen.getByText('Enrolled students may apply.')).toBeVisible()
    expect(screen.getByText(/The source translation remains available/)).toBeInTheDocument()
    expect(screen.queryByText('Some details could not be verified.')).not.toBeInTheDocument()
    expect(screen.queryByText('Retry without Korean transcription')).not.toBeInTheDocument()
  })

  it('does not attach an in-flight ledger or semantic response to replacement photos', async () => {
    let finish!: (value: AnalysisResult) => void
    vi.mocked(api.analyzeLedger).mockReturnValue(new Promise((resolve) => { finish = resolve }))
    const { container } = render(<App />)
    await screen.findByText('Photos are read on your device.')
    addPhoto(container, 'first.png'); fireEvent.click(screen.getByRole('button', { name: 'Analyze notice photo' }))
    await screen.findByText('Enrolled students may apply.')
    await waitFor(() => expect(api.analyzeLedger).toHaveBeenCalledOnce())
    addPhoto(container, 'second.png')
    await act(async () => finish({ source_ledger: ledger } as AnalysisResult))
    expect(screen.queryByText('Enrolled students may apply.')).not.toBeInTheDocument()
    expect(screen.getByText('second.png')).toBeInTheDocument()
  })

  it('keeps photo capture available when health or translation connections fail', async () => {
    vi.mocked(api.health).mockRejectedValue(new Error('Network offline'))
    vi.mocked(api.translateLedger).mockRejectedValue(new Error('Translation offline'))
    vi.mocked(api.analyzeLedger).mockRejectedValue(new Error('Semantic offline'))
    const { container } = render(<App />)
    await screen.findByText(/Server connection is unavailable/)
    expect(screen.getByRole('button', { name: /Upload Image/ })).toBeEnabled()
    addPhoto(container); fireEvent.click(screen.getByRole('button', { name: 'Analyze notice photo' }))
    expect(await screen.findByText('Text from this source region is preserved below.')).toBeVisible()
    expect(screen.getAllByAltText('Preserved source region eligible')[0]).toHaveAttribute('src', expect.stringMatching(/^blob:/))
    expect(await screen.findByText(/The source translation remains available/)).toBeInTheDocument()
  })
})
