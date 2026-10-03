import { Camera, ChevronLeft, ChevronRight, FileImage, ImagePlus, LoaderCircle, ScanLine, Trash2, Upload } from 'lucide-react'
import { useRef } from 'react'
import type { BrowserOcrPage } from '../ocr/browserOcr'
import type { ImageDemoSummary } from '../types'
import type { SourceCorrection } from '../api/client'
import { PhotoTimings, type PhotoTimingsData } from './PhotoTimings'

export interface ImageDraft { id: string; file: File; previewUrl: string; source: 'camera_photo' | 'uploaded_image' }
export type ImageAnalysisStatus = 'checking' | 'ready' | 'unavailable' | 'error'

interface Props {
  pages: ImageDraft[]
  demos: ImageDemoSummary[]
  status: ImageAnalysisStatus
  localOcrAvailable?: boolean
  busy: boolean
  processingImages: boolean
  progressStage: number
  ocrCompleted: number
  onAdd: (files: FileList | File[], source: ImageDraft['source'], replace?: boolean) => void
  onRemove: (id: string) => void
  onMove: (index: number, direction: -1 | 1) => void
  onAnalyze: () => void
  onLoadDemo: (demo: ImageDemoSummary) => void
  recoveredPages: BrowserOcrPage[] | null
  sourceCorrections?: SourceCorrection[]
  photoTimings?: PhotoTimingsData | null
  onEditRecoveredPage: (index: number, text: string) => void
  onRetryAnalysis: () => void
}

const stages = ['Browser OCR on this device', 'Source translation', 'English instructions and source coverage']

