"""No response, journal row or exported file may carry a full card number,
a full account number, or anything CVV-shaped."""

from __future__ import annotations

import json

import pytest

from app.config import settings
from app.engine.mask import has_unmasked_pan
from app.store import store
from conftest import requires_db

ACCOUNT_NUMBER = "8830041926390"
CARD_NUMBER = "4157889923144821"

GET_ENDPOINTS = [
    "/api/health", "/api/summary", "/api/cashflow", "/api/subscriptions",
    "/api/findings", "/api/email-recon", "/api/tri-source",
    "/api/statement?source=account", "/api/statement?source=card",
    "/api/report?period=month", "/api/report/all", "/api/monitor/reminders",
    "/api/monitor/history", "/api/audit", "/api/audit/flags",
    "/api/i18n/vi", "/api/i18n/en", "/api/disclaimer",
]


@pytest.mark.parametrize("path", GET_ENDPOINTS)
def test_endpoints_never_leak_raw_identifiers(client, path):
    response = client.get(path)
    assert response.status_code == 200, path
    body = response.text
    assert ACCOUNT_NUMBER not in body, path
    assert CARD_NUMBER not in body, path
    for token in ("cvv", "cvc", "security_code", "card_number"):
        assert token not in body.lower(), f"{path} exposes {token}"


def test_card_rows_show_only_the_last_four(client):
    rows = client.get("/api/statement?source=card").json()["rows"]
    assert rows
    for row in rows:
        assert row["card"] == "•••• 4821"


def test_account_profile_is_masked(client):
    account = client.get("/api/summary").json()["account"]
    assert account["account_masked"] == "••••••6390"
    assert account["card_masked"] == "•••• 4821"
    assert ACCOUNT_NUMBER not in json.dumps(account)


def test_chat_responses_are_masked(client):
    response = client.post("/api/chat", json={
        "question": "Cho mình xem sao kê thẻ", "lang": "vi"})
    assert response.status_code == 200
    assert CARD_NUMBER not in response.text
    assert not has_unmasked_pan(response.json()["answer"])


def test_audit_export_is_masked(client, db_ready):
    requires_db(db_ready)
    from app.monitor import run_scan

    run_scan("test", "vi")
    for fmt in ("csv", "json"):
        body = client.get(f"/api/audit/export?format={fmt}").text
        assert ACCOUNT_NUMBER not in body
        assert CARD_NUMBER not in body


def test_no_cvv_field_exists_anywhere_in_the_models():
    """CVV cannot be stored because no model has a field for it."""
    from app.engine import models

    for name in dir(models):
        obj = getattr(models, name)
        fields = getattr(obj, "__dataclass_fields__", {})
        for field in fields:
            assert "cvv" not in field.lower()
            assert "cvc" not in field.lower()


def test_the_sample_dataset_itself_contains_no_cvv():
    for path in settings.data_dir.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_bytes().lower()
        assert b"cvv" not in text, path
        assert b"cvc" not in text, path
