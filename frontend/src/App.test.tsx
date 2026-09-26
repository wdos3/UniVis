import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { api } from './api/client'

vi.mock('./api/client', () => ({
  api: {
    demos: vi.fn(),
    imageDemos: vi.fn(),
    health: vi.fn(),
  },
}))

describe('App availability', () => {
  afterEach(cleanup)

  beforeEach(() => {
    vi.mocked(api.demos).mockResolvedValue([{ id: 'demo', title: 'Synthetic notice', category: 'Example', original_text: '공지', questions: [] }])
    vi.mocked(api.imageDemos).mockResolvedValue([])
  })

  it('keeps text and synthetic notices available when hosted OCR is absent', async () => {
    vi.mocked(api.health).mockResolvedValue({ status: 'ok', openai_configured: false, default_provider: 'mock', ocr_provider: 'paddleocr-local-unavailable-on-vercel', public_mode: true })
    render(<App />)

    expect(await screen.findByText('Photo analysis is unavailable on this website.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Take a Photo/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /Upload text-based PDF or TXT/i })).toBeEnabled()
    expect(await screen.findByRole('button', { name: /Synthetic notice/ })).toBeEnabled()
    expect(screen.queryByRole('button', { name: 'Researcher View' })).not.toBeInTheDocument()

    fireEvent.change(screen.getByPlaceholderText('공지사항의 한국어 텍스트를 여기에 붙여넣으세요…'), { target: { value: '공지' } })
    expect(screen.getByRole('button', { name: 'Generate instructions' })).toBeEnabled()
  })

  it('enables photo controls and local researcher tools when OCR is configured', async () => {
    vi.mocked(api.health).mockResolvedValue({ status: 'ok', openai_configured: true, default_provider: 'openai', ocr_provider: 'paddleocr-ppocrv5-korean-container', public_mode: false })
    render(<App />)

    expect(await screen.findByRole('button', { name: 'Researcher View' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Take a Photo/i })).toBeEnabled()
    expect(screen.getByRole('button', { name: /Upload Image/i })).toBeEnabled()
    expect(screen.getByRole('button', { name: /Upload PDF or TXT/i })).toBeEnabled()
  })
})
