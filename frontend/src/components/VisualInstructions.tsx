import {
  AlertTriangle, ArrowDown, BadgeInfo, CalendarDays, Check, Clock3, CreditCard,
  FileCheck2, GitBranch, Globe2, Mail, MapPin, Phone, Route, ShieldAlert, UserRoundCheck,
  X,
} from 'lucide-react'
import { useState } from 'react'
import type { AnalysisResult, Contact, GroundedItem, LabeledFact } from '../types'
import { Evidence } from './Evidence'

interface VisualProps { result: AnalysisResult; showEvidence?: boolean; compact?: boolean }

function CardTitle({ icon: Icon, children }: { icon: typeof CalendarDays; children: React.ReactNode }) {
  return <h2 className="card-title"><Icon size={19} aria-hidden="true" />{children}</h2>
}

function FactList({ items, showEvidence, onViewImage }: { items: LabeledFact[]; showEvidence: boolean; onViewImage?: (item: GroundedItem) => void }) {
  return <ul className="fact-list">{items.map((item, index) => <li key={`${item.text}-${index}`}><Check size={16} aria-hidden="true" /><div><span>{item.text}</span><Evidence item={item} visible={showEvidence} onViewImage={onViewImage} /></div></li>)}</ul>
}

function ContactLine({ contact }: { contact: Contact }) {
  return <div className="contact-line">
    {contact.name && <strong>{contact.name}</strong>}
    {contact.phone && <span><Phone size={15} aria-hidden="true" />{contact.phone}</span>}
    {contact.email && <span><Mail size={15} aria-hidden="true" />{contact.email}</span>}
    {contact.details && <span>{contact.details}</span>}
  </div>
}

