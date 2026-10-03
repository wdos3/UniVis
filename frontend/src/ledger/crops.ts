import type { BoundingBox, SourceLedger, SourceUnit } from '../types'

export interface LocalSourceImage { page_number: number; url: string; file?: File }
export interface RecoveryRegion { unit_ids: string[]; data_url: string }

interface RecoveryPlan { unit_ids: string[]; page_number: number; box: BoundingBox }

export async function decodeLocalSource(file: File): Promise<{ image: CanvasImageSource; width: number; height: number; close: () => void }> {
  if (typeof createImageBitmap === 'function') {
    try {
      const bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' })
      return { image: bitmap, width: bitmap.width, height: bitmap.height, close: () => bitmap.close() }
    } catch {
      // Image-element decoding remains available in browsers without bitmap
      // support or for files that their bitmap decoder does not accept.
    }
  }
  const image = new Image()
  const url = URL.createObjectURL(file)
  try {
    await new Promise<void>((resolve, reject) => {
      image.onload = () => resolve()
      image.onerror = () => reject(new Error('The recovery image decoder did not accept this file.'))
      image.src = url
    })
    return { image, width: image.naturalWidth, height: image.naturalHeight, close: () => { image.src = ''; URL.revokeObjectURL(url) } }
  } catch (problem) {
    URL.revokeObjectURL(url)
    throw problem
  }
}

function priority(unit: SourceUnit, gaps: string[]): number {
  const readings = [unit.source_text, ...unit.alternatives.map((candidate) => candidate.text)].join(' ')
  if (!unit.source_text && unit.translation_status === 'source_crop') return 1000
  const conflict = new Set(unit.alternatives.map((candidate) => candidate.text)).size > 1
  return (gaps.some((gap) => gap.includes(unit.id)) ? 500 : 0)
    + (/문의|연락|전화|contact|@|https?:|\d{2,4}[.\s-]\d{3,4}[.\s-][\dA-Za-z]{3,4}/i.test(readings) ? 400 : 0)
    + (/\d/.test(readings) ? 180 : 0)
    + (/불가|없|제외|금지|아니|않|cannot|not\b/i.test(readings) ? 120 : 0)
    + (conflict ? 160 : 0) + (unit.translation_status === 'source_crop' ? 80 : 0)
    + (unit.confidence !== null && unit.confidence < 0.85 ? 40 : 0) - (unit.source_text.length < 5 ? 70 : 0)
}

function overlapFraction(first: BoundingBox, second: BoundingBox): number {
  const width = Math.max(0, Math.min(first.x + first.width, second.x + second.width) - Math.max(first.x, second.x))
  const height = Math.max(0, Math.min(first.y + first.height, second.y + second.height) - Math.max(first.y, second.y))
  return width * height / Math.min(first.width * first.height, second.width * second.height)
}

export function planRecoveryCrops(ledger: SourceLedger): RecoveryPlan[] {
  const difficult = ledger.units.filter((unit) => unit.translation_status === 'source_crop'
    || (unit.translation_status === 'literal' && /\p{Script=Hangul}/u.test(unit.source_text)) || (unit.confidence !== null && unit.confidence < 0.85)
    || new Set(unit.alternatives.map((candidate) => candidate.text)).size > 1)
    .sort((first, second) => priority(second, ledger.coverage.protected_value_gaps) - priority(first, ledger.coverage.protected_value_gaps) || first.order - second.order)
  const used = new Set<string>()
  const plans: RecoveryPlan[] = []
  for (const unit of difficult) {
    if (used.has(unit.id)) continue
    const sourceBox = unit.box ?? { x: 0, y: 0, width: 1, height: 1 }
    const related = ledger.units.filter((candidate) => candidate.page_number === unit.page_number && !used.has(candidate.id)
      && (candidate.id === unit.id || candidate.block_id === unit.block_id
        || (candidate.box && overlapFraction(sourceBox, candidate.box) >= 0.55)))
    related.forEach((candidate) => used.add(candidate.id))
    const boxes = related.flatMap((candidate) => candidate.box ? [candidate.box] : [])
    const x = Math.min(sourceBox.x, ...boxes.map((box) => box.x)); const y = Math.min(sourceBox.y, ...boxes.map((box) => box.y))
    const right = Math.max(sourceBox.x + sourceBox.width, ...boxes.map((box) => box.x + box.width))
    const bottom = Math.max(sourceBox.y + sourceBox.height, ...boxes.map((box) => box.y + box.height))
    plans.push({ unit_ids: related.map((candidate) => candidate.id), page_number: unit.page_number, box: { x, y, width: right - x, height: bottom - y } })
    if (plans.length === 4) break
  }
  return plans
}

/** Recovery crops are bounded and ephemeral, including reduced-page fallbacks. */
export async function recoveryCrops(ledger: SourceLedger, pages: LocalSourceImage[]): Promise<RecoveryRegion[]> {
  const plans = planRecoveryCrops(ledger)
  const regions: RecoveryRegion[] = []
  let remaining = 1_500_000
  for (const plan of plans) {
    const page = pages.find((candidate) => candidate.page_number === plan.page_number)
    if (!page?.file) continue
    let bitmap: Awaited<ReturnType<typeof decodeLocalSource>> | undefined
    try {
      bitmap = await decodeLocalSource(page.file)
      const box = plan.box
      const left = Math.max(0, Math.floor(box.x * bitmap.width) - 8)
      const top = Math.max(0, Math.floor(box.y * bitmap.height) - 8)
      const width = Math.min(bitmap.width - left, Math.ceil(box.width * bitmap.width) + 16)
      const height = Math.min(bitmap.height - top, Math.ceil(box.height * bitmap.height) + 16)
      if (width <= 0 || height <= 0) continue
      const scale = Math.min(1, 900 / Math.max(width, height))
      const canvas = document.createElement('canvas')
      canvas.width = Math.max(1, Math.round(width * scale)); canvas.height = Math.max(1, Math.round(height * scale))
      const context = canvas.getContext('2d')
      if (!context) continue
      context.drawImage(bitmap.image, left, top, width, height, 0, 0, canvas.width, canvas.height)
      const dataUrl = canvas.toDataURL('image/jpeg', 0.8)
      if (!dataUrl.startsWith('data:image/jpeg;base64,') || dataUrl.length > Math.min(1_200_000, remaining)) continue
      remaining -= dataUrl.length
      regions.push({ unit_ids: plan.unit_ids, data_url: dataUrl })
    } catch {
      // Crop export is optional recovery. The ledger and browser source view
      // remain available even when this browser cannot produce a thumbnail.
    } finally {
      bitmap?.close()
    }
  }
  return regions
}
