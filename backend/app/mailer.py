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
from html import escape
from html.parser import HTMLParser
from typing import Any

from .config import settings
from .engine import pipeline, reports
from .engine.mask import scrub_text
from .engine.models import Label, fmt_display
from .engine.render import (
    bucket_note,
    conversion_lines,
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
    totals = report["totals"]
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
    comparison = report["comparison"]["spend"]
    # The figures below are a sum across currencies wherever a rate covered the
    # rows. What went into them, and at whose rate, has to be checkable from the
    # email itself — otherwise the reader is asked to trust a restated total.
    restated = conversion_lines(totals, lang)
    # A $0.00 in the overview may still mean "none the rates could reach".
    # The difference belongs in the email, not only in the API payload.
    caveats = excluded_lines(excluded, lang)

    # Keep the draft deliberately brief. The full evidence remains available
    # in the app; an email is a scan-friendly summary, not a second dashboard.
    shown_findings = findings[:3]
    upcoming = analysis.subs_forecast.get("upcoming", [])[:3]
    copy = {
        "overview": "Tổng quan" if lang == "vi" else "Overview",
        "top": "3 khoản chi lớn nhất" if lang == "vi" else "Top 3 purchases",
        "review": "Cần xem lại" if lang == "vi" else "Needs review",
        "upcoming": "Sắp tới" if lang == "vi" else "Upcoming",
        "none": "Không có cảnh báo." if lang == "vi" else "No alerts.",
        "more": "cảnh báo khác trong ứng dụng" if lang == "vi"
                else "more alert(s) in the app",
    }

    # A compact plain-text version is retained for chat previews and as the
    # MIME fallback used by mail clients that do not render HTML.
    lines = [heading,
             f"{profile['owner_name']} — {profile['account_masked']} / "
             f"{profile['card_masked']}",
             f"{report['period']['start']} → {report['period']['end']}", "",
             copy["overview"]]
    for key, catalog_key in overview_keys.items():
        lines.append(f"• {t(lang, catalog_key)}: {fmt_display(totals[key], lang)}"
                     f"{bucket_note(key, report, lang)}")
    if comparison["percent"] is not None:
        sign = "+" if comparison["delta_cents"] > 0 else ""
        lines.append(f"• vs {report['comparison']['period_key']}: "
                     f"{sign}{fmt_display(comparison['delta_cents'], lang)} "
                     f"({sign}{comparison['percent']}%)")
    if restated:
        lines.append(f"  {t(lang, 'fx.head')}:")
        lines += [f"   · {line}" for line in restated]
    lines += ["", copy["top"]]
    for row in report["top_purchases"]:
        label = row["merchant"] or row["descriptor"]
        lines.append(f"• {label}: {fmt_display(row['amount_cents'], lang)} "
                     f"[{row['ref']}]")
    lines += ["", copy["review"]]
    if not shown_findings:
        lines.append(f"• {copy['none']}")
    for item in shown_findings:
        lines.append(f"• {item['title']} — {item['next_step']}")
        if item["dispute"]["text"]:
            lines.append(f"  {item['dispute']['text']}")
    if len(findings) > len(shown_findings):
        lines.append(f"• +{len(findings) - len(shown_findings)} {copy['more']}")
    if upcoming:
        lines += ["", copy["upcoming"]]
        for item in upcoming:
            lines.append(f"• {item['merchant']}: "
                         f"{fmt_display(item['amount_cents'], lang)} — "
                         f"{item['next_charge']}")
    if caveats:
        lines += ["", t(lang, "excluded.head")]
        lines += [f"• {line}" for line in caveats]
    lines += ["", disclaimer(lang)]
    body_text = scrub_text("\n".join(lines))

    def h(value: Any) -> str:
        return escape(scrub_text(str(value)), quote=True)

    metric_rows = "".join(
        "<tr><th>" + h(t(lang, catalog_key)) + "</th><td>" +
        h(fmt_display(totals[key], lang) +
          bucket_note(key, report, lang)) + "</td></tr>"
        for key, catalog_key in overview_keys.items()
    )
    comparison_html = ""
    if comparison["percent"] is not None:
        sign = "+" if comparison["delta_cents"] > 0 else ""
        comparison_html = (
            "<p class=\"comparison\">vs " +
            h(report["comparison"]["period_key"]) + ": <strong>" +
            h(f"{sign}{fmt_display(comparison['delta_cents'], lang)} "
              f"({sign}{comparison['percent']}%)") + "</strong></p>"
        )
    top_html = "".join(
        "<li><span>" + h(row["merchant"] or row["descriptor"]) +
        " <small>[" + h(row["ref"]) + "]</small></span><strong>" +
        h(fmt_display(row["amount_cents"], lang)) + "</strong></li>"
        for row in report["top_purchases"]
    ) or "<li>—</li>"
    finding_html = "".join(
        "<li><strong>" + h(item["title"]) + "</strong><br><span>" +
        h(item["next_step"]) +
        (("<br><em>" + h(item["dispute"]["text"]) + "</em>")
         if item["dispute"]["text"] else "") + "</span></li>"
        for item in shown_findings
    ) or "<li>" + h(copy["none"]) + "</li>"
    if len(findings) > len(shown_findings):
        finding_html += ("<li class=\"muted\">+" +
                         str(len(findings) - len(shown_findings)) + " " +
                         h(copy["more"]) + "</li>")
    upcoming_html = ""
    if upcoming:
        rows = "".join(
            "<li><span>" + h(item["merchant"]) + "</span><span>" +
            h(fmt_display(item["amount_cents"], lang)) + " · " +
            h(item["next_charge"]) + "</span></li>" for item in upcoming
        )
        upcoming_html = ("<section><h2>" + h(copy["upcoming"]) +
                         "</h2><ul class=\"split\">" + rows +
                         "</ul></section>")
    caveat_html = ""
    if caveats:
        caveat_html = ("<aside><strong>" + h(t(lang, "excluded.head")) +
                       "</strong><ul>" +
                       "".join("<li>" + h(line) + "</li>" for line in caveats) +
                       "</ul></aside>")
    fx_html = ""
    if restated:
        fx_html = ("<aside><strong>" + h(t(lang, "fx.head")) +
                   "</strong><ul>" +
                   "".join("<li>" + h(line) + "</li>" for line in restated) +
                   "</ul></aside>")

    body_html = f"""<!doctype html>
<html lang="{h(lang)}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<style>
body{{margin:0;background:#f5f6f8;color:#20242c;font:14px/1.5 Arial,sans-serif}}main{{max-width:680px;margin:0 auto;background:#fff;padding:28px}}h1{{font-size:20px;margin:0 0 4px}}h2{{font-size:15px;margin:22px 0 9px}}p{{margin:4px 0}}.meta,.muted,small{{color:#687080}}table{{width:100%;border-collapse:collapse}}th,td{{padding:7px 0;border-bottom:1px solid #e8eaf0}}th{{text-align:left;font-weight:500}}td{{text-align:right;font-weight:700}}ul{{margin:0;padding-left:20px}}li{{margin:7px 0}}ul.split{{list-style:none;padding:0}}ul.split li{{display:flex;justify-content:space-between;gap:16px}}.comparison{{margin-top:8px}}aside{{margin-top:20px;padding:12px;background:#f6f7f9;border-radius:8px;font-size:12px}}footer{{margin-top:22px;padding-top:14px;border-top:1px solid #e8eaf0;color:#687080;font-size:11px}}
</style></head><body><main>
<header><h1>{h(heading)}</h1><p class="meta">{h(profile['owner_name'])} · {h(profile['account_masked'])} / {h(profile['card_masked'])}</p><p class="meta">{h(report['period']['start'])} → {h(report['period']['end'])}</p></header>
<section><h2>{h(copy['overview'])}</h2><table>{metric_rows}</table>{comparison_html}</section>
<section><h2>{h(copy['top'])}</h2><ul class="split">{top_html}</ul></section>
<section><h2>{h(copy['review'])}</h2><ul>{finding_html}</ul></section>
{upcoming_html}{fx_html}{caveat_html}<footer>{h(disclaimer(lang))}</footer>
</main></body></html>"""

    return {
        "subject": heading,
        # Keep the legacy body key textual; the explicit HTML key avoids
        # surprising callers that use the draft as a chat preview.
        "body": body_text,
        "body_html": body_html,
        "body_text": body_text,
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
        recipient=target, subject=content["subject"], body=content["body_html"],
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
        "body": content["body_text"],
        "body_text": content["body_text"],
        "body_html": content["body_html"],
        "content_type": "text/html",
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


class _PlainTextParser(HTMLParser):
    """Small dependency-free HTML fallback for multipart report email."""

    _BLOCKS = {"br", "p", "div", "section", "header", "footer", "aside",
               "tr", "li", "h1", "h2", "h3"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.ignored_depth = 0

    def handle_starttag(self, tag: str,
                        attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"style", "script"}:
            self.ignored_depth += 1
            return
        if self.ignored_depth:
            return
        if tag == "li":
            self.parts.append("\n• ")
        elif tag in self._BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"style", "script"} and self.ignored_depth:
            self.ignored_depth -= 1
            return
        if self.ignored_depth:
            return
        if tag == "th":
            self.parts.append(": ")
        elif tag == "span":
            self.parts.append(" ")
        elif tag in self._BLOCKS or tag == "td":
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.ignored_depth:
            self.parts.append(data)


def _html_to_text(body: str) -> str:
    parser = _PlainTextParser()
    parser.feed(body)
    lines = (" ".join(line.split()) for line in "".join(parser.parts).splitlines())
    return "\n".join(line for line in lines if line).strip()


def _build_message(recipient: str, subject: str, body: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = _smtp_sender()
    msg["To"] = recipient
    msg["Subject"] = subject
    msg["Date"] = format_datetime(datetime.now().astimezone())
    msg["Message-ID"] = make_msgid(domain="nexa.local")
    msg["X-Nexa-Delivery"] = "smtp"
    if body.lstrip().lower().startswith(("<!doctype html", "<html")):
        msg.set_content(_html_to_text(body))
        msg.add_alternative(body, subtype="html")
    else:
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
