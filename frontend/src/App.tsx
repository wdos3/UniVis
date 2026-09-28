import { useEffect, useMemo, useRef, useState } from 'react'
import {
  ArrowRight, BookOpenCheck, ChevronDown, Download, Eye, EyeOff, FileText, FlaskConical,
  Image as ImageIcon, LayoutDashboard, LoaderCircle, LockKeyhole, PanelTop, Upload, WandSparkles,
} from 'lucide-react'
import { api } from './api/client'
import { FidelityReport } from './components/FidelityReport'
import { ImageInputPanel, type ImageAnalysisStatus, type ImageDraft } from './components/ImageInputPanel'
import { OriginalImageView } from './components/OriginalImageView'
import { VisualInstructions } from './components/VisualInstructions'
import { isBrowserOcrSupported, recognizeImages } from './ocr/browserOcr'
import { AdminView } from './pages/AdminView'
import { ResearchMode } from './research/ResearchMode'
import type { AnalysisResult, DemoQuestion, DemoSummary, ImageDemoSummary } from './types'

type Tab = 'original' | 'translation' | 'simplified' | 'visual'
type View = 'workspace' | 'research' | 'admin'

const tabOptions: { id: Tab; label: string; short: string }[] = [
  { id: 'original', label: 'Original Korean', short: 'Original' },
  { id: 'translation', label: 'Translation', short: 'A' },
  { id: 'simplified', label: 'Simplified Text', short: 'B' },
  { id: 'visual', label: 'Visual Instructions', short: 'C' },
]

