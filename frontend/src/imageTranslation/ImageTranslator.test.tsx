import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api/client'
import { recognizeImages } from '../ocr/browserOcr'
import { renderTranslatedImage } from './renderer'
import { ImageTranslator } from './ImageTranslator'

vi.mock('../api/client', () => ({ api: { translateImageText: vi.fn(), analyzeClientOcr: vi.fn() } }))
vi.mock('../ocr/browserOcr', () => ({ isBrowserOcrSupported: () => true, recognizeImages: vi.fn() }))
vi.mock('./regions', () => ({ buildTranslationRegions: () => [
  { id: 'R001', sourceText: '신청 기간', box: { x: .1, y: .1, width: .4, height: .1 }, spanCount: 1 },
  { id: 'R002', sourceText: '800', box: { x: .6, y: .1, width: .2, height: .1 }, spanCount: 1 },
] }))
vi.mock('./renderer', () => ({ renderTranslatedImage: vi.fn() }))

const ocr = { pages: [{ text: '신청 기간\n800', spans: [] }], latencyMs: 100, initializationMs: 0,
  inferenceMs: 100, modelState: 'reused' as const, detectionMs: 50, recognitionMs: 50, detailPasses: 0, recoveryWarnings: [] }
const response = { regions: [
  { id: 'R001', source_text: '신청 기간', translated_text: 'Application period', status: 'translated' as const },
  { id: 'R002', source_text: '800', translated_text: '800', status: 'unchanged' as const },
], provider: 'mymemory', request_count: 1, latency_ms: 20, metrics_complete: true }

function choosePhoto(name = 'notice.jpg') {
  fireEvent.change(screen.getByLabelText('Choose image to translate'), {
    target: { files: [new File(['photo'], name, { type: 'image/jpeg' })] },
  })
}

