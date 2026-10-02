import type { BoundingBox } from '../types'
import type { TranslationRegion } from './regions'

export interface RenderTranslationRegion extends TranslationRegion {
  translatedText: string
  status: 'translated' | 'unchanged' | 'failed'
}

export interface RenderDiagnostic {
  id: string
  status: 'rendered' | 'original'
  reason: 'translated' | 'unchanged' | 'failed' | 'overlap' | 'invalid_box' | 'too_small'
  fontSize?: number
  lineCount?: number
}

export interface TextLayout {
  fits: boolean
  fontSize: number
  lineHeight: number
  lines: string[]
}

interface TextLayoutOptions {
  text: string
  width: number
  height: number
  maxFontSize: number
  minFontSize: number
  measureText: (text: string, fontSize: number) => number
}

function wrapText(text: string, width: number, fontSize: number, measure: TextLayoutOptions['measureText']): string[] {
  const lines: string[] = []
  for (const paragraph of text.replace(/\r\n?/g, '\n').split('\n')) {
    let line = ''
    for (const word of paragraph.trim().split(/\s+/).filter(Boolean)) {
      const combined = line ? `${line} ${word}` : word
      if (measure(combined, fontSize) <= width) {
        line = combined
        continue
      }
      if (line) lines.push(line)
      line = ''
      // Long URLs and unspaced identifiers wrap without deleting characters or
      // adding a hyphen that could be mistaken for part of the source value.
      for (const character of Array.from(word)) {
        if (line && measure(line + character, fontSize) > width) {
          lines.push(line)
          line = ''
        }
        line += character
      }
    }
    lines.push(line)
  }
  return lines
}

/** Find the largest legible size that fits the complete text; never truncate. */
export function layoutText(options: TextLayoutOptions): TextLayout {
  const { text, width, height, minFontSize, maxFontSize, measureText } = options
  const minimum = Math.max(1, minFontSize)
  const maximum = Math.max(minimum, maxFontSize)
  const atSize = (fontSize: number): TextLayout => {
    const lineHeight = fontSize * 1.15
    const lines = wrapText(text, width, fontSize, measureText)
    return {
      fits: width > 0 && height > 0 && lineHeight * lines.length <= height
        && lines.every((line) => measureText(line, fontSize) <= width),
      fontSize, lineHeight, lines,
    }
  }
  let best = atSize(minimum)
  if (!best.fits) return best
  let low = minimum
  let high = maximum
  while (high - low > 0.25) {
    const middle = (low + high) / 2
    const candidate = atSize(middle)
    if (candidate.fits) {
      best = candidate
      low = middle
    } else {
      high = middle
    }
  }
  const largest = atSize(maximum)
  return largest.fits ? largest : best
}

function validBox(box: BoundingBox): boolean {
  if (![box.x, box.y, box.width, box.height].every(Number.isFinite)
    || box.x < 0 || box.y < 0 || box.width <= 0 || box.height <= 0
    || box.x + box.width > 1.000001 || box.y + box.height > 1.000001) return false
  return box.x < 1 && box.y < 1
}

function pixelBox(box: BoundingBox, width: number, height: number): BoundingBox | null {
  if (!validBox(box)) return null
  return {
    x: box.x * width, y: box.y * height,
    width: Math.min(box.width * width, width - box.x * width),
    height: Math.min(box.height * height, height - box.y * height),
  }
}

function overlaps(left: BoundingBox, right: BoundingBox): boolean {
  return Math.min(left.x + left.width, right.x + right.width) - Math.max(left.x, right.x) > 1e-9
    && Math.min(left.y + left.height, right.y + right.height) - Math.max(left.y, right.y) > 1e-9
}

export interface TranslationPlacement {
  id: string
  box: BoundingBox | null
  reason: 'overlap' | 'invalid_box' | null
}

function neighboringLines(left: BoundingBox, right: BoundingBox): boolean {
  const horizontalOverlap = Math.min(left.x + left.width, right.x + right.width) - Math.max(left.x, right.x)
  const verticalOverlap = Math.min(left.y + left.height, right.y + right.height) - Math.max(left.y, right.y)
  const minHeight = Math.min(left.height, right.height)
  const minWidth = Math.min(left.width, right.width)
  const centerDistance = Math.abs(left.y + left.height / 2 - right.y - right.height / 2)
  return horizontalOverlap >= minWidth * 0.8 && verticalOverlap <= minHeight * 0.5
    && centerDistance >= minHeight * 0.5
    && Math.abs(left.x - right.x) <= Math.max(minWidth * 0.08, minHeight * 0.8)
}

