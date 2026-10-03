import { api } from '../api/client'
import type { SourceLedger, SourceUnit } from '../types'
import { fallbackLedger, pendingLedger, reconcileLedger } from './sourceLedger'

export function ledgerTranslationBatches(units: SourceUnit[]): SourceUnit[][] {
  const batches: SourceUnit[][] = []
  let batch: SourceUnit[] = []; let textSize = 0; let candidateSize = 0
  for (const unit of units) {
    const alternatives = unit.alternatives.reduce((size, candidate) => size + candidate.text.length, 0)
    if (batch.length && (batch.length === 4000 || textSize + unit.source_text.length > 150000 || candidateSize + alternatives > 300000)) {
      batches.push(batch); batch = []; textSize = 0; candidateSize = 0
    }
    batch.push(unit); textSize += unit.source_text.length; candidateSize += alternatives
  }
  if (batch.length) batches.push(batch)
  return batches
}

/** Bounded batches reconcile exact source IDs and retain failed batch evidence. */
export async function translateSourceLedger(original: SourceLedger, signal?: AbortSignal): Promise<SourceLedger> {
  const batches = ledgerTranslationBatches(original.units)
  const results: SourceLedger[] = []
  // Two API requests at a time keep backend/provider concurrency bounded.
  for (let offset = 0; offset < batches.length; offset += 2) {
    if (signal?.aborted) throw new DOMException('Translation was cancelled.', 'AbortError')
    results.push(...await Promise.all(batches.slice(offset, offset + 2).map(async (units) => {
      const source = pendingLedger(units, original.metrics.ocr_ms, original.metrics.layout_ms)
      try {
        return reconcileLedger(source, await api.translateLedger(units, original.metrics.ocr_ms, original.metrics.layout_ms, signal))
      } catch (problem) {
        if (signal?.aborted) throw problem
        return { ...fallbackLedger(source), metrics: { ...source.metrics, usage_complete: false } }
      }
    })))
  }
  if (!results.length) return fallbackLedger(original)
  if (results.length === 1) return results[0]
  const units = results.flatMap((result, index) => result.units.map((unit) => ({ ...unit, block_id: `batch-${index + 1}-${unit.block_id}` })))
  const blocks = results.flatMap((result, index) => result.blocks.map((block) => ({ ...block, id: `batch-${index + 1}-${block.id}` })))
  return { ...original, units, blocks,
    coverage: { ...original.coverage, translated_unit_ids: results.flatMap((result) => result.coverage.translated_unit_ids),
      fallback_unit_ids: results.flatMap((result) => result.coverage.fallback_unit_ids) },
    metrics: { ...original.metrics, layout_ms: results.reduce((total, result) => total + result.metrics.layout_ms, 0),
      translation_ms: results.reduce((total, result) => total + result.metrics.translation_ms, 0),
      validation_ms: results.reduce((total, result) => total + result.metrics.validation_ms, 0),
      translation_requests: results.reduce((total, result) => total + result.metrics.translation_requests, 0),
      usage_complete: results.every((result) => result.metrics.usage_complete) },
  }
}
