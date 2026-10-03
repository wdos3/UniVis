import type { OcrResult, OcrResultItem } from '@paddleocr/paddleocr-js'
import type { BrowserOcrPage } from '../ocr/browserOcr'
import type { BoundingBox, SourceBlock, SourceLedger, SourcePoint, SourceUnit } from '../types'

function hash(value: string): string {
  let result = 2166136261
  for (const character of value) result = Math.imul(result ^ character.charCodeAt(0), 16777619)
  return (result >>> 0).toString(36)
}

export function makeSourceUnit(options: {
  page: number; text: string; order: number; box?: BoundingBox | null; polygon?: SourcePoint[]
  confidence?: number | null; pass?: string; id?: string
}): SourceUnit {
  const imageId = `page-${options.page}`
  const id = options.id ?? `${imageId}-unit-${hash(`${options.order}|${options.text}|${JSON.stringify(options.box ?? null)}`)}`
  return {
    id, page_number: options.page, image_id: imageId, order: options.order, source_text: options.text,
    box: options.box ?? null, polygon: options.polygon ?? [], confidence: options.confidence ?? null,
    alternatives: [{ text: options.text, confidence: options.confidence ?? null, pass_name: options.pass ?? 'initial' }],
    block_id: `${id}-block`, section_id: `${imageId}-section`, table_id: null, table_row: null, table_column: null,
    english: '', translation_provider: '', translation_status: 'pending', translation_source_ids: [], semantic_refs: [], display_destinations: [],
  }
}

function geometry(item: OcrResultItem, image: OcrResult['image']): { polygon: SourcePoint[]; box: BoundingBox | null } {
  if (!image?.width || !image.height || !item.poly?.length) return { polygon: [], box: null }
  const polygon = item.poly.map(([x, y]) => ({ x: x / image.width, y: y / image.height }))
  if (!polygon.every(({ x, y }) => Number.isFinite(x) && Number.isFinite(y) && x >= 0 && x <= 1 && y >= 0 && y <= 1)) {
    return { polygon: [], box: null }
  }
  const x = Math.min(...polygon.map((point) => point.x))
  const y = Math.min(...polygon.map((point) => point.y))
  const width = Math.max(...polygon.map((point) => point.x)) - x
  const height = Math.max(...polygon.map((point) => point.y)) - y
  return { polygon, box: width > 0 && height > 0 ? { x, y, width, height } : null }
}

/** Capture every observation before legacy span/text limits can discard it. */
export function captureSourceUnits(result: OcrResult, page: number, pass = 'initial'): SourceUnit[] {
  let readingOrder = 0
  return result.items.flatMap((item, order) => {
    const text = item.text.trim()
    if (!text && !item.poly?.length) return []
    const confidence = Number.isFinite(item.score) && item.score >= 0 && item.score <= 1 ? item.score : null
    const pieces = text.match(/[\s\S]{1,20000}/g) ?? ['']
    return pieces.map((piece, segment) => makeSourceUnit({ page, text: piece, order: readingOrder++, ...geometry(item, result.image), confidence, pass,
      id: `page-${page}-${pass}-observation-${order + 1}${pieces.length > 1 ? `-segment-${segment + 1}` : ''}` }))
  })
}

function sameArea(first: SourceUnit, second: SourceUnit): boolean {
  if (!first.box || !second.box) return false
  const a = first.box; const b = second.box
  const width = Math.max(0, Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x))
  const height = Math.max(0, Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y))
  return Math.min(a.width, b.width) / Math.max(a.width, b.width) >= 0.8
    && width * height >= Math.max(a.width * a.height, b.width * b.height) * 0.7
}

/** Alternative reads stay attached to their original unit, including conflicts. */
export function mergeSourceObservations(previous: SourceUnit[], observations: SourceUnit[]): SourceUnit[] {
  const units = previous.map((unit) => ({ ...unit, alternatives: [...unit.alternatives] }))
  for (const observation of observations) {
    const unit = units.find((candidate) => sameArea(candidate, observation))
    if (!unit) { units.push(observation); continue }
    for (const alternative of observation.alternatives) {
      if (!unit.alternatives.some((candidate) => candidate.text === alternative.text && candidate.pass_name === alternative.pass_name)) unit.alternatives.push(alternative)
    }
    // Keep the first physical unit and authoritative original reading. Higher
    // confidence is evidence for recovery, not permission to remove negations.
  }
  return units.map((unit, order) => ({ ...unit, order }))
}

export function unitsFromPages(pages: BrowserOcrPage[], imageIds?: string[]): SourceUnit[] {
  return pages.flatMap((page, index) => {
    if (page.source_units) return page.source_units.map((unit) => ({ ...unit, image_id: imageIds?.[index] ?? unit.image_id }))
    const positions = new Map<string, typeof page.spans>()
    page.spans.forEach((span) => positions.set(span.text, [...(positions.get(span.text) ?? []), span]))
    return page.text.split(/\r?\n/).filter((text) => text.trim()).map((text, order) => {
      const span = positions.get(text)?.shift()
      return { ...makeSourceUnit({ page: index + 1, text: text.trim(), order, box: span?.box, confidence: span?.confidence }), image_id: imageIds?.[index] ?? `page-${index + 1}` }
    })
  })
}

