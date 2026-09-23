from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client(tmp_path: Path):
    old_path = os.environ.get("VISNOTICE_DB_PATH")
    os.environ["VISNOTICE_DB_PATH"] = str(tmp_path / "test.db")
    with TestClient(app) as test_client:
        yield test_client
    if old_path is None:
        os.environ.pop("VISNOTICE_DB_PATH", None)
    else:
        os.environ["VISNOTICE_DB_PATH"] = old_path
