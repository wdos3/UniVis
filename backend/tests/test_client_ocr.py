from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from app import main
from app.services import public_access
from app.services.demos import DEMOS
from app.services.storage import get_notice, list_notices


def client_ocr_payload(*page_texts: str) -> dict[str, Any]:
    return {
        "pages": [{"text": text} for text in page_texts],
        "target_language": "en",
        "provider": "mock",
        "input_type": "uploaded_image",
        "ocr_latency_ms": 1234,
    }


def test_client_ocr_preserves_ordered_page_evidence_without_storing_images(
    client: TestClient, monkeypatch: MonkeyPatch,
) -> None:
    first, second = DEMOS[0].original_text.split("제출 서류:", 1)
    calls = 0
    original_pipeline = main.analyze_text_pipeline

    async def count_pipeline(*args, **kwargs):
        nonlocal calls
        calls += 1
        return await original_pipeline(*args, **kwargs)

    monkeypatch.setattr(main, "analyze_text_pipeline", count_pipeline)
    response = client.post("/api/analyze-client-ocr", json=client_ocr_payload(first, f"제출 서류:{second}"))

    assert response.status_code == 200
    assert calls == 1
    result = response.json()
    assert result["acquisition"]["input_type"] == "uploaded_image"
    assert result["acquisition"]["source_pages"] == 2
    assert result["acquisition"]["ocr_provider"] == "browser-ocr-kor-eng"
    assert result["acquisition"]["ocr_latency_ms"] == 1234
    assert result["acquisition"]["text_extraction_status"] == "available"
    assert result["original_text"].startswith("[Page 1]\n")
    assert "[Page 2]\n제출 서류:" in result["original_text"]
    assert result["recovered_text"] == result["original_text"]
    assert [page["page_number"] for page in result["source_pages"]] == [1, 2]
    assert all(not page["original_url"] and not page["processed_url"] for page in result["source_pages"])
    assert all(page["id"].startswith(result["id"]) for page in result["source_pages"])
    assert result["notice"]["audience"][0]["source_page"] == 1
    assert result["notice"]["required_documents"][0]["source_page"] == 2
    assert result["notice"]["required_documents"][0]["source_image_id"] == result["source_pages"][1]["id"]

    stored = get_notice(result["id"])
    assert stored is not None
    assert all(not page.original_url and not page.processed_url for page in stored.source_pages)


def test_client_ocr_marks_empty_page_for_review(client: TestClient) -> None:
    response = client.post("/api/analyze-client-ocr", json=client_ocr_payload(DEMOS[0].original_text, ""))

    assert response.status_code == 200
    result = response.json()
    assert result["acquisition"]["text_extraction_status"] == "partial"
    assert result["acquisition"]["pages_needing_review"] == 1
    assert result["source_pages"][1]["readable"] is False
    assert result["source_pages"][1]["quality_issues"][0]["code"] == "ocr_empty_page"
    assert any("page(s): 2" in warning for warning in result["notice"]["unverified_items"])


def test_client_ocr_rejects_unreadable_and_oversized_text(client: TestClient) -> None:
    unreadable = client.post("/api/analyze-client-ocr", json=client_ocr_payload("University notice"))
    assert unreadable.status_code == 422
    assert "too little Korean text" in unreadable.json()["detail"]

    too_many_pages = client.post("/api/analyze-client-ocr", json=client_ocr_payload(*(["공지사항"] * 13)))
    assert too_many_pages.status_code == 422

    oversized_page = client.post("/api/analyze-client-ocr", json=client_ocr_payload("공지사항" * 5001))
    assert oversized_page.status_code == 422

    too_much_total = client.post("/api/analyze-client-ocr", json=client_ocr_payload(*(["공지사항" * 3000] * 5)))
    assert too_much_total.status_code == 422


def test_client_ocr_rejects_image_data_and_client_metadata(client: TestClient) -> None:
    payload = client_ocr_payload(DEMOS[0].original_text)
    payload["image"] = "base64-image-data"
    assert client.post("/api/analyze-client-ocr", json=payload).status_code == 422

    payload = client_ocr_payload(DEMOS[0].original_text)
    payload["pages"][0]["filename"] = "private-poster.jpg"
    assert client.post("/api/analyze-client-ocr", json=payload).status_code == 422


def test_mock_client_ocr_rejects_partial_demo_title_without_inventing_facts(client: TestClient) -> None:
    partial = client.post(
        "/api/analyze-client-ocr",
        json=client_ocr_payload(DEMOS[0].original_text[:80]),
    )
    changed_deadline = client.post(
        "/api/analyze-client-ocr",
        json=client_ocr_payload(DEMOS[0].original_text.replace("9월 25일", "9월 26일")),
    )

    assert partial.status_code == 422
    assert changed_deadline.status_code == 422
    assert "incomplete or real notice photo" in partial.json()["detail"]
    assert list_notices() == []


def test_client_ocr_is_publicly_rate_limited(client: TestClient, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("VISNOTICE_PUBLIC_MODE", "1")
    monkeypatch.setattr(public_access, "analysis_limiter", public_access.PublicAnalysisLimiter(max_per_minute=1))
    payload = client_ocr_payload(DEMOS[0].original_text)

    assert client.post("/api/analyze-client-ocr", json=payload).status_code == 200
    assert client.post("/api/analyze-client-ocr", json=payload).status_code == 429


def test_reprocessing_client_ocr_preserves_blank_middle_page(client: TestClient) -> None:
    first, second = DEMOS[0].original_text.split("제출 서류:", 1)
    analyzed = client.post(
        "/api/analyze-client-ocr",
        json=client_ocr_payload(first, "", f"제출 서류:{second}"),
    ).json()
    assert analyzed["notice"]["source_facts"][2]["source_page"] == 3

    corrected = client.post(
        f"/api/notices/{analyzed['id']}/reprocess-recovered-text",
        json={"text": analyzed["recovered_text"], "provider": "mock"},
    )

    assert corrected.status_code == 200
    result = corrected.json()
    assert result["acquisition"]["text_extraction_status"] == "partial"
    assert result["acquisition"]["pages_needing_review"] == 1
    assert result["notice"]["source_facts"][2]["source_page"] == 3
    assert result["notice"]["source_facts"][2]["source_image_id"] == result["source_pages"][2]["id"]
    assert "[Page 2]\n\n\n[Page 3]" in result["recovered_text"]
