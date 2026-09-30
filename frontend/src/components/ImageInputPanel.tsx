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

const stages = ['Browser OCR on this device', 'Server translation and semantic analysis']

export function ImageInputPanel({ pages, demos, status, busy, processingImages, progressStage, ocrCompleted, onAdd, onRemove, onMove, onAnalyze, onLoadDemo, recoveredPages, sourceCorrections = [], photoTimings, onEditRecoveredPage, onRetryAnalysis }: Props) {
  const cameraInput = useRef<HTMLInputElement>(null)
  const imageInput = useRef<HTMLInputElement>(null)
  const correctionInputs = useRef<(HTMLTextAreaElement | null)[]>([])
  const canAnalyzeImages = status === 'ready' && !busy
  const recoveredCharacters = recoveredPages?.reduce((count, page) => count + page.text.length, 0) ?? 0
  const canRetry = canAnalyzeImages && !!recoveredPages?.some((page) => page.text.trim())
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
  return <section className="image-input-panel">
    <div className="capture-intro"><div><span className="eyebrow-text">Primary input</span><h3>Photograph a campus notice</h3><p>Take a photo or combine several pages. You can review their order before analysis.</p></div><ScanLine size={38} aria-hidden="true" /></div>
    <div className={`ocr-status ${status === 'ready' ? 'available' : ''}`} role="status">
      {status === 'ready' ? <><strong>Photos are read on your device.</strong> The Korean/English OCR model downloads on first use, which can take extra time. Photos stay in this browser; recognized text and any locally decoded QR web URLs are sent to the server for analysis. Links are never opened automatically. Check them against the original notice.</> : status === 'unavailable' ? <><strong>Photo analysis is unavailable in this browser.</strong> This browser lacks a feature needed for local OCR. Try a recent browser, paste Korean text, or upload a text-based PDF/TXT file.</> : status === 'error' ? <><strong>Photo analysis could not be checked.</strong> Refresh the page to retry. Text and synthetic notices remain available.</> : <>Checking photo analysis availability…</>}
    </div>
    <div className="capture-actions">
      <input ref={cameraInput} hidden type="file" accept="image/*" capture="environment" onChange={(event) => { if (event.target.files) onAdd(event.target.files, 'camera_photo'); event.target.value = '' }} />
      <input ref={imageInput} hidden type="file" accept="image/jpeg,image/png,image/webp,.jpg,.jpeg,.png,.webp" multiple onChange={(event) => { if (event.target.files) onAdd(event.target.files, 'uploaded_image'); event.target.value = '' }} />
      <button className="camera-button" disabled={!canAnalyzeImages} onClick={() => cameraInput.current?.click()}><Camera size={22} /><span><strong>Take a Photo</strong><small>Use the rear camera</small></span></button>
      <button className="image-upload-button" disabled={!canAnalyzeImages} onClick={() => imageInput.current?.click()}><ImagePlus size={21} /><span><strong>Upload Image</strong><small>JPG, PNG, WEBP</small></span></button>
    </div>

    {pages.length > 0 && <div className="image-tray"><div className="tray-heading"><div><strong>Notice images</strong><span>{pages.length} {pages.length === 1 ? 'page' : 'pages'} · Check the order before analysis</span></div><button className="text-button" disabled={!canAnalyzeImages} onClick={() => imageInput.current?.click()}><Upload size={15} />Add another page</button></div>
      <ol className="page-previews">{pages.map((page, index) => <li key={page.id}>
        <div className="page-number">Page {index + 1}</div><img src={page.previewUrl} alt={`Notice page ${index + 1} preview`} />
        <div className="page-name" title={page.file.name}>{page.file.name}</div>
        <div className="page-controls"><button disabled={busy || index === 0} onClick={() => onMove(index, -1)} aria-label={`Move page ${index + 1} earlier`}><ChevronLeft size={16} /></button><button disabled={busy || index === pages.length - 1} onClick={() => onMove(index, 1)} aria-label={`Move page ${index + 1} later`}><ChevronRight size={16} /></button><button disabled={busy} onClick={() => onRemove(page.id)} aria-label={`Remove page ${index + 1}`}><Trash2 size={16} /></button></div>
      </li>)}</ol>
      {processingImages ? <div className="processing-pipeline" role="status"><div className="pipeline-title"><LoaderCircle className="spin" size={18} />{progressStage === 0 ? `Reading pages on this device (${ocrCompleted}/${pages.length})…` : 'Analyzing recovered text…'}</div><ol>{stages.map((stage, index) => <li className={index < progressStage ? 'done' : index === progressStage ? 'current' : ''} key={stage}><span>{index < progressStage ? '✓' : index === progressStage ? '●' : '○'}</span>{stage}</li>)}</ol></div> : <button className="analyze-images-button" disabled={!canAnalyzeImages} onClick={onAnalyze}><ScanLine size={19} />Analyze {pages.length > 1 ? `${pages.length} pages as one notice` : 'notice photo'}</button>}
      {recoveredPages && !processingImages && <div className="ocr-correction-panel">
        <div className="ocr-correction-heading"><strong>Review recognized text before retrying</strong><span>{recoveredCharacters.toLocaleString()} / 50,000 characters</span></div>
        <p>Analysis did not complete, but the photos were read on this device. Compare each page with its photo and correct OCR mistakes. Editing existing lines keeps their approximate positions; unchanged lines keep their positions when other lines are added or removed. Rearranging lines clears position hints. Remove text only if the photo confirms it is decorative or irrelevant. The photos remain in this browser.</p>
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
        <button className="analyze-images-button" disabled={!canRetry} onClick={onRetryAnalysis}>Retry analysis with corrected text</button>
      </div>}
    </div>}

    <div className="image-demo-strip"><span>Synthetic image demos</span><p>These test browser OCR. Mock mode may not interpret imperfectly recognized text; the synthetic text library remains available.</p><div>{demos.map((demo) => <button key={demo.id} disabled={!canAnalyzeImages} onClick={() => onLoadDemo(demo)}><FileImage size={15} /><span><strong>{demo.title}</strong><small>{demo.description}</small></span></button>)}</div></div>
  </section>
}
