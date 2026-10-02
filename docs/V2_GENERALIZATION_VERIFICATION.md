# Version 2 general recovery verification

## Scope and operating boundary

This change extends the existing split pipeline to varied Korean notices. It does
not select an answer by poster title, image hash, university, or fixture text.
Whole-sentence Sogang replacements were removed; the remaining glossary fixes
require the corresponding Korean term in the quoted source. Version 1 and main
are outside this change.

The hosted route still uses browser PaddleOCR (Korean/English), MyMemory, and
server-side `gpt-4o-mini`. Photos remain local browser objects. Only recovered
text, bounded positions, and locally decoded HTTP(S) QR URLs go to the API.
The Vercel static-frontend/Python-API packaging and Python 3.12 remain unchanged.

Photo requests opt into best-effort interpretation. Verified readable details can
survive an unresolved section or failed targeted audit. Unsafe dependent claims
are removed and English verification gaps identify recovered page/line locations.
If no instructions can be verified, the result is an English unavailable state.
Users do not have to type Korean. Strict text/document API defaults remain strict.
Neither a partial result nor an automated audit establishes semantic perfection.

## Final-review recovery follow-through, Oct 2

Further real-photo diagnostics showed that a malformed targeted coverage reply
was discarding independent readable repairs before final review. The safe
standalone coverage result remains conservative; its separate internal candidate
notice is passed only to mandatory final English review. Known rejected meanings,
blocked source quotations, invented evidence and invalid grouped assignments
remain excluded. Partial targeted retries quarantine invalid assignments while
retaining independent valid ones for review. Strict text/document behavior is
unchanged.

Final review now certifies both each English claim and the complete meaning of
each recovered source unit. Local checklist/role changes and deterministic
contradiction guards precede the call. A supported partial clause is insufficient
for complete source coverage; final status comes from surviving supported wording,
its exact citations, and collective literal/condition/spending checks. A complete
supported replacement can clear an earlier gap. Source units use required keyed
enum verdicts in the structured response: the diagnostic list-based response
omitted one English ID and nine source IDs and classified two source IDs twice.
The new schema eliminates those bookkeeping failures in valid parsed responses;
it does not establish semantic correctness by itself.

The redundant global partial-result warning banner was removed. Concrete source
gaps, the partial status and optional retained-OCR retry remain visible. No
unreadable content is relabeled verified. Pipe-delimited phone/email contact
parsing was fixed generically, preserving readable addresses and internal address
punctuation. Directly conflicting explicit dates are withheld before model review;
valid individual range endpoints remain eligible, and software decimals are not
treated as calendar dates.

## Corpus and evidence

Five original photographs were supplied in
`C:\Users\Lam\Desktop\Coding\Korean Images`. The checked-in
`backend/tests/fixtures/korean_photo_corpus.json` records original hashes, file
sizes, EXIF orientation, review criteria, and unreadable regions. Images are not
copied into the repository. Each displayed photograph is portrait-oriented after
EXIF rotation.

| Filename suffix | Main notice | Distinct challenge |
| --- | --- | --- |
| `_01.jpg` | Sogang undergraduate research support | Tiny seal, supervision, two instalments, footer contact |
| `_02.jpg` | Sogang creative-convergence free research | Two columns, wrapped restrictions/topics, two funding categories |
| `_03.jpg` | Seoul fair-price establishments promotion | Illustrated business labels, voucher conditions, maps/QR routes |
| `_04.jpg` | Sogang sustainability AI video contest | Award table, individual/team amounts, cropped unrelated posters |
| `_06.jpg` | Korea Chamber of Commerce 2027 hiring | English-test score table, recruitment stages and conditions |

Manual verified main-poster transcriptions are reference fixtures. They exclude
unreadable handwriting/stamps and incomplete neighboring notices. Corrected-text
benchmarks therefore measure reference-text semantics, not automatic photo
reading. The earlier KCCI photo also existed in `data/uploads`; the historical
report's original unavailability statement was corrected.

## Recovery and integrity checks

- Adaptive small-text recovery uses image size and OCR confidence, plus a bounded
  lower-edge check for tall downscaled photographs. At most two extra crops run.
  Conflicting readings remain source evidence rather than being silently replaced.
- QR scanning has a 1.5-second budget checked between synchronous decodes. Already
  decoded URLs survive later failures; a single decode can exceed the budget.
  QR wall time is reported separately and is not added twice to parallel OCR work.
