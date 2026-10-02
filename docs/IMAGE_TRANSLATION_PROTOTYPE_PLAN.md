# Image translation prototype

Build a separate, minimal mode in Version 2 that reads Korean text with the existing browser OCR, translates complete positioned regions, and paints English back into those regions on the original photograph. This mode makes no semantic extraction, audit, or OpenAI requests. Preserve Version 1, the existing semantic workspace, the experimental branch and free Vercel packaging.

## Implementation

- Keep image bytes, EXIF orientation, OCR geometry, canvas drawing and PNG export in the browser.
- Add a bounded text-only translation endpoint using the existing free MyMemory provider. Deduplicate repeated text, preserve region IDs, and keep independent successful regions when a translation fails.
- Retain Latin-only values and URLs without translating them. Failed or still-Korean translations leave the source pixels visible.
- Group nearby continuation lines conservatively without combining neighboring table columns. Fit complete English into the same source region and report regions whose complete text cannot fit readably.
- Provide photo upload, original/translated comparison, translation count and stage timings, source/English region inspection, and download of the actual translated PNG.

## Provider choice

Google Cloud Translation requires an authenticated project and enabled billing, despite its free monthly allowance. Papago offers an image-synthesis API, but requires NAVER Cloud credentials and usage billing. No credentials or billing setup are available/authorized for these providers. Start with the already configured MyMemory text translator; do not use undocumented consumer endpoints. Quota failures must remain visible and preserve original text.

## Validation

Add focused region grouping, complete-text fitting, API association/partial-failure and UI stale-result tests. Run relevant backend/frontend tests, lint and build checks; review the diff. Exercise actual browser OCR → translation → canvas → PNG on the supplied Sogang and KCCI photographs, and additional images as time/provider quota allows. Compare translation region coverage with recovered OCR, separately from linguistic correctness. Deploy only after validation to the existing experimental alias and verify the new mode plus the existing workspace.
