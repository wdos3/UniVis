import { useEffect, useRef, useState } from 'react'
import type { SourceBlock, SourceLedger, SourceUnit } from '../types'
import type { LocalSourceImage } from '../ledger/crops'
import './sourceLedger.css'

function SourceCrop({ unit, page }: { unit: SourceUnit; page?: LocalSourceImage }) {
  const [dimensions, setDimensions] = useState({ width: 1, height: 1 })
  if (!page) return <p className="ledger-source-unavailable">The original region is retained with this notice; its photo is available on the original device.</p>
  const box = unit.box
  if (!box) return <a href={page.url} target="_blank" rel="noopener noreferrer">View preserved source page {unit.page_number}</a>
  return <figure className="ledger-crop">
    <div style={{ aspectRatio: `${box.width * dimensions.width} / ${box.height * dimensions.height}` }}>
      <img src={page.url} alt={`Preserved source region ${unit.id}`} onLoad={(event) => {
        const image = event.currentTarget
        if (image.naturalWidth && image.naturalHeight) setDimensions({ width: image.naturalWidth, height: image.naturalHeight })
      }} style={{ width: `${100 / box.width}%`, left: `${-box.x / box.width * 100}%`, top: `${-box.y / box.height * 100}%` }} />
    </div><figcaption>Source region · page {unit.page_number}</figcaption>
  </figure>
}

function UnitContent({ unit, pages, preserveCrop, sharedEnglish = false }: { unit: SourceUnit; pages: LocalSourceImage[]; preserveCrop: boolean; sharedEnglish?: boolean }) {
  const page = pages.find((candidate) => candidate.page_number === unit.page_number)
  return <div className="ledger-unit" data-source-unit-id={unit.id}>
    {!sharedEnglish && <p lang="en">{unit.english || 'This source region remains available below while its translation is prepared.'}</p>}
    {preserveCrop || unit.translation_status === 'source_crop' || unit.recovery_source === 'vision' ? <SourceCrop unit={unit} page={page} /> : null}
    <details><summary>Source evidence</summary><SourceCrop unit={unit} page={page} /><p lang="ko">{unit.source_text}</p>
      {unit.alternatives.length > 1 && <ul>{unit.alternatives.map((candidate, index) => <li key={`${candidate.pass_name}-${index}`} lang="ko">{candidate.text}</li>)}</ul>}
      {unit.recovered_source_text && <p lang="ko"><span lang="en">{unit.recovery_source === 'vision' ? 'Image-assisted reading' : 'Alternate OCR reading'}: </span>{unit.recovered_source_text}</p>}
      <small>{unit.id} · {unit.translation_provider || 'Local OCR'} · {unit.translation_status}</small>
    </details>
  </div>
}

