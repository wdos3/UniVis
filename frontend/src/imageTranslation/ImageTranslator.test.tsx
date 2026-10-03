import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api/client'
import { recognizeImages } from '../ocr/browserOcr'
import { makeSourceUnit, pendingLedger } from '../ledger/sourceLedger'
import type { SourceLedger } from '../types'
import { renderTranslatedImage } from './renderer'
import { ImageTranslator } from './ImageTranslator'

vi.mock('../api/client', () => ({ api: { translateLedger: vi.fn(), analyzeLedger: vi.fn() } }))
vi.mock('../ocr/browserOcr', () => ({ isBrowserOcrSupported: () => true, recognizeImages: vi.fn() }))
vi.mock('./renderer', () => ({ renderTranslatedImage: vi.fn() }))

const units = [makeSourceUnit({ id: 'R001', page: 1, text: '신청 기간', order: 0, box: { x: .1, y: .1, width: .4, height: .1 } }),
  makeSourceUnit({ id: 'R002', page: 1, text: '800', order: 1, box: { x: .6, y: .1, width: .2, height: .1 } })]
const ocr = { pages: [{ text: '신청 기간\n800', spans: [], source_units: units }], latencyMs: 100, initializationMs: 0,
  inferenceMs: 100, modelState: 'reused' as const, detectionMs: 50, recognitionMs: 50, detailPasses: 0, recoveryWarnings: [] }
const response: SourceLedger = pendingLedger(units.map((unit, index) => ({ ...unit, english: index ? '800' : 'Application period',
  translation_provider: 'mymemory', translation_status: 'translated', translation_source_ids: [unit.id] })))

function choosePhoto(name = 'notice.jpg') {
  fireEvent.change(screen.getByLabelText('Choose image to translate'), { target: { files: [new File(['photo'], name, { type: 'image/jpeg' })] } })
}

