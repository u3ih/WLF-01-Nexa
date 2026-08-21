"""Self-notification: draft, confirm, send — and everything that must fail."""

from __future__ import annotations

from email import policy
from email.parser import BytesParser

from app.config import settings
from app.mailer import (
    DraftError, OwnerOnlyError, assert_owner, create_draft, send_confirmed,
)
from conftest import requires_db
import pytest


def test_owner_check_accepts_only_the_owner():
    assert assert_owner(settings.owner_email) == settings.owner_email.lower()
    for address in ["billing@netflix.com", "support@wealify.example.com",
                    "attacker@example.org", ""]:
        with pytest.raises(OwnerOnlyError):
            assert_owner(address)


def test_draft_does_not_send(db_ready):
    requires_db(db_ready)
    draft = create_draft("vi", "month", "2026-07")
    assert draft["sent"] is False
    assert draft["requires_confirmation"] is True
    assert draft["recipient"] == settings.owner_email
    assert draft["confirm_token"]


def test_confirmed_send_writes_one_outbox_file(db_ready):
    requires_db(db_ready)
    before = set(settings.outbox_dir.glob("*.eml"))
    draft = create_draft("vi", "month", "2026-07")
    result = send_confirmed(draft["confirm_token"])
    assert result["sent"] is True
    assert result["recipient"] == settings.owner_email
    after = set(settings.outbox_dir.glob("*.eml"))
    assert len(after - before) == 1
    # The message is base64-encoded because the report is not ASCII, so decode
    # it rather than grepping the raw file.
    written = (after - before).pop()
    message = BytesParser(policy=policy.default).parsebytes(written.read_bytes())
    body = message.get_content()
    assert message["To"] == settings.owner_email
    assert "4157889923144821" not in body
    assert "•••• 4821" in body
    assert "60 ngày" in body


def test_token_is_single_use(db_ready):
    requires_db(db_ready)
    draft = create_draft("vi", "month", "2026-07")
    send_confirmed(draft["confirm_token"])
    with pytest.raises(DraftError):
        send_confirmed(draft["confirm_token"])


def test_third_party_recipient_is_refused_before_the_token_is_checked(db_ready):
    requires_db(db_ready)
    draft = create_draft("vi", "month", "2026-07")
    # Valid token, wrong address.
    with pytest.raises(OwnerOnlyError):
        send_confirmed(draft["confirm_token"], recipient="billing@netflix.com")
    # Nonsense token, wrong address: still an owner error, not a token error.
    with pytest.raises(OwnerOnlyError):
        send_confirmed("not-a-real-token", recipient="billing@netflix.com")
    # The draft survives the rejected attempts.
    assert send_confirmed(draft["confirm_token"])["sent"] is True


def test_api_requires_explicit_confirmation(client, db_ready):
    requires_db(db_ready)
    draft = client.post("/api/report/draft",
                        json={"lang": "vi", "period": "month"}).json()
    unconfirmed = client.post("/api/report/send", json={
        "confirm_token": draft["confirm_token"], "lang": "vi", "confirmed": False})
    assert unconfirmed.status_code == 428

    third_party = client.post("/api/report/send", json={
        "confirm_token": draft["confirm_token"], "recipient": "billing@netflix.com",
        "confirmed": True, "lang": "vi"})
    assert third_party.status_code == 403

    sent = client.post("/api/report/send", json={
        "confirm_token": draft["confirm_token"], "confirmed": True, "lang": "vi"})
    assert sent.status_code == 200
    assert sent.json()["recipient"] == settings.owner_email

    reused = client.post("/api/report/send", json={
        "confirm_token": draft["confirm_token"], "confirmed": True, "lang": "vi"})
    assert reused.status_code == 409


def test_bad_token_alone_is_a_conflict_not_a_permission_error(client, db_ready):
    requires_db(db_ready)
    response = client.post("/api/report/send", json={
        "confirm_token": "totally-invalid-token", "confirmed": True, "lang": "vi"})
    assert response.status_code == 409