export function pendingLedger(units: SourceUnit[], ocrMs = 0, layoutMs = 0): SourceLedger {
  return {
    units, blocks: units.map((unit): SourceBlock => ({ id: unit.block_id, unit_ids: [unit.id], kind: 'paragraph', section_id: unit.section_id,
      source_text: unit.source_text, english: unit.english, translation_status: unit.translation_status,
      table_id: unit.table_id, table_row: unit.table_row, table_column: unit.table_column })),
    coverage: { source_unit_ids: units.map((unit) => unit.id), translated_unit_ids: [], displayed_unit_ids: [], semantic_unit_ids: [], fallback_unit_ids: [], protected_value_gaps: [], meaning_checked: false },
    metrics: { ocr_ms: ocrMs, layout_ms: layoutMs, translation_ms: 0, semantic_ms: 0, validation_ms: 0, rendering_ms: 0,
      translation_requests: 0, semantic_requests: 0, usage_complete: true },
  }
}

export function fallbackLedger(ledger: SourceLedger): SourceLedger {
  const units = ledger.units.map((unit): SourceUnit => ({ ...unit,
    english: unit.english || (!unit.source_text || /\p{Script=Hangul}/u.test(unit.source_text) ? 'Text from this source region is preserved below.' : unit.source_text),
    translation_status: unit.english ? unit.translation_status : !unit.source_text || /\p{Script=Hangul}/u.test(unit.source_text) ? 'source_crop' : 'literal',
    translation_source_ids: [unit.id],
  }))
  return { ...ledger, units, blocks: ledger.blocks.map((block) => ({ ...block,
    english: block.english || block.unit_ids.map((id) => units.find((unit) => unit.id === id)?.english ?? '').join('\n'),
    translation_status: block.english ? block.translation_status : 'source_crop',
  })), coverage: { ...ledger.coverage, fallback_unit_ids: [...new Set([...ledger.coverage.fallback_unit_ids,
    ...units.filter((unit) => unit.translation_status === 'source_crop' || unit.translation_status === 'literal').map((unit) => unit.id)])]
    .filter((id) => units.some((unit) => unit.id === id)) } }
}

/** Never attach a response to a different source or discard an absent unit. */
export function reconcileLedger(original: SourceLedger, response: SourceLedger): SourceLedger {
  const counts = new Map<string, number>()
  const sourceIds = new Set(original.units.map((unit) => unit.id))
  response.units.forEach((unit) => counts.set(unit.id, (counts.get(unit.id) ?? 0) + 1))
  const byId = new Map(response.units.map((unit) => [unit.id, unit]))
  const units = original.units.map((source) => {
    const candidate = byId.get(source.id)
    return counts.get(source.id) === 1 && candidate?.source_text === source.source_text
      && candidate.translation_source_ids.includes(source.id)
      && new Set(candidate.translation_source_ids).size === candidate.translation_source_ids.length
      && candidate.translation_source_ids.every((id) => sourceIds.has(id))
      && !/\p{Script=Hangul}/u.test(candidate.english)
      ? { ...candidate, page_number: source.page_number, image_id: source.image_id, order: source.order,
        polygon: source.polygon, box: source.box, confidence: source.confidence, alternatives: source.alternatives }
      : { ...source, english: '', translation_status: 'source_crop' as const }
  })
  const ids = new Set(units.map((unit) => unit.id))
  const blocks: SourceBlock[] = []
  const represented = new Set<string>()
  const blockIds = new Set<string>()
  for (const block of response.blocks) {
    if (!block.unit_ids.length || blockIds.has(block.id) || new Set(block.unit_ids).size !== block.unit_ids.length
      || block.unit_ids.some((id) => !ids.has(id) || represented.has(id))) continue
    blocks.push(block)
    blockIds.add(block.id)
    block.unit_ids.forEach((id) => represented.add(id))
  }
  for (const block of pendingLedger(units.filter((unit) => !represented.has(unit.id))).blocks) {
    blocks.push({ ...block, id: blockIds.has(block.id) ? `${block.unit_ids[0]}-preserved-block` : block.id })
  }
  return fallbackLedger({ ...response, units, blocks, coverage: { ...response.coverage, source_unit_ids: units.map((unit) => unit.id),
    translated_unit_ids: units.filter((unit) => unit.translation_status === 'translated' && unit.english.trim()).map((unit) => unit.id),
    displayed_unit_ids: [...new Set(original.coverage.displayed_unit_ids)].filter((id) => ids.has(id)),
    semantic_unit_ids: [...new Set(response.coverage.semantic_unit_ids)].filter((id) => ids.has(id)),
  } })
}

export function recordLedgerDisplay(ledger: SourceLedger, sourceIds: string[], renderingMs: number, destination = 'translation_view'): SourceLedger {
  const displayed = new Set(sourceIds)
  const units = ledger.units.map((unit) => displayed.has(unit.id) && !unit.display_destinations.includes(destination)
    ? { ...unit, display_destinations: [...unit.display_destinations, destination] } : unit)
  return { ...ledger, units: units.every((unit, index) => unit === ledger.units[index]) ? ledger.units : units,
    coverage: { ...ledger.coverage, displayed_unit_ids: ledger.units.filter((unit) => displayed.has(unit.id)).map((unit) => unit.id) },
    metrics: { ...ledger.metrics, rendering_ms: renderingMs } }
}
