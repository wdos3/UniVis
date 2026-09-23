from __future__ import annotations

class DocumentExtractionError(ValueError):
    pass


def extract_pdf(data: bytes) -> str:
    try:
        import fitz

        document = fitz.open(stream=data, filetype="pdf")
    except ImportError as exc:
        raise DocumentExtractionError("PDF support is not installed in this deployment. Use a text file or the local/container runtime.") from exc
    except Exception as exc:
        raise DocumentExtractionError("The PDF could not be opened. It may be damaged or encrypted.") from exc

    try:
        text = "\n".join(page.get_text("text") for page in document).strip()
    finally:
        document.close()
    if not text:
        raise DocumentExtractionError(
            "No selectable text was found. This may be an image-only PDF; OCR is not available in this prototype."
        )
    return text
