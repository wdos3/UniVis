import { useEffect, useState } from 'react'
import { AlertTriangle, ArrowLeft, Braces, Check, Image as ImageIcon, Save } from 'lucide-react'
import { api } from '../api/client'
import { FidelityReport } from '../components/FidelityReport'
import { VisualInstructions } from '../components/VisualInstructions'
import type { AnalysisResult, NoticeData } from '../types'

export function AdminView({ current, onExit, onUpdated }: { current: AnalysisResult | null; onExit: () => void; onUpdated: (result: AnalysisResult) => void }) {
  const [notices, setNotices] = useState<AnalysisResult[]>([])
  const [selected, setSelected] = useState<AnalysisResult | null>(current)
  const [draft, setDraft] = useState(current ? JSON.stringify(current.notice, null, 2) : '')
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)
  const criticalFactCount = selected?.notice.source_facts.filter((fact) => fact.critical).length ?? 0
  const verifiedCriticalFactCount = selected?.notice.source_facts.filter((fact) => fact.critical && fact.state === 'verified').length ?? 0

  useEffect(() => { api.notices().then(setNotices).catch(() => setNotices([])) }, [])

  function choose(result: AnalysisResult) { setSelected(result); setDraft(JSON.stringify(result.notice, null, 2)); setError(''); setSaved(false) }
  async function save() {
    if (!selected) return
    try {
      const parsed = JSON.parse(draft) as NoticeData
      const updated = await api.updateNotice(selected.id, parsed)
      const withLocalImages = {
        ...updated,
        source_pages: updated.source_pages.map((page, index) => ({
          ...page,
          original_url: selected.source_pages[index]?.original_url || page.original_url,
          processed_url: selected.source_pages[index]?.processed_url || page.processed_url,
        })),
      }
      setSelected(withLocalImages); setDraft(JSON.stringify(updated.notice, null, 2)); setSaved(true); setError(''); onUpdated(withLocalImages)
      setNotices((previous) => previous.map((item) => item.id === updated.id ? updated : item))
    } catch (problem) { setSaved(false); setError(problem instanceof Error ? problem.message : 'Could not save changes.') }
  }

  return <main className="admin-page page-shell">
    <header className="admin-header"><button className="text-button" onClick={onExit}><ArrowLeft size={16} />Back to workspace</button><div><span className="eyebrow-text">Researcher tools</span><h1>Notice review</h1></div></header>
    <div className="admin-layout">
      <aside className="notice-index"><h2>Processed notices</h2>{notices.length === 0 && <p className="muted">Generate a notice to add it here.</p>}{notices.map((notice) => <button className={selected?.id === notice.id ? 'active' : ''} key={notice.id} onClick={() => choose(notice)}><span>{notice.notice.notice_type}</span><strong>{notice.notice.title}</strong><small>{new Date(notice.created_at).toLocaleString()}</small></button>)}</aside>
      <section className="editor-panel">
        {!selected ? <div className="empty-state"><Braces size={36} /><h2>No notice selected</h2><p>Process a notice in the workspace, then review it here.</p></div> : <>
          <div className="editor-heading"><div><span className="eyebrow-text">Manual correction</span><h2>{selected.notice.title}</h2></div><button className="primary-button" onClick={save}><Save size={16} />Validate & regenerate</button></div>
          <div className="admin-image-report">
            <div><ImageIcon size={20} /><span>Source type<strong>{selected.acquisition.input_type.replaceAll('_', ' ')}</strong></span></div>
            <div><span>OCR<strong>{selected.acquisition.ocr_provider}</strong></span></div>
            <div><span>Translation<strong>{selected.acquisition.translation_provider} ({selected.acquisition.translation_requests})</strong></span></div>
            <div><span>Semantic provider<strong>{selected.acquisition.semantic_provider}</strong></span></div>
            <div><span>Semantic calls<strong>{selected.acquisition.semantic_requests}</strong></span></div>
            <div><span>Semantic tokens<strong>{selected.acquisition.semantic_total_tokens}</strong></span></div>
            {selected.source_pages.length > 0 && <>
              <div><span>Pages<strong>{selected.acquisition.source_pages}</strong></span></div>
              <div><span>Pages needing review<strong>{selected.acquisition.pages_needing_review}</strong></span></div>
              <div><span>Text extraction<strong>{selected.acquisition.text_extraction_status}</strong></span></div>
              <div><span>Quality warnings<strong>{selected.acquisition.quality_warnings}</strong></span></div>
              <div><span>Critical facts detected<strong>{criticalFactCount}</strong></span></div>
              <div><span>Critical facts verified<strong>{verifiedCriticalFactCount}</strong></span></div>
              <div><span>Critical facts needing review<strong>{selected.acquisition.critical_facts_needing_review}</strong></span></div>
            </>}
            {selected.acquisition.reconciliation_conflicts.length > 0 && <div className="admin-conflicts"><AlertTriangle size={16} /><span><strong>Extraction conflicts</strong>{selected.acquisition.reconciliation_conflicts.join(' · ')}</span></div>}
          </div>
          <p className="muted">Edit the typed structured representation. Saving validates every field and regenerates template selection, simplified text, and coverage checks without calling AI.</p>
          <label className="json-editor"><span>Structured extraction (JSON)</span><textarea spellCheck={false} value={draft} onChange={(event) => { setDraft(event.target.value); setSaved(false) }} /></label>
          {error && <p className="error-message" role="alert">{error}</p>}{saved && <p className="save-message"><Check size={16} />Saved and regenerated.</p>}
          <FidelityReport report={selected.fidelity} />
          <div className="admin-preview"><span className="eyebrow-text">Regenerated preview</span><VisualInstructions result={selected} showEvidence /></div>
        </>}
      </section>
    </div>
  </main>
}