/** Partition only slight overlaps of adjacent lines, retaining source boxes. */
export function planTranslationPlacements(regions: Array<{ id: string; box: BoundingBox; replace: boolean }>): TranslationPlacement[] {
  const boxes = regions.map((region) => validBox(region.box) ? { ...region.box } : null)
  const blocked = new Set<number>()
  const neighbors: Array<[number, number]> = []
  for (let left = 0; left < boxes.length; left += 1) {
    for (let right = left + 1; right < boxes.length; right += 1) {
      const first = boxes[left]
      const second = boxes[right]
      if (!first || !second || !overlaps(first, second)) continue
      if (neighboringLines(first, second)) {
        neighbors.push([left, right])
      } else {
        if (regions[left].replace) blocked.add(left)
        if (regions[right].replace) blocked.add(right)
      }
    }
  }
  const tops = boxes.map((box) => box?.y ?? 0)
  const bottoms = boxes.map((box) => box ? box.y + box.height : 0)
  for (const [left, right] of neighbors) {
    const first = boxes[left]!
    const second = boxes[right]!
    const [upper, lower] = first.y + first.height / 2 < second.y + second.height / 2 ? [left, right] : [right, left]
    const upperBox = boxes[upper]!
    const lowerBox = boxes[lower]!
    const replaceUpper = regions[upper].replace && !blocked.has(upper)
    const replaceLower = regions[lower].replace && !blocked.has(lower)
    if (replaceUpper && replaceLower) {
      const boundary = (Math.max(upperBox.y, lowerBox.y) + Math.min(upperBox.y + upperBox.height, lowerBox.y + lowerBox.height)) / 2
      bottoms[upper] = Math.min(bottoms[upper], boundary)
      tops[lower] = Math.max(tops[lower], boundary)
    } else if (replaceUpper) {
      bottoms[upper] = Math.min(bottoms[upper], lowerBox.y)
    } else if (replaceLower) {
      tops[lower] = Math.max(tops[lower], upperBox.y + upperBox.height)
    }
  }
  return regions.map((region, index) => {
    const box = boxes[index]
    if (!box) return { id: region.id, box: null, reason: 'invalid_box' }
    if (blocked.has(index) || bottoms[index] <= tops[index]) return { id: region.id, box: null, reason: 'overlap' }
    if (tops[index] === box.y && bottoms[index] === box.y + box.height) return { id: region.id, box, reason: null }
    return { id: region.id, box: { ...box, y: tops[index], height: bottoms[index] - tops[index] }, reason: null }
  })
}

function boundaryBackground(context: CanvasRenderingContext2D, box: BoundingBox, width: number, height: number): number[] {
  const margin = 3
  const x = Math.max(0, Math.floor(box.x) - margin)
  const y = Math.max(0, Math.floor(box.y) - margin)
  const right = Math.min(width, Math.ceil(box.x + box.width) + margin)
  const bottom = Math.min(height, Math.ceil(box.y + box.height) + margin)
  const pixels = context.getImageData(x, y, right - x, bottom - y)
  const colors = new Map<string, { count: number; sums: number[] }>()
  for (let row = 0; row < pixels.height; row += 1) {
    for (let column = 0; column < pixels.width; column += 1) {
      const inside = column + x > box.x + 1 && column + x < box.x + box.width - 1
        && row + y > box.y + 1 && row + y < box.y + box.height - 1
      if (inside) continue
      const index = (row * pixels.width + column) * 4
      if (pixels.data[index + 3] < 128) continue
      const rgb = Array.from(pixels.data.slice(index, index + 3))
      const key = rgb.map((channel) => Math.floor(channel / 32)).join(',')
      const sample = colors.get(key) ?? { count: 0, sums: [0, 0, 0] }
      sample.count += 1
      rgb.forEach((channel, channelIndex) => { sample.sums[channelIndex] += channel })
      colors.set(key, sample)
    }
  }
  const mostCommon = [...colors.values()].sort((left, right) => right.count - left.count)[0]
  return mostCommon ? mostCommon.sums.map((sum) => Math.round(sum / mostCommon.count)) : [255, 255, 255]
}

