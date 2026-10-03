from hashlib import sha256


def derived_id(prefix: str, source_id: str) -> str:
    """Keep derived identifiers bounded without changing physical source IDs."""
    value = f"{prefix}-{source_id}"
    if len(value) <= 128:
        return value
    digest = sha256(value.encode("utf-8")).hexdigest()[:16]
    return f"{value[:111]}-{digest}"