- Audits compare actual English fields with every recovered source unit. Invalid
  retry partitions are discarded; independent valid facts can remain in photo mode.
- Copied short fragments and requirements fabricated from unfinished clauses are
  rejected. Audit instructions prohibit hiding damaged OCR with guessed names or
  romanization, and preserve independent-notice scope and table associations.
- Exact-value, contact, payment-direction, and selected condition checks supplement
  the semantic audit. Correct full-unit repairs replace stale conflicting primary
  claims on the same page. Explicit source-page quotations must match that page.
- Six KCCI English-test pairings are checked from positioned table evidence. A
  choice clause about documents cannot establish an English-score qualification.
- Translation outages can use Korean source semantics in photo mode. Failed-provider
  token usage is unavailable; known completed-stage usage is retained and incomplete
  measurements are labeled.

Injected-audit contract tests cover unrelated tuition, housing, scholarship,
registration, hiring, and event examples. These test control flow and data
integrity with supplied model responses; they do not measure real model accuracy.

## Measurements and final verification

Measurements are single runs on this computer/browser with the configured
providers. They include no statistical accuracy or runtime claim. The 10–15-second
target is not met. Model preparation, detection, recognition, QR work, latest API
request, translation, semantic requests, and available token usage are measured.
Retry totals retain original OCR time and the latest request, excluding prior
requests and editing time.

Local JSON/UI evidence is retained under
`C:\Users\Lam\AppData\Local\Temp\univis-verification`. The following are real
provider calls, not injected test responses. These runs happened during development
and do not all use the final guard set.

### Automatic photo runs during development

All five photos were uploaded through the browser UI without editing Korean.
The five initial runs returned HTTP 200; the fair-price run incorrectly received
an `audited` status despite romanized noise. That finding motivated the additional
final English review and caption checks. HTTP success and coverage status are not
accuracy measurements.

| Case | Browser OCR | Translation | Semantic work | Total | Semantic calls / known tokens |
| --- | ---: | ---: | ---: | ---: | ---: |
| Undergraduate research `_01` | 43.887 s | 2.342 s | 35.436 s | 82.106 s | 3 / 14,071 |
| Creative research `_02` | 47.533 s | 2.385 s | 45.012 s | 95.246 s | 3 / 18,538 |
| Fair-price promotion `_03` | 44.241 s | 2.215 s | 25.270 s | 72.081 s | 3 / 11,922 |
| Video contest `_04` | 47.944 s | 2.015 s | 34.946 s | 85.232 s | 4 / 16,826 |
| KCCI hiring `_06` | 26.962 s | 3.052 s | 62.817 s | 93.097 s | 4 / 27,746 |

These are the `general-XX-auto-result.json` artifacts (`01` uses
`general-01-auto-partial-result.json`; `06` uses
`general-06-pre-support-result.json`). Original-photo manifest hashes identify
the inputs. No image-specific output is selected at runtime.

### Later checks and their limits

| Run | Measurement | Result / evidence |
| --- | --- | --- |
| Fresh video-contest photo, Oct 1 | OCR 43.989 s; translation 1.257 s; semantic 36.878 s; total 82.556 s; 4 calls / 20,930 known tokens | HTTP 200 partial, 46 recovered-source gaps. Video requirements, eligibility, dates, application route survived. Award associations were withheld. A neighboring bare Friday schedule was found and subsequently guarded. |
| Fresh creative-research photo, Oct 2, first attempt | OCR 36.951 s; translation 1.219 s; semantic 42.022 s; total 80.591 s; 5 calls / 22,587 known tokens | HTTP 200 English unavailable interpretation: final review was unusable, all instructions withheld. This motivated independent field-classification recovery. |
| Creative-research UI retry, retained OCR | Translation 1.230 s; semantic 41.279 s; reported total 79.854 s includes original 36.951 s OCR; 4 calls / 21,341 known tokens | HTTP 200 partial, 48 gaps. No new OCR or Korean editing. Enrolled-student audience, Aug 24–Sep 20 dates, three documents, 2–5 team rule, both funding categories and spending scope survived. Leave/funding exclusion, duplicate-support restrictions, full topic options, card-payment procedure, contact and submission channel remained withheld. This does **not** satisfy the complete primary-poster goal. |
| KCCI positioned-request replay, retained photo OCR | Actual backend wall 50.982 s; reported total 77.630 s includes retained 26.962 s OCR; 5 calls / 31,014 known tokens | HTTP 200 partial, 56 gaps. All six printed score pairs survive with boxes and applicability explicitly unverified. Whole-selection-online and without-notice claims absent. Preference placement, unquoted application checklists and bare cells found in this run motivated subsequent structural fixes. |