describe('image translation workflow', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(recognizeImages).mockResolvedValue(ocr)
    vi.mocked(api.translateLedger).mockResolvedValue(response)
    vi.stubGlobal('createImageBitmap', vi.fn().mockResolvedValue({ width: 2296, height: 4080, close: vi.fn() }))
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn().mockImplementation(() => `blob:${Math.random()}`) })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() })
    vi.mocked(renderTranslatedImage).mockReturnValue({
      canvas: { toBlob: (callback: BlobCallback) => callback(new Blob(['png'], { type: 'image/png' })) } as HTMLCanvasElement,
      diagnostics: [{ id: 'R001-block', status: 'rendered', reason: 'translated' }, { id: 'R002-block', status: 'original', reason: 'unchanged' }],
    })
  })
  afterEach(() => { cleanup(); vi.unstubAllGlobals() })

  it('sends text and layout with exact source IDs and exports PNG without semantic analysis', async () => {
    render(<ImageTranslator onExit={vi.fn()} />); choosePhoto()
    fireEvent.click(screen.getByRole('button', { name: 'Translate image' }))
    expect(await screen.findByText('1 of 2 source units placed with English in the image')).toBeInTheDocument()
    expect(api.translateLedger).toHaveBeenCalledWith(units, 100, 0, expect.any(AbortSignal))
    expect(api.analyzeLedger).not.toHaveBeenCalled()
    expect(renderTranslatedImage).toHaveBeenCalledWith(expect.objectContaining({ width: 2296, height: 4080,
      regions: [expect.objectContaining({ id: 'R001-block', translatedText: 'Application period', sourceUnitIds: ['R001'] }), expect.anything()] }))
    expect(screen.getByRole('link', { name: 'Download translated PNG' })).toHaveAttribute('download', 'notice-english.png')
    expect(screen.getByText('Application period')).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: 'Show original image' }))
    expect(screen.getByAltText('Original photo to translate')).toBeInTheDocument()
  })

  it('preserves a missing translation unit with its crop and continues drawing unaffected English', async () => {
    vi.mocked(api.translateLedger).mockResolvedValue({ ...response, units: [response.units[0]], blocks: [response.blocks[0]] })
    render(<ImageTranslator onExit={vi.fn()} />); choosePhoto()
    fireEvent.click(screen.getByRole('button', { name: 'Translate image' }))
    await screen.findByRole('link', { name: 'Download translated PNG' })
    expect(screen.getByText('Application period')).toBeVisible()
    expect(screen.getByText('800', { selector: '[lang="en"]' })).toBeVisible()
    expect(screen.getAllByAltText('Preserved source region R002').length).toBeGreaterThan(0)
  })

  it('rejects a foreign ID association without blocking output or repainting its source', async () => {
    vi.mocked(api.translateLedger).mockResolvedValue({ ...response, units: [{ ...response.units[0], id: 'wrong' }, response.units[1]] })
    render(<ImageTranslator onExit={vi.fn()} />); choosePhoto()
    fireEvent.click(screen.getByRole('button', { name: 'Translate image' }))
    await screen.findByRole('link', { name: 'Download translated PNG' })
    expect(renderTranslatedImage).toHaveBeenCalledWith(expect.objectContaining({ regions: expect.arrayContaining([expect.objectContaining({ id: 'R001-block', status: 'failed' })]) }))
    expect(screen.getAllByAltText('Preserved source region R001').length).toBeGreaterThan(0)
  })

  it('shows English beside the crop when image placement fails', async () => {
    vi.mocked(renderTranslatedImage).mockReturnValue({ canvas: { toBlob: (callback: BlobCallback) => callback(new Blob(['png'])) } as HTMLCanvasElement,
      diagnostics: [{ id: 'R001-block', status: 'original', reason: 'too_small' }, { id: 'R002-block', status: 'original', reason: 'overlap' }] })
    render(<ImageTranslator onExit={vi.fn()} />); choosePhoto()
    fireEvent.click(screen.getByRole('button', { name: 'Translate image' }))
    await screen.findByRole('link', { name: 'Download translated PNG' })
    expect(screen.getByText('Application period')).toBeVisible()
    expect(screen.getAllByAltText('Preserved source region R001').length).toBeGreaterThan(0)
  })

  it('ignores OCR from a replaced photo', async () => {
    let finish!: (result: typeof ocr) => void
    vi.mocked(recognizeImages).mockReturnValue(new Promise((resolve) => { finish = resolve }))
    render(<ImageTranslator onExit={vi.fn()} />); choosePhoto('first.jpg')
    fireEvent.click(screen.getByRole('button', { name: 'Translate image' })); choosePhoto('second.jpg')
    await act(async () => finish(ocr))
    expect(api.translateLedger).not.toHaveBeenCalled()
    expect(screen.queryByRole('link', { name: 'Download translated PNG' })).not.toBeInTheDocument()
  })

  it('aborts translation and prevents stale output after replacing the photo', async () => {
    let finish!: (result: SourceLedger) => void
    vi.mocked(api.translateLedger).mockReturnValue(new Promise((resolve) => { finish = resolve }))
    render(<ImageTranslator onExit={vi.fn()} />); choosePhoto('first.jpg')
    fireEvent.click(screen.getByRole('button', { name: 'Translate image' }))
    await waitFor(() => expect(api.translateLedger).toHaveBeenCalledOnce())
    const signal = vi.mocked(api.translateLedger).mock.calls[0][3]!
    choosePhoto('second.jpg'); expect(signal.aborted).toBe(true)
    await act(async () => finish(response))
    expect(renderTranslatedImage).not.toHaveBeenCalled()
  })

  it('releases original and output URLs on exit', async () => {
    const view = render(<ImageTranslator onExit={vi.fn()} />); choosePhoto()
    fireEvent.click(screen.getByRole('button', { name: 'Translate image' }))
    await screen.findByRole('link', { name: 'Download translated PNG' }); view.unmount()
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(2)
  })

  it('reuses OCR for the same photo and reads a newly selected photo again', async () => {
    render(<ImageTranslator onExit={vi.fn()} />); choosePhoto('first.jpg')
    fireEvent.click(screen.getByRole('button', { name: 'Translate image' }))
    await screen.findByRole('link', { name: 'Download translated PNG' })
    fireEvent.click(screen.getByRole('button', { name: 'Translate image' })); await screen.findByText(/OCR reused/)
    expect(recognizeImages).toHaveBeenCalledOnce()
    choosePhoto('second.jpg'); fireEvent.click(screen.getByRole('button', { name: 'Translate image' }))
    await screen.findByRole('link', { name: 'Download translated PNG' }); expect(recognizeImages).toHaveBeenCalledTimes(2)
  })
})
