import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { PhotoTimings, type PhotoTimingsData } from './PhotoTimings'

const timings: PhotoTimingsData = {
  latencyMs: 1200,
  initializationMs: 100,
  inferenceMs: 1100,
  modelState: 'reused',
  detectionMs: 200,
  recognitionMs: 500,
  detailPasses: 1,
  recoveryWarnings: [],
  serverRequestMs: 800,
}

describe('PhotoTimings', () => {
  afterEach(cleanup)

  it('shows parallel QR work without adding it to the processing total', () => {
    render(<PhotoTimings timings={{ ...timings, qrMs: 600 }} />)

    expect(screen.getByText('Measured photo processing · 2.0s')).toBeInTheDocument()
    expect(screen.getByText('QR preparation and scanning (parallel)')).toBeInTheDocument()
    expect(screen.getByText('0.6s')).toBeInTheDocument()
    expect(screen.getByText(/QR work runs alongside OCR/)).toHaveTextContent('its time is not added to the total')
  })

  it('labels incomplete QR work without reporting a fabricated elapsed time', () => {
    render(<PhotoTimings timings={{ ...timings, qrMs: null }} />)

    expect(screen.getByText('QR preparation and scanning (parallel)')).toBeInTheDocument()
    expect(screen.getByText('Stopped before completion')).toBeInTheDocument()
  })

  it('keeps older timing data usable without a QR measurement', () => {
    render(<PhotoTimings timings={timings} />)

    expect(screen.getByText('Measured photo processing · 2.0s')).toBeInTheDocument()
    expect(screen.queryByText('QR preparation and scanning (parallel)')).not.toBeInTheDocument()
  })
})
