# Cross-notice regression evidence

`cross_notice_contracts.json` contains **synthetic** Korean text and explicitly
written English reference sentences. Its tuition, housing, scholarship,
registration, hiring, and event cases use different institutions, dates, amounts,
conditions, and submission channels. Tests inject provider audit responses to
check application behavior: full-source coverage, targeted retries, exact clause
citations and page numbers, conditional date pairing, and removal of English
claims rejected by the audit. They do not measure browser OCR or external model
accuracy, and they are not evidence that arbitrary images succeed.

`kcci_2027_corrected.txt` is a **manual transcription of a real photograph**,
visually inspected at original resolution on 2026-10-01. It includes the printed
six-column English-score table reconstructed into explicit test/threshold rows,
plus the hiring conditions, preferences, application method, selection stages,
application-writing restrictions, employment conditions, and enquiry channel.
The source image is gitignored and is not included in this fixture:

- Local path: `data/uploads/image-d21762e85663/page-001-08288e4b-original.jpg`
- SHA-256: `99bef2caaefb08cdbd9f20b009119945b551d87077c5f34f3d53c189b66a25af`
- Stored size: 3,048,691 bytes; EXIF-oriented display: 2296 × 4080 pixels
- Heading: `2027년 대한상공회의소 신입직원 채용`

The printed headcount is transcribed literally as `0명`. This transcription does
not interpret that recruitment notation as a known headcount. Dates abbreviated
on the poster are left abbreviated; their omitted year is not added here.
`kcci_2027_scores_verified.txt` is an explicitly marked partial transcription of
the score section only. Neither transcription is a raw browser OCR capture.

A read-only SHA-256 inventory of `data/uploads` on 2026-10-01 found 754 original
files but only 11 distinct byte sequences. Most were duplicate generated demo
images, blank/test pages, or EXIF tests. Two distinct byte sequences were real
notice photographs: this KCCI hiring poster and the Sogang undergraduate research
support poster already used for photo-flow checks. This inventory does not imply
a diverse real-photo evaluation set.

## User-supplied five-photo corpus

The user subsequently supplied `C:/Users/Lam/Desktop/Coding/Korean Images`.
`korean_photo_corpus.json` records all five filenames, SHA-256 hashes, sizes,
orientation, notice types, manual transcription fixtures, review requests, and
critical fact checklists. Every image was inspected at original resolution.
Images 01 and 06 are byte-identical to the previously available research-support
and KCCI photographs. Images 02, 03, and 04 add the actual creative-convergence
poster, a Seoul fair-price-business promotion, and a video contest.

The new manual transcriptions cover each main poster. They do not transcribe
unverified seal wording or reconstruct partially photographed neighboring
posters. Those regions are explicitly recorded as review requests. QR labels are
transcribed; QR destinations are not guessed or populated from prior knowledge.
The creative-research photo transcription also preserves the printed example of
another supported undergraduate-research program and QR labels that were absent
from the older corrected-text fixture. These references are useful to human
reviewers but do not establish that the application successfully reads each raw
photo or that its external-model results contain every reference detail.
