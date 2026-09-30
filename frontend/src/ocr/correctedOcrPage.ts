import type { BrowserOcrPage } from './browserOcr'
import type { OcrSpan } from '../types'

function lines(text: string): string[] {
  return text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean)
}

function uniqueLineIndexes(source: string[]): Map<string, number> {
  const indexes = new Map<string, number>()
  const duplicates = new Set<string>()
  source.forEach((line, index) => {
    if (indexes.has(line)) duplicates.add(line)
    indexes.set(line, index)
  })
  duplicates.forEach((line) => indexes.delete(line))
  return indexes
}

export function correctedOcrPage(page: BrowserOcrPage, text: string): BrowserOcrPage {
  const previous = lines(page.text)
  const corrected = lines(text)
  const previousIndexes = uniqueLineIndexes(previous)
  const correctedIndexes = uniqueLineIndexes(corrected)
  const anchors = corrected.flatMap((line, index) => {
    const previousIndex = previousIndexes.get(line)
    return previousIndex !== undefined && correctedIndexes.has(line)
      ? [{ previousIndex, correctedIndex: index }] : []
  })

  // Reordered text no longer has a reliable relationship to the original photo.
  if (anchors.some((anchor, index) => index > 0 && anchor.previousIndex <= anchors[index - 1].previousIndex)) {
    return { text, spans: [] }
  }

  const spansByLine = new Map<number, OcrSpan>()
  page.spans.forEach((span) => {
    const index = previousIndexes.get(span.text.trim())
    if (index !== undefined) spansByLine.set(index, span)
  })
  const correctedSpans = new Map<number, OcrSpan>()
  anchors.forEach(({ previousIndex, correctedIndex }) => {
    const span = spansByLine.get(previousIndex)
    if (span) correctedSpans.set(correctedIndex, span)
  })

  // In a segment with the same number of lines, retain approximate positions
  // for in-place edits. Added/removed lines keep only their unchanged anchors.
  const boundaries = [
    { previousIndex: -1, correctedIndex: -1 },
    ...anchors,
    { previousIndex: previous.length, correctedIndex: corrected.length },
  ]
  for (let index = 1; index < boundaries.length; index++) {
    const start = boundaries[index - 1]
    const end = boundaries[index]
    const previousCount = end.previousIndex - start.previousIndex - 1
    const correctedCount = end.correctedIndex - start.correctedIndex - 1
    if (previousCount !== correctedCount) continue
    for (let offset = 1; offset <= previousCount; offset++) {
      const correctedIndex = start.correctedIndex + offset
      const span = spansByLine.get(start.previousIndex + offset)
      const correctedText = corrected[correctedIndex]
      if (span && correctedText.length <= 500) {
        // The SDK confidence describes the old reading, not a manual correction.
        correctedSpans.set(correctedIndex, { text: correctedText, box: span.box })
      }
    }
  }

  return {
    text,
    spans: [...correctedSpans].sort(([left], [right]) => left - right).map(([, span]) => span),
  }
}
