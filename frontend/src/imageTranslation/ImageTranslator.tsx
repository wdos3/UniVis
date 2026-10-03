import { useCallback, useEffect, useRef, useState } from 'react'
import { ArrowLeft, Download, Image as ImageIcon, LoaderCircle, Upload } from 'lucide-react'
import { isBrowserOcrSupported, recognizeImages, type BrowserOcrResult } from '../ocr/browserOcr'
import { SourceLedgerView } from '../components/SourceLedgerView'
import { fallbackLedger, pendingLedger, recordLedgerDisplay, unitsFromPages } from '../ledger/sourceLedger'
import { ledgerOverlayRegions, type LedgerOverlayRegion } from '../ledger/overlayRegions'
import { decodeLocalSource } from '../ledger/crops'
import { translateSourceLedger } from '../ledger/translateLedger'
import type { SourceLedger } from '../types'
import { renderTranslatedImage, type RenderDiagnostic } from './renderer'
import './imageTranslation.css'

interface Photo { file: File; url: string }

interface ImageTranslationOutput {
  url: string
  regions: LedgerOverlayRegion[]
  ledger: SourceLedger
  diagnostics: RenderDiagnostic[]
  detectedSpans: number
  ocrMs: number
  ocrReused: boolean
  translationMs: number
  renderMs: number
  totalMs: number
}

function pngBlob(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve, reject) => canvas.toBlob((blob) => {
    if (blob) resolve(blob)
    else reject(new Error('The translated image could not be exported.'))
  }, 'image/png'))
}

