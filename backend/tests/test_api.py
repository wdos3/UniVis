from __future__ import annotations

import csv
import io
import re

import fitz
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from starlette.datastructures import UploadFile

from app.main import MAX_UPLOAD_BYTES
from app.services import public_access
from app.services.demos import DEMOS


def test_mock_text_ingestion_and_admin_update(client: TestClient) -> None:
    response = client.post("/api/analyze", json={"text": DEMOS[0].original_text, "provider": "mock", "target_language": "en"})
    assert response.status_code == 200
    result = response.json()
    assert result["notice"]["title"] == "Extension of Stay for International Students"
    assert re.fullmatch(r"notice-[0-9a-f]{32}", result["id"])
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


def test_public_mode_blocks_researcher_routes_without_admin_token(client: TestClient, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("VISNOTICE_PUBLIC_MODE", "1")
    monkeypatch.delenv("VISNOTICE_ADMIN_TOKEN", raising=False)
    analyzed = client.post("/api/analyze", json={"text": DEMOS[0].original_text, "provider": "mock"}).json()
    assert client.get("/api/health").json()["public_mode"] is True

    assert client.get("/api/notices").status_code == 403
    assert client.put(f"/api/notices/{analyzed['id']}", json=analyzed["notice"]).status_code == 403
    assert client.post(
        f"/api/notices/{analyzed['id']}/reprocess-recovered-text",
        json={"text": "수정", "provider": "mock"},
    ).status_code == 403
    assert client.get("/api/research/results.csv").status_code == 403


def test_admin_token_protects_researcher_routes(client: TestClient, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("VISNOTICE_PUBLIC_MODE", "1")
    monkeypatch.setenv("VISNOTICE_ADMIN_TOKEN", "test-only-admin-secret")
    analyzed = client.post("/api/analyze", json={"text": DEMOS[0].original_text, "provider": "mock"}).json()
    headers = {"X-VisNotice-Admin-Token": "test-only-admin-secret"}

    assert client.get("/api/notices").status_code == 401
    assert client.get("/api/notices", headers={"X-VisNotice-Admin-Token": "wrong"}).status_code == 401
    assert client.get("/api/notices", headers=headers).json()[0]["id"] == analyzed["id"]
    assert client.put(f"/api/notices/{analyzed['id']}", json=analyzed["notice"], headers=headers).status_code == 200
    assert client.get("/api/research/results.csv", headers=headers).status_code == 200


def test_vercel_mode_denies_researcher_routes_without_token(client: TestClient, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("VISNOTICE_PUBLIC_MODE", "0")
    monkeypatch.delenv("VISNOTICE_ADMIN_TOKEN", raising=False)

    assert client.get("/api/health").json()["public_mode"] is True
    assert client.get("/api/notices").status_code == 403


def test_public_analysis_limit_applies_only_in_public_mode(client: TestClient, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(public_access, "analysis_limiter", public_access.PublicAnalysisLimiter(max_per_minute=1))
    request = {"text": DEMOS[0].original_text, "provider": "mock"}

    monkeypatch.setenv("VISNOTICE_PUBLIC_MODE", "1")
    assert client.post("/api/analyze", json=request).status_code == 200
    limited = client.post("/api/analyze", json=request)
    assert limited.status_code == 429
    assert limited.headers["Retry-After"] == "60"

    monkeypatch.setenv("VISNOTICE_PUBLIC_MODE", "0")
    assert client.post("/api/analyze", json=request).status_code == 200


def test_failed_public_analysis_releases_concurrency_slot(client: TestClient, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("VISNOTICE_PUBLIC_MODE", "1")
    monkeypatch.setattr(
        public_access, "analysis_limiter", public_access.PublicAnalysisLimiter(max_concurrent=1, max_per_minute=2),
    )
    failed = client.post(
        "/api/analyze-images",
        files={"files": ("invalid.jpg", b"not an image", "image/jpeg")},
        data={"provider": "mock"},
    )
    assert failed.status_code == 422
    assert client.post("/api/analyze", json={"text": DEMOS[0].original_text, "provider": "mock"}).status_code == 200


def test_upload_reads_are_bounded(client: TestClient, monkeypatch: MonkeyPatch) -> None:
    read_sizes: list[int] = []
    original_read = UploadFile.read

    async def recorded_read(self: UploadFile, size: int = -1) -> bytes:
        read_sizes.append(size)
        return await original_read(self, size)

    monkeypatch.setattr(UploadFile, "read", recorded_read)
    text_response = client.post(
        "/api/upload",
        files={"file": ("notice.txt", DEMOS[0].original_text.encode(), "text/plain")},
        data={"provider": "mock"},
    )
    image_response = client.post(
        "/api/analyze-images",
        files={"files": ("notice.jpg", b"not an image", "image/jpeg")},
        data={"provider": "mock"},
    )
    assert text_response.status_code == 200
    assert image_response.status_code == 422
    assert read_sizes == [MAX_UPLOAD_BYTES + 1, MAX_UPLOAD_BYTES + 1]
