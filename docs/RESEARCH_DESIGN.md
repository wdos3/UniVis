# Research design

## Research question

The prototype is designed to test whether information visualization helps international students understand actionable Korean university notices beyond the effects of English translation and text simplification.

It does not presume an advantage for any condition.

## Conditions

- **A - Translation:** faithful English translation intended as the ordinary machine-translation baseline.
- **B - Simplified Text:** concise English headings and lists without visual diagrams or icons.
- **C - Visual Instructions:** the same simplified facts rendered as checklists, timelines, step flows, conditional tables, warnings, and information cards.

Research Mode displays one condition at a time and does not reveal the other tabs.

Camera capture, image upload, PDF upload, and pasted text are acquisition methods, not a fourth experimental condition. All three conditions must be generated from the same canonical facts for a given notice. A study should either hold acquisition method constant or record and pre-specify how it will be handled in analysis; image quality can otherwise become a confound.

## Measures

### Comprehension accuracy

```text
correct scored answers / total scored answers
```

The included automatic scorer uses normalized substring matching only. Researchers should blind-review answers or replace the scorer before a formal study.

### Completion time

Elapsed whole seconds from pressing **Begin study task** to submitting all responses.

### Critical Information Miss Rate

```text
tested critical facts answered incorrectly / total tested critical facts
```

Demo questions link to a critical fact ID. The exported prototype metric is `1 - comprehension_accuracy` across scored questions; a formal protocol should specify question-to-fact weighting in advance.

### Confidence

A required self-report item from 1 (not confident) to 5 (very confident).

### Preference

The requested post-comparison preference question is not included in the single-condition session because it would reveal the existence of other formats. It should be collected in a separate post-study survey after all assigned tasks.

## Acquisition-quality metadata

Each processed notice records acquisition type, source-page count, text-recovery status, quality-warning count, pages needing review, critical facts needing review, OCR/translation/semantic provider names, translation request count, and semantic input/output/total tokens. These fields describe the notice pipeline and are separate from participant outcome measures. If image inputs are used in a study, report them and define exclusion or adjudication rules before data collection.

## Stored fields

Participant code, notice ID, condition, timestamps, duration, answers, automatic correctness, and confidence are stored. Notice snapshots also retain source-image metadata and derived acquisition-quality counts. Names, accounts, email addresses, IP addresses, and demographic data are not collected by the app.

## Study cautions

- Counterbalance notice and condition order.
- Do not reuse a notice after participants learn its facts.
- Hold acquisition method constant or model its effect explicitly.
- Predefine rules for unreadable pages and facts marked `needs_review`.
- Validate translations and scoring keys with bilingual reviewers.
- Pilot icons with culturally diverse international students.
- Report AI/model version, input type, image-quality exclusions, and researcher corrections.
- Treat synthetic-notice results separately from real-notice results.
- Obtain appropriate ethics review and consent before participant research.
