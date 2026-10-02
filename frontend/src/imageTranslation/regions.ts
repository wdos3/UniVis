import type { BoundingBox, OcrSpan } from '../types'

export interface TranslationRegion {
  id: string
  sourceText: string
  box: BoundingBox
  spanCount: number
  confidence?: number
}

function intersection(left: BoundingBox, right: BoundingBox): { width: number; height: number } {
  return {
    width: Math.max(0, Math.min(left.x + left.width, right.x + right.width) - Math.max(left.x, right.x)),
    height: Math.max(0, Math.min(left.y + left.height, right.y + right.height) - Math.max(left.y, right.y)),
  }
}

function validSpan(span: OcrSpan): boolean {
  const { x, y, width, height } = span.box
  return Boolean(span.text.trim()) && [x, y, width, height].every(Number.isFinite)
    && x >= 0 && y >= 0 && width > 0 && height > 0
    && x + width <= 1.000001 && y + height <= 1.000001
}

function printedValues(text: string): string[] {
  return (text.match(/[+−-]?[A-Za-z]*\d+(?:[.,:/-]\d+)*(?:[A-Za-z]+\d*)*/g) ?? [])
    .map((value) => value.toUpperCase())
}

function sameReadingArea(left: OcrSpan, right: OcrSpan): boolean {
  const leftValues = printedValues(left.text)
  const rightValues = printedValues(right.text)
  // Confidence cannot resolve competing dates, amounts, scores, or grade codes.
  // Keep each reading so the renderer retains the original conflicting source.
  if (leftValues.length !== rightValues.length || leftValues.some((value, index) => value !== rightValues[index])) return false
  const overlap = intersection(left.box, right.box)
  const minWidth = Math.min(left.box.width, right.box.width)
  const minHeight = Math.min(left.box.height, right.box.height)
  const maxWidth = Math.max(left.box.width, right.box.width)
  const endpointTolerance = Math.min(maxWidth * 0.1, minHeight * 0.8)
  // A recovery crop may read only the suffix of an existing line. Treating
  // containment as duplication would discard the rest of that source sentence.
  // Competing partial readings stay available; the renderer handles overlap.
  return overlap.width >= minWidth * 0.65 && overlap.height >= minHeight * 0.7
    && minWidth / maxWidth >= 0.8 && overlap.width >= maxWidth * 0.75
    && Math.abs(left.box.x - right.box.x) <= endpointTolerance
    && Math.abs(left.box.x + left.box.width - right.box.x - right.box.width) <= endpointTolerance
    && minHeight / Math.max(left.box.height, right.box.height) >= 0.55
}

function completeReading(text: string): string {
  return text.trim().replace(/^[·•]\s*/, '').replace(/\s+/g, ' ')
}

function sameCompleteReading(left: OcrSpan, right: OcrSpan): boolean {
  if (completeReading(left.text) !== completeReading(right.text)) return false
  const overlap = intersection(left.box, right.box)
  const overlapArea = overlap.width * overlap.height
  const leftArea = left.box.width * left.box.height
  const rightArea = right.box.width * right.box.height
  const horizontalCenterDistance = Math.abs(left.box.x + left.box.width / 2 - right.box.x - right.box.width / 2)
  const verticalCenterDistance = Math.abs(left.box.y + left.box.height / 2 - right.box.y - right.box.height / 2)
  // Complete matching words can have different crop padding or a missed list
  // bullet. Tight center checks distinguish a repeat read from adjacent rows.
  return overlapArea >= Math.min(leftArea, rightArea) * 0.65
    && overlapArea >= Math.max(leftArea, rightArea) * 0.4
    && horizontalCenterDistance <= Math.max(left.box.width, right.box.width) * 0.15
    && verticalCenterDistance <= Math.max(left.box.height, right.box.height) * 0.25
}

function readingOrder(left: OcrSpan, right: OcrSpan): number {
  return left.box.y - right.box.y || left.box.x - right.box.x
}

function union(left: BoundingBox, right: BoundingBox): BoundingBox {
  const x = Math.min(left.x, right.x)
  const y = Math.min(left.y, right.y)
  return {
    x, y,
    width: Math.max(left.x + left.width, right.x + right.width) - x,
    height: Math.max(left.y + left.height, right.y + right.height) - y,
  }
}

function hasParallelCell(span: OcrSpan, candidates: OcrSpan[]): boolean {
  return candidates.some((candidate) => {
    if (candidate === span) return false
    const overlap = intersection(span.box, candidate.box)
    // Geometry alone cannot distinguish broad table cells from paragraph
    // columns. Retain their source positions rather than merging across rows.
    return overlap.height > Math.min(span.box.height, candidate.box.height) * 0.5
      && overlap.width === 0
  })
}

function canContinue(previous: OcrSpan, next: OcrSpan, candidates: OcrSpan[]): boolean {
  const height = Math.min(previous.box.height, next.box.height)
  const gap = next.box.y - previous.box.y - previous.box.height
  if (gap < -height * 0.1 || gap > height * 0.65) return false
  if (Math.max(previous.box.height, next.box.height) / height > 1.3) return false
  if (Math.abs(previous.box.x - next.box.x) > height * 0.8) return false
  // A wrapped line normally follows a nearly full preceding line. Short labels
  // and independent table entries must retain their individual translation boxes.
  if (previous.box.width < next.box.width * 0.8) return false
  if (hasParallelCell(previous, candidates) || hasParallelCell(next, candidates)) return false
  return true
}

/** Retain source geometry and resolve repeated crop readings before translation. */
export function buildTranslationRegions(spans: OcrSpan[]): TranslationRegion[] {
  const byQuality = spans.filter(validSpan).map((span) => ({ ...span, text: span.text.trim() }))
    .sort((left, right) => (right.confidence ?? -1) - (left.confidence ?? -1)
      || right.text.length - left.text.length || readingOrder(left, right))
  const unique: OcrSpan[] = []
  for (const span of byQuality) {
    if (!unique.some((candidate) => sameCompleteReading(span, candidate) || sameReadingArea(span, candidate))) unique.push(span)
  }
  unique.sort(readingOrder)
  const used = new Set<OcrSpan>()
  const groups: OcrSpan[][] = []
  for (const first of unique) {
    if (used.has(first)) continue
    const group = [first]
    used.add(first)
    let box = first.box
    let previous = first
    for (const next of unique) {
      if (used.has(next) || !canContinue(previous, next, unique)) continue
      const proposed = union(box, next.box)
      const coversOtherText = unique.some((other) => {
        if (other === next || group.includes(other)) return false
        const overlap = intersection(proposed, other.box)
        return overlap.width > 0 && overlap.height > 0
      })
      if (coversOtherText) continue
      group.push(next)
      used.add(next)
      box = proposed
      previous = next
    }
    groups.push(group)
  }
  return groups.map((group, index) => {
    const confidences = group.map((span) => span.confidence).filter((value): value is number => value !== undefined)
    return {
      id: `region-${index + 1}`,
      sourceText: group.map((span) => span.text).join('\n'),
      box: group.map((span) => span.box).reduce(union),
      spanCount: group.length,
      ...(confidences.length ? { confidence: Math.min(...confidences) } : {}),
    }
  })
}
