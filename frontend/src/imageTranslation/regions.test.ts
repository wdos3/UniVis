import { describe, expect, it } from 'vitest'
import type { OcrSpan } from '../types'
import { buildTranslationRegions } from './regions'

function span(text: string, x: number, y: number, width = 0.4, height = 0.03, confidence?: number): OcrSpan {
  return { text, box: { x, y, width, height }, ...(confidence !== undefined ? { confidence } : {}) }
}

describe('positioned translation regions', () => {
  it('chooses the higher confidence repeated crop reading even when words differ', () => {
    const regions = buildTranslationRegions([
      span('신청기긴', 0.1, 0.2, 0.3, 0.03, 0.7),
      span('신청기간', 0.102, 0.201, 0.299, 0.03, 0.98),
    ])
    expect(regions).toEqual([{
      id: 'region-1', sourceText: '신청기간',
      box: { x: 0.102, y: 0.201, width: 0.299, height: 0.03 },
      confidence: 0.98, spanCount: 1,
    }])
  })

  it('retains the same printed value at distinct positions', () => {
    const regions = buildTranslationRegions([span('800', 0.1, 0.2), span('800', 0.1, 0.6)])
    expect(regions.map((region) => region.sourceText)).toEqual(['800', '800'])
  })

  it('deduplicates complete matching crop text with a leading bullet and different box height', () => {
    const regions = buildTranslationRegions([
      span('·학력,전공,성별,연령제한 없음', 0.51, 0.49, 0.195, 0.009, 0.98),
      span('학력,전공,성별,연령제한 없음', 0.522, 0.488, 0.183, 0.013, 0.99),
    ])
    expect(regions).toHaveLength(1)
    expect(regions[0].sourceText).toBe('학력,전공,성별,연령제한 없음')
    expect(regions[0].confidence).toBe(0.99)
  })

  it('normalizes repeated whitespace and a leading dot bullet without removing interior text', () => {
    const regions = buildTranslationRegions([
      span('• Submit  application and  plan by 2026.09.20', 0.1, 0.2, 0.6, 0.02, 0.95),
      span('Submit application and plan by 2026.09.20', 0.12, 0.198, 0.58, 0.026, 0.99),
    ])
    expect(regions).toHaveLength(1)
    expect(regions[0].sourceText).toBe('Submit application and plan by 2026.09.20')
  })

  it('keeps identical wording on distinct adjacent rows', () => {
    const regions = buildTranslationRegions([
      span('800 이상', 0.1, 0.2, 0.15, 0.02),
      span('800 이상', 0.1, 0.222, 0.15, 0.02),
      span('기준', 0.4, 0.2, 0.1, 0.02),
      span('기준', 0.4, 0.222, 0.1, 0.02),
    ])
    expect(regions.map((region) => region.sourceText)).toEqual(['800 이상', '기준', '800 이상', '기준'])
  })

  it('does not use the complete-text relaxation for partial or conflicting values', () => {
    const regions = buildTranslationRegions([
      span('·TOEIC 800 이상', 0.1, 0.2, 0.3, 0.02, 0.98),
      span('TOEIC 850 이상', 0.12, 0.198, 0.28, 0.027, 0.99),
    ])
    expect(regions.map((region) => region.sourceText)).toEqual(['TOEIC 850 이상', '·TOEIC 800 이상'])
  })

  it.each([
    ['TOEIC800이상', 'TOEIC850이상'],
    ['2026.09.20까지 제출', '2026.09.21까지 제출'],
    ['18:00 마감', '18:30 마감'],
    ['FLEX 2B 이상', 'FLEX 2C 이상'],
    ['OPIc IM3 이상', 'OPIc IM2 이상'],
    ['1,000,000원 지원', '1,100,000원 지원'],
    ['-150원', '150원'],
  ])('retains competing printed values in nearly identical boxes: %s versus %s', (first, second) => {
    const regions = buildTranslationRegions([
      span(first, 0.1, 0.2, 0.3, 0.02, 0.98),
      span(second, 0.101, 0.2005, 0.3, 0.02, 0.99),
    ])
    expect(regions).toHaveLength(2)
    expect(regions.map((region) => region.sourceText)).toEqual([first, second])
  })

  it('deduplicates an exact repeated score instead of treating it as a value conflict', () => {
    const regions = buildTranslationRegions([
      span('·OPIc IM3 이상', 0.1, 0.2, 0.3, 0.02, 0.98),
      span('OPIc IM3 이상', 0.101, 0.2005, 0.3, 0.02, 0.99),
    ])
    expect(regions).toHaveLength(1)
    expect(regions[0].sourceText).toBe('OPIc IM3 이상')
  })

  it('retains numbered punctuation distinctions in matching text', () => {
    const regions = buildTranslationRegions([
      span('1. Required documents', 0.1, 0.2, 0.3, 0.02, 0.98),
      span('Required documents', 0.12, 0.198, 0.28, 0.027, 0.99),
    ])
    expect(regions).toHaveLength(2)
    expect(regions.map((region) => region.sourceText)).toContain('1. Required documents')
  })

  it('retains interior bullets rather than treating them as list-marker noise', () => {
    const regions = buildTranslationRegions([
      span('collection · use consent', 0.1, 0.2, 0.3, 0.02, 0.98),
      span('collection use consent', 0.12, 0.198, 0.28, 0.027, 0.99),
    ])
    expect(regions).toHaveLength(2)
    expect(regions.map((region) => region.sourceText)).toContain('collection · use consent')
  })

  it('retains a complete sentence when a higher-confidence crop reads only its suffix', () => {
    const regions = buildTranslationRegions([
      span('재학생은 신청 가능하며 휴학생은 지원금 지급 제외', 0.1, 0.2, 0.6, 0.03, 0.85),
      span('휴학생은 지원금 지급 제외', 0.4, 0.2, 0.3, 0.03, 0.99),
    ])
    expect(regions).toHaveLength(2)
    expect(regions[0].sourceText).toBe('재학생은 신청 가능하며 휴학생은 지원금 지급 제외')
    expect(regions[0].box).toEqual({ x: 0.1, y: 0.2, width: 0.6, height: 0.03 })
    expect(regions[1].sourceText).toBe('휴학생은 지원금 지급 제외')
  })

  it('does not confuse a shifted partial line with a duplicate despite comparable widths', () => {
    const regions = buildTranslationRegions([
      span('연구 기자재 구매 및 대여 비용', 0.1, 0.2, 0.6, 0.03, 0.85),
      span('기자재 구매 및 대여 비용', 0.16, 0.2, 0.54, 0.03, 0.99),
    ])
    expect(regions.map((region) => region.sourceText)).toEqual(['연구 기자재 구매 및 대여 비용', '기자재 구매 및 대여 비용'])
  })

  it('joins closely aligned wrapped text and retains every line and literal', () => {
    const regions = buildTranslationRegions([
      span('신청서 및 연구계획서를', 0.1, 0.2, 0.6, 0.03, 0.99),
      span('2026.09.20까지 제출', 0.1, 0.242, 0.4, 0.03, 0.95),
    ])
    expect(regions).toHaveLength(1)
    expect(regions[0].sourceText).toBe('신청서 및 연구계획서를\n2026.09.20까지 제출')
    expect(regions[0].spanCount).toBe(2)
    expect(regions[0].confidence).toBe(0.95)
    expect(regions[0].box.height).toBeCloseTo(0.072)
  })

  it('keeps table rows and columns separate even with close aligned cells', () => {
    const regions = buildTranslationRegions([
      span('TOEIC', 0.1, 0.2, 0.2), span('800 이상', 0.4, 0.2, 0.2),
      span('TEPS', 0.1, 0.242, 0.2), span('309 이상', 0.4, 0.242, 0.2),
    ])
    expect(regions.map((region) => region.sourceText)).toEqual(['TOEIC', '800 이상', 'TEPS', '309 이상'])
  })

  it('keeps broad table cells separate even when geometry resembles wrapped paragraphs', () => {
    const regions = buildTranslationRegions([
      span('신청 자격 및 제출 서류', 0.03, 0.2, 0.4, 0.025),
      span('지원 금액 및 지급 방법', 0.57, 0.2, 0.4, 0.025),
      span('재학생 신청 가능', 0.03, 0.238, 0.35, 0.025),
      span('휴학생 지급 제외', 0.57, 0.238, 0.35, 0.025),
    ])
    expect(regions).toHaveLength(4)
    expect(regions.map((region) => region.spanCount)).toEqual([1, 1, 1, 1])
    expect(regions.map((region) => region.sourceText)).toEqual([
      '신청 자격 및 제출 서류', '지원 금액 및 지급 방법', '재학생 신청 가능', '휴학생 지급 제외',
    ])
  })

  it('does not merge independent columns or different font heights', () => {
    const regions = buildTranslationRegions([
      span('왼쪽 제목', 0.1, 0.1, 0.3, 0.06),
      span('작은 글씨', 0.1, 0.17, 0.3, 0.02),
      span('오른쪽 내용', 0.6, 0.22, 0.3, 0.02),
    ])
    expect(regions).toHaveLength(3)
  })

  it('does not group across a nearby independent text box', () => {
    const regions = buildTranslationRegions([
      span('첫 번째 긴 줄', 0.1, 0.2, 0.6),
      span('둘째 줄', 0.1, 0.247, 0.3),
      span('별도 주석', 0.45, 0.238, 0.2, 0.01),
    ])
    expect(regions.find((region) => region.sourceText.includes('첫 번째'))?.spanCount).toBe(1)
    expect(regions.map((region) => region.sourceText).join('\n')).toContain('별도 주석')
  })

  it('retains close independent short labels rather than merging into a following sentence', () => {
    const regions = buildTranslationRegions([
      span('대상', 0.1, 0.2, 0.07),
      span('재학생 2–5인 팀', 0.1, 0.242, 0.4),
    ])
    expect(regions).toHaveLength(2)
  })

  it('keeps Latin text, numeric values, and all valid geometry unchanged', () => {
    const source = [span('TOEFL iBT', 0.6, 0.4), span('91', 0.1, 0.2), span('office@example.ac.kr', 0.1, 0.7)]
    const copy = structuredClone(source)
    expect(buildTranslationRegions(source).map((region) => region.sourceText)).toEqual(['91', 'TOEFL iBT', 'office@example.ac.kr'])
    expect(source).toEqual(copy)
  })

  it('ignores empty and invalid boxes rather than covering arbitrary pixels', () => {
    expect(buildTranslationRegions([
      span('', 0.1, 0.2), span('off-page', 0.9, 0.2, 0.2), span('invalid', NaN, 0.3),
      span('zero area', 0.1, 0.4, 0), span('valid', 0.1, 0.8),
    ]).map((region) => region.sourceText)).toEqual(['valid'])
  })
})