Later runs above experienced actual MyMemory failure and are marked
`metrics_complete=false`. The measured tokens are known completed semantic calls;
failed-provider cost is unavailable, not zero. MyMemory remains the configured
baseline and its failure does not force a Korean correction.

The KCCI literal pairs are TOEIC 800, TEPS 309, FLEX 2B, TOEFL iBT 91,
TOEIC Speaking 150, and OPIc IM3. Printing the source table does not certify
applicant eligibility or revive an unverified OR condition.

The saved `general-release-photo-04-request.json` was discovered to contain the
fair-price text-only replay, not video-contest geometry. It was **not** used as
a video-contest replay. The video-contest result/UI artifacts establish the
earlier actual photo run; its positioned request is unavailable. This artifact
limitation is preserved rather than claiming a final positioned check of case 04.

Manual corrected-reference backend runs were also attempted: creative research
HTTP 502 / 39.518 s, fair-price HTTP 200 / 23.854 s / 3 calls / 8,348 tokens,
video contest HTTP 502 / 31.873 s, and KCCI HTTP 502 / 63.239 s. Those runs used
strict completeness and earlier guards. The successful fair-price reference
contained the dates, voucher caps/conditions, lottery criterion and lookup routes;
the failed references are not successes or OCR measurements.

### Automated checks and reviewed fixes

Final backend checks: `python -m pytest backend/tests -q` **858 passed**;
`ruff check backend/app backend/tests` passed. Six dependency deprecation warnings
remain. Frontend: `npm run test` **75 passed in nine files**, `npm run lint`,
and `npm run build` (TypeScript, Vite, V1 asset aliases) passed. `git diff --check`
passed. A second agent independently reviewed final behavior, partition recovery,
source roles, retry ownership, photo privacy and unchanged packaging.

Additional regressions cover selective quarantine of malformed targeted replies,
internal-only candidate recovery, whole-source-unit coverage, required keyed
verdict schemas, directly conflicting dates versus legitimate range endpoints,
calendar/version disambiguation, shared-quotation literal coverage, contact pipe
separators, and removal of the redundant partial-result banner. The semantic
prompt also requires coherent continuation relationships and complete enumerated
options; its effectiveness is checked through actual runs rather than assumed
from the wording.

Tests distinguish a reviewed contextual weekly schedule from a detached weekday,
ordinary identity-document submission from an unquoted application checklist,
visible preferences from mandatory eligibility, and named course codes from raw
generic cells. Incomplete final-review partitions preserve only unique known
classifications; missing, repeated or conflicting fields are insufficient.
Unknown IDs never introduce facts. Strict verification defaults still reject
malformed partitions. These are behavioral regression tests, not an empirical
translation-accuracy score.

The first Oct 2 release (`bad9cbcccf9d7e5614c8472f70dc28b8b4baeb26`,
deployment `dpl_C9y2RWAb46oz71DKXjexjdmMT2f7`) was Ready on the existing alias.
Root, health, current JS, worker, WASM and QR assets returned HTTP 200; public
`/api/notices` returned the expected HTTP 403. A fresh unedited primary photo
returned a partial English result: UI wall 120.5 s, OCR 49.5 s, translation
1.5 s, semantic 69.1 s, five calls and 32,979 reported tokens. OCR preparation
was 4.1 s, detection 28.2 s, recognition 15.6 s, parallel QR 1.4 s, with two
additional small-text checks. Model assets may have been cached; this is not a
cold-download benchmark. The old global banner was absent. Important research
topics and spending/payment details were still missing, so this run did not
satisfy the complete-primary-notice goal.

## Repair-context and independent-stage follow-through

The actual retained primary OCR trace showed incomplete targeted requirements,
incorrect source-ID associations and isolated spending continuations. Every retry
target now requires a complete detail. Explicit nearby read-only context lets a
repair quote a heading or completing clause while target assignments remain
exactly once. Unknown, repeated-within-detail, targeted, blocked or cross-page
context cannot establish a claim. Photo mode quarantines dependent invalid
groups; strict mode rejects invalid context. Shared context between independent
details is permitted, and context does not inflate repaired-unit counts.

