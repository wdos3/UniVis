# Information schema

The backend owns the canonical Pydantic schema; TypeScript mirrors it for rendering.

## `NoticeData`

| Field | Type | Meaning |
|---|---|---|
| `title` | string | Concise English notice title |
| `notice_type` | string | Actionable category such as Scholarship or Dormitory |
| `audience` | grounded item[] | Groups explicitly addressed |
| `purpose` | string | Overall purpose without invented action |
| `summary` | string | Short, qualification-preserving summary |
| `actions` | action[] | Student actions; ordered only when source supports order |
| `deadlines` | deadline[] | Dates/times with purpose |
| `required_documents` | document[] | Required or explicitly optional documents |
| `eligibility` | grounded item[] | Eligibility rules and conditions |
| `exceptions` | grounded item[] | Exceptions to the general instruction |
| `warnings` | grounded item[] | Explicit cautions or prohibitions |
| `consequences` | grounded item[] | Explicit consequences only |
| `locations` | grounded item[] | Physical or online locations |
| `contacts` | contact[] | Office, phone, email, or details |
| `fees` | grounded item[] | Payments applicants owe, with amount and condition |
| `financial_support` | grounded item[] | Grants, allowances, or reimbursements awarded to participants |
| `links` | grounded item[] | Source-provided URLs or named systems |
| `key_details` | grounded item[] | Other grounded facts, including research topics and process details |
| `conditional_groups` | conditional group[] | Separate group-specific dates or rules that must not be flattened |
| `source_language` | string | Initially `ko` |
| `target_language` | string | Initially `en` |
| `ambiguities` | string[] | Source passages with unclear meaning |
| `unverified_items` | string[] | Validation/provider items needing review |
| `source_facts` | source fact[] | Canonical extracted facts and coverage inventory |
| `template_overrides` | object | Optional researcher overrides for deterministic template defaults |

## Grounding and image provenance

Every major item extends:

| Field | Meaning |
|---|---|
| `source_evidence` | Exact Korean phrase supporting the item |
| `source_fact_ids` | One or more IDs such as `F004` |
| `state` | `verified`, `needs_review`, or `not_stated` |
| `source_page` | Optional one-based page number |
| `source_image_id` | Optional stable ID for the uploaded page |
| `bounding_box` | Optional normalized `x`, `y`, `width`, `height` region |

`SourceFact` carries the same page, image, and bounding-box provenance. Blank evidence is allowed only when an item itself is explicitly marked for review or not stated. Generated numerical confidence is deliberately absent.

## Specialized fields

An `Action` has `step`, `action`, `details`, optional `deadline`, optional `location`, and `required_items`. A `Deadline` separates `date`, `time`, and `description`. A `DocumentRequirement` has `required` and `condition`, preventing an optional item from becoming mandatory. A `Contact` separates name, phone, email, and other details. A `ConditionalGroup` keeps the group label, application period, and details together.

## Source pages and acquisition report

Each `SourcePage` records its ordered page number, filename, media type, original and processed URLs, dimensions, readability, quality issues, and any detected QR codes. A QR result stores the decoded URL, source page, and optional bounding box; the UI never opens it automatically.

`ImageAcquisitionReport` contains:

- provider identifiers and request counts for OCR, translation, and semantic analysis;
- per-stage and total pipeline latency in milliseconds;
- semantic input, output, and total token usage;

- input type: text, selectable-text PDF, camera photo, uploaded image, or image PDF;
- source-page count and text-recovery status;
- quality-warning and pages-needing-review counts;
- critical facts needing review;
- OCR, translation, and semantic provider names;
- translation and semantic request counts;
- semantic input, output, and total token usage;
- retained extraction-conflict details for backward-compatible stored results.

## Source facts and coverage

`SourceFact` contains a sequential ID matching `F\d{3,}`, semantic kind, exact source text, critical flag, review state, and optional image provenance. Coverage is the intersection of critical source IDs and IDs referenced by output elements. Unknown references are treated as potentially invented; unreferenced critical IDs are potentially missing.

## Derived output

`AnalysisResult` adds original/recovered text, faithful translation, simplified text, selected templates, language-detection flag, provider name, synthetic-data flag, source pages, acquisition report, and `FidelityReport`. Derived fields are recalculated after every researcher edit or recovered-text correction.
