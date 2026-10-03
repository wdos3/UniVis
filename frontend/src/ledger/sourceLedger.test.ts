import { describe, expect, it } from 'vitest'
import type { OcrResult } from '@paddleocr/paddleocr-js'
import { captureSourceUnits, fallbackLedger, makeSourceUnit, mergeSourceObservations, pendingLedger, reconcileLedger, recordLedgerDisplay } from './sourceLedger'

const first = makeSourceUnit({ id: 'first', page: 1, text: '신청 가능', order: 0, box: { x: .1, y: .2, width: .5, height: .03 }, confidence: .8 })
const second = makeSourceUnit({ id: 'second', page: 1, text: '2026.09.20 18:00', order: 1, box: { x: .1, y: .3, width: .5, height: .03 } })
const original = pendingLedger([first, second])
const translated = pendingLedger([first, second].map((unit) => ({ ...unit, english: unit.id === 'first' ? 'Applications allowed' : unit.source_text,
  translation_source_ids: [unit.id], translation_status: 'translated' as const })))

describe('source ledger preservation', () => {
  it('captures skewed polygons, multiline/long text and unpositioned observations without span limits', () => {
    const long = '가'.repeat(501)
    const result = { image: { width: 1000, height: 2000 }, items: [
      { text: '조건\n신청 불가', score: .5, poly: [[10, 20], [200, 25], [200, 45], [10, 40]] },
      { text: long, score: .9 },
      ...Array.from({ length: 260 }, (_, index) => ({ text: `항목 ${index}`, score: .99 })),
    ] } as OcrResult
    const units = captureSourceUnits(result, 2)
    expect(units).toHaveLength(262)
    expect(units[0]).toMatchObject({ source_text: '조건\n신청 불가', page_number: 2, polygon: [{ x: .01, y: .01 }, { x: .2, y: .0125 }, { x: .2, y: .0225 }, { x: .01, y: .02 }] })
    expect(units[1].source_text).toBe(long)
    expect(units[1].box).toBeNull()
    expect(captureSourceUnits(result, 2).map((unit) => unit.id)).toEqual(units.map((unit) => unit.id))
  })

  it('attaches conflicting high-confidence negation reads as alternatives without deleting original text', () => {
    const alternative = { ...first, id: 'detail', source_text: '신청 불가', confidence: .99, alternatives: [{ text: '신청 불가', confidence: .99, pass_name: 'detail' }] }
    const merged = mergeSourceObservations([first], [alternative])
    expect(merged).toHaveLength(1)
    expect(merged[0].id).toBe(first.id)
    expect(merged[0].source_text).toBe('신청 가능')
    expect(merged[0].alternatives.map((candidate) => candidate.text)).toEqual(['신청 가능', '신청 불가'])
  })

  it('keeps partial crop readings as separate physical evidence', () => {
    const partial = { ...first, id: 'partial', box: { x: .4, y: .2, width: .2, height: .03 }, source_text: '불가' }
    expect(mergeSourceObservations([first], [partial])).toHaveLength(2)
  })

  it('maps reordered translation responses by exact source IDs', () => {
    const reconciled = reconcileLedger(original, { ...translated, units: [...translated.units].reverse() })
    expect(reconciled.units.map((unit) => [unit.id, unit.english])).toEqual([['first', 'Applications allowed'], ['second', '2026.09.20 18:00']])
  })

  it.each(['missing', 'duplicate', 'changed_source', 'unmapped', 'foreign_mapping', 'duplicate_mapping', 'korean_english'])('preserves units after a %s response defect', (defect) => {
    const candidate = structuredClone(translated)
    if (defect === 'missing') { candidate.units = candidate.units.slice(1); candidate.blocks = candidate.blocks.slice(1) }
    if (defect === 'duplicate') candidate.units.push(candidate.units[0])
    if (defect === 'changed_source') candidate.units[0].source_text = '신청 불가'
    if (defect === 'unmapped') candidate.units[0].translation_source_ids = ['second']
    if (defect === 'foreign_mapping') candidate.units[0].translation_source_ids = ['first', 'foreign']
    if (defect === 'duplicate_mapping') candidate.units[0].translation_source_ids = ['first', 'first']
    if (defect === 'korean_english') candidate.units[0].english = 'Applications 가능'
    const reconciled = recordLedgerDisplay(reconcileLedger(original, candidate), ['first', 'second'], 0)
    expect(reconciled.units).toHaveLength(2)
    expect(reconciled.units[0].source_text).toBe('신청 가능')
    expect(reconciled.units[0].translation_status).toBe('source_crop')
    expect(reconciled.coverage.displayed_unit_ids).toEqual(['first', 'second'])
    expect(reconciled.coverage.translated_unit_ids).not.toContain('first')
  })

  it('uses source crops when no source reading exists without fabricating text', () => {
    const blank = makeSourceUnit({ page: 1, text: '', order: 0 })
    const ledger = fallbackLedger(pendingLedger([blank]))
    expect(ledger.units[0].source_text).toBe('')
    expect(ledger.units[0].translation_status).toBe('source_crop')
    expect(ledger.coverage.fallback_unit_ids).toEqual([blank.id])
  })

  it('keeps local image identity authoritative and display coverage tied to local reconciliation', () => {
    const response = structuredClone(translated)
    Object.assign(response.units[0], { image_id: 'other-photo', page_number: 99, order: 999, confidence: 1 })
    response.coverage.displayed_unit_ids = ['first', 'second']
    const ledger = reconcileLedger(original, response)
    expect(ledger.units[0]).toMatchObject({ image_id: first.image_id, page_number: first.page_number, order: first.order, confidence: first.confidence })
    expect(ledger.coverage.displayed_unit_ids).toEqual([])
  })

  it('preserves semantic fallback provenance separately from accepted semantic IDs', () => {
    const response = { ...translated, coverage: { ...translated.coverage, semantic_unit_ids: ['first'], fallback_unit_ids: ['second'] } }
    const ledger = reconcileLedger(original, response)
    expect(ledger.coverage.semantic_unit_ids).toEqual(['first'])
    expect(ledger.coverage.fallback_unit_ids).toEqual(['second'])
    expect(ledger.coverage.displayed_unit_ids).toEqual([])
  })
})
