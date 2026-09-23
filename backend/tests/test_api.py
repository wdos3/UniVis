from __future__ import annotations

import csv
import io

import fitz
from fastapi.testclient import TestClient

from app.services.demos import DEMOS


def test_mock_text_ingestion_and_admin_update(client: TestClient) -> None:
    response = client.post("/api/analyze", json={"text": DEMOS[0].original_text, "provider": "mock", "target_language": "en"})
    assert response.status_code == 200
    result = response.json()
    assert result["notice"]["title"] == "Extension of Stay for International Students"
    assert result["fidelity"]["potentially_missing"] == []
    result["notice"]["summary"] = "Researcher-corrected summary."
    updated = client.put(f"/api/notices/{result['id']}", json=result["notice"])
    assert updated.status_code == 200
    assert updated.json()["simplified_text"].find("Researcher-corrected summary.") >= 0


def test_pdf_extraction(client: TestClient) -> None:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Korean university notice test")
    payload = document.tobytes()
    document.close()
    response = client.post(
        "/api/upload",
        files={"file": ("notice.pdf", payload, "application/pdf")},
        data={"provider": "mock", "target_language": "en"},
    )
    assert response.status_code == 200
    assert "Korean university notice test" in response.json()["original_text"]


def test_image_only_pdf_returns_clear_error(client: TestClient) -> None:
    document = fitz.open()
    document.new_page()
    payload = document.tobytes()
    document.close()
    response = client.post("/api/upload", files={"file": ("scan.pdf", payload, "application/pdf")}, data={"provider": "mock"})
    assert response.status_code == 422
    assert "Unable to reliably read" in response.json()["detail"]


def test_research_result_csv_export(client: TestClient) -> None:
    payload = {
        "participant_id": "=unsafe-cell",
        "notice_id": "demo-visa-2026",
        "condition": "C",
        "started_at": "2026-01-01T00:00:00Z",
        "finished_at": "2026-01-01T00:01:00Z",
        "duration_seconds": 60,
        "confidence": 4,
        "answers": [{"question_id": "q1", "answer": "Sep 25", "correct": True}, {"question_id": "q2", "answer": "Unknown", "correct": False}],
    }
    assert client.post("/api/research/results", json=payload).status_code == 201
    response = client.get("/api/research/results.csv")
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert rows[0]["participant_id"] == "'=unsafe-cell"
    assert rows[0]["comprehension_accuracy"] == "0.5"
    assert rows[0]["critical_information_miss_rate"] == "0.5"
