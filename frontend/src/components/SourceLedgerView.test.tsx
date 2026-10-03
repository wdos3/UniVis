import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { makeSourceUnit, pendingLedger } from '../ledger/sourceLedger'
import { SourceLedgerView } from './SourceLedgerView'

afterEach(cleanup)

describe('complete source translation view', () => {
  it('retains table label/value column pairings and every displayed source ID', () => {
    const entries = ['TOEIC', 'TOEFL iBT', '800', '91']
    const ledger = pendingLedger(entries.map((text, index) => ({ ...makeSourceUnit({ page: 1, text, order: index, id: `unit-${index}` }),
      english: text, table_id: 'scores', table_row: Math.floor(index / 2), table_column: index % 2, translation_source_ids: [`unit-${index}`] })))
    ledger.blocks = ledger.blocks.map((block, index) => ({ ...block, kind: 'table_cell', table_id: 'scores', table_row: Math.floor(index / 2), table_column: index % 2 }))
    const { container } = render(<SourceLedgerView ledger={ledger} />)
    const rows = within(screen.getByRole('table')).getAllByRole('row')
    expect(within(rows[0]).getAllByRole('cell').map((cell) => cell.querySelector('[lang="en"]')?.textContent)).toEqual(['TOEIC', 'TOEFL iBT'])
    expect(within(rows[1]).getAllByRole('cell').map((cell) => cell.querySelector('[lang="en"]')?.textContent)).toEqual(['800', '91'])
    expect([...container.querySelectorAll('[data-source-unit-id]')].map((element) => element.getAttribute('data-source-unit-id'))).toEqual(ledger.units.map((unit) => unit.id))
  })

  it('renders an orphan unit and source crop even when block metadata is absent', () => {
    const unit = { ...makeSourceUnit({ page: 1, text: '문의', order: 0, id: 'contact', box: { x: .1, y: .8, width: .4, height: .02 } }),
      english: 'Contact: best available reading', translation_status: 'source_crop' as const }
    const ledger = pendingLedger([unit]); ledger.blocks = []
    render(<SourceLedgerView ledger={ledger} pages={[{ page_number: 1, url: 'blob:original' }]} />)
    expect(screen.getByText(unit.english)).toBeVisible()
    expect(screen.getAllByAltText('Preserved source region contact')[0]).toHaveAttribute('src', 'blob:original')
  })

  it('shows a shared paragraph once while retaining all source region evidence', () => {
    const units = [0, 1].map((order) => ({ ...makeSourceUnit({ page: 1, text: `source ${order}`, order, id: `unit-${order}` }),
      english: 'Enrolled students may apply. Students on leave cannot receive funding.', translation_source_ids: ['unit-0', 'unit-1'] }))
    const ledger = pendingLedger(units)
    ledger.blocks = [{ ...ledger.blocks[0], unit_ids: ['unit-0', 'unit-1'] }]
    const { container } = render(<SourceLedgerView ledger={ledger} />)
    expect(screen.getAllByText(units[0].english)).toHaveLength(1)
    expect(container.querySelectorAll('[data-source-unit-id]')).toHaveLength(2)
  })

  it('reports actual rendered source IDs after commit without repeatedly notifying on unchanged units', async () => {
    const ledger = pendingLedger([makeSourceUnit({ page: 1, text: 'source', order: 0, id: 'one' })])
    const displayed = vi.fn()
    const view = render(<SourceLedgerView ledger={ledger} onDisplayed={displayed} />)
    await waitFor(() => expect(displayed).toHaveBeenCalledWith(['one'], expect.any(Number)))
    view.rerender(<SourceLedgerView ledger={{ ...ledger, metrics: { ...ledger.metrics, rendering_ms: 25 } }} onDisplayed={displayed} />)
    expect(displayed).toHaveBeenCalledTimes(1)
  })
})
