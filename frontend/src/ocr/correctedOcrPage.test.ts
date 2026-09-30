import { describe, expect, it } from 'vitest'
import { correctedOcrPage } from './correctedOcrPage'
import type { BrowserOcrPage } from './browserOcr'

const box = { x: 0.1, y: 0.2, width: 0.3, height: 0.04 }
const page: BrowserOcrPage = {
  text: 'seal noise\nTOEIC\n800 이상\nTEPS\n310 이상',
  spans: ['seal noise', 'TOEIC', '800 이상', 'TEPS', '310 이상'].map((text, index) => ({
    text, box: { ...box, y: box.y + index * 0.1 }, confidence: index === 0 ? 0.55 : 0.99,
  })),
}

describe('corrected OCR positions', () => {
  it('retains unchanged score-table positions when a corrupt seal line is removed', () => {
    const corrected = correctedOcrPage(page, 'TOEIC\n800 이상\nTEPS\n310 이상')
    expect(corrected.spans).toEqual(page.spans.slice(1))
  })

  it('preserves an in-place corrected line position but drops the old OCR confidence', () => {
    const corrected = correctedOcrPage(page, 'seal noise\nTOEIC\n850 이상\nTEPS\n310 이상')
    expect(corrected.spans[2]).toEqual({ text: '850 이상', box: page.spans[2].box })
    expect(corrected.spans[1]).toEqual(page.spans[1])
  })

  it('does not assign source positions to newly inserted text', () => {
    const corrected = correctedOcrPage(page, `${page.text}\nContact the office`)
    expect(corrected.spans).toEqual(page.spans)
  })

  it('discards geometry when source lines are reordered', () => {
    const corrected = correctedOcrPage(page, 'seal noise\nTEPS\n310 이상\nTOEIC\n800 이상')
    expect(corrected.spans).toEqual([])
  })

  it('does not guess positions for ambiguous duplicate lines', () => {
    const repeated = { text: 'Heading\nSame\nSame', spans: [
      { text: 'Heading', box }, { text: 'Same', box }, { text: 'Same', box: { ...box, y: 0.7 } },
    ] }
    expect(correctedOcrPage(repeated, 'Heading\nSame').spans).toEqual([{ text: 'Heading', box }])
  })
})
