import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ImageInputPanel, type ImageDraft } from './ImageInputPanel'

const page: ImageDraft = {
  id: 'page-1',
  file: new File(['image'], 'notice.png', { type: 'image/png' }),
  previewUrl: 'data:image/png;base64,aW1hZ2U=',
  source: 'uploaded_image',
}

describe('ImageInputPanel', () => {
  afterEach(cleanup)

  it('provides a rear-camera input and prominent image actions', () => {
    const { container } = render(<ImageInputPanel pages={[]} demos={[]} status="ready" busy={false} processingImages={false} progressStage={0} ocrCompleted={0} onAdd={vi.fn()} onRemove={vi.fn()} onMove={vi.fn()} onAnalyze={vi.fn()} onLoadDemo={vi.fn()} />)
    expect(screen.getByText('Take a Photo')).toBeInTheDocument()
    expect(screen.getByText('Upload Image')).toBeInTheDocument()
    expect(container.querySelector('input[capture="environment"]')).toHaveAttribute('accept', 'image/*')
  })

  it('shows ordered previews and starts analysis', () => {
    const analyze = vi.fn()
    const move = vi.fn()
    render(<ImageInputPanel pages={[page, { ...page, id: 'page-2', file: new File(['two'], 'page-two.png') }]} demos={[]} status="ready" busy={false} processingImages={false} progressStage={0} ocrCompleted={0} onAdd={vi.fn()} onRemove={vi.fn()} onMove={move} onAnalyze={analyze} onLoadDemo={vi.fn()} />)
    expect(screen.getByText('Page 1')).toBeInTheDocument()
    expect(screen.getByText('Page 2')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Move page 2 earlier' }))
    expect(move).toHaveBeenCalledWith(1, -1)
    fireEvent.click(screen.getByRole('button', { name: 'Analyze 2 pages as one notice' }))
    expect(analyze).toHaveBeenCalled()
  })

  it('explains unsupported browser OCR and prevents image analysis', () => {
    const analyze = vi.fn()
    render(<ImageInputPanel pages={[page]} demos={[]} status="unavailable" busy={false} processingImages={false} progressStage={0} ocrCompleted={0} onAdd={vi.fn()} onRemove={vi.fn()} onMove={vi.fn()} onAnalyze={analyze} onLoadDemo={vi.fn()} />)
    expect(screen.getByRole('status')).toHaveTextContent('Photo analysis is unavailable in this browser.')
    expect(screen.getByRole('button', { name: /Take a Photo/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /Upload Image/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Analyze notice photo' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Analyze notice photo' }))
    expect(analyze).not.toHaveBeenCalled()
  })

  it('shows browser OCR progress and locks page edits while working', () => {
    render(<ImageInputPanel pages={[page]} demos={[]} status="ready" busy processingImages progressStage={0} ocrCompleted={0} onAdd={vi.fn()} onRemove={vi.fn()} onMove={vi.fn()} onAnalyze={vi.fn()} onLoadDemo={vi.fn()} />)
    expect(screen.getByText('Reading pages on this device (0/1)…')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Remove page 1' })).toBeDisabled()
    expect(screen.getByRole('button', { name: /Take a Photo/i })).toBeDisabled()
  })
})
