import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { VisualInstructions } from './VisualInstructions'
import type { AnalysisResult } from '../types'

const grounded = { source_evidence: '여권', source_fact_ids: ['F001'], state: 'verified' as const, source_page: null, source_image_id: null, bounding_box: null }
const result: AnalysisResult = {
  id: 'test', created_at: '', original_text: '여권', faithful_translation: 'Passport', simplified_text: '', provider: 'mock', synthetic: true, korean_detected: true, recovered_text: '', source_pages: [], acquisition: { input_type: 'text', source_pages: 0, text_extraction_status: 'not_applicable', quality_warnings: 0, pages_needing_review: 0, critical_facts_needing_review: 0, reconciliation_conflicts: [], ocr_provider: 'not_applicable', translation_provider: 'mock-translation', semantic_provider: 'mock-semantic', translation_requests: 0, semantic_requests: 0, semantic_input_tokens: 0, semantic_output_tokens: 0, semantic_total_tokens: 0, ocr_latency_ms: 0, translation_latency_ms: 0, semantic_latency_ms: 0, total_latency_ms: 0 },
  templates: {}, fidelity: { checks: [], warnings: [], critical_fields_in_source: 1, critical_fields_represented: 1, potentially_missing: [], potentially_invented: [], serious_issue: false },
  notice: {
    title: 'Test Notice', notice_type: 'Visa / immigration', audience: [], purpose: '', summary: 'Prepare one document.',
    actions: [{ ...grounded, step: 1, action: 'Prepare your passport.', details: '', deadline: null, location: null, required_items: [] }],
    deadlines: [], required_documents: [{ ...grounded, name: 'Passport', required: true, condition: '' }], eligibility: [], exceptions: [], warnings: [], consequences: [], locations: [], contacts: [], fees: [], financial_support: [], links: [], key_details: [], conditional_groups: [], source_language: 'ko', target_language: 'en', ambiguities: [], unverified_items: [], source_facts: [{ id: 'F001', kind: 'document', source_text: '여권', critical: true, state: 'verified', source_page: null, source_image_id: null, bounding_box: null }], template_overrides: { checklist: null, step_flow: null, timeline: null, decision_tree: null, warning_cards: null, information_cards: null },
  },
}

describe('VisualInstructions', () => {
  it('renders deterministic checklist and steps', () => {
    render(<VisualInstructions result={result} />)
    expect(screen.getByText('What you need')).toBeInTheDocument()
    expect(screen.getByText('Prepare your passport.')).toBeInTheDocument()
  })

  it('shows Korean evidence only when requested', () => {
    const { rerender } = render(<VisualInstructions result={result} />)
    expect(screen.queryByText('여권')).not.toBeInTheDocument()
    rerender(<VisualInstructions result={result} showEvidence />)
    expect(screen.getAllByText('여권').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Verified from notice').length).toBeGreaterThan(0)
  })

  it('shows key details and action requirements', () => {
    const detailed: AnalysisResult = {
      ...result,
      notice: {
        ...result.notice,
        actions: [{ ...result.notice.actions[0], required_items: ['TOEIC score'] }],
        key_details: [{ ...grounded, text: 'Three-month probation period', label: 'Employment' }],
        financial_support: [{ ...grounded, text: 'Activity stipend: KRW 200,000 per student', label: 'Scholarship' }],
      },
    }
    render(<VisualInstructions result={detailed} />)
    expect(screen.getByText('Required items: TOEIC score')).toBeInTheDocument()
    expect(screen.getByText('Three-month probation period')).toBeInTheDocument()
    expect(screen.getByText('Employment')).toBeInTheDocument()
    expect(screen.getByText('Activity stipend: KRW 200,000 per student')).toBeInTheDocument()
  })

  it('does not infer information-only status when submission instructions are in audited details', () => {
    render(<VisualInstructions result={{ ...result, notice: {
      ...result.notice, actions: [],
      key_details: [{ ...grounded, text: 'Submit the application through S Plus.', label: 'Application detail' }],
    } }} />)
    expect(screen.getByText('Submit the application through S Plus.')).toBeInTheDocument()
    expect(screen.queryByText('Information only')).not.toBeInTheDocument()
  })
})
