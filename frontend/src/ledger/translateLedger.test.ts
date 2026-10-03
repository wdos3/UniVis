import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api/client'
import { makeSourceUnit, pendingLedger } from './sourceLedger'
import { ledgerTranslationBatches, translateSourceLedger } from './translateLedger'

vi.mock('../api/client', () => ({ api: { translateLedger: vi.fn() } }))
beforeEach(() => vi.clearAllMocks())

describe('bounded source-mapped translation batches', () => {
  it('preserves provider-stage timing separately from client request wait', async () => {
    const source = pendingLedger([makeSourceUnit({ page: 1, text: '신청', order: 0 })])
    vi.mocked(api.translateLedger).mockResolvedValue({ ...source, metrics: { ...source.metrics, translation_ms: 17, layout_ms: 3, validation_ms: 5 } })
    const result = await translateSourceLedger(source)
    expect(result.metrics).toMatchObject({ translation_ms: 17, layout_ms: 3, validation_ms: 5 })
  })

  it('batches oversized inventories without dropping or reordering source IDs', () => {
    const units = Array.from({ length: 4001 }, (_, order) => makeSourceUnit({ page: 1, text: `source ${order}`, order, id: `unit-${order}` }))
    const batches = ledgerTranslationBatches(units)
    expect(batches.map((batch) => batch.length)).toEqual([4000, 1])
    expect(batches.flat().map((unit) => unit.id)).toEqual(units.map((unit) => unit.id))
  })

  it('retains failed-batch evidence while continuing other translations', async () => {
    const units = Array.from({ length: 9 }, (_, order) => makeSourceUnit({ page: 1, text: '가'.repeat(20000), order, id: `unit-${order}` }))
    vi.mocked(api.translateLedger).mockImplementation(async (batch) => {
      if (batch[0].id === 'unit-0') throw new Error('Temporary provider failure')
      const ledger = pendingLedger(batch.map((unit) => ({ ...unit, english: 'Translated source', translation_status: 'translated', translation_source_ids: [unit.id] })))
      return { ...ledger, metrics: { ...ledger.metrics, translation_ms: 13, validation_ms: 7 } }
    })
    const result = await translateSourceLedger(pendingLedger(units))
    expect(api.translateLedger).toHaveBeenCalledTimes(2)
    expect(result.units.map((unit) => unit.id)).toEqual(units.map((unit) => unit.id))
    expect(result.units[0].translation_status).toBe('source_crop')
    expect(result.units[8].english).toBe('Translated source')
    expect(new Set(result.blocks.map((block) => block.id)).size).toBe(result.blocks.length)
    expect(result.metrics.usage_complete).toBe(false)
    expect(result.metrics).toMatchObject({ translation_ms: 13, validation_ms: 7 })
  })
})