Quoted English acronym expansions are restored when wholly omitted and uniquely
explicit in the field's evidence. A complete, directly attached English
parenthetical definition can also be corrected to that exact printed expansion;
word overlap or matching acronym initials must identify it as a definition.
Numeric, conditional, negated, malformed, ambiguous or unparenthesized conflicting
wording remains for semantic repair. Restored wording cannot revive a known
rejected claim.
Nominal consent-document names can retain the full printed personal-information
collection-and-use scope. Whole-page title/summary context does not trigger
acronym insertion. The interview-stage guard distinguishes `전형` (selection
process) from `전` (before), avoiding a false rejection of interview applicants'
documents.

The non-mock photo baseline translation now overlaps Korean-source extraction,
which deliberately does not consume that translation. Individual stage timings
remain measured, total time accounts for overlap, and fatal errors or cancellation
cancel and join sibling requests. Strict text/document and mock dependencies are
unchanged. Controlled tests establish overlap, not a measured live speedup.

Source continuations beginning with a standalone genitive or connector must quote
their preceding clause before assigning a subject or alternative. Targeted retry
includes the preceding same-page line, including for a final source unit, and
keeps blocked text withheld. Grouped quotations use source order rather than
model-supplied ID order. Counterfactual tests cover an unrelated identity-document
alternative as well as the observed research-topic split.

Explicit open parentheticals and a trailing dependent matching modifier also
require their actual following source line. Incomplete groups are retried and
withheld if the source relationship cannot be recovered; citations are never
silently widened. Final English review locally excludes open-ended extensions
such as “other related expenses” when the field's quotation supplies a closed
list. Explicit open lists remain eligible for semantic review. Unrelated
page-level wording and a guitar named `기타` cannot authorize extra items.

Follow-through provider runs used the original retained positioned OCR, without
another OCR pass or Korean editing. The primary returned HTTP 200 in 62.203 s
backend wall time: translation 3.060 s, semantic 61.297 s (extraction 18.281 s,
coverage 34.890 s, final review 8.123 s), four calls and 28,705 reported tokens.
Its reported total 98.936 s includes the earlier 36.951 s OCR. It retained the
MVP printed expansion, application documents, equipment rental, books and
printing. It still omitted the AI-function clause, misworded some research scope,
and added unsupported “other related expenses.” A subsequent local guard was
motivated by this observed failure; this run is not a success for complete output.

The positioned KCCI replay returned HTTP 200 in 89.760 s backend wall time:
translation 3.194 s, semantic 88.915 s, five calls and 37,748 tokens. Reported total
116.465 s includes the earlier 26.962 s OCR. All six printed score pairs survived,
but preferences still appeared as eligibility and selection stages were
incomplete. Neither replay establishes a controlled latency improvement or
universal correctness; provider responses varied between attempts.

The follow-through release deployed code commit
`97c56aba71f874dddf9e980bffd7fd5734b72cd9` as
`dpl_7iFa4jkz23eDFhjtnS3BufasMqBY` on the existing experimental alias. Vercel
reported Ready and rebuilt the static frontend and Python 3.12 API. Fresh root,
health, frontend JS, OCR worker, WASM and QR assets returned HTTP 200; public
`/api/notices` returned the expected HTTP 403. Root retained `no-store`, health
reported `gpt-4o-mini` and public mode, and the old banner string was absent from
the deployed JS. No hosting configuration, credentials or Version 1 code changed.

Fresh hosted original-photo verification after that deployment required no Korean
editing. The primary returned English in 132.7 s UI wall time (132.3 s pipeline):
OCR 38.1 s, baseline translation 1.9 s / five requests, semantic 94.1 s / four
calls / 28,821 tokens. Expanded timing showed model preparation 2.8 s, detection
19.4 s, recognition 12.2 s, parallel QR 1.4 s, image reading 35.3 s, two additional
small-text checks, and latest API/network 94.6 s. The browser OCR model was
initialized; download/cache state does not establish a cold-start benchmark.

