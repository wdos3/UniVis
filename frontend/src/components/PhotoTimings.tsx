import type { BrowserOcrMetrics } from '../ocr/browserOcr'

export interface PhotoTimingsData extends BrowserOcrMetrics {
  serverRequestMs?: number
  translationRequestMs?: number
}

function seconds(milliseconds: number): string {
  return `${(milliseconds / 1000).toFixed(1)}s`
}

export function PhotoTimings({ timings }: { timings: PhotoTimingsData }) {
  return <>
    {timings.recoveryWarnings.map((warning) => <p className="inline-notice" role="status" key={warning}>{warning}</p>)}
    <details className="photo-timings">
      <summary>Measured photo processing{timings.serverRequestMs !== undefined ? ` · ${seconds(timings.latencyMs + timings.serverRequestMs)}` : ''}</summary>
      <dl>
        <div><dt>OCR preparation ({timings.modelState === 'reused' ? 'model reused' : 'model initialized'})</dt><dd>{seconds(timings.initializationMs)}</dd></div>
        {timings.detectionMs !== null && <div><dt>Text detection</dt><dd>{seconds(timings.detectionMs)}</dd></div>}
        {timings.recognitionMs !== null && <div><dt>Text recognition</dt><dd>{seconds(timings.recognitionMs)}</dd></div>}
        {timings.qrMs !== undefined && <div><dt>QR preparation and scanning (parallel)</dt><dd>{timings.qrMs === null ? 'Stopped before completion' : seconds(timings.qrMs)}</dd></div>}
        <div><dt>Reading images and QR codes</dt><dd>{seconds(timings.inferenceMs)}</dd></div>
        <div><dt>Additional small-text checks</dt><dd>{timings.detailPasses}</dd></div>
        {timings.translationRequestMs !== undefined && <div><dt>Translation request wait, including network</dt><dd>{seconds(timings.translationRequestMs)}</dd></div>}
        {timings.serverRequestMs !== undefined && <div><dt>{timings.translationRequestMs === undefined ? 'Latest server analysis, including network' : 'Translation, image recovery and instructions, including network'}</dt><dd>{seconds(timings.serverRequestMs)}</dd></div>}
      </dl>
      <p>Measured on this device. The total includes local OCR and the latest server processing sequence; editing time and earlier failed requests are excluded. Translation request wait is part of that sequence. Detection and recognition are parts of image reading. QR work runs alongside OCR, so its time is not added to the total. For oversized notices, ledger stage times sum work across concurrently processed batches rather than elapsed wall time.</p>
    </details>
  </>
}
