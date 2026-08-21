"""Report drafting and self-notification.

Two hard rules live here, enforced in code rather than in a prompt:
  1. report emails always go to the configured notification address;
  2. report emails are sent only after the user confirms a specific draft token.
Letters aimed at a merchant or the bank are produced as drafts only — this
module has no code path that sends them. The SMTP test path sends only a small
configuration check to the same notification address.
"""

from __future__ import annotations

import secrets
from datetime import date, datetime
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid
from typing import Any

from .config import settings
from .engine import pipeline, reports
from .engine.mask import scrub_text
from .engine.models import Label, fmt_display
from .engine.render import (
    bucket_scope_note,
    disclaimer,
    excluded_lines,
    render_findings,
    t,
)
from .store import store


class DraftError(ValueError):
    pass


class MailConfigError(RuntimeError):
    pass


class MailDeliveryError(RuntimeError):
    pass


def mail_recipient() -> str:
    target = (settings.mail_to or "").strip().lower()
    if not target:
        raise MailConfigError("missing mail recipient; set NEXA_MAIL_TO")
    return target


def build_report_body(lang: str, period_kind: str = "month",
                      period_key: str | None = None,
                      today: date | None = None) -> dict[str, Any]:
    today = today or settings.today()
    analysis = pipeline.cached()
    report = reports.build(analysis.ds, period_kind, period_key,
                           analysis.subs_forecast, analysis.fx)
    profile = analysis.account_profile()
    findings = render_findings(analysis.alerts, lang, today)

    heading = t(lang, "mail.draft_subject", period=report["period"]["label"])
    lines: list[str] = []
    lines.append(heading)
    lines.append("=" * len(heading))
    lines.append("")
    lines.append(f"{profile['owner_name']} — {profile['account_masked']} / "
                 f"{profile['card_masked']}")
    lines.append(f"{report['period']['start']} → {report['period']['end']}")
    lines.append("")
    totals = report["totals"]
    lines.append("1) " + ("Tổng quan" if lang == "vi" else "Overview"))
    overview_keys = {
        "payin_cents": "cashflow.payin",
        "spend_cents": "cashflow.purchase",
        "fees_cents": "cashflow.fee",
        "payout_cents": "cashflow.payout",
        "transfer_to_card_cents": "cashflow.transfer_to_card",
        # Money off a card and back into the wallet. Not one of the brief's
        # five, but it is $500 in August alone and had no line of its own.
        "transfer_to_wallet_cents": "cashflow.transfer_to_wallet",
    }
    excluded = report.get("excluded", {})
    for key, catalog_key in overview_keys.items():
        lines.append(f"   - {t(lang, catalog_key)}: "
                     f"{fmt_display(totals[key], lang)}"
                     f"{bucket_scope_note(key, excluded, lang)}")
    comparison = report["comparison"]["spend"]
    if comparison["percent"] is not None:
        arrow = "+" if comparison["delta_cents"] > 0 else ""
        lines.append(f"   - vs {report['comparison']['period_key']}: "
                     f"{arrow}{fmt_display(comparison['delta_cents'], lang)} "
                     f"({arrow}{comparison['percent']}%)")
    # A $0.00 in the block above may mean "none" or may mean "none in USD".
    # The difference belongs in the email, not only in the API payload.
    caveats = excluded_lines(excluded, lang)
    if caveats:
        lines.append(f"   {t(lang, 'excluded.head')}:")
        lines += [f"     · {line}" for line in caveats]
    lines.append("")

    lines.append("2) " + ("3 khoản chi lớn nhất" if lang == "vi"
                          else "Top 3 purchases"))
    for row in report["top_purchases"]:
        label = row["merchant"] or row["descriptor"]
        lines.append(f"   - {row['date']} {label}: "
                     f"{fmt_display(row['amount_cents'], lang)} [{row['ref']}]")
    lines.append("")

    lines.append("3) " + ("Gói định kỳ & kỳ trừ kế tiếp" if lang == "vi"
                          else "Subscriptions & next charges"))
    for item in analysis.subs_forecast.get("upcoming", []):
        lines.append(f"   - {item['merchant']}: "
                     f"{fmt_display(item['amount_cents'], lang)} → {item['next_charge']}")
    lines.append(f"   ({'Dự kiến cả năm' if lang == 'vi' else 'Annual projection'}: "
                 f"{fmt_display(analysis.subs_forecast.get('annual_projection_cents', 0), lang)})")
    lines.append("")

    lines.append("4) " + ("Khoản cần bạn xem lại" if lang == "vi"
                          else "Items for you to review"))
    if not findings:
        lines.append("   - " + ("Không có khoản nào được gắn cờ trong kỳ này."
                                if lang == "vi"
                                else "No items were flagged for this period."))
    for item in findings:
        lines.append(f"   - [{item['label_text']}] {item['title']}")
        lines.append(f"     {item['detail']}")
        if item["dispute"]["text"]:
            lines.append(f"     {item['dispute']['text']}")
        srcs = ", ".join(f"{s['kind_text']}:{s['ref']}" for s in item["sources"])
        lines.append("     " + t(lang, "common.sources_line", sources=srcs))
        lines.append(f"     → {item['next_step']}")
    lines.append("")

    lines.append("-" * 72)
    lines.append(disclaimer(lang))

    return {
        "subject": heading,
        "body": scrub_text("\n".join(lines)),
        "period_key": report["period"]["key"],
        "period_label": report["period"]["label"],
        "counts": {
            "alerts": len(findings),
            "needs_your_confirmation": sum(
                1 for f in analysis.alerts
                if f.label is Label.NEEDS_YOUR_CONFIRMATION),
            "insufficient_data": sum(
                1 for f in analysis.alerts if f.label is Label.INSUFFICIENT_DATA),
        },
    }


