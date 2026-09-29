import { AlertTriangle, CheckCircle2, Gauge } from 'lucide-react'
import type { FidelityReport as Fidelity } from '../types'

export function FidelityReport({ report }: { report: Fidelity }) {
  const coverage = report.critical_fields_in_source === 0 ? 0 : Math.round(report.critical_fields_represented / report.critical_fields_in_source * 100)
  return <section className="fidelity-panel">
    <div className="panel-heading"><div><span className="eyebrow-text">Researcher view</span><h2>Automated fidelity checks</h2></div><div className="coverage-ring" aria-label={`${coverage}% of identified critical facts linked`}><Gauge size={18} />{coverage}%</div></div>
    <p className="muted">This measures links among AI-identified facts only. It cannot detect facts the AI omitted from its inventory.</p>
    <div className="fidelity-stats"><div><strong>{report.critical_fields_in_source}</strong><span>Identified critical facts</span></div><div><strong>{report.critical_fields_represented}</strong><span>Linked in output</span></div><div><strong>{report.potentially_missing.length}</strong><span>Unlinked identified facts</span></div><div><strong>{report.potentially_invented.length}</strong><span>Unknown references</span></div></div>
    {!!report.unmapped_source_line_count && <details className="unmapped-lines"><summary>{report.unmapped_source_line_count} OCR line(s) not mapped to the summary</summary><p>These source lines may include important details. Check them against the original image and full translation; they are not automatically interpreted.{report.unmapped_source_line_count > (report.unmapped_source_lines?.length ?? 0) && ` Showing the first ${report.unmapped_source_lines?.length ?? 0} of ${report.unmapped_source_line_count} lines.`}</p><ul>{report.unmapped_source_lines?.map((line, index) => <li key={`${index}-${line}`} lang="ko">{line}</li>)}</ul></details>}
    <ul className="check-list">{report.checks.map((check) => <li key={check}><CheckCircle2 size={16} />{check}</li>)}{report.warnings.map((warning) => <li className="check-warning" key={warning}><AlertTriangle size={16} />{warning}</li>)}</ul>
  </section>
}
