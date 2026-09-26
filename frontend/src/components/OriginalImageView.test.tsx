import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AnalysisResult } from '../types'
import { OriginalImageView } from './OriginalImageView'

const result = { id: 'notice-1', recovered_text: '공지사항', source_pages: [] } as unknown as AnalysisResult

describe('OriginalImageView editing', () => {
  afterEach(cleanup)

  it('shows recovered text without editing controls in public mode', () => {
    render(<OriginalImageView result={result} provider="auto" editable={false} onUpdated={vi.fn()} />)
    expect(screen.getByText('공지사항')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Edit recovered text' })).not.toBeInTheDocument()
  })

  it('keeps local editing available', () => {
    render(<OriginalImageView result={result} provider="auto" editable onUpdated={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Edit recovered text' }))
    expect(screen.getByRole('button', { name: 'Save & regenerate outputs' })).toBeEnabled()
  })
})
