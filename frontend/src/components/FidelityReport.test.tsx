import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { FidelityReport } from './FidelityReport'

describe('FidelityReport', () => {
  it('does not present model-identified facts as complete source coverage', () => {
    render(<FidelityReport report={{
      checks: [], warnings: [], critical_fields_in_source: 8,
      critical_fields_represented: 8, potentially_missing: [],
      potentially_invented: [], unmapped_source_line_count: 1,
      unmapped_source_lines: ['거시경제 조사·연구'], serious_issue: false,
    }} />)

    expect(screen.getByText('Identified critical facts')).toBeInTheDocument()
    expect(screen.getByText(/cannot detect facts the AI omitted/)).toBeInTheDocument()
    expect(screen.queryByText('Critical facts in source')).not.toBeInTheDocument()
    expect(screen.getByText('1 OCR line(s) not mapped to the summary')).toBeInTheDocument()
  })
})
