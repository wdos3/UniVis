from __future__ import annotations

from app.models import ImageDemoSummary


IMAGE_DEMOS = [
    ImageDemoSummary(id="image-clean", title="Clean printed notice", description="High-contrast visa notice with exact dates and documents.", page_urls=["/demo-images/clean-visa-notice.png"]),
    ImageDemoSummary(id="image-angled", title="Angled phone photo", description="A notice photographed against a wall at a slight angle.", page_urls=["/demo-images/angled-visa-notice.jpg"]),
    ImageDemoSummary(id="image-table", title="Conditional date table", description="Different course-registration periods for different groups.", page_urls=["/demo-images/course-table-notice.png"]),
    ImageDemoSummary(id="image-mixed", title="Korean + English", description="Official English terms embedded in a Korean notice.", page_urls=["/demo-images/mixed-korean-english-notice.png"]),
    ImageDemoSummary(id="image-multipage", title="Two-page scholarship", description="Eligibility and deadline on page 1; documents and exception on page 2.", page_urls=["/demo-images/multi-page-scholarship-1.png", "/demo-images/multi-page-scholarship-2.png"]),
    ImageDemoSummary(id="image-qr", title="Notice with QR code", description="A synthetic notice containing a safe example QR URL.", page_urls=["/demo-images/qr-visa-notice.png"]),
]