export function renderTranslatedImage(options: {
  image: CanvasImageSource
  width: number
  height: number
  regions: RenderTranslationRegion[]
}): { canvas: HTMLCanvasElement; diagnostics: RenderDiagnostic[] } {
  const { image, width, height, regions } = options
  if (!Number.isSafeInteger(width) || !Number.isSafeInteger(height) || width <= 0 || height <= 0) {
    throw new Error('The image dimensions must be positive whole pixels.')
  }
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const context = canvas.getContext('2d')
  if (!context) throw new Error('This browser could not create the translated image canvas.')
  context.drawImage(image, 0, 0, width, height)
  const replaceable = regions.map((region) => region.status === 'translated' && Boolean(region.translatedText.trim())
    && region.sourceText.replace(/\s+/g, ' ').trim() !== region.translatedText.replace(/\s+/g, ' ').trim())
  const unfitLayouts = new Map<number, TextLayout>()
  let placements: TranslationPlacement[]
  let boxes: Array<BoundingBox | null>
  let layouts: Array<TextLayout | null>
  // A line that fails the fit check becomes retained source. Recompute the
  // neighboring paint bounds before drawing so English cannot erase that line.
  let fitChanged: boolean
  do {
    placements = planTranslationPlacements(regions.map((region, index) => ({ ...region, replace: replaceable[index] })))
    boxes = placements.map((placement) => placement.box ? pixelBox(placement.box, width, height) : null)
    layouts = boxes.map((box, index) => {
      if (!box || !replaceable[index]) return null
      const padding = Math.min(3, box.height * 0.06, box.width * 0.02)
      const minFontSize = Math.max(10, width / 220)
      return layoutText({
        text: regions[index].translatedText,
        width: box.width - padding * 2,
        height: box.height - padding * 2,
        minFontSize,
        maxFontSize: Math.max(minFontSize, box.height / Math.max(1, regions[index].spanCount) * 0.85),
        measureText: (text, fontSize) => {
          context.font = `${fontSize}px Arial, sans-serif`
          return context.measureText(text).width
        },
      })
    })
    fitChanged = false
    layouts.forEach((layout, index) => {
      if (!layout || layout.fits) return
      unfitLayouts.set(index, layout)
      replaceable[index] = false
      fitChanged = true
    })
  } while (fitChanged)
  const diagnostics: RenderDiagnostic[] = []
  // Sample the unmodified source before painting any region, so translation
  // order cannot change another region's background or foreground color.
  const backgrounds = boxes.map((box, index) => box && layouts[index]?.fits ? boundaryBackground(context, box, width, height) : null)
  for (const [index, region] of regions.entries()) {
    const diagnostic: RenderDiagnostic = { id: region.id, status: 'original', reason: 'failed' }
    diagnostics.push(diagnostic)
    if (region.status !== 'translated' || !region.translatedText.trim()) {
      diagnostic.reason = region.status === 'unchanged' ? 'unchanged' : 'failed'
      continue
    }
    if (region.sourceText.replace(/\s+/g, ' ').trim() === region.translatedText.replace(/\s+/g, ' ').trim()) {
      diagnostic.reason = 'unchanged'
      continue
    }
    const box = boxes[index]
    const unfit = unfitLayouts.get(index)
    if (unfit) {
      diagnostic.reason = 'too_small'
      diagnostic.fontSize = unfit.fontSize
      diagnostic.lineCount = unfit.lines.length
      continue
    }
    if (!box) {
      diagnostic.reason = placements[index].reason ?? 'invalid_box'
      continue
    }
    const layout = layouts[index]
    if (!layout) continue
    const padding = Math.min(3, box.height * 0.06, box.width * 0.02)
    diagnostic.fontSize = layout.fontSize
    diagnostic.lineCount = layout.lines.length
    const background = backgrounds[index] ?? [255, 255, 255]
    context.fillStyle = `rgb(${background.join(',')})`
    context.fillRect(box.x, box.y, box.width, box.height)
    const luminance = background[0] * 0.2126 + background[1] * 0.7152 + background[2] * 0.0722
    context.fillStyle = luminance > 140 ? '#111111' : '#ffffff'
    context.font = `${layout.fontSize}px Arial, sans-serif`
    context.textBaseline = 'top'
    context.textAlign = 'left'
    const top = box.y + (box.height - layout.lines.length * layout.lineHeight) / 2
    layout.lines.forEach((line, lineIndex) => {
      context.fillText(line, box.x + padding, top + lineIndex * layout.lineHeight)
    })
    diagnostic.status = 'rendered'
    diagnostic.reason = 'translated'
  }
  return { canvas, diagnostics }
}
