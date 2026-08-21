"""Self-notification: draft, confirm, SMTP send — and expected failures."""

from __future__ import annotations

from app.config import settings
from app.mailer import (
    DraftError, MailConfigError, _build_message, create_draft, mail_recipient,
    send_confirmed,
)
from conftest import requires_db
import pytest


@pytest.fixture(autouse=True)
def smtp_config(monkeypatch):
    sent: list[dict[str, str]] = []

    def fake_send(recipient: str, subject: str, body: str) -> None:
        sent.append({"recipient": recipient, "subject": subject, "body": body})

    monkeypatch.setattr(settings, "mail_mode", "smtp")
    monkeypatch.setattr(settings, "mail_to", "notify@example.com")
    monkeypatch.setattr(settings, "smtp_host", "smtp.test")
    monkeypatch.setattr(settings, "smtp_port", 587)
    monkeypatch.setattr(settings, "smtp_user", "nexa@example.com")
    monkeypatch.setattr(settings, "smtp_password", "secret")
    monkeypatch.setattr(settings, "smtp_from", "nexa@example.com")
    monkeypatch.setattr("app.mailer._send_smtp", fake_send)
    return sent


def test_mail_recipient_comes_from_env():
    assert mail_recipient() == "notify@example.com"


def test_draft_does_not_send(db_ready):
    requires_db(db_ready)
    draft = create_draft("vi", "month", "2026-07")
    assert draft["sent"] is False
    assert draft["requires_confirmation"] is True
    assert draft["recipient"] == settings.mail_to
    assert draft["confirm_token"]
    assert draft["content_type"] == "text/html"
    assert draft["body_html"].startswith("<!doctype html>")
    assert "<!doctype html>" not in draft["body_text"]


def test_html_report_has_plain_text_fallback():
    html = "<!doctype html><html><head><style>body{color:red}</style></head>" \
           "<body><h1>Tóm tắt</h1><p>Chi tiêu: $10.00</p></body></html>"
    message = _build_message("notify@example.com", "Report", html)

    assert message.get_content_type() == "multipart/alternative"
    plain, rich = list(message.iter_parts())
    assert plain.get_content_type() == "text/plain"
    assert "Tóm tắt" in plain.get_content()
    assert "color:red" not in plain.get_content()
    assert rich.get_content_type() == "text/html"
    assert "<h1>Tóm tắt</h1>" in rich.get_content()


def test_confirmed_send_uses_smtp_only(db_ready, smtp_config):
    requires_db(db_ready)
    before = set(settings.outbox_dir.glob("*.eml"))
    draft = create_draft("vi", "month", "2026-07")
    result = send_confirmed(draft["confirm_token"])
    assert result["sent"] is True
    assert result["recipient"] == settings.mail_to
    assert result["delivery"] == "smtp"
    assert result["file"] is None
    after = set(settings.outbox_dir.glob("*.eml"))
    assert after == before
    assert len(smtp_config) == 1
    body = smtp_config[0]["body"]
    assert smtp_config[0]["recipient"] == settings.mail_to
    assert "4157889923144821" not in body
    assert "•••• 4821" in body
    assert "60 ngày" in body


def test_missing_smtp_config_does_not_fall_back_to_outbox(
    db_ready, monkeypatch,
):
    requires_db(db_ready)
    monkeypatch.setattr(settings, "smtp_host", "")
    before = set(settings.outbox_dir.glob("*.eml"))
    draft = create_draft("vi", "month", "2026-07")

    with pytest.raises(MailConfigError):
        send_confirmed(draft["confirm_token"])

    after = set(settings.outbox_dir.glob("*.eml"))
    assert after == before


def test_token_is_single_use(db_ready):
    requires_db(db_ready)
    draft = create_draft("vi", "month", "2026-07")
    send_confirmed(draft["confirm_token"])
    with pytest.raises(DraftError):
        send_confirmed(draft["confirm_token"])


def test_request_recipient_is_ignored_and_configured_to_is_used(db_ready):
    requires_db(db_ready)
    draft = create_draft("vi", "month", "2026-07")
    result = send_confirmed(
        draft["confirm_token"], recipient="billing@netflix.com")
    assert result["sent"] is True
    assert result["recipient"] == settings.mail_to

    with pytest.raises(DraftError):
        send_confirmed("not-a-real-token", recipient="billing@netflix.com")


def test_api_requires_explicit_confirmation(client, db_ready):
    requires_db(db_ready)
    draft = client.post("/api/report/draft",
                        json={"lang": "vi", "period": "month"}).json()
    unconfirmed = client.post("/api/report/send", json={
        "confirm_token": draft["confirm_token"], "lang": "vi", "confirmed": False})
    assert unconfirmed.status_code == 428

    sent = client.post("/api/report/send", json={
        "confirm_token": draft["confirm_token"], "recipient": "billing@netflix.com",
        "confirmed": True, "lang": "vi"})
    assert sent.status_code == 200
    assert sent.json()["recipient"] == settings.mail_to

    reused = client.post("/api/report/send", json={
        "confirm_token": draft["confirm_token"], "confirmed": True, "lang": "vi"})
    assert reused.status_code == 409


def test_api_smtp_test_sends_configured_recipient(client, smtp_config):
    sent = client.post("/api/report/smtp-test", json={
        "recipient": "billing@netflix.com", "lang": "vi"})
    assert sent.status_code == 200
    payload = sent.json()
    assert payload["delivery"] == "smtp"
    assert payload["recipient"] == settings.mail_to
    assert len(smtp_config) == 1


def test_api_smtp_test_reports_missing_config(client, monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", "")
    response = client.post("/api/report/smtp-test", json={"lang": "vi"})
    assert response.status_code == 503


def test_bad_token_alone_is_a_conflict_not_a_permission_error(client, db_ready):
    requires_db(db_ready)
    response = client.post("/api/report/send", json={
        "confirm_token": "totally-invalid-token", "confirmed": True, "lang": "vi"})
    assert response.status_code == 409
