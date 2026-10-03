import type { BoundingBox, SourceLedger } from '../types'
import type { RenderTranslationRegion } from '../imageTranslation/renderer'

export interface LedgerOverlayRegion extends RenderTranslationRegion { sourceUnitIds: string[] }

function union(boxes: BoundingBox[]): BoundingBox {
  const x = Math.min(...boxes.map((box) => box.x)); const y = Math.min(...boxes.map((box) => box.y))
  return { x, y, width: Math.max(...boxes.map((box) => box.x + box.width)) - x,
    height: Math.max(...boxes.map((box) => box.y + box.height)) - y }
}

/** Image placement is a projection of the ledger, never its source authority. */
export function ledgerOverlayRegions(ledger: SourceLedger, page = 1): LedgerOverlayRegion[] {
  const byId = new Map(ledger.units.map((unit) => [unit.id, unit]))
  return ledger.blocks.flatMap((block) => {
    const units = block.unit_ids.flatMap((id) => byId.get(id) ? [byId.get(id)!] : [])
    if (!units.length || units.some((unit) => unit.page_number !== page || !unit.box)) return []
    return [{ id: block.id, sourceUnitIds: units.map((unit) => unit.id),
      sourceText: units.map((unit) => unit.source_text).join('\n'),
      translatedText: block.english || units.map((unit) => unit.english).join('\n'),
      box: union(units.map((unit) => unit.box!)), spanCount: units.length,
      status: units.some((unit) => unit.translation_status === 'source_crop' || unit.translation_status === 'pending')
        ? 'failed' as const : 'translated' as const,
    }]
  })
}
