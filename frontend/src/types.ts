export type ReviewState = 'verified' | 'needs_review' | 'not_stated'
export interface BoundingBox { x: number; y: number; width: number; height: number }
export interface OcrSpan { text: string; box: BoundingBox }
export interface ClientOcrPage { text: string; spans?: OcrSpan[] }

export interface GroundedItem {
  source_evidence: string
  source_fact_ids: string[]
  state: ReviewState
  source_page: number | null
  source_image_id: string | null
  bounding_box: BoundingBox | null
}

export interface LabeledFact extends GroundedItem { text: string; label: string }
export interface Deadline extends GroundedItem { date: string; time: string; description: string }
export interface DocumentRequirement extends GroundedItem { name: string; required: boolean; condition: string }
export interface Action extends GroundedItem { step: number; action: string; details: string; deadline: string | null; location: string | null; required_items: string[] }
export interface Contact extends GroundedItem { name: string; phone: string; email: string; details: string }
export interface SourceFact {
  id: string
  kind: string
  source_text: string
  critical: boolean
  state: ReviewState
  source_page: number | null
  source_image_id: string | null
  bounding_box: BoundingBox | null
}
export interface ConditionalGroup extends GroundedItem { group: string; application_period: string; details: string }
export interface QRCode { url: string; source_page: number; bounding_box: BoundingBox | null }
export interface ImageQualityIssue { code: string; message: string; severity: 'warning' | 'blocking' }
export interface SourcePage {
  id: string; page_number: number; filename: string; media_type: string; original_url: string; processed_url: string
  width: number; height: number; readable: boolean; quality_issues: ImageQualityIssue[]; qr_codes: QRCode[]
}
export interface ImageAcquisitionReport {
  input_type: 'text' | 'pdf_text' | 'camera_photo' | 'uploaded_image' | 'image_pdf'
  source_pages: number; text_extraction_status: 'not_applicable' | 'available' | 'partial' | 'unavailable'
  quality_warnings: number; pages_needing_review: number; critical_facts_needing_review: number; reconciliation_conflicts: string[]
  ocr_provider: string; translation_provider: string; semantic_provider: string
  translation_requests: number; semantic_requests: number
  semantic_input_tokens: number; semantic_output_tokens: number; semantic_total_tokens: number
  ocr_latency_ms: number; translation_latency_ms: number; semantic_latency_ms: number; total_latency_ms: number
}

export interface NoticeData {
  title: string
  notice_type: string
  audience: LabeledFact[]
  purpose: string
  summary: string
  actions: Action[]
  deadlines: Deadline[]
  required_documents: DocumentRequirement[]
  eligibility: LabeledFact[]
  exceptions: LabeledFact[]
  warnings: LabeledFact[]
  consequences: LabeledFact[]
  locations: LabeledFact[]
  contacts: Contact[]
  fees: LabeledFact[]
  links: LabeledFact[]
  key_details: LabeledFact[]
  conditional_groups: ConditionalGroup[]
  source_language: string
  target_language: string
  ambiguities: string[]
  unverified_items: string[]
  source_facts: SourceFact[]
  template_overrides: {
    checklist: boolean | null
    step_flow: boolean | null
    timeline: boolean | null
    decision_tree: boolean | null
    warning_cards: boolean | null
    information_cards: boolean | null
  }
}

export interface FidelityReport {
  checks: string[]
  warnings: string[]
  critical_fields_in_source: number
  critical_fields_represented: number
  potentially_missing: string[]
  potentially_invented: string[]
  unmapped_source_line_count?: number
  unmapped_source_lines?: string[]
  serious_issue: boolean
}

export interface AnalysisResult {
  id: string
  created_at: string
  original_text: string
  faithful_translation: string
  simplified_text: string
  notice: NoticeData
  templates: Record<string, boolean>
  fidelity: FidelityReport
  korean_detected: boolean
  provider: string
  synthetic: boolean
  recovered_text: string
  source_pages: SourcePage[]
  acquisition: ImageAcquisitionReport
}

export interface DemoQuestion { id: string; prompt: string; expected_answer: string; critical_fact_id: string | null }
export interface DemoSummary { id: string; title: string; category: string; original_text: string; questions: DemoQuestion[] }
export interface ImageDemoSummary { id: string; title: string; description: string; page_urls: string[] }
