import { AlertTriangle, CheckCircle2, Edit3, QrCode, Save, X } from 'lucide-react'
import { useState } from 'react'
import { api } from '../api/client'
import type { AnalysisResult } from '../types'

export function OriginalImageView({ result, provider, onUpdated }: { result: AnalysisResult; provider: string; onUpdated: (result: AnalysisResult) => void }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(result.recovered_text)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  async function save() {
    setSaving(true); setError('')
    try {
      const updated = await api.reprocessRecoveredText(result.id, draft, provider)
      onUpdated(updated); setEditing(false)
    } catch (problem) { setError(problem instanceof Error ? problem.message : 'Could not reprocess recovered text.') }
    finally { setSaving(false) }
  }

  return <article className="original-image-view">
    <div className="source-gallery">{result.source_pages.map((page) => <figure key={page.id}><div className="source-image-wrap"><img src={page.original_url} alt={`Original notice page ${page.page_number}`} /></div><figcaption><strong>Page {page.page_number}</strong><span>{page.filename}</span>{page.readable ? <span className="readable"><CheckCircle2 size={14} />Readable</span> : <span className="needs-review"><AlertTriangle size={14} />Needs review</span>}</figcaption>
      {page.quality_issues.length > 0 && <ul className="quality-list">{page.quality_issues.map((issue) => <li key={issue.code}><AlertTriangle size={14} />{issue.message}</li>)}</ul>}
      {page.qr_codes.map((qr) => <div className="qr-result" key={qr.url}><QrCode size={16} /><div><strong>QR code detected</strong><code>{qr.url}</code><small>Link not opened automatically</small></div></div>)}
    </figure>)}</div>
    <section className="recovered-text"><div className="recovered-heading"><div><span className="eyebrow-text">Recovered Korean content</span><h2>Text used for interpretation</h2></div>{editing ? <button className="text-button" onClick={() => { setEditing(false); setDraft(result.recovered_text) }}><X size={15} />Cancel</button> : <button className="secondary-button" onClick={() => setEditing(true)}><Edit3 size={15} />Edit recovered text</button>}</div>
      {editing ? <><textarea lang="ko" value={draft} onChange={(event) => setDraft(event.target.value)} /><button className="primary-button" disabled={saving || !draft.trim()} onClick={save}><Save size={15} />{saving ? 'Reprocessing…' : 'Save & regenerate outputs'}</button>{error && <p className="error-message">{error}</p>}</> : <div className="prose-output" lang="ko">{result.recovered_text}</div>}
    </section>
  </article>
}
