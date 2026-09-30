# Version 2 recovery and latency work

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
