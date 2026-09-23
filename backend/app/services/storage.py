from __future__ import annotations

import csv
import io
import json
import os
import sqlite3
from pathlib import Path

from app.models import AnalysisResult, ResearchResultCreate


def database_path() -> Path:
    configured = os.getenv("VISNOTICE_DB_PATH")
    if configured:
        return Path(configured)
    if os.getenv("VERCEL") == "1":
        return Path("/tmp/visnotice-v2") / "visnotice.db"
    return Path(__file__).resolve().parents[3] / "visnotice.db"


def connect() -> sqlite3.Connection:
    database_path().parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path())
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database() -> None:
    with connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS notices (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                title TEXT NOT NULL,
                category TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS research_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                participant_id TEXT NOT NULL,
                notice_id TEXT NOT NULL,
                condition_code TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT NOT NULL,
                duration_seconds INTEGER NOT NULL,
                confidence INTEGER NOT NULL,
                answers_json TEXT NOT NULL
            );
            """
        )


def save_notice(result: AnalysisResult) -> None:
    with connect() as connection:
        connection.execute(
            """INSERT OR REPLACE INTO notices (id, created_at, title, category, payload)
               VALUES (?, ?, ?, ?, ?)""",
            (result.id, result.created_at, result.notice.title, result.notice.notice_type, result.model_dump_json()),
        )


def list_notices() -> list[AnalysisResult]:
    with connect() as connection:
        rows = connection.execute("SELECT payload FROM notices ORDER BY created_at DESC").fetchall()
    return [AnalysisResult.model_validate_json(row["payload"]) for row in rows]


def get_notice(notice_id: str) -> AnalysisResult | None:
    with connect() as connection:
        row = connection.execute("SELECT payload FROM notices WHERE id = ?", (notice_id,)).fetchone()
    return AnalysisResult.model_validate_json(row["payload"]) if row else None


def save_research_result(result: ResearchResultCreate) -> int:
    with connect() as connection:
        cursor = connection.execute(
            """INSERT INTO research_results
               (participant_id, notice_id, condition_code, started_at, finished_at, duration_seconds, confidence, answers_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                result.participant_id,
                result.notice_id,
                result.condition,
                result.started_at,
                result.finished_at,
                result.duration_seconds,
                result.confidence,
                json.dumps([answer.model_dump() for answer in result.answers], ensure_ascii=False),
            ),
        )
        return int(cursor.lastrowid)


def _safe_csv_cell(value: object) -> str:
    text = str(value)
    return f"'{text}" if text.startswith(("=", "+", "-", "@")) else text


def export_research_csv() -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(
        [
            "result_id", "participant_id", "notice_id", "condition", "started_at", "finished_at",
            "duration_seconds", "confidence", "correct_answers", "total_scored_answers",
            "comprehension_accuracy", "critical_information_miss_rate", "answers_json",
        ]
    )
    with connect() as connection:
        rows = connection.execute("SELECT * FROM research_results ORDER BY id").fetchall()
    for row in rows:
        answers = json.loads(row["answers_json"])
        scored = [answer for answer in answers if answer.get("correct") is not None]
        correct = sum(answer.get("correct") is True for answer in scored)
        accuracy = correct / len(scored) if scored else ""
        miss_rate = 1 - accuracy if accuracy != "" else ""
        writer.writerow(
            [
                row["id"], _safe_csv_cell(row["participant_id"]), row["notice_id"], row["condition_code"],
                row["started_at"], row["finished_at"], row["duration_seconds"], row["confidence"],
                correct, len(scored), accuracy, miss_rate, json.dumps(answers, ensure_ascii=False),
            ]
        )
    return output.getvalue()
