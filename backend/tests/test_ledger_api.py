from __future__ import annotations

from types import SimpleNamespace
import sqlite3

from app.models import LabeledFact, NoticeData
from app.services.ledger_layout import build_source_ledger
from app.models import SourceUnit
from app.services.storage import get_notice


def test_translation_api_retains_all_ids_before_semantics(client, monkeypatch) -> None:
    async def translate(ledger):
        for block in ledger.blocks:
            block.english = "Enrolled students: apply by 2026.09.20."
            block.translation_status = "translated"
        for unit in ledger.units:
            unit.english = ledger.blocks[0].english
            unit.translation_status = "translated"
            unit.translation_source_ids = [unit.id]
        ledger.coverage.translated_unit_ids = [u.id for u in ledger.units]
        return ledger

    monkeypatch.setattr("app.main.translate_ledger", translate)
    response = client.post(
        "/api/translate-ledger",
        json={
            "units": [
                {
                    "id": "u1",
                    "image_id": "image1",
                    "page_number": 1,
                    "order": 0,
                    "source_text": "재학생 신청 2026.09.20",
                },
                {
                    "id": "u2",
                    "image_id": "image1",
                    "page_number": 1,
                    "order": 1,
                    "source_text": "재학생 신청 2026.09.20",
                },
            ],
            "ocr_latency_ms": 123,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["coverage"]["source_unit_ids"] == ["u1", "u2"]
    assert body["coverage"]["displayed_unit_ids"] == []
    assert body["metrics"]["ocr_ms"] == 123
    assert not body["coverage"]["meaning_checked"]


def test_semantic_result_includes_independent_ledger_and_no_image_bytes(
    client, monkeypatch
) -> None:
    ledger = build_source_ledger(
        [
            SourceUnit(
                id="u1",
                image_id="image1",
                page_number=1,
                order=0,
                source_text="참여 불가",
            )
        ]
    )
    ledger.units[0].english = "Participation is not allowed."
    ledger.blocks[0].english = ledger.units[0].english

    async def analyze(incoming, provider, regions):
        assert provider == "openai"
        assert regions[0].unit_ids == ["u1"]
        incoming.metrics.semantic_requests = 1
        incoming.metrics.input_tokens = 120
        incoming.metrics.output_tokens = 32
        incoming.metrics.total_tokens = 152
        notice = NoticeData(
            title="Participation conditions",
            warnings=[
                LabeledFact(
                    text="Participation is not allowed.",
                    source_evidence="참여 불가",
                    source_unit_ids=["u1"],
                )
            ],
        )
        return SimpleNamespace(notice=notice, ledger=incoming)

    monkeypatch.setattr("app.main.analyze_ledger", analyze)
    response = client.post(
        "/api/analyze-ledger",
        json={
            "ledger": ledger.model_dump(),
            "provider": "openai",
            "regions": [
                {"unit_ids": ["u1"], "data_url": "data:image/jpeg;base64,/9j/"}
            ],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert "Participation is not allowed." in body["simplified_text"]
    assert body["source_ledger"]["units"][0]["id"] == "u1"
    assert body["acquisition"]["semantic_total_tokens"] == 152
    assert body["acquisition"]["english_coverage_status"] == "not_audited"
    assert "data:image" not in response.text
    stored = get_notice(body["id"])
    assert stored is not None
    assert "data:image" not in stored.model_dump_json()


def test_ledger_translation_request_does_not_accept_duplicate_source_ids(
    client,
) -> None:
    item = {
        "id": "u1",
        "image_id": "image1",
        "page_number": 1,
        "order": 0,
        "source_text": "신청",
    }
    response = client.post("/api/translate-ledger", json={"units": [item, item]})
    assert response.status_code == 422


def test_optional_persistence_failure_does_not_withhold_result(
    client, monkeypatch
) -> None:
    ledger = build_source_ledger(
        [
            SourceUnit(
                id="u1", image_id="image1", page_number=1, order=0, source_text="신청"
            )
        ]
    )

    async def analyze(incoming, provider, regions):
        return SimpleNamespace(
            notice=NoticeData(title="Application instructions"), ledger=incoming
        )

    def fail_save(result):
        raise sqlite3.OperationalError("temporary disk unavailable")

    monkeypatch.setattr("app.main.analyze_ledger", analyze)
    monkeypatch.setattr("app.main.save_notice", fail_save)
    response = client.post("/api/analyze-ledger", json={"ledger": ledger.model_dump()})
    assert response.status_code == 200
    assert response.json()["notice"]["title"] == "Application instructions"
