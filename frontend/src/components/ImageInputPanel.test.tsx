import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ImageInputPanel, type ImageDraft } from './ImageInputPanel'

const page: ImageDraft = {
  id: 'page-1',
  file: new File(['image'], 'notice.png', { type: 'image/png' }),
  previewUrl: 'data:image/png;base64,aW1hZ2U=',
  source: 'uploaded_image',
}

const correctionProps = {
  recoveredPages: null,
  onEditRecoveredPage: vi.fn(),
  onRetryAnalysis: vi.fn(),
}

describe('ImageInputPanel', () => {
  afterEach(cleanup)

  it('provides a rear-camera input and prominent image actions', () => {
    const { container } = render(<ImageInputPanel {...correctionProps} pages={[]} demos={[]} status="ready" busy={false} processingImages={false} progressStage={0} ocrCompleted={0} onAdd={vi.fn()} onRemove={vi.fn()} onMove={vi.fn()} onAnalyze={vi.fn()} onLoadDemo={vi.fn()} />)
    expect(screen.getByText('Take a Photo')).toBeInTheDocument()
    expect(screen.getByText('Upload Image')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('up to four bounded recovery crops can be sent to OpenAI')
    expect(screen.getByRole('status')).toHaveTextContent('Locally decoded QR links are never opened automatically')
    expect(container.querySelector('input[capture="environment"]')).toHaveAttribute('accept', 'image/*')
  })

  it('shows ordered previews and starts analysis', () => {
    const analyze = vi.fn()
    const move = vi.fn()
    render(<ImageInputPanel {...correctionProps} pages={[page, { ...page, id: 'page-2', file: new File(['two'], 'page-two.png') }]} demos={[]} status="ready" busy={false} processingImages={false} progressStage={0} ocrCompleted={0} onAdd={vi.fn()} onRemove={vi.fn()} onMove={move} onAnalyze={analyze} onLoadDemo={vi.fn()} />)
    expect(screen.getByText('Page 1')).toBeInTheDocument()
    expect(screen.getByText('Page 2')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Move page 2 earlier' }))
    expect(move).toHaveBeenCalledWith(1, -1)
    fireEvent.click(screen.getByRole('button', { name: 'Analyze 2 pages as one notice' }))
    expect(analyze).toHaveBeenCalled()
  })

  it('replaces independent notice images while additions stay pages of the same notice', () => {
    const add = vi.fn()
    const { container } = render(<ImageInputPanel {...correctionProps} pages={[page]} demos={[]} status="ready" busy={false} processingImages={false} progressStage={0} ocrCompleted={0} onAdd={add} onRemove={vi.fn()} onMove={vi.fn()} onAnalyze={vi.fn()} onLoadDemo={vi.fn()} />)
    const input = container.querySelector('input[multiple]')!
    const another = new File(['new image'], 'another-notice.png', { type: 'image/png' })
    expect(screen.getByText(/Combine images only when they are pages of the same notice/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Upload another notice' }))
    fireEvent.change(input, { target: { files: [another] } })
    expect(add).toHaveBeenLastCalledWith([another], 'uploaded_image', true)

    fireEvent.click(screen.getByRole('button', { name: 'Add another page' }))
    fireEvent.change(input, { target: { files: [another] } })
    expect(add).toHaveBeenLastCalledWith([another], 'uploaded_image', false)
  })

  it('explains unsupported browser OCR and prevents image analysis', () => {
    const analyze = vi.fn()
    render(<ImageInputPanel {...correctionProps} pages={[page]} demos={[]} status="unavailable" busy={false} processingImages={false} progressStage={0} ocrCompleted={0} onAdd={vi.fn()} onRemove={vi.fn()} onMove={vi.fn()} onAnalyze={analyze} onLoadDemo={vi.fn()} />)
    expect(screen.getByRole('status')).toHaveTextContent('Photo analysis is unavailable in this browser.')
    expect(screen.getByRole('button', { name: /Take a Photo/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /Upload Image/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Analyze notice photo' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Analyze notice photo' }))
    expect(analyze).not.toHaveBeenCalled()
  })

  it('shows browser OCR progress and locks page edits while working', () => {
    render(<ImageInputPanel {...correctionProps} pages={[page]} demos={[]} status="ready" busy processingImages progressStage={0} ocrCompleted={0} onAdd={vi.fn()} onRemove={vi.fn()} onMove={vi.fn()} onAnalyze={vi.fn()} onLoadDemo={vi.fn()} />)
    expect(screen.getByText('Reading pages on this device (0/1)…')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Remove page 1' })).toBeDisabled()
    expect(screen.getByRole('button', { name: /Take a Photo/i })).toBeDisabled()
  })

  it('offers editable OCR text and retry without sending the photo again', () => {
    const edit = vi.fn()
    const retry = vi.fn()
    render(<ImageInputPanel {...correctionProps} pages={[page]} demos={[]} status="ready" busy={false} processingImages={false} progressStage={1} ocrCompleted={1} onAdd={vi.fn()} onRemove={vi.fn()} onMove={vi.fn()} onAnalyze={vi.fn()} onLoadDemo={vi.fn()} recoveredPages={[{ text: '지원 마감', spans: [] }]} onEditRecoveredPage={edit} onRetryAnalysis={retry} />)

    expect(screen.getByRole('link', { name: 'Open page photo' })).toHaveAttribute('href', page.previewUrl)
    expect(screen.getByText(/You can retry without editing Korean/)).toBeInTheDocument()
    fireEvent.change(screen.getByRole('textbox', { name: /Page 1 recognized text/i }), { target: { value: '지원 마감 9월 30일' } })
    expect(edit).toHaveBeenCalledWith(0, '지원 마감 9월 30일')
    fireEvent.click(screen.getByRole('button', { name: 'Retry analysis' }))
    expect(retry).toHaveBeenCalledOnce()
  })

  it('does not retry a page beyond the server text limit', () => {
    render(<ImageInputPanel {...correctionProps} pages={[page]} demos={[]} status="ready" busy={false} processingImages={false} progressStage={1} ocrCompleted={1} onAdd={vi.fn()} onRemove={vi.fn()} onMove={vi.fn()} onAnalyze={vi.fn()} onLoadDemo={vi.fn()} recoveredPages={[{ text: '가'.repeat(20_001), spans: [] }]} />)
    expect(screen.getByRole('button', { name: 'Retry analysis' })).toBeDisabled()
    expect(screen.getByText(/20,001 \/ 20,000/)).toBeInTheDocument()
  })

  it('allows retrying an empty reading without asking the user to enter Korean', () => {
    const retry = vi.fn()
    render(<ImageInputPanel {...correctionProps} pages={[page]} demos={[]} status="ready" busy={false} processingImages={false} progressStage={1} ocrCompleted={1} onAdd={vi.fn()} onRemove={vi.fn()} onMove={vi.fn()} onAnalyze={vi.fn()} onLoadDemo={vi.fn()} recoveredPages={[{ text: '', spans: [] }]} onRetryAnalysis={retry} />)

    expect(screen.getByRole('button', { name: 'Retry analysis' })).toBeEnabled()
    fireEvent.click(screen.getByRole('button', { name: 'Retry analysis' }))
    expect(retry).toHaveBeenCalledOnce()
  })

  it('finds an actionable source correction in the retained page text', () => {
    const corrupted = '문의:02.710.25n0'
    const text = `신청 기간\n${corrupted}`
    render(<ImageInputPanel {...correctionProps} pages={[page]} demos={[]} status="ready" busy={false} processingImages={false} progressStage={1} ocrCompleted={1} onAdd={vi.fn()} onRemove={vi.fn()} onMove={vi.fn()} onAnalyze={vi.fn()} onLoadDemo={vi.fn()} recoveredPages={[{ text, spans: [] }]} sourceCorrections={[{
      page: 1, line: 47, text: corrupted, reason: 'Retype the unreadable telephone digit from the photo.',
    }]} />)
    expect(screen.getByText('Retype the unreadable telephone digit from the photo.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Find in page text' }))
    const input = screen.getByRole('textbox', { name: /Page 1 recognized text/i }) as HTMLTextAreaElement
    expect(input).toHaveFocus()
    expect(input.selectionStart).toBe(text.indexOf(corrupted))
    expect(input.selectionEnd).toBe(text.length)
  })

  it('flags low-confidence lines without suggesting that confidence certifies other text', () => {
    render(<ImageInputPanel {...correctionProps} pages={[page]} demos={[]} status="ready" busy={false} processingImages={false} progressStage={1} ocrCompleted={1} onAdd={vi.fn()} onRemove={vi.fn()} onMove={vi.fn()} onAnalyze={vi.fn()} onLoadDemo={vi.fn()} recoveredPages={[{
      text: '기간입C이끼지', spans: [{ text: '기간입C이끼지', confidence: 0.556, box: { x: 0.8, y: 0.1, width: 0.1, height: 0.03 } }],
    }]} />)
    expect(screen.getByText(/OCR confidence is 56%/)).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: /Page 1 recognized text/i })).toHaveValue('기간입C이끼지')
    expect(screen.getByRole('button', { name: 'Retry analysis' })).toBeEnabled()
  })
})