function App() {
  const [view, setView] = useState<View>('workspace')
  const [demos, setDemos] = useState<DemoSummary[]>([])
  const [imageDemos, setImageDemos] = useState<ImageDemoSummary[]>([])
  const [imagePages, setImagePages] = useState<ImageDraft[]>([])
  const [progressStage, setProgressStage] = useState(0)
  const [ocrCompleted, setOcrCompleted] = useState(0)
  const [questions, setQuestions] = useState<DemoQuestion[]>([])
  const [text, setText] = useState('')
  const [provider, setProvider] = useState('auto')
  const [openaiConfigured, setOpenaiConfigured] = useState(false)
  const [imageAnalysisStatus, setImageAnalysisStatus] = useState<ImageAnalysisStatus>('checking')
  const [publicMode, setPublicMode] = useState(true)
  const [result, setResult] = useState<AnalysisResult | null>(null)
  const [activeTab, setActiveTab] = useState<Tab>('visual')
  const [showEvidence, setShowEvidence] = useState(false)
  const [busy, setBusy] = useState(false)
  const [processingImages, setProcessingImages] = useState(false)
  const [error, setError] = useState('')
  const fileInput = useRef<HTMLInputElement>(null)
  const textArea = useRef<HTMLTextAreaElement>(null)
  const imagePagesRef = useRef<ImageDraft[]>([])
  const resultImageUrls = useRef<string[]>([])
  const resultImageOwnerId = useRef<string | null>(null)

  useEffect(() => { imagePagesRef.current = imagePages }, [imagePages])
  useEffect(() => () => {
    imagePagesRef.current.forEach((page) => URL.revokeObjectURL(page.previewUrl))
    resultImageUrls.current.forEach((url) => URL.revokeObjectURL(url))
  }, [])

  useEffect(() => {
    Promise.all([api.demos(), api.imageDemos()]).then(([demoData, imageDemoData]) => { setDemos(demoData); setImageDemos(imageDemoData) }).catch((problem) => setError(problem instanceof Error ? problem.message : 'Could not load the examples.'))
    api.health().then((health) => {
      setOpenaiConfigured(health.openai_configured)
      setImageAnalysisStatus(isBrowserOcrSupported() ? 'ready' : 'unavailable')
      setPublicMode(health.public_mode !== false)
    }).catch((problem) => {
      setImageAnalysisStatus('error')
      setError(problem instanceof Error ? problem.message : 'Could not connect to the backend.')
    })
  }, [])

  const activeDemo = useMemo(() => demos.find((demo) => demo.original_text === text), [demos, text])

  function clearResultImages() {
    resultImageUrls.current.forEach((url) => URL.revokeObjectURL(url))
    resultImageUrls.current = []
    resultImageOwnerId.current = null
  }

  function showResult(analyzed: AnalysisResult) {
    clearResultImages()
    setResult(analyzed)
  }

  function attachLocalImages(analyzed: AnalysisResult, pages: ImageDraft[]): AnalysisResult {
    if (analyzed.source_pages.length !== pages.length) throw new Error('The analysis returned an unexpected number of source pages.')
    const urls = pages.map((page) => URL.createObjectURL(page.file))
    clearResultImages()
    resultImageUrls.current = urls
    resultImageOwnerId.current = analyzed.id
    return {
      ...analyzed,
      source_pages: analyzed.source_pages.map((page, index) => ({
        ...page,
        filename: pages[index].file.name,
        media_type: pages[index].file.type || page.media_type,
        original_url: urls[index],
        processed_url: urls[index],
      })),
    }
  }

  function updateResult(updated: AnalysisResult) {
    if (updated.id === resultImageOwnerId.current && resultImageUrls.current.length && updated.source_pages.length === resultImageUrls.current.length) {
      setResult({
        ...updated,
        source_pages: updated.source_pages.map((page, index) => ({
          ...page,
          filename: result?.source_pages[index]?.filename ?? page.filename,
          media_type: result?.source_pages[index]?.media_type ?? page.media_type,
          original_url: resultImageUrls.current[index],
          processed_url: resultImageUrls.current[index],
        })),
      })
      return
    }
    showResult(updated)
  }

  async function loadDemo(id: string) {
    if (!id) return
    const demo = demos.find((item) => item.id === id)
    setBusy(true); setError('')
    try {
      const loaded = await api.demo(id)
      imagePages.forEach((page) => URL.revokeObjectURL(page.previewUrl)); setImagePages([])
      setText(demo?.original_text ?? loaded.original_text); setQuestions(demo?.questions ?? []); showResult(loaded); setActiveTab('visual')
    } catch (problem) { setError(problem instanceof Error ? problem.message : 'Could not load the demo.') }
    finally { setBusy(false) }
  }

  async function generate() {
    if (!text.trim()) return
    setBusy(true); setError('')
    try {
      const analyzed = await api.analyze(text, provider)
      showResult(analyzed); setQuestions(activeDemo?.questions ?? []); setActiveTab('visual')
    } catch (problem) { setError(problem instanceof Error ? problem.message : 'Analysis failed.') }
    finally { setBusy(false) }
  }

  async function upload(file: File) {
    setBusy(true); setError('')
    try {
      const analyzed = await api.upload(file, provider)
      setText(analyzed.original_text); showResult(analyzed); setQuestions([]); setActiveTab('visual')
    } catch (problem) { setError(problem instanceof Error ? problem.message : 'Upload failed.') }
    finally { setBusy(false); if (fileInput.current) fileInput.current.value = '' }
  }

  function addImages(files: FileList | File[], source: ImageDraft['source'], replace = false) {
    const incoming = Array.from(files)
    const remaining = 12 - (replace ? 0 : imagePages.length)
    const additions = incoming.slice(0, remaining).map((file) => ({ id: crypto.randomUUID(), file, previewUrl: URL.createObjectURL(file), source }))
    if (additions.length) { clearResultImages(); setResult(null); setQuestions([]); setText('') }
    if (replace) imagePages.forEach((page) => URL.revokeObjectURL(page.previewUrl))
    setImagePages(replace ? additions : [...imagePages, ...additions])
    setError(incoming.length > remaining ? 'A notice can contain at most 12 pages.' : '')
  }

  function removeImage(id: string) {
    setImagePages((previous) => { const removed = previous.find((page) => page.id === id); if (removed) URL.revokeObjectURL(removed.previewUrl); return previous.filter((page) => page.id !== id) })
  }

  function moveImage(index: number, direction: -1 | 1) {
    setImagePages((previous) => { const next = [...previous]; const destination = index + direction; if (destination < 0 || destination >= next.length) return previous; [next[index], next[destination]] = [next[destination], next[index]]; return next })
  }

  async function analyzeImages() {
    if (!imagePages.length || imageAnalysisStatus !== 'ready') return
    const pages = [...imagePages]
    clearResultImages(); setResult(null); setQuestions([])
    setBusy(true); setProcessingImages(true); setError(''); setProgressStage(0); setOcrCompleted(0)
    try {
      const source = pages.some((page) => page.source === 'camera_photo') ? 'camera_photo' : 'uploaded_image'
      const recovered = await recognizeImages(pages.map((page) => page.file), (completed) => setOcrCompleted(completed))
      setText(recovered.pages.map((page) => page.text).join('\n\n'))
      setProgressStage(1)
      const analyzed = await api.analyzeClientOcr(recovered.pages, recovered.latencyMs, provider, source)
      setResult(attachLocalImages(analyzed, pages)); setQuestions([]); setActiveTab('original')
    } catch (problem) { setError(problem instanceof Error ? problem.message : 'Image analysis failed.') }
    finally { setBusy(false); setProcessingImages(false); setProgressStage(0); setOcrCompleted(0) }
  }

  async function loadImageDemo(demo: ImageDemoSummary) {
    setBusy(true); setError('')
    try {
      const files = await Promise.all(demo.page_urls.map(async (url) => { const response = await fetch(url); if (!response.ok) throw new Error('Could not load the demo image.'); const blob = await response.blob(); return new File([blob], url.split('/').pop() ?? 'demo-notice.png', { type: blob.type }) }))
      addImages(files, 'uploaded_image', true)
    } catch (problem) { setError(problem instanceof Error ? problem.message : 'Could not load image demo.') }
    finally { setBusy(false) }
  }

  if (view === 'research' && result) return <ResearchMode result={result} questions={questions} publicMode={publicMode} onExit={() => setView('workspace')} />
  if (view === 'admin' && !publicMode) return <AdminView current={result} onExit={() => setView('workspace')} onUpdated={updateResult} />

  return <div className="app">
    <header className="site-header">
      <a className="brand" href="#top" aria-label="VisNotice Version 2 home"><span className="brand-mark"><PanelTop size={20} /></span><span><strong>VisNotice — Version 2</strong><small>Token-efficient split pipeline</small></span></a>
      <nav aria-label="Application modes"><button onClick={() => setView('research')} disabled={!result || busy}><FlaskConical size={16} />Research Mode</button>{!publicMode && <button disabled={busy} onClick={() => setView('admin')}><LayoutDashboard size={16} />Researcher View</button>}</nav>
    </header>

    <main id="top">
      <section className="hero page-shell">
        <div className="hero-copy"><span className="eyebrow-text">Korean OCR → Translation → One semantic call</span><h1>Turn complex notices into <em>clear next steps.</em></h1><p>VisNotice Version 2 separates text recovery, translation, and semantic structuring to reduce OpenAI token use while retaining source evidence.</p>
          <div className="trust-row"><span><LockKeyhole size={15} />Source evidence retained</span><span><BookOpenCheck size={15} />Facts checked for coverage</span></div>
        </div>
        <div className="hero-motif" aria-hidden="true"><div className="paper-card back"><span /><span /><span /></div><div className="paper-card front"><span className="paper-label">Next step</span><strong>Prepare documents</strong><div className="mini-check"><i>✓</i>Passport</div><div className="mini-check"><i>✓</i>Residence Card</div></div><ArrowRight className="motif-arrow" /></div>
      </section>

      <section className="workspace page-shell">
        <div className="workspace-heading"><div><span className="section-number">01</span><div><h2>Capture a notice</h2><p>{imageAnalysisStatus === 'unavailable' ? 'Paste Korean text, upload a text-based document, or try a synthetic notice.' : 'Take a photo, combine image pages, upload a PDF, or paste Korean text.'}</p></div></div><label className="language-select">Output language<select disabled aria-label="Output language"><option>English</option></select><ChevronDown size={14} /></label></div>
        <ImageInputPanel pages={imagePages} demos={imageDemos} status={imageAnalysisStatus} busy={busy} processingImages={processingImages} progressStage={progressStage} ocrCompleted={ocrCompleted} onAdd={addImages} onRemove={removeImage} onMove={moveImage} onAnalyze={analyzeImages} onLoadDemo={loadImageDemo} />
        <div className="input-divider"><span>or use a document / text source</span></div>
        <div className="secondary-methods"><input ref={fileInput} hidden type="file" accept=".pdf,.txt" onChange={(event) => event.target.files?.[0] && upload(event.target.files[0])} /><button className="secondary-button" disabled={busy} onClick={() => fileInput.current?.click()}><Upload size={17} />Upload text-based PDF or TXT</button><button className="secondary-button" disabled={busy} onClick={() => textArea.current?.focus()}><FileText size={17} />Paste Korean text</button></div>
        <div className="input-grid">
          <div className="notice-input-card">
            <div className="input-toolbar"><span><FileText size={16} />Korean notice text</span><span className="character-count">{text.length.toLocaleString()} / 200,000</span></div>
            <textarea ref={textArea} lang="ko" value={text} disabled={busy} onChange={(event) => { setText(event.target.value); setQuestions([]) }} placeholder="공지사항의 한국어 텍스트를 여기에 붙여넣으세요…" />
            <div className="input-actions"><span>Text input remains available for controlled experiments and corrections.</span></div>
          </div>
          <aside className="demo-card"><span className="eyebrow-text">Start with an example</span><h3>Synthetic notice library</h3><p>Fictional examples exercise deadlines, conditions, documents, and exceptions.</p><div className="demo-list">{demos.map((demo) => <button key={demo.id} disabled={busy} onClick={() => loadDemo(demo.id)}><span>{demo.category}</span><strong>{demo.title}</strong><ArrowRight size={15} /></button>)}</div></aside>
        </div>
        <div className="generate-bar"><label>Semantic provider<select value={provider} disabled={busy} onChange={(event) => setProvider(event.target.value)}><option value="auto">Auto {openaiConfigured ? '(OpenAI)' : '(mock fallback)'}</option><option value="mock">Mock / demo only</option><option value="openai" disabled={!openaiConfigured}>OpenAI {!openaiConfigured && '— key not configured'}</option></select></label><button className="generate-button" disabled={busy || !text.trim()} onClick={generate}>{busy ? <LoaderCircle className="spin" size={18} /> : <WandSparkles size={18} />}{busy ? 'Analyzing…' : 'Generate instructions'}</button></div>
        <p className="privacy-note"><LockKeyhole size={14} />Notice photos stay in this browser; only their recognized text is sent to this site's server for translation and analysis. Text-based PDF/TXT uploads and generated results are stored on the server. Extracted text may be sent to the translation service, then bilingual text to the semantic provider.</p>
        {error && <p className="error-message" role="alert">{error}</p>}
      </section>

      {result && <section className="results page-shell">
        <div className="results-heading"><div><span className="section-number">02</span><div><span className="eyebrow-text">Analysis complete · {result.provider}</span><h2>{result.notice.title}</h2></div></div><div className="result-tools"><label className="toggle"><input type="checkbox" checked={showEvidence} onChange={(event) => setShowEvidence(event.target.checked)} /><span>{showEvidence ? <Eye size={16} /> : <EyeOff size={16} />}{showEvidence ? 'Evidence shown' : 'Show source evidence'}</span></label><button className="secondary-button" onClick={() => window.print()}><Download size={16} />Print / Save PDF</button></div></div>
        {!result.korean_detected && <div className="inline-notice" role="status">The notice does not appear to be primarily Korean. Analysis was allowed, but the source language should be reviewed.</div>}
        <div className="image-metrics"><div><ImageIcon size={18} /><span>OCR<strong>{result.acquisition.ocr_provider} · {(result.acquisition.ocr_latency_ms / 1000).toFixed(1)}s</strong></span></div><div><span>Translation<strong>{result.acquisition.translation_provider} · {result.acquisition.translation_requests} request(s) · {(result.acquisition.translation_latency_ms / 1000).toFixed(1)}s</strong></span></div><div><span>Semantic step<strong>{result.acquisition.semantic_provider} · {result.acquisition.semantic_requests} call(s) · {(result.acquisition.semantic_latency_ms / 1000).toFixed(1)}s</strong></span></div><div><span>OpenAI tokens<strong>{result.acquisition.semantic_total_tokens.toLocaleString()}</strong></span></div>{result.source_pages.length > 0 && <><div><span>Pages<strong>{result.acquisition.source_pages}</strong></span></div><div><span>Total pipeline<strong>{(result.acquisition.total_latency_ms / 1000).toFixed(1)}s</strong></span></div><div><span>Facts needing review<strong>{result.acquisition.critical_facts_needing_review}</strong></span></div></>}</div>
        <div className="condition-tabs" role="tablist" aria-label="Notice presentation conditions">{tabOptions.map((tab) => <button id={`tab-${tab.id}`} role="tab" aria-selected={activeTab === tab.id} aria-controls={`panel-${tab.id}`} className={activeTab === tab.id ? 'active' : ''} onClick={() => setActiveTab(tab.id)} key={tab.id}><span>{tab.short}</span>{tab.label}</button>)}</div>
        <div className="tab-panel" id={`panel-${activeTab}`} role="tabpanel" aria-labelledby={`tab-${activeTab}`}>
          {activeTab === 'original' && (result.source_pages.length > 0 ? <OriginalImageView result={result} provider={provider} editable={!publicMode} onUpdated={updateResult} /> : <article className="reading-panel"><div className="reading-meta"><span>Source language</span><strong>Korean</strong></div><div className="prose-output" lang="ko">{result.original_text}</div></article>)}
          {activeTab === 'translation' && <article className="reading-panel"><div className="reading-meta"><span>Condition A</span><strong>Faithful translation</strong></div><p className="condition-description">Baseline translation preserves detail and structure without deliberate simplification.</p><div className="prose-output">{result.faithful_translation}</div></article>}
          {activeTab === 'simplified' && <article className="reading-panel"><div className="reading-meta"><span>Condition B</span><strong>Simplified text</strong></div><p className="condition-description">Concise, structured English without visual diagrams or icons.</p><div className="prose-output simplified-output">{result.simplified_text}</div></article>}
          {activeTab === 'visual' && <VisualInstructions result={result} showEvidence={showEvidence} />}
        </div>
        <FidelityReport report={result.fidelity} />
        <div className="research-cta"><div><FlaskConical size={24} /><div><span className="eyebrow-text">Ready to evaluate</span><h3>Present one condition without revealing the others</h3><p>Research Mode records answers, confidence, and completion time on this site's server.</p></div></div><button className="primary-button" disabled={questions.length === 0} onClick={() => setView('research')}>Open Research Mode<ArrowRight size={16} /></button>{questions.length === 0 && <small>Load a synthetic demo to use its comprehension questions.</small>}</div>
      </section>}
    </main>
    <footer className="site-footer page-shell"><div><strong>VisNotice — Version 2</strong><span>Token-efficient visual notice instructions</span></div><p>Split-pipeline prototype · Always verify against the official notice.</p></footer>
  </div>
}

export default App
