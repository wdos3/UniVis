from __future__ import annotations

import io
from pathlib import Path

import fitz
from fastapi.testclient import TestClient
from PIL import Image
import pytest

from app.services.extraction.reconciliation import reconcile_text_sources
from app.services.images.preprocessing import prepare_image


DEMO_IMAGES = Path(__file__).resolve().parents[2] / "demo_data" / "images"


def image_payload(name: str) -> tuple[str, bytes, str]:
    path = DEMO_IMAGES / name
    media_type = "image/jpeg" if path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
    return path.name, path.read_bytes(), media_type


def test_single_image_upload_and_mixed_language_preservation(client: TestClient) -> None:
    response = client.post(
        "/api/analyze-images",
        files=[("files", image_payload("mixed-korean-english-notice.png"))],
        data={"provider": "mock", "input_type": "uploaded_image", "target_language": "en"},
    )
    assert response.status_code == 200
    result = response.json()
    assert result["acquisition"]["source_pages"] == 1
    assert result["source_pages"][0]["filename"] == "mixed-korean-english-notice.png"
    assert "외국인등록증" in result["recovered_text"]
    assert any(document["name"] == "Residence Card" for document in result["notice"]["required_documents"])


def test_multiple_images_keep_page_order(client: TestClient) -> None:
    response = client.post(
        "/api/analyze-images",
        files=[
            ("files", image_payload("multi-page-scholarship-2.png")),
            ("files", image_payload("multi-page-scholarship-1.png")),
        ],
        data={"provider": "mock", "input_type": "camera_photo"},
    )
    assert response.status_code == 200
    pages = response.json()["source_pages"]
    assert [page["filename"] for page in pages] == ["multi-page-scholarship-2.png", "multi-page-scholarship-1.png"]
    assert [page["page_number"] for page in pages] == [1, 2]


def test_table_rows_are_not_flattened(client: TestClient) -> None:
    response = client.post(
        "/api/analyze-images",
        files=[("files", image_payload("course-table-notice.png"))],
        data={"provider": "mock", "input_type": "uploaded_image"},
    )
    assert response.status_code == 200
    groups = response.json()["notice"]["conditional_groups"]
    assert groups == [
        {
            "source_evidence": "재학생 2월 15일~17일", "source_fact_ids": ["F001"], "state": "verified", "source_page": 1,
            "source_image_id": groups[0]["source_image_id"], "bounding_box": None, "group": "Enrolled students", "application_period": "February 15–17, 2027", "details": "",
        },
        {
            "source_evidence": "신입생 2월 19일", "source_fact_ids": ["F002"], "state": "verified", "source_page": 1,
            "source_image_id": groups[1]["source_image_id"], "bounding_box": None, "group": "New students", "application_period": "February 19, 2027", "details": "",
        },
    ]


def test_invalid_and_oversized_images_are_rejected(client: TestClient) -> None:
    invalid = client.post(
        "/api/analyze-images",
        files=[("files", ("broken.png", b"not an image", "image/png"))],
        data={"provider": "mock", "input_type": "uploaded_image"},
    )
    assert invalid.status_code == 422
    assert "not a readable image" in invalid.json()["detail"]

    oversized = client.post(
        "/api/analyze-images",
        files=[("files", ("large.png", b"0" * (15 * 1024 * 1024 + 1), "image/png"))],
        data={"provider": "mock", "input_type": "uploaded_image"},
    )
    assert oversized.status_code == 413


def test_exif_rotation_is_applied() -> None:
    image = Image.new("RGB", (1200, 800), "white")
    exif = Image.Exif()
    exif[274] = 6
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", exif=exif)
    prepared = prepare_image(buffer.getvalue(), "rotated.jpg", "image/jpeg", "test-exif", 1)
    assert prepared.page.width == 800
    assert prepared.page.height == 1200


def test_qr_code_is_detected(client: TestClient) -> None:
    response = client.post(
        "/api/analyze-images",
        files=[("files", image_payload("qr-visa-notice.png"))],
        data={"provider": "mock", "input_type": "uploaded_image"},
    )
    assert response.status_code == 200
    codes = response.json()["source_pages"][0]["qr_codes"]
    assert codes[0]["url"] == "https://example.edu/synthetic-notice"


def test_image_only_pdf_is_rendered_and_analyzed_visually(client: TestClient) -> None:
    _, image_data, _ = image_payload("clean-visa-notice.png")
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_image(page.rect, stream=image_data)
    pdf_data = document.tobytes()
    document.close()
    response = client.post(
        "/api/upload",
        files={"file": ("clean-visa-notice.pdf", pdf_data, "application/pdf")},
        data={"provider": "mock"},
    )
    assert response.status_code == 200
    result = response.json()
    assert result["acquisition"]["input_type"] == "image_pdf"
    assert result["source_pages"][0]["filename"].startswith("clean-visa-notice-")


def test_manual_recovered_text_correction_reprocesses_notice(client: TestClient) -> None:
    analyzed = client.post(
        "/api/analyze-images",
        files=[("files", image_payload("clean-visa-notice.png"))],
        data={"provider": "mock", "input_type": "uploaded_image"},
    ).json()
    corrected_text = f"{analyzed['recovered_text']}\n연구자 수정 완료"
    corrected = client.post(
        f"/api/notices/{analyzed['id']}/reprocess-recovered-text",
        json={"text": corrected_text, "provider": "mock"},
    )
    assert corrected.status_code == 200
    assert corrected.json()["recovered_text"] == corrected_text
    assert corrected.json()["source_pages"][0]["filename"] == "clean-visa-notice.png"


def test_unknown_photo_fails_conservatively_in_mock_mode(client: TestClient) -> None:
    _, data, _ = image_payload("clean-visa-notice.png")
    response = client.post(
        "/api/analyze-images",
        files=[("files", ("unknown-poster.png", data, "image/png"))],
        data={"provider": "mock", "input_type": "uploaded_image"},
    )
    assert response.status_code == 422
    assert "Configure OPENAI_API_KEY" in response.json()["detail"]


def test_pipeline_failure_is_reported_without_source_content(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail_pipeline(*_args, **_kwargs):
        raise RuntimeError("provider details must not leak")

    monkeypatch.setattr("app.main.analyze_image_pipeline", fail_pipeline)
    response = client.post(
        "/api/analyze-images",
        files=[("files", image_payload("clean-visa-notice.png"))],
        data={"provider": "openai", "input_type": "uploaded_image"},
    )
    assert response.status_code == 502
    assert response.json()["detail"] == "The configured Version 2 pipeline could not complete the analysis."
    assert "provider details" not in response.text


def test_conflicting_exact_values_are_flagged() -> None:
    conflicts = reconcile_text_sources("Deadline 2026.09.30 at 14:00", ["Deadline 2026.09.30 at 16:00"])
    assert any("14:00" in conflict for conflict in conflicts)
    assert any("16:00" in conflict for conflict in conflicts)
