"""Shared fixtures.

The answer-key tests run against the generated sample, which is what
`ground_truth.json` describes. `settings.data_dir` points at the real Wealify
export, so those tests pin the sample directory explicitly rather than
following the setting — otherwise changing the app's input silently changes
what the answer key is compared against.
"""

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

# The generated sample: the only dataset `ground_truth.json` describes.
SAMPLE_DIR = BACKEND_ROOT / "data" / "sample"


@pytest.fixture(scope="session", autouse=True)
def dataset() -> None:
    if not (SAMPLE_DIR / "ground_truth.json").exists():
        subprocess.run([sys.executable, "-m", "data.generate"],
                       cwd=BACKEND_ROOT, check=True,
                       stdout=subprocess.DEVNULL)
    # The API fixtures below serve whatever `settings.data_dir` points at, so
    # the suite covers the real input too.
    settings.data_dir = SAMPLE_DIR
    pipeline.reset_cache()


@pytest.fixture(scope="session")
def truth() -> dict:
    return json.loads((SAMPLE_DIR / "ground_truth.json").read_text())


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