describe('image translation workflow', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(recognizeImages).mockResolvedValue(ocr)
    vi.mocked(api.translateImageText).mockResolvedValue(response)
    vi.stubGlobal('createImageBitmap', vi.fn().mockResolvedValue({ width: 2296, height: 4080, close: vi.fn() }))
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn().mockImplementation(() => `blob:${Math.random()}`) })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() })
    vi.mocked(renderTranslatedImage).mockReturnValue({
      canvas: { toBlob: (callback: BlobCallback) => callback(new Blob(['png'], { type: 'image/png' })) } as HTMLCanvasElement,
      diagnostics: [{ id: 'R001', status: 'rendered', reason: 'translated' }, { id: 'R002', status: 'original', reason: 'unchanged' }],
    })
  })
  afterEach(() => { cleanup(); vi.unstubAllGlobals() })

  it('sends only associated text regions and exports the translated image without semantic analysis', async () => {
    render(<ImageTranslator onExit={vi.fn()} />)
    choosePhoto()
    fireEvent.click(screen.getByRole('button', { name: 'Translate image' }))
    expect(await screen.findByText('1 of 2 regions replaced with English')).toBeInTheDocument()
    expect(api.translateImageText).toHaveBeenCalledWith([{ id: 'R001', text: '신청 기간' }, { id: 'R002', text: '800' }], expect.any(AbortSignal))
    expect(api.analyzeClientOcr).not.toHaveBeenCalled()
    expect(renderTranslatedImage).toHaveBeenCalledWith(expect.objectContaining({ width: 2296, height: 4080,
      regions: [expect.objectContaining({ id: 'R001', translatedText: 'Application period', status: 'translated' }), expect.objectContaining({ id: 'R002', status: 'unchanged' })] }))
    expect(screen.getByRole('link', { name: 'Download translated PNG' })).toHaveAttribute('download', 'notice-english.png')
    fireEvent.click(screen.getByRole('button', { name: 'Show original image' }))
    expect(screen.getByAltText('Original photo to translate')).toBeInTheDocument()
  })

  it('preserves partial translation results and reports the retained source region', async () => {
    vi.mocked(api.translateImageText).mockResolvedValue({ ...response, metrics_complete: false, regions: [
      { ...response.regions[0], status: 'failed', translated_text: '신청 기간', error: 'Free quota reached.' }, response.regions[1],
    ] })
    vi.mocked(renderTranslatedImage).mockReturnValue({ canvas: { toBlob: (callback: BlobCallback) => callback(new Blob(['png'])) } as HTMLCanvasElement,
      diagnostics: [{ id: 'R001', status: 'original', reason: 'failed' }, { id: 'R002', status: 'original', reason: 'unchanged' }] })
    render(<ImageTranslator onExit={vi.fn()} />)
    choosePhoto()
    fireEvent.click(screen.getByRole('button', { name: 'Translate image' }))
    expect(await screen.findByText('0 of 2 regions replaced with English')).toBeInTheDocument()
    expect(screen.getByText(/1 regions kept their original text/)).toBeInTheDocument()
    expect(renderTranslatedImage).toHaveBeenCalledWith(expect.objectContaining({ regions: [expect.objectContaining({ status: 'failed' }), expect.anything()] }))
  })

  it('rejects mismatched IDs before painting source pixels', async () => {
    vi.mocked(api.translateImageText).mockResolvedValue({ ...response, regions: [{ ...response.regions[0], id: 'wrong' }, response.regions[1]] })
    render(<ImageTranslator onExit={vi.fn()} />)
    choosePhoto()
    fireEvent.click(screen.getByRole('button', { name: 'Translate image' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('did not match')
    expect(renderTranslatedImage).not.toHaveBeenCalled()
    expect(screen.getByAltText('Original photo to translate')).toBeInTheDocument()
  })

  it('ignores OCR from a replaced photo and does not translate stale text', async () => {
    let finish!: (result: typeof ocr) => void
    vi.mocked(recognizeImages).mockReturnValue(new Promise((resolve) => { finish = resolve }))
    render(<ImageTranslator onExit={vi.fn()} />)
    choosePhoto('first.jpg')
    fireEvent.click(screen.getByRole('button', { name: 'Translate image' }))
    choosePhoto('second.jpg')
    await act(async () => finish(ocr))
    expect(api.translateImageText).not.toHaveBeenCalled()
    expect(screen.queryByRole('link', { name: 'Download translated PNG' })).not.toBeInTheDocument()
    expect(screen.getByText('second.jpg · Original')).toBeInTheDocument()
  })

  it('aborts translation and prevents stale output after replacing the photo', async () => {
    let finish!: (result: typeof response) => void
    vi.mocked(api.translateImageText).mockReturnValue(new Promise((resolve) => { finish = resolve }))
    render(<ImageTranslator onExit={vi.fn()} />)
    choosePhoto('first.jpg')
    fireEvent.click(screen.getByRole('button', { name: 'Translate image' }))
    await waitFor(() => expect(api.translateImageText).toHaveBeenCalledOnce())
    const signal = vi.mocked(api.translateImageText).mock.calls[0][1]!
    choosePhoto('second.jpg')
    expect(signal.aborted).toBe(true)
    await act(async () => finish(response))
    expect(renderTranslatedImage).not.toHaveBeenCalled()
    expect(screen.getByText('second.jpg · Original')).toBeInTheDocument()
  })

  it('releases original and output URLs on exit', async () => {
    const view = render(<ImageTranslator onExit={vi.fn()} />)
    choosePhoto()
    fireEvent.click(screen.getByRole('button', { name: 'Translate image' }))
    await screen.findByRole('link', { name: 'Download translated PNG' })
    view.unmount()
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(2)
  })

  it('reuses OCR for the same photo and reads a newly selected photo again', async () => {
    render(<ImageTranslator onExit={vi.fn()} />)
    choosePhoto('first.jpg')
    fireEvent.click(screen.getByRole('button', { name: 'Translate image' }))
    await screen.findByRole('link', { name: 'Download translated PNG' })
    fireEvent.click(screen.getByRole('button', { name: 'Translate image' }))
    await screen.findByText(/OCR reused/)
    expect(recognizeImages).toHaveBeenCalledOnce()
    expect(api.translateImageText).toHaveBeenCalledTimes(2)

    choosePhoto('second.jpg')
    fireEvent.click(screen.getByRole('button', { name: 'Translate image' }))
    await screen.findByRole('link', { name: 'Download translated PNG' })
    expect(recognizeImages).toHaveBeenCalledTimes(2)
    expect(screen.queryByText(/OCR reused/)).not.toBeInTheDocument()
  })
})
