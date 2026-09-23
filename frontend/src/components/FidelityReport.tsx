import { AlertTriangle, CheckCircle2, Gauge } from 'lucide-react'
import type { FidelityReport as Fidelity } from '../types'

export function FidelityReport({ report }: { report: Fidelity }) {
  const coverage = report.critical_fields_in_source === 0 ? 0 : Math.round(report.critical_fields_represented / report.critical_fields_in_source * 100)
  return <section className="fidelity-panel">
    <div className="panel-heading"><div><span className="eyebrow-text">Researcher view</span><h2>Automated fidelity checks</h2></div><div className="coverage-ring" aria-label={`${coverage}% critical fact coverage`}><Gauge size={18} />{coverage}%</div></div>
    <p className="muted">These checks support review; they do not guarantee accuracy.</p>
    <div className="fidelity-stats"><div><strong>{report.critical_fields_in_source}</strong><span>Critical facts in source</span></div><div><strong>{report.critical_fields_represented}</strong><span>Represented</span></div><div><strong>{report.potentially_missing.length}</strong><span>Potentially missing</span></div><div><strong>{report.potentially_invented.length}</strong><span>Potentially invented</span></div></div>
    <ul className="check-list">{report.checks.map((check) => <li key={check}><CheckCircle2 size={16} />{check}</li>)}{report.warnings.map((warning) => <li className="check-warning" key={warning}><AlertTriangle size={16} />{warning}</li>)}</ul>
  </section>
}
