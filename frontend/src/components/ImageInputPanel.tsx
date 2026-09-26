import { Camera, ChevronLeft, ChevronRight, FileImage, ImagePlus, LoaderCircle, ScanLine, Trash2, Upload } from 'lucide-react'
import { useRef } from 'react'
import type { ImageDemoSummary } from '../types'

export interface ImageDraft { id: string; file: File; previewUrl: string; source: 'camera_photo' | 'uploaded_image' }
export type ImageAnalysisStatus = 'checking' | 'ready' | 'unavailable' | 'error'

interface Props {
  pages: ImageDraft[]
  demos: ImageDemoSummary[]
  status: ImageAnalysisStatus
  busy: boolean
  progressStage: number
  onAdd: (files: FileList | File[], source: ImageDraft['source'], replace?: boolean) => void
  onRemove: (id: string) => void
  onMove: (index: number, direction: -1 | 1) => void
  onAnalyze: () => void
  onLoadDemo: (demo: ImageDemoSummary) => void
}

const stages = ['Images prepared for OCR', 'PaddleOCR (Korean)', 'Temporary translation', 'One semantic call', 'Deterministic visual instructions']

export function ImageInputPanel({ pages, demos, status, busy, progressStage, onAdd, onRemove, onMove, onAnalyze, onLoadDemo }: Props) {
  const cameraInput = useRef<HTMLInputElement>(null)
  const imageInput = useRef<HTMLInputElement>(null)
  const canAnalyzeImages = status === 'ready'
  return <section className="image-input-panel">
    <div className="capture-intro"><div><span className="eyebrow-text">Primary input</span><h3>Photograph a campus notice</h3><p>Take a photo or combine several pages. You can review their order before analysis.</p></div><ScanLine size={38} aria-hidden="true" /></div>
    {status !== 'ready' && <div className="ocr-status" role="status">
      {status === 'unavailable' ? <><strong>Photo analysis is unavailable on this website.</strong> The OCR service is not connected. Paste Korean text, upload a text-based PDF or TXT file, or open a synthetic notice below.</> : status === 'error' ? <><strong>Photo analysis could not be checked.</strong> Refresh the page to retry. Text and synthetic notices remain available.</> : <>Checking photo analysis availability…</>}
    </div>}
    <div className="capture-actions">
      <input ref={cameraInput} hidden type="file" accept="image/*" capture="environment" onChange={(event) => event.target.files && onAdd(event.target.files, 'camera_photo')} />
      <input ref={imageInput} hidden type="file" accept="image/jpeg,image/png,image/webp,image/heic,image/heif,.jpg,.jpeg,.png,.webp,.heic,.heif" multiple onChange={(event) => event.target.files && onAdd(event.target.files, 'uploaded_image')} />
      <button className="camera-button" disabled={!canAnalyzeImages} onClick={() => cameraInput.current?.click()}><Camera size={22} /><span><strong>Take a Photo</strong><small>Use the rear camera</small></span></button>
      <button className="image-upload-button" disabled={!canAnalyzeImages} onClick={() => imageInput.current?.click()}><ImagePlus size={21} /><span><strong>Upload Image</strong><small>JPG, PNG, WEBP, HEIC</small></span></button>
    </div>

    {pages.length > 0 && <div className="image-tray"><div className="tray-heading"><div><strong>Notice images</strong><span>{pages.length} {pages.length === 1 ? 'page' : 'pages'} · Check the order before analysis</span></div><button className="text-button" disabled={!canAnalyzeImages} onClick={() => imageInput.current?.click()}><Upload size={15} />Add another page</button></div>
      <ol className="page-previews">{pages.map((page, index) => <li key={page.id}>
        <div className="page-number">Page {index + 1}</div><img src={page.previewUrl} alt={`Notice page ${index + 1} preview`} />
        <div className="page-name" title={page.file.name}>{page.file.name}</div>
        <div className="page-controls"><button disabled={index === 0} onClick={() => onMove(index, -1)} aria-label={`Move page ${index + 1} earlier`}><ChevronLeft size={16} /></button><button disabled={index === pages.length - 1} onClick={() => onMove(index, 1)} aria-label={`Move page ${index + 1} later`}><ChevronRight size={16} /></button><button onClick={() => onRemove(page.id)} aria-label={`Remove page ${index + 1}`}><Trash2 size={16} /></button></div>
      </li>)}</ol>
      {busy ? <div className="processing-pipeline" role="status"><div className="pipeline-title"><LoaderCircle className="spin" size={18} />Reading notice…</div><ol>{stages.map((stage, index) => <li className={index < progressStage ? 'done' : index === progressStage ? 'current' : ''} key={stage}><span>{index < progressStage ? '✓' : index === progressStage ? '●' : '○'}</span>{stage}</li>)}</ol></div> : <button className="analyze-images-button" disabled={!canAnalyzeImages} onClick={onAnalyze}><ScanLine size={19} />Analyze {pages.length > 1 ? `${pages.length} pages as one notice` : 'notice photo'}</button>}
    </div>}

    <div className="image-demo-strip"><span>Synthetic image demos</span><div>{demos.map((demo) => <button key={demo.id} disabled={!canAnalyzeImages} onClick={() => onLoadDemo(demo)}><FileImage size={15} /><span><strong>{demo.title}</strong><small>{demo.description}</small></span></button>)}</div></div>
  </section>
}
