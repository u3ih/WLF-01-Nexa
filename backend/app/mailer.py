"""Report drafting and self-notification.

Two hard rules live here, enforced in code rather than in a prompt:
  1. a report can only ever be addressed to the account owner's own address;
  2. nothing is sent until the user confirms a specific draft token.
Letters aimed at a merchant or the bank are produced as drafts only — this
module has no code path that sends them.
"""

from __future__ import annotations

import secrets
from datetime import date, datetime
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path
from typing import Any

from .config import settings
from .engine import pipeline, reports
from .engine.mask import scrub_text
from .engine.models import Label, fmt_display
from .engine.render import disclaimer, render_findings, t
from .store import store


class OwnerOnlyError(PermissionError):
    """Raised when anything tries to send to an address that is not the owner."""


class DraftError(ValueError):
    pass


def assert_owner(recipient: str) -> str:
    owner = (settings.owner_email or "").strip().lower()
    target = (recipient or "").strip().lower()
    if not owner:
        raise OwnerOnlyError("no owner address is configured")
    if target != owner:
        raise OwnerOnlyError(
            f"refused: reports may only be sent to the account owner "
            f"({owner}); requested {target or 'empty address'}"
        )
    return owner


def build_report_body(lang: str, period_kind: str = "month",
                      period_key: str | None = None,
                      today: date | None = None) -> dict[str, Any]:
    today = today or settings.today()
    analysis = pipeline.cached()
    report = reports.build(analysis.ds, period_kind, period_key,
                           analysis.subs_forecast)
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
    }
    for key, catalog_key in overview_keys.items():
        lines.append(f"   - {t(lang, catalog_key)}: {fmt_display(totals[key], lang)}")
    comparison = report["comparison"]["spend"]
    if comparison["percent"] is not None:
        arrow = "+" if comparison["delta_cents"] > 0 else ""
        lines.append(f"   - vs {report['comparison']['period_key']}: "
                     f"{arrow}{fmt_display(comparison['delta_cents'], lang)} "
                     f"({arrow}{comparison['percent']}%)")
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
    owner = assert_owner(recipient or settings.owner_email)
    content = build_report_body(lang, period_kind, period_key)
    token = secrets.token_urlsafe(24)
    draft_id = store.create_draft(
        recipient=owner, subject=content["subject"], body=content["body"],
        period_key=content["period_key"], lang=lang, token=token,
        delivery=settings.mail_mode,
    )
    store.log("report_draft_created", reason=f"draft {draft_id} for {owner}",
              detail={"period": content["period_key"], "lang": lang,
                      "delivery": settings.mail_mode})
    return {
        "draft_id": draft_id,
        "confirm_token": token,
        "recipient": owner,
        "subject": content["subject"],
        "body": content["body"],
        "period_key": content["period_key"],
        "period_label": content["period_label"],
        "counts": content["counts"],
        "confirm_prompt": t(lang, "mail.confirm_prompt", owner_email=owner),
        "requires_confirmation": True,
        "sent": False,
    }


def _write_outbox(recipient: str, subject: str, body: str,
                  when: date) -> Path:
    msg = EmailMessage()
    msg["From"] = "nexa@localhost"
    msg["To"] = recipient
    msg["Subject"] = subject
    msg["Date"] = format_datetime(datetime.now().astimezone())
    msg["X-Nexa-Delivery"] = "outbox"
    msg.set_content(body)
    settings.outbox_dir.mkdir(parents=True, exist_ok=True)
    path = settings.outbox_dir / f"{when.isoformat()}-{secrets.token_hex(4)}.eml"
    path.write_bytes(msg.as_bytes())
    return path


def _send_smtp(recipient: str, subject: str, body: str) -> None:
    import smtplib

    msg = EmailMessage()
    msg["From"] = settings.smtp_user or "nexa@localhost"
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
        smtp.starttls()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(msg)


def send_confirmed(token: str, recipient: str | None = None,
                   lang: str = "vi") -> dict[str, Any]:
    """Send a specific confirmed draft — owner address only, one use only.

    The recipient is checked FIRST, before the token is even looked up, so a
    request aimed at a third party is always refused as such and never leaks
    whether the token happened to be valid.
    """
    if recipient is not None:
        assert_owner(recipient)

    draft = store.draft_by_token(token)
    if draft is None:
        raise DraftError("unknown or expired confirmation token")
    if draft["status"] != "draft":
        raise DraftError(f"draft {draft['id']} was already {draft['status']}")

    owner = assert_owner(recipient or draft["recipient"])
    if draft["recipient"].strip().lower() != owner:
        raise OwnerOnlyError("the stored draft is addressed elsewhere")

    path: Path | None = None
    if settings.mail_mode == "smtp" and settings.smtp_host:
        _send_smtp(owner, draft["subject"], draft["body"])
        delivery = "smtp"
    else:
        path = _write_outbox(owner, draft["subject"], draft["body"],
                             settings.today())
        delivery = "outbox"

    store.mark_draft_sent(draft["id"], str(path) if path else None)
    store.log("report_sent", reason=f"draft {draft['id']} sent to {owner}",
              detail={"delivery": delivery, "file": str(path) if path else None})
    return {
        "draft_id": draft["id"],
        "recipient": owner,
        "delivery": delivery,
        "file": str(path) if path else None,
        "message": t(lang, "mail.sent", owner_email=owner),
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