The English panel contained no Korean characters or the removed banner. It
preserved the application dates, enrolled-student and leave-of-absence conditions,
2–5-person teams, both funding amounts, and the readable phone/email. An independent
fixture comparison confirmed the missing three documents and submission channel,
all four designated topics and detailed-announcement requirement, equipment
purchases/rental/materials, institute visit/card payment, and activity-funding
scope/scholarship relationship. Duplicate-support wording retained the same/similar
topic restriction but left its within-university scope ambiguous. Retained wording
also added unsupported current-status claims: recruitment beginning “now” and the
call being “open,” although the printed deadline had passed. English and deterministic
visual tabs rendered. This was a partial result with 48 affected source-line IDs
and 27 identified critical facts needing review; those are different metrics.
This run did not meet complete-output or timing goals, and a structurally valid
automated verdict must not be treated as semantic proof.

A second fresh hosted original photo exercised KCCI on the same release, with no
Korean correction and a reused OCR model. The app cleared the prior notice on
upload and rendered English and visual cards. UI wall time was 173.6 s (170.4 s
pipeline): OCR 69.3 s, translation 2.5 s / eight requests, semantic 101.1 s / three
reported calls / 18,090 known tokens. Failed-attempt usage was unavailable, so
those tokens are incomplete. Expanded timing showed detection 26.1 s,
recognition 40.1 s, parallel QR 1.6 s, image reading 69.2 s, two small-text checks,
and latest API/network 104.4 s. QR reached its budget and the already decoded URL
survived; printed text processing continued.

All six exact printed pairs appeared in both English and visual output: TOEIC
800, TEPS 309, FLEX 2B, TOEFL iBT 91, TOEIC Speaking 150, and OPIc IM3. Their
qualification applicability remained unverified. The source-evidence toggle and
TOEIC/800 link opened the correct original photo with that table cell highlighted.
The output still omitted important dates, selection stages, preferences and
documents, and incorrectly attached the essay exam's three-question count to
aptitude testing. Both runs had no captured browser warning/error logs. Screenshots
and expanded DOM evidence were saved outside the repository. These findings
remain failures of complete semantic interpretation despite passing automated
checks and successful site operation.

The last guards additionally withhold a graduation document missing its explicit
expected-graduation alternative or interview stage, detached expense noun phrases
misclassified as restrictions, and bare date/time/question-count cells lacking
event context. Complete source-grounded alternatives and contextual schedules
remain eligible. A missing printed phrase spanning OCR lines now implicates only
its located source units; the whole-page fallback remains when location cannot be
established.

Predeployment runtime with required verdict maps returned HTTP 200 for the
retained primary photo (original OCR 36.951 s; translation 2.646 s; semantic
57.322 s; reported total 97.339 s; four calls / 28,126 tokens) and positioned KCCI
OCR (backend wall 71.027 s; five calls / 37,528 tokens; reported total 97.708 s
includes earlier 26.962 s OCR). The primary retained the student-selected topic,
card-payment instruction and email but still lacked complete research-topic and
funding relationships. KCCI retained all six score pairs but incompletely
expressed preferences, documents and selection stages. The reviewer gave both
runs structurally valid but semantically overconfident verdicts; local proof
correctly preserved a partial status. Required keys fix bookkeeping, not truth.

After the last guards, an **offline deterministic replay**, injecting all-positive
verdicts and making no OCR/provider requests, removed the observed contradictory
document/expense/bare-cell output. Located missing phrases reduced the earlier
blanket source-gap counts from 61 to 37 for the primary and 98 to 52 for KCCI.
This is guard verification, not another empirical translation run. Two preceding
local requests failed because the temporary diagnostic wrapper did not accept a
new keyword; the wrapper was fixed outside the repository. Those instrumentation
failures are retained separately and are not successful product runs.

## Remaining limits

Undetected or cut-off text cannot be reconstructed. Plausible OCR mistakes and
semantic scope/table errors can still evade checks. Recovery may withhold readable
information when an audit fails; this is reported as a gap, not completeness.
The source audit has a 120-unit bound. Input and rate limits, unsupported browsers,
model-download failures, network loss, and external-service outages remain possible.
No result is claimed to have no omissions. See [LIMITATIONS.md](LIMITATIONS.md).
The local syllable-matching caption guard is conservative and incomplete: a
legitimate mixed borrowing such as “Ramyeon Soup” can be withheld, while other
phonetic OCR noise can evade it. It never guesses a replacement. Structural
guards and the additional model review can still reject readable details or
approve an incorrect interpretation. Partial results often lack a verified title.
The latest primary photo check still misses important legible content; runtime
and token cost remain substantially above the requested target. This release
improves failure handling and evidence integrity, not universal image correctness.
