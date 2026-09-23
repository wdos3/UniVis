from __future__ import annotations

from app.services.pdf import DocumentExtractionError


def render_pdf_pages(data: bytes, max_pages: int = 12) -> list[tuple[bytes, str]]:
    try:
        import fitz

        document = fitz.open(stream=data, filetype="pdf")
    except ImportError as exc:
        raise DocumentExtractionError("Image-only PDF rendering is not installed in this deployment. Use the local/container runtime.") from exc
    except Exception as exc:
        raise DocumentExtractionError("The PDF could not be opened. It may be damaged or encrypted.") from exc
    try:
        if document.page_count > max_pages:
            raise DocumentExtractionError(f"The PDF has more than the {max_pages}-page prototype limit.")
        pages: list[tuple[bytes, str]] = []
        matrix = fitz.Matrix(2, 2)
        for index, page in enumerate(document):
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            pages.append((pixmap.tobytes("png"), f"pdf-page-{index + 1}.png"))
        return pages
    finally:
        document.close()