export function VisualInstructions({ result, showEvidence = false, compact = false }: VisualProps) {
  const n = result.notice
  const detailGroups = new Map<string, LabeledFact[]>()
  for (const item of n.key_details) {
    const label = item.label.trim() || 'Other key details'
    detailGroups.set(label, [...(detailGroups.get(label) ?? []), item])
  }
  const [evidenceItem, setEvidenceItem] = useState<GroundedItem | null>(null)
  const evidencePage = result.source_pages.find((page) => page.page_number === evidenceItem?.source_page)
  const warningItems: LabeledFact[] = [...n.warnings, ...n.exceptions, ...n.consequences]
  return (
    <article className={`visual-sheet ${compact ? 'visual-sheet--compact' : ''}`} id="visual-instructions">
      <header className="visual-header">
        <div className="eyebrow"><span>{n.notice_type}</span>{result.synthetic && <span>Synthetic demonstration notice</span>}</div>
        <h1>{n.title}</h1>
        {n.summary && <p>{n.summary}</p>}
      </header>

      {n.audience.length > 0 && <section className="visual-card audience-card">
        <CardTitle icon={UserRoundCheck}>Who this is for</CardTitle>
        <FactList items={n.audience} showEvidence={showEvidence} onViewImage={setEvidenceItem} />
      </section>}

      {n.deadlines.length > 0 && <section className="visual-card deadline-section">
        <CardTitle icon={CalendarDays}>{n.deadlines.length > 1 ? 'Key dates' : 'Deadline'}</CardTitle>
        <div className={result.templates.timeline ? 'timeline' : 'deadline-grid'}>
          {n.deadlines.map((deadline, index) => <div className="deadline-item" key={`${deadline.date}-${index}`}>
            {result.templates.timeline && <span className="timeline-dot" aria-hidden="true" />}
            <strong>{deadline.date || 'Date needs review'}</strong>
            {deadline.time && <span className="detail-line"><Clock3 size={15} aria-hidden="true" />{deadline.time}</span>}
            {deadline.description && <span>{deadline.description}</span>}
            <Evidence item={deadline} visible={showEvidence} onViewImage={setEvidenceItem} />
          </div>)}
        </div>
      </section>}

      {n.required_documents.length > 0 && <section className="visual-card checklist-card">
        <CardTitle icon={FileCheck2}>What you need</CardTitle>
        <ul className="document-list">{n.required_documents.map((document, index) => <li key={`${document.name}-${index}`} className={!document.required ? 'optional' : ''}>
          <span className="check-box" aria-hidden="true"><Check size={15} /></span>
          <div><strong>{document.name}</strong>{!document.required && <span className="tag">Optional</span>}{document.condition && <small>{document.condition}</small>}<Evidence item={document} visible={showEvidence} onViewImage={setEvidenceItem} /></div>
        </li>)}</ul>
      </section>}

      {n.eligibility.length > 0 && <section className="visual-card eligibility-card">
        <CardTitle icon={BadgeInfo}>Eligibility</CardTitle>
        <FactList items={n.eligibility} showEvidence={showEvidence} onViewImage={setEvidenceItem} />
      </section>}

      {n.conditional_groups.length > 0 && <section className="visual-card group-table-card"><CardTitle icon={UserRoundCheck}>Dates by student group</CardTitle><div className="group-table" role="table"><div className="group-table__header" role="row"><span role="columnheader">Student group</span><span role="columnheader">Application period</span></div>{n.conditional_groups.map((group) => <div className="group-table__row" role="row" key={`${group.group}-${group.application_period}`}><strong role="cell">{group.group}</strong><span role="cell">{group.application_period || group.details}</span><Evidence item={group} visible={showEvidence} onViewImage={setEvidenceItem} /></div>)}</div></section>}

      {result.templates.decision_tree && n.eligibility.length > 0 && <section className="visual-card decision-card">
        <CardTitle icon={GitBranch}>Eligibility decision</CardTitle>
        {n.eligibility.map((item, index) => <div className="decision-tree" key={`${item.text}-${index}`}>
          <div className="decision-question">{item.text}</div>
          <div className="decision-branches"><div><span>Condition met</span><strong>Continue to the application steps</strong></div><div><span>Condition not met</span><strong>The notice does not confirm eligibility</strong></div></div>
          <Evidence item={item} visible={showEvidence} onViewImage={setEvidenceItem} />
        </div>)}
      </section>}

      {n.actions.length > 0 && <section className="visual-card step-section">
        <CardTitle icon={Route}>What to do</CardTitle>
        <ol className={result.templates.step_flow ? 'step-flow' : 'action-list'}>{n.actions.map((action, index) => <li key={`${action.step}-${action.action}`}>
          <div className="step-number" aria-label={`Step ${action.step}`}>{action.step}</div>
          <div className="step-copy"><strong>{action.action}</strong>{action.details && <p>{action.details}</p>}{action.deadline && <span className="detail-line"><Clock3 size={15} />{action.deadline}</span>}{action.location && <span className="detail-line"><MapPin size={15} />{action.location}</span>}{action.required_items.length > 0 && <p>Required items: {action.required_items.join(', ')}</p>}<Evidence item={action} visible={showEvidence} onViewImage={setEvidenceItem} /></div>
          {index < n.actions.length - 1 && <ArrowDown className="step-arrow" size={20} aria-hidden="true" />}
        </li>)}</ol>
      </section>}

      {[...detailGroups].map(([label, items]) => <section className="visual-card info-card" key={label}>
        <CardTitle icon={BadgeInfo}>{label}</CardTitle>
        <FactList items={items} showEvidence={showEvidence} onViewImage={setEvidenceItem} />
      </section>)}

      {warningItems.length > 0 && <section className="visual-card warning-card">
        <CardTitle icon={ShieldAlert}>Important</CardTitle>
        {warningItems.map((item, index) => <div className="warning-row" key={`${item.text}-${index}`}><AlertTriangle size={18} aria-hidden="true" /><div><strong>{item.text}</strong><Evidence item={item} visible={showEvidence} onViewImage={setEvidenceItem} /></div></div>)}
      </section>}

      {(n.locations.length > 0 || n.contacts.length > 0 || n.fees.length > 0 || n.financial_support.length > 0 || n.links.length > 0) && <section className="info-grid">
        {n.locations.length > 0 && <div className="visual-card info-card"><CardTitle icon={MapPin}>Location</CardTitle><FactList items={n.locations} showEvidence={showEvidence} onViewImage={setEvidenceItem} /></div>}
        {n.contacts.length > 0 && <div className="visual-card info-card"><CardTitle icon={Phone}>Contact</CardTitle>{n.contacts.map((contact, index) => <div key={index}><ContactLine contact={contact} /><Evidence item={contact} visible={showEvidence} onViewImage={setEvidenceItem} /></div>)}</div>}
        {n.fees.length > 0 && <div className="visual-card info-card"><CardTitle icon={CreditCard}>Fee</CardTitle><FactList items={n.fees} showEvidence={showEvidence} onViewImage={setEvidenceItem} /></div>}
        {n.financial_support.length > 0 && <div className="visual-card info-card"><CardTitle icon={CreditCard}>Financial support</CardTitle><FactList items={n.financial_support} showEvidence={showEvidence} onViewImage={setEvidenceItem} /></div>}
        {n.links.length > 0 && <div className="visual-card info-card"><CardTitle icon={Globe2}>Online</CardTitle><FactList items={n.links} showEvidence={showEvidence} onViewImage={setEvidenceItem} /></div>}
      </section>}

      {(n.ambiguities.length > 0 || n.unverified_items.length > 0) && <section className="review-banner" role="alert">
        <AlertTriangle size={20} aria-hidden="true" /><div><strong>Researcher review needed</strong><ul>{[...n.ambiguities, ...n.unverified_items].map((item) => <li key={item}>{item}</li>)}</ul></div>
      </section>}
      <footer className="visual-footer">Check the official university notice before acting. Automated interpretation may contain errors.</footer>
      {evidenceItem && evidencePage && <div className="evidence-modal" role="dialog" aria-modal="true" aria-label={`Source evidence on page ${evidencePage.page_number}`}><button className="modal-backdrop" aria-label="Close source image" onClick={() => setEvidenceItem(null)} /><div className="evidence-dialog"><div className="dialog-heading"><div><span className="eyebrow-text">Source page {evidencePage.page_number}</span><strong lang="ko">{evidenceItem.source_evidence}</strong></div><button onClick={() => setEvidenceItem(null)} aria-label="Close"><X size={20} /></button></div><div className="evidence-image-wrap">{evidencePage.original_url ? <><img src={evidencePage.original_url} alt={`Original notice page ${evidencePage.page_number}`} />{evidenceItem.bounding_box && <span className="evidence-highlight" style={{ left: `${evidenceItem.bounding_box.x * 100}%`, top: `${evidenceItem.bounding_box.y * 100}%`, width: `${evidenceItem.bounding_box.width * 100}%`, height: `${evidenceItem.bounding_box.height * 100}%` }} />}</> : <p className="source-image-unavailable">This photo was kept on the original device and is no longer available here.</p>}</div></div></div>}
    </article>
  )
}