export function ImageTranslator({ onExit }: { onExit: () => void }) {
  const [photo, setPhoto] = useState<Photo | null>(null)
  const [output, setOutput] = useState<ImageTranslationOutput | null>(null)
  const [ledger, setLedger] = useState<SourceLedger | null>(null)
  const [showOriginal, setShowOriginal] = useState(false)
  const [busy, setBusy] = useState(false)
  const [stage, setStage] = useState('')
  const [error, setError] = useState('')
  const input = useRef<HTMLInputElement>(null)
  const ownedUrls = useRef<string[]>([])
  const selectionVersion = useRef(0)
  const inFlight = useRef(false)
  const controller = useRef<AbortController | null>(null)
  const ocrCache = useRef<{ version: number; result: BrowserOcrResult } | null>(null)
  const supported = isBrowserOcrSupported()
  const ledgerDisplayed = useCallback((ids: string[], renderingMs: number) => {
    setLedger((previous) => previous ? recordLedgerDisplay(previous, ids, Math.max(previous.metrics.rendering_ms, renderingMs)) : previous)
    setOutput((previous) => previous ? { ...previous, ledger: recordLedgerDisplay(previous.ledger, ids, previous.renderMs + renderingMs) } : previous)
  }, [])

  useEffect(() => () => {
    selectionVersion.current += 1
    controller.current?.abort()
    ocrCache.current = null
    ownedUrls.current.forEach((url) => URL.revokeObjectURL(url))
  }, [])

  function selectPhoto(file: File) {
    if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) { setError('Choose a JPG, PNG or WebP photo.'); return }
    if (file.size > 15 * 1024 * 1024) { setError('Choose an image smaller than 15 MB.'); return }
    selectionVersion.current += 1
    controller.current?.abort()
    ocrCache.current = null
    ownedUrls.current.forEach((url) => URL.revokeObjectURL(url))
    const url = URL.createObjectURL(file)
    ownedUrls.current = [url]
    setPhoto({ file, url })
    setOutput(null)
    setLedger(null)
    setShowOriginal(false)
    setError('')
    setStage('')
  }

  async function translatePhoto() {
    if (!photo || inFlight.current) return
    inFlight.current = true
    const version = selectionVersion.current
    const current = () => selectionVersion.current === version
    const started = performance.now()
    const abortController = new AbortController()
    controller.current = abortController
    setBusy(true)
    setError('')
    setStage('Reading text on this device…')
    let bitmap: Awaited<ReturnType<typeof decodeLocalSource>> | undefined
    try {
      const ocrReused = ocrCache.current?.version === version
      const ocr = ocrReused ? ocrCache.current!.result : await recognizeImages([photo.file])
      if (!current()) return
      ocrCache.current = { version, result: ocr }
      const spans = ocr.pages[0]?.spans ?? []
      const original = pendingLedger(unitsFromPages(ocr.pages), ocrReused ? 0 : ocr.latencyMs)
      setStage(`Translating ${original.units.length} source units…`)
      const translationStarted = performance.now()
      let translated: SourceLedger
      try {
        translated = await translateSourceLedger(original, abortController.signal)
      } catch {
        if (!current()) return
        translated = fallbackLedger(original)
        setError('The translation connection ended. The source image and recovered regions are retained below.')
      }
      const translationMs = performance.now() - translationStarted
      if (!current()) return
      setLedger(translated)
      const regions = ledgerOverlayRegions(translated)
      setStage('Placing English into the photo…')
      const renderStarted = performance.now()
      bitmap = await decodeLocalSource(photo.file)
      if (!current()) return
      const scale = Math.min(1, Math.sqrt(25_000_000 / (bitmap.width * bitmap.height)))
      const rendered = renderTranslatedImage({ image: bitmap.image, width: Math.round(bitmap.width * scale), height: Math.round(bitmap.height * scale), regions })
      const blob = await pngBlob(rendered.canvas)
      if (!current()) return
      const url = URL.createObjectURL(blob)
      ownedUrls.current.filter((owned) => owned !== photo.url).forEach((owned) => URL.revokeObjectURL(owned))
      ownedUrls.current = [photo.url, url]
      const renderedIds = new Set(rendered.diagnostics.filter((diagnostic) => diagnostic.status === 'rendered')
        .flatMap((diagnostic) => regions.find((region) => region.id === diagnostic.id)?.sourceUnitIds ?? []))
      translated = { ...translated, units: translated.units.map((unit) => ({ ...unit,
        display_destinations: renderedIds.has(unit.id) ? [...new Set([...unit.display_destinations, 'translated_image'])] : unit.display_destinations })),
        metrics: { ...translated.metrics, rendering_ms: Math.round(performance.now() - renderStarted) } }
      setLedger(translated)
      setOutput({ url, regions, ledger: translated, diagnostics: rendered.diagnostics, detectedSpans: spans.length,
        ocrMs: ocrReused ? 0 : ocr.latencyMs, ocrReused, translationMs, renderMs: performance.now() - renderStarted, totalMs: performance.now() - started })
      setShowOriginal(false)
    } catch (problem) {
      if (current()) setError(problem instanceof Error ? problem.message : 'Image translation failed. Try again.')
    } finally {
      bitmap?.close()
      inFlight.current = false
      if (controller.current === abortController) controller.current = null
      setBusy(false)
      if (current()) setStage('')
    }
  }

  const replacedIds = new Set(output?.diagnostics.filter((item) => item.status === 'rendered')
    .flatMap((item) => output.regions.find((region) => region.id === item.id)?.sourceUnitIds ?? []) ?? [])
  const preservedIds = ledger?.units.filter((unit) => !replacedIds.has(unit.id)).map((unit) => unit.id) ?? []

  return <div className="app image-translator">
    <header className="site-header"><strong>VisNotice · Image translation</strong><button className="secondary-button" onClick={onExit}><ArrowLeft size={16} />Notice workspace</button></header>
    <main className="page-shell overlay-workspace">
      <h1>Translate text in the picture</h1>
      <p>Read Korean text, translate it into English, and put the English back in the same place.</p>
      <p className="muted">Photos and the finished image stay in this browser. Recognized text is sent to the translation service. This mode does not run semantic analysis.</p>
      <div className="overlay-actions">
        <input ref={input} type="file" accept="image/jpeg,image/png,image/webp" hidden aria-label="Choose image to translate" onChange={(event) => {
          const file = event.target.files?.[0]
          if (file) selectPhoto(file)
          event.target.value = ''
        }} />
        <button className="secondary-button" onClick={() => input.current?.click()}><Upload size={16} />{photo ? 'Choose another image' : 'Upload image'}</button>
        <button className="primary-button" disabled={!photo || busy} onClick={translatePhoto}>{busy ? <LoaderCircle size={16} className="spin" /> : <ImageIcon size={16} />}Translate image</button>
        {output && <>
          <button className="secondary-button" aria-pressed={showOriginal} onClick={() => setShowOriginal(!showOriginal)}>{showOriginal ? 'Show translated image' : 'Show original image'}</button>
          <a className="secondary-button" href={output.url} download={`${photo?.file.name.replace(/\.[^.]+$/, '') ?? 'notice'}-english.png`}><Download size={16} />Download translated PNG</a>
        </>}
      </div>
      {!supported && <p role="status">Local OCR is unavailable in this browser. The original image and its source regions will still be preserved.</p>}
      {stage && <p role="status">{stage}</p>}
      {error && <p className="overlay-error" role="alert">{error}</p>}
      {output && <div className="overlay-report" role="status">
        <strong>{replacedIds.size} of {output.ledger.units.length} source units placed with English in the image</strong>
        <p>Every source unit remains in the translation below. Regions that do not fit retain their original crop alongside the English.</p>
        <p>OCR {output.ocrReused ? 'reused' : `${(output.ocrMs / 1000).toFixed(1)}s`} · Translation {(output.translationMs / 1000).toFixed(1)}s · Drawing {(output.renderMs / 1000).toFixed(1)}s · Total {(output.totalMs / 1000).toFixed(1)}s</p>
        <small>{output.ledger.metrics.translation_requests} known translation requests · {output.detectedSpans} positioned OCR spans{!output.ledger.metrics.usage_complete && ' · failed-attempt usage unavailable'}</small>
      </div>}
      {photo && <figure className="overlay-preview"><img src={output && !showOriginal ? output.url : photo.url} alt={output && !showOriginal ? 'English translations placed in the original photo' : 'Original photo to translate'} /><figcaption>{photo.file.name} · {output && !showOriginal ? 'Translated' : 'Original'}</figcaption></figure>}
      {ledger && <SourceLedgerView ledger={ledger} onDisplayed={ledgerDisplayed} pages={photo ? [{ page_number: 1, url: photo.url, file: photo.file }] : []} preservedIds={preservedIds} />}
    </main>
  </div>
}