def create_draft(lang: str = "vi", period_kind: str = "month",
                 period_key: str | None = None,
                 recipient: str | None = None) -> dict[str, Any]:
    """Prepare a report and park it. Nothing is sent by this call."""
    target = mail_recipient()
    content = build_report_body(lang, period_kind, period_key)
    token = secrets.token_urlsafe(24)
    draft_id = store.create_draft(
        recipient=target, subject=content["subject"], body=content["body"],
        period_key=content["period_key"], lang=lang, token=token,
        delivery="smtp",
    )
    store.log("report_draft_created", reason=f"draft {draft_id} for {target}",
              detail={"period": content["period_key"], "lang": lang,
                      "delivery": "smtp"})
    return {
        "draft_id": draft_id,
        "confirm_token": token,
        "recipient": target,
        "subject": content["subject"],
        "body": content["body"],
        "period_key": content["period_key"],
        "period_label": content["period_label"],
        "counts": content["counts"],
        "confirm_prompt": t(lang, "mail.confirm_prompt", owner_email=target),
        "requires_confirmation": True,
        "sent": False,
    }


def _smtp_sender() -> str:
    return (
        settings.smtp_from
        or settings.smtp_user
        or "nexa@localhost"
    )


def _require_smtp_config() -> None:
    if settings.mail_mode != "smtp":
        raise MailConfigError(
            "outbox delivery is disabled; set NEXA_MAIL_MODE=smtp"
        )
    mail_recipient()
    if not settings.smtp_host.strip():
        raise MailConfigError("missing SMTP host; set NEXA_SMTP_HOST")
    if settings.smtp_port <= 0:
        raise MailConfigError("invalid SMTP port; set NEXA_SMTP_PORT")
    if settings.smtp_user and not settings.smtp_password:
        raise MailConfigError("missing SMTP password; set NEXA_SMTP_PASSWORD")


def _build_message(recipient: str, subject: str, body: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = _smtp_sender()
    msg["To"] = recipient
    msg["Subject"] = subject
    msg["Date"] = format_datetime(datetime.now().astimezone())
    msg["Message-ID"] = make_msgid(domain="nexa.local")
    msg["X-Nexa-Delivery"] = "smtp"
    msg.set_content(body)
    return msg


def _send_smtp(recipient: str, subject: str, body: str) -> None:
    import smtplib

    _require_smtp_config()
    msg = _build_message(recipient, subject, body)
    smtp_class = smtplib.SMTP_SSL if settings.smtp_ssl else smtplib.SMTP
    try:
        with smtp_class(
            settings.smtp_host,
            settings.smtp_port,
            timeout=settings.smtp_timeout_seconds,
        ) as smtp:
            if settings.smtp_starttls and not settings.smtp_ssl:
                smtp.starttls()
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(msg)
    except (OSError, smtplib.SMTPException) as exc:
        raise MailDeliveryError(f"SMTP delivery failed: {exc}") from exc


def send_smtp_test(recipient: str | None = None, lang: str = "vi") -> dict[str, Any]:
    target = mail_recipient()
    _require_smtp_config()
    subject = "Nexa SMTP test"
    body = (
        "Nexa SMTP configuration test.\n\n"
        "If you received this email, the SMTP connection is working."
    )
    _send_smtp(target, subject, body)
    try:
        store.log(
            "smtp_test_sent",
            reason=f"SMTP test sent to {target}",
            detail={"host": settings.smtp_host, "port": settings.smtp_port},
        )
    except Exception:                                  # noqa: BLE001
        pass
    return {
        "recipient": target,
        "delivery": "smtp",
        "smtp_host": settings.smtp_host,
        "smtp_port": settings.smtp_port,
        "message": "SMTP test email sent",
        "sent": True,
    }


def send_confirmed(token: str, recipient: str | None = None,
                   lang: str = "vi") -> dict[str, Any]:
    """Send a specific confirmed draft to NEXA_MAIL_TO, one use only."""

    draft = store.draft_by_token(token)
    if draft is None:
        raise DraftError("unknown or expired confirmation token")
    if draft["status"] != "draft":
        raise DraftError(f"draft {draft['id']} was already {draft['status']}")

    target = mail_recipient()

    _require_smtp_config()
    _send_smtp(target, draft["subject"], draft["body"])
    delivery = "smtp"

    store.mark_draft_sent(draft["id"], None)
    store.log("report_sent", reason=f"draft {draft['id']} sent to {target}",
              detail={"delivery": delivery, "file": None})
    return {
        "draft_id": draft["id"],
        "recipient": target,
        "delivery": delivery,
        "file": None,
        "message": t(lang, "mail.sent", owner_email=target),
        "sent": True,
    }


def cancellation_guide(merchant: str, next_charge: str,
                       lang: str = "vi") -> dict[str, str]:
    """A draft for the *user* to act on. Nothing is sent anywhere."""
    return {
        "title": t(lang, "cancel_guide.title", merchant=merchant),
        "body": t(lang, "cancel_guide.body", merchant=merchant,
                  next_charge=next_charge),
        "sent": "false",
    }
