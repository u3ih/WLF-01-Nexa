"""Shared fixtures. The dataset is regenerated once so the suite always runs
against the committed generator rather than whatever is on disk."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.config import settings          # noqa: E402
from app.engine import pipeline          # noqa: E402
from app.main import app                 # noqa: E402
from app.store import store              # noqa: E402

TODAY = date(2026, 8, 19)


@pytest.fixture(scope="session", autouse=True)
def dataset() -> None:
    if not (settings.data_dir / "ground_truth.json").exists():
        subprocess.run([sys.executable, "-m", "data.generate"],
                       cwd=BACKEND_ROOT, check=True,
                       stdout=subprocess.DEVNULL)
    pipeline.reset_cache()


@pytest.fixture(scope="session")
def truth() -> dict:
    return json.loads((settings.data_dir / "ground_truth.json").read_text())


@pytest.fixture(scope="session")
def analysis():
    return pipeline.cached()


@pytest.fixture(scope="session", autouse=True)
def deterministic_llm() -> None:
    """Force the offline tier for the suite.

    The model is exercised separately (NEXA_TEST_LLM=1) — the graded numbers
    must be asserted against the engine, not against a model's phrasing.
    """
    from app.llm.client import client as llm_client

    settings.offline_mode = True
    llm_client.status(refresh=True)


@pytest.fixture(scope="session")
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def db_ready() -> bool:
    return store.init_schema()


def requires_db(db_ready: bool) -> None:
    if not db_ready:
        pytest.skip(f"Postgres unavailable: {store.last_error}")
