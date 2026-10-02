import { describe, expect, it } from 'vitest'
import { layoutText, planTranslationPlacements } from './renderer'
import type { BoundingBox } from '../types'

const measureText = (text: string, fontSize: number) => Array.from(text).length * fontSize * 0.5

function layout(text: string, width: number, height: number, minFontSize = 10, maxFontSize = 24) {
  return layoutText({ text, width, height, minFontSize, maxFontSize, measureText })
}

describe('complete English image text layout', () => {
  it('keeps the full translation while wrapping and reducing font size', () => {
    const text = 'Submit the application and research plan by September 20, 2026.'
    const result = layout(text, 130, 60)
    expect(result.fits).toBe(true)
    expect(result.lines.join(' ')).toBe(text)
    expect(result.fontSize).toBeGreaterThanOrEqual(10)
    expect(result.lines.every((line) => measureText(line, result.fontSize) <= 130)).toBe(true)
    expect(result.lines.length * result.lineHeight).toBeLessThanOrEqual(60)
  })

  it('never deletes characters or adds hyphens to a long URL', () => {
    const text = 'https://example.ac.kr/application/2026-09-20?team=2-5'
    const result = layout(text, 80, 90)
    expect(result.fits).toBe(true)
    expect(result.lines.length).toBeGreaterThan(1)
    expect(result.lines.join('')).toBe(text)
    expect(result.lines.every((line) => measureText(line, result.fontSize) <= 80)).toBe(true)
  })

  it('retains paragraph breaks and every printed test-score value', () => {
    const result = layout('TOEIC 800\nTEPS 309\nOPIc IM3', 160, 100)
    expect(result.fits).toBe(true)
    expect(result.lines).toEqual(['TOEIC 800', 'TEPS 309', 'OPIc IM3'])
  })

  it('reports a legibility failure with the complete text still available', () => {
    const text = 'Participants must be currently enrolled; students on leave cannot receive funding.'
    const result = layout(text, 30, 12)
    expect(result.fits).toBe(false)
    expect(result.fontSize).toBe(10)
    expect(result.lines.join('').replace(/\s/g, '')).toBe(text.replace(/\s/g, ''))
  })

  it('accepts an exact width and height boundary without clipping', () => {
    const result = layout('800', 15, 11.5, 10, 10)
    expect(result.fits).toBe(true)
    expect(result.lines).toEqual(['800'])
    expect(result.fontSize).toBe(10)
  })

  it('rejects a character wider than the original box', () => {
    const result = layout('W', 4, 20, 10, 10)
    expect(result.fits).toBe(false)
    expect(result.lines).toEqual(['W'])
  })

  it('selects the maximum size when it fits', () => {
    expect(layout('Apply', 300, 60).fontSize).toBe(24)
  })

  it('handles Unicode code points without splitting surrogate pairs', () => {
    const text = 'Apply 📚 now'
    const result = layout(text, 25, 60, 10, 10)
    expect(result.fits).toBe(true)
    expect(result.lines.join('').replace(/\s/g, '')).toBe(text.replace(/\s/g, ''))
    expect(result.lines.some((line) => line.includes('📚'))).toBe(true)
  })

  it('reports zero-sized layout boundaries as unfit', () => {
    expect(layout('Apply', 0, 40).fits).toBe(false)
    expect(layout('Apply', 200, 0).fits).toBe(false)
  })
})

describe('neighbor-safe translation placement', () => {
  const first = { id: 'first', box: { x: 0.1, y: 0.2, width: 0.6, height: 0.04 }, replace: true }
  const second = { id: 'second', box: { x: 0.105, y: 0.232, width: 0.5, height: 0.04 }, replace: true }

  function intersects(left: BoundingBox, right: BoundingBox): boolean {
    return Math.min(left.x + left.width, right.x + right.width) - Math.max(left.x, right.x) > 1e-9
      && Math.min(left.y + left.height, right.y + right.height) - Math.max(left.y, right.y) > 1e-9
  }

  it('partitions slight overlap of adjacent tilted lines at their shared midpoint', () => {
    const source = structuredClone([first, second])
    const placements = planTranslationPlacements(source)
    expect(placements.every((placement) => placement.reason === null)).toBe(true)
    expect(placements[0].box?.y).toBe(first.box.y)
    expect(placements[0].box!.y + placements[0].box!.height).toBeCloseTo(0.236)
    expect(placements[1].box?.y).toBeCloseTo(0.236)
    expect(intersects(placements[0].box!, placements[1].box!)).toBe(false)
    expect(source).toEqual([first, second])
  })

  it('does not paint any part of a neighboring region retained as original', () => {
    const placements = planTranslationPlacements([first, { ...second, replace: false }])
    expect(placements[0].box!.y + placements[0].box!.height).toBeCloseTo(second.box.y)
    expect(placements[1].box).toEqual(second.box)
    expect(intersects(placements[0].box!, second.box)).toBe(false)
  })

  it('protects an upper original line when the lower line is translated', () => {
    const placements = planTranslationPlacements([{ ...first, replace: false }, second])
    expect(placements[0].box).toEqual(first.box)
    expect(placements[1].box!.y).toBeCloseTo(first.box.y + first.box.height)
    expect(intersects(first.box, placements[1].box!)).toBe(false)
  })

  it('keeps competing partial crop readings original', () => {
    const placements = planTranslationPlacements([
      first, { id: 'suffix', box: { ...first.box, x: 0.4, width: 0.3 }, replace: true },
    ])
    expect(placements.map((placement) => placement.reason)).toEqual(['overlap', 'overlap'])
    expect(placements.every((placement) => placement.box === null)).toBe(true)
  })

  it('keeps severe vertical overlap original', () => {
    const placements = planTranslationPlacements([first, { ...second, box: { ...second.box, y: 0.21 } }])
    expect(placements.map((placement) => placement.reason)).toEqual(['overlap', 'overlap'])
  })

  it('does not partition crossing columns that happen to overlap', () => {
    const placements = planTranslationPlacements([
      first, { ...second, box: { ...second.box, x: 0.65, width: 0.3 } },
    ])
    expect(placements.map((placement) => placement.reason)).toEqual(['overlap', 'overlap'])
  })

  it('partitions a chain of lines without overlaps or input-order dependence', () => {
    const third = { id: 'third', box: { ...second.box, y: 0.264 }, replace: true }
    const placements = planTranslationPlacements([first, second, third])
    const reversed = planTranslationPlacements([third, second, first])
    expect(placements).toEqual(reversed.reverse())
    for (let index = 1; index < placements.length; index += 1) {
      expect(intersects(placements[index - 1].box!, placements[index].box!)).toBe(false)
    }
  })

  it('uses an original boundary when a neighboring line becomes unrenderable', () => {
    const third = { id: 'third', box: { ...second.box, y: 0.264 }, replace: true }
    const placements = planTranslationPlacements([first, { ...second, replace: false }, third])
    expect(intersects(placements[0].box!, second.box)).toBe(false)
    expect(intersects(placements[2].box!, second.box)).toBe(false)
  })

  it('rejects invalid geometry while preserving unrelated placements', () => {
    const placements = planTranslationPlacements([
      first, { id: 'invalid', box: { x: 0.9, y: 0.5, width: 0.2, height: 0.04 }, replace: true },
    ])
    expect(placements[0]).toEqual({ id: 'first', box: first.box, reason: null })
    expect(placements[1]).toEqual({ id: 'invalid', box: null, reason: 'invalid_box' })
  })
})