export function ImageInputPanel({ pages, demos, status, localOcrAvailable = true, busy, processingImages, progressStage, ocrCompleted, onAdd, onRemove, onMove, onAnalyze, onLoadDemo, recoveredPages, sourceCorrections = [], photoTimings, onEditRecoveredPage, onRetryAnalysis }: Props) {
  const cameraInput = useRef<HTMLInputElement>(null)
  const imageInput = useRef<HTMLInputElement>(null)
  const replaceImages = useRef(false)
  const correctionInputs = useRef<(HTMLTextAreaElement | null)[]>([])
  const canAnalyzeImages = status === 'ready' && !busy
  const recoveredCharacters = recoveredPages?.reduce((count, page) => count + page.text.length, 0) ?? 0
  const canRetry = canAnalyzeImages && !!recoveredPages?.length
    && recoveredCharacters <= 50_000 && recoveredPages.every((page) => page.text.length <= 20_000)
  const lowConfidenceLines = recoveredPages?.flatMap((page, index) => page.spans.flatMap((span) =>
    span.confidence !== undefined && span.confidence < 0.85
      && !sourceCorrections.some((correction) => correction.text === span.text)
      ? [{ page: index + 1, line: null, text: span.text,
        reason: `OCR confidence is ${Math.round(span.confidence * 100)}%. Compare this line with the photo and correct any misread characters.` }] : [])) ?? []
  const corrections = [...sourceCorrections, ...lowConfidenceLines]

  function correctionLocation(correction: SourceCorrection): { pageIndex: number; offset: number } | null {
    if (!recoveredPages || !correction.text) return null
    const candidates = recoveredPages.flatMap((page, pageIndex) => {
      const offset = page.text.indexOf(correction.text)
      return offset >= 0 ? [{ pageIndex, offset }] : []
    })
    return candidates.find(({ pageIndex }) => pageIndex + 1 === correction.page)
      ?? (candidates.length === 1 ? candidates[0] : null)
  }

  function focusCorrection(correction: SourceCorrection) {
    const location = correctionLocation(correction)
    if (!location) return
    const input = correctionInputs.current[location.pageIndex]
    input?.focus()
    input?.setSelectionRange(location.offset, location.offset + correction.text.length)
  }

  function chooseImages(replace = false) {
    replaceImages.current = replace
    imageInput.current?.click()
  }
  return <section className="image-input-panel">
    <div className="capture-intro"><div><span className="eyebrow-text">Primary input</span><h3>Photograph a Korean notice</h3><p>Analyze different notices one at a time. Combine images only when they are pages of the same notice, then check their order before analysis.</p></div><ScanLine size={38} aria-hidden="true" /></div>
    <div className={`ocr-status ${status === 'ready' ? 'available' : ''}`} role="status">
      {status === 'ready' ? <><strong>{localOcrAvailable ? 'Photos are read on your device.' : 'Photo recovery remains available without local OCR.'}</strong> {localOcrAvailable && 'The Korean/English OCR model downloads on first use, which can take extra time. '}Original images remain on your device. Recognized text, layout, and up to four bounded recovery crops can be sent to OpenAI through the API; a reduced page may be included when local OCR is unavailable. Recovery images are not stored on the server. Locally decoded QR links are never opened automatically.</> : status === 'unavailable' ? <><strong>Photo analysis is unavailable in this browser.</strong> This browser lacks a feature needed for local OCR. Try a recent browser, paste Korean text, or upload a text-based PDF/TXT file.</> : status === 'error' ? <><strong>Photo analysis could not be checked.</strong> Refresh the page to retry. Text and synthetic notices remain available.</> : <>Checking photo analysis availability…</>}
    </div>
    <div className="capture-actions">
      <input ref={cameraInput} hidden type="file" accept="image/*" capture="environment" onChange={(event) => { if (event.target.files) onAdd(event.target.files, 'camera_photo'); event.target.value = '' }} />
      <input ref={imageInput} hidden type="file" accept="image/jpeg,image/png,image/webp,.jpg,.jpeg,.png,.webp" multiple onChange={(event) => { if (event.target.files?.length) onAdd(event.target.files, 'uploaded_image', replaceImages.current); replaceImages.current = false; event.target.value = '' }} />
      <button className="camera-button" disabled={!canAnalyzeImages} onClick={() => cameraInput.current?.click()}><Camera size={22} /><span><strong>Take a Photo</strong><small>Use the rear camera</small></span></button>
      <button className="image-upload-button" disabled={!canAnalyzeImages} onClick={() => chooseImages()}><ImagePlus size={21} /><span><strong>Upload Image</strong><small>JPG, PNG, WEBP</small></span></button>
    </div>

    {pages.length > 0 && <div className="image-tray"><div className="tray-heading"><div><strong>Notice images</strong><span>{pages.length} {pages.length === 1 ? 'page' : 'pages'} · Pages of the same notice</span></div><button className="text-button" disabled={!canAnalyzeImages} onClick={() => chooseImages()}><Upload size={15} />Add another page</button><button className="text-button" disabled={!canAnalyzeImages} onClick={() => chooseImages(true)}><ImagePlus size={15} />Upload another notice</button></div>
      <ol className="page-previews">{pages.map((page, index) => <li key={page.id}>
        <div className="page-number">Page {index + 1}</div><img src={page.previewUrl} alt={`Notice page ${index + 1} preview`} />
        <div className="page-name" title={page.file.name}>{page.file.name}</div>
        <div className="page-controls"><button disabled={busy || index === 0} onClick={() => onMove(index, -1)} aria-label={`Move page ${index + 1} earlier`}><ChevronLeft size={16} /></button><button disabled={busy || index === pages.length - 1} onClick={() => onMove(index, 1)} aria-label={`Move page ${index + 1} later`}><ChevronRight size={16} /></button><button disabled={busy} onClick={() => onRemove(page.id)} aria-label={`Remove page ${index + 1}`}><Trash2 size={16} /></button></div>
      </li>)}</ol>
      {processingImages ? <div className="processing-pipeline" role="status"><div className="pipeline-title"><LoaderCircle className="spin" size={18} />{progressStage === 0 ? `Reading pages on this device (${ocrCompleted}/${pages.length})…` : 'Analyzing recovered text…'}</div><ol>{stages.map((stage, index) => <li className={index < progressStage ? 'done' : index === progressStage ? 'current' : ''} key={stage}><span>{index < progressStage ? '✓' : index === progressStage ? '●' : '○'}</span>{stage}</li>)}</ol></div> : <button className="analyze-images-button" disabled={!canAnalyzeImages} onClick={onAnalyze}><ScanLine size={19} />Analyze {pages.length > 1 ? `${pages.length} pages as one notice` : 'notice photo'}</button>}
      {recoveredPages && !processingImages && <div className="ocr-correction-panel">
        <div className="ocr-correction-heading"><strong>Retry without Korean transcription</strong><span>{recoveredCharacters.toLocaleString()} / 50,000 characters</span></div>
        <p>The service could not finish this attempt. You can retry without editing Korean, or upload a clearer photo. Source-text editing is optional for users who can check the original wording. The photos remain in this browser.</p>
        {corrections.length > 0 && <div className="ocr-correction-requests"><strong>Details to check against the photo</strong><ol>{corrections.map((correction, index) => <li key={`${correction.page}-${correction.line}-${index}`}>
          <span>{correction.page ? `Page ${correction.page}` : 'Source text'}{correction.line ? ` · source line ${correction.line}` : ''}</span>
          <blockquote lang="ko">{correction.text}</blockquote><p>{correction.reason}</p>
          {correctionLocation(correction) && <button className="text-button" disabled={busy} onClick={() => focusCorrection(correction)}>Find in page text</button>}
        </li>)}</ol></div>}
        {photoTimings && <PhotoTimings timings={photoTimings} />}
        <div className="ocr-correction-pages">{recoveredPages.map((recovered, index) => <label key={pages[index].id}>
          <span>Page {index + 1} recognized text · {recovered.text.length.toLocaleString()} / 20,000 <a href={pages[index].previewUrl} target="_blank" rel="noopener noreferrer" onClick={(event) => event.stopPropagation()}>Open page photo</a></span>
          <textarea ref={(element) => { correctionInputs.current[index] = element }} lang="ko" value={recovered.text} maxLength={20_000} disabled={busy} onChange={(event) => onEditRecoveredPage(index, event.target.value)} />
        </label>)}</div>
        <button className="analyze-images-button" disabled={!canRetry} onClick={onRetryAnalysis}>Retry analysis</button>
      </div>}
    </div>}

    <div className="image-demo-strip"><span>Synthetic image demos</span><p>These test browser OCR. Mock mode may not interpret imperfectly recognized text; the synthetic text library remains available.</p><div>{demos.map((demo) => <button key={demo.id} disabled={!canAnalyzeImages} onClick={() => onLoadDemo(demo)}><FileImage size={15} /><span><strong>{demo.title}</strong><small>{demo.description}</small></span></button>)}</div></div>
  </section>
}
