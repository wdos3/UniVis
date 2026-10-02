# Version 2 general notice recovery and latency work

## Scope and constraints

Continue `prototype/paddleocr-gpt41mini`; preserve Version 1 and keep Version 2 separate from the default branch. Keep browser-local photo bytes, PaddleOCR.js, temporary MyMemory translation, `gpt-4o-mini`, deterministic React rendering, and the existing Vercel static frontend/Python function packaging. Never infer unreadable values or expose credentials.

## Inspection and baseline

- Confirm clean working tree, branch/remote, current README, architecture/limitations, deployment configuration, tests, and the live alias.
- Measure corrected Sogang text and raw positioned browser OCR through the hosted endpoints. Find available original regression photos and inspect them before using them.
- Record provider timings, requests, token usage, and observed output/failure. A source-line audit cannot prove absence of omissions or recover words OCR missed.

## Focused implementation

- Preserve OCR confidence and useful geometry through text corrections; expose exact lines requiring correction while retaining every recovered line for review.
- Harden malformed/free translation responses and retain clear exam/score pairings, rejecting ambiguous tables rather than deleting unresolved columns.
- Keep the independent English completeness audit and literal/date/amount/negation safeguards; reduce repeated audit prompt content and reject corrupted contacts without inventing replacements.
- Measure extraction, English repair, coverage audit, translation, browser OCR, and total time separately.

## Validation and delivery

- Add behavior regressions for correction errors, confidence validation, geometry after edits, translation failures, score pairing, and exact source values.
- Run backend tests/lint, frontend tests/lint/type/build checks; inspect the diff and remove unused code.
- Exercise available original photo input and corrected retries in the browser, compare against explicit Sogang and KCCI requirements, and record remaining uncertainty.
- Commit/push only this experimental branch; deploy validated changes to the linked Vercel project, verify the alias/assets/API and photo/correction flow, and document measured results and limitations.

## Generalization follow-through

Retain grounded candidates internally through partial audit failures, then
require final English support and whole-source-unit meaning checks. Resolve local
presentation changes before review; certify only the surviving display. Preserve
independent valid retry assignments while quarantining malformed ID groups.
Remove the redundant global warning banner; keep concrete source gaps and
optional source-preserving retry visible. Validate actual photo and positioned
table flows after the final changes, and record known incompleteness honestly.

The user requires one pipeline for varied Korean images, not a bespoke Sogang
translator. Remove complete-sentence canonical rewrites and keep only source-backed
glossary corrections. Preserve gpt-4o-mini and the independent audit with one bounded
retry for malformed provider classifications. Test counterfactual source values,
unseen notice categories, Korean contact particles, and rating/table layouts.

Use all five actual photos in the supplied Korean Images folder as independent
notices; record first-pass outcomes, correction/retry costs, and source comparisons.
Synthetic injected-audit tests establish contracts, not empirical OCR/model accuracy.
Retain uncertain readings and return English gaps or an unavailable state rather
than guessing or requiring Korean transcription. Retry from retained OCR is
optional and must not rerun OCR or restore a replaced image's stale results.
Review the complete diff, run checks, validate locally, deploy only the experimental
branch to its existing Vercel alias, and repeat hosted usability/photo checks.

Follow the observed repair losses through the actual pipeline: require complete
targeted repairs and preserve nearby exact source context for continuations.
Restore only explicit printed acronym expansions and source-backed consent names.
Overlap independent photo baseline translation and Korean-source extraction while
retaining stage timings, failure accounting, and joined cancellation. Verify these
changes against retained positioned OCR and fresh hosted photographs before release.
