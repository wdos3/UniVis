import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, Download, Image as ImageIcon, LoaderCircle, Upload } from 'lucide-react'
import { api, type ImageTextTranslationResult } from '../api/client'
import { isBrowserOcrSupported, recognizeImages, type BrowserOcrResult } from '../ocr/browserOcr'
import { buildTranslationRegions, type TranslationRegion } from './regions'
import { renderTranslatedImage, type RenderDiagnostic } from './renderer'
import './imageTranslation.css'

interface Photo { file: File; url: string }

interface ImageTranslationOutput {
  url: string
  regions: TranslationRegion[]
  translation: ImageTextTranslationResult
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
    let bitmap: ImageBitmap | undefined
    try {
      const ocrReused = ocrCache.current?.version === version
      const ocr = ocrReused ? ocrCache.current!.result : await recognizeImages([photo.file])
      if (!current()) return
      ocrCache.current = { version, result: ocr }
      const spans = ocr.pages[0]?.spans ?? []
      const regions = buildTranslationRegions(spans)
      if (!regions.length) throw new Error('No positioned text was detected. Try a closer, sharper photo.')
      if (regions.length > 200) throw new Error('This photo has more than 200 text regions. Try one poster or page at a time.')
      setStage(`Translating ${regions.length} text regions…`)
      const translationStarted = performance.now()
      const translation = await api.translateImageText(regions.map((region) => ({ id: region.id, text: region.sourceText })), abortController.signal)
      const translationMs = performance.now() - translationStarted
      if (!current()) return
      const byId = new Map(translation.regions.map((region) => [region.id, region]))
      if (byId.size !== regions.length || translation.regions.length !== regions.length
        || regions.some((region) => byId.get(region.id)?.source_text !== region.sourceText)) {
        throw new Error('The translation response did not match the detected text regions. Try translating again.')
      }
      setStage('Placing English into the photo…')
      const renderStarted = performance.now()
      bitmap = await createImageBitmap(photo.file, { imageOrientation: 'from-image' })
      if (!current()) return
      if (bitmap.width * bitmap.height > 25_000_000) throw new Error('This image is too large to draw safely. Resize it below 25 megapixels.')
      const rendered = renderTranslatedImage({ image: bitmap, width: bitmap.width, height: bitmap.height,
        regions: regions.map((region) => {
          const translated = byId.get(region.id)!
          return { ...region, translatedText: translated.translated_text, status: translated.status }
        }),
      })
      const blob = await pngBlob(rendered.canvas)
      if (!current()) return
      const url = URL.createObjectURL(blob)
      ownedUrls.current.filter((owned) => owned !== photo.url).forEach((owned) => URL.revokeObjectURL(owned))
      ownedUrls.current = [photo.url, url]
      setOutput({ url, regions, translation, diagnostics: rendered.diagnostics, detectedSpans: spans.length,
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

  const replaced = output?.diagnostics.filter((item) => item.status === 'rendered').length ?? 0
  const unchanged = output?.translation.regions.filter((item) => item.status === 'unchanged').length ?? 0
  const preserved = output ? output.regions.length - replaced - unchanged : 0

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
        <button className="primary-button" disabled={!photo || busy || !supported} onClick={translatePhoto}>{busy ? <LoaderCircle size={16} className="spin" /> : <ImageIcon size={16} />}Translate image</button>
        {output && <>
          <button className="secondary-button" aria-pressed={showOriginal} onClick={() => setShowOriginal(!showOriginal)}>{showOriginal ? 'Show translated image' : 'Show original image'}</button>
          <a className="secondary-button" href={output.url} download={`${photo?.file.name.replace(/\.[^.]+$/, '') ?? 'notice'}-english.png`}><Download size={16} />Download translated PNG</a>
        </>}
      </div>
      {!supported && <p role="alert">This browser cannot run local OCR. Use a recent browser with WebAssembly support.</p>}
      {stage && <p role="status">{stage}</p>}
      {error && <p className="overlay-error" role="alert">{error}</p>}
      {output && <div className="overlay-report" role="status">
        <strong>{replaced} of {output.regions.length} regions replaced with English</strong>
        <p>{unchanged} regions already contained Latin text or numbers. {preserved} regions kept their original text because translation or readable placement failed.</p>
        <p>OCR {output.ocrReused ? 'reused' : `${(output.ocrMs / 1000).toFixed(1)}s`} · Translation {(output.translationMs / 1000).toFixed(1)}s · Drawing {(output.renderMs / 1000).toFixed(1)}s · Total {(output.totalMs / 1000).toFixed(1)}s</p>
        <small>{output.translation.provider} · {output.translation.request_count} known translation requests · {output.detectedSpans} positioned OCR spans{!output.translation.metrics_complete && ' · failed-attempt usage unavailable'}</small>
      </div>}
      {photo && <figure className="overlay-preview"><img src={output && !showOriginal ? output.url : photo.url} alt={output && !showOriginal ? 'English translations placed in the original photo' : 'Original photo to translate'} /><figcaption>{photo.file.name} · {output && !showOriginal ? 'Translated' : 'Original'}</figcaption></figure>}
      {output && <details className="overlay-regions"><summary>Read translations ({output.regions.length} regions)</summary>
        <p>These are machine translations of detected text. Replacement counts measure placement, not translation accuracy or text that OCR missed.</p>
        <ol>{output.regions.map((region) => {
          const translated = output.translation.regions.find((item) => item.id === region.id)!
          const drawn = output.diagnostics.find((item) => item.id === region.id)
          return <li key={region.id}><span className="overlay-region-status">{region.id} · {drawn?.status === 'rendered' ? 'Placed in image' : translated.status === 'unchanged' ? 'Original retained' : `Original retained: ${translated.error || drawn?.reason || 'translation failed'}`}</span><div lang="ko">{region.sourceText}</div><div>{translated.translated_text}</div></li>
        })}</ol>
      </details>}
    </main>
  </div>
}