export function SourceLedgerView({ ledger, pages = [], pending = false, preservedIds = [], onDisplayed }: {
  ledger: SourceLedger; pages?: LocalSourceImage[]; pending?: boolean; preservedIds?: string[]
  onDisplayed?: (sourceIds: string[], renderingMs: number) => void
}) {
  const view = useRef<HTMLElement>(null)
  useEffect(() => {
    if (!onDisplayed) return
    const started = performance.now()
    let active = true
    const report = () => {
      if (!active) return
      const ids = [...new Set(Array.from(view.current?.querySelectorAll('[data-source-unit-id]') ?? [])
        .map((element) => element.getAttribute('data-source-unit-id')).filter((id): id is string => Boolean(id)))]
      onDisplayed(ids, Math.round(performance.now() - started))
    }
    if (typeof requestAnimationFrame !== 'function') {
      queueMicrotask(report)
      return () => { active = false }
    }
    const frame = requestAnimationFrame(report)
    return () => { active = false; cancelAnimationFrame(frame) }
  }, [ledger.units, onDisplayed])
  const byId = new Map(ledger.units.map((unit) => [unit.id, unit]))
  const preserved = new Set(preservedIds)
  const referenced = new Set(ledger.blocks.flatMap((block) => block.unit_ids))
  const blocks: SourceBlock[] = [...ledger.blocks, ...ledger.units.filter((unit) => !referenced.has(unit.id)).map((unit): SourceBlock => ({
    id: `${unit.id}-fallback`, unit_ids: [unit.id], kind: 'caption', section_id: unit.section_id,
    source_text: unit.source_text, english: unit.english, translation_status: unit.translation_status,
    table_id: null, table_row: null, table_column: null,
  }))]
  const tables = new Map<string, SourceBlock[]>()
  blocks.forEach((block) => { if (block.table_id) tables.set(block.table_id, [...(tables.get(block.table_id) ?? []), block]) })
  const renderedTables = new Set<string>()
  const content = (block: SourceBlock) => {
    const units = block.unit_ids.flatMap((id) => byId.get(id) ? [byId.get(id)!] : [])
    const sharedEnglish = units.length > 1 && Boolean(units[0].english)
      && units.every((unit) => unit.english === units[0].english && unit.translation_source_ids.every((id) => block.unit_ids.includes(id)))
    return <>{sharedEnglish && <p lang="en">{units[0].english}</p>}{units.map((unit) =>
      <UnitContent key={unit.id} unit={unit} pages={pages} preserveCrop={preserved.has(unit.id)} sharedEnglish={sharedEnglish} />)}</>
  }
  return <section ref={view} className="source-ledger-view" aria-label="Complete source translation">
    <h2>Notice translation</h2>
    {pending && <p role="status">English instructions are being organized. The translated source details remain available here.</p>}
    <p className="ledger-explanation">Each translated detail stays connected to its source region. Small or difficult regions include the original crop alongside the available English.</p>
    {blocks.map((block) => {
      if (block.table_id) {
        if (renderedTables.has(block.table_id)) return null
        renderedTables.add(block.table_id)
        const cells = tables.get(block.table_id)!
        const rows = [...new Set(cells.map((cell) => cell.table_row ?? 0))].sort((a, b) => a - b)
        const columns = [...new Set(cells.map((cell) => cell.table_column ?? 0))].sort((a, b) => a - b)
        return <div className="ledger-table-wrap" key={block.table_id}><table><caption>Source table</caption><tbody>{rows.map((row) => <tr key={row}>{columns.map((column) => <td key={column}>{cells.filter((cell) => (cell.table_row ?? 0) === row && (cell.table_column ?? 0) === column).map((cell) => <div key={cell.id}>{content(cell)}</div>)}</td>)}</tr>)}</tbody></table></div>
      }
      return <div className={`ledger-block ledger-block--${block.kind}`} key={block.id}>{content(block)}</div>
    })}
    <details className="ledger-coverage"><summary>Source coverage and measured processing</summary>
      <p>{ledger.units.length} source units · {ledger.coverage.translated_unit_ids.length} translated · {ledger.coverage.fallback_unit_ids.length} source fallbacks · {ledger.coverage.displayed_unit_ids.length} displayed source IDs</p>
      <p>These counts track preservation and display. They do not establish translation accuracy or text that OCR missed.</p>
      <p>OCR {(ledger.metrics.ocr_ms / 1000).toFixed(1)}s · Layout {(ledger.metrics.layout_ms / 1000).toFixed(1)}s · Translation {(ledger.metrics.translation_ms / 1000).toFixed(1)}s · Semantic {(ledger.metrics.semantic_ms / 1000).toFixed(1)}s · Validation {(ledger.metrics.validation_ms / 1000).toFixed(1)}s · Drawing {(ledger.metrics.rendering_ms / 1000).toFixed(1)}s</p>
      <p>{ledger.metrics.semantic_requests} semantic requests · {ledger.metrics.input_tokens ?? 'Unavailable'} input / {ledger.metrics.output_tokens ?? 'Unavailable'} output / {ledger.metrics.total_tokens ?? 'Unavailable'} total tokens{!ledger.metrics.usage_complete && ' · Some request usage is unavailable'}</p>
    </details>
  </section>
}
