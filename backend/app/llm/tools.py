"""The assistant's entire capability surface.

Every tool here is read-only. There is deliberately no tool that cancels a
plan, opens a dispute, moves money or locks a card, so no prompt, however
phrased, can reach one.

The one tool that can cause an outward action (`draft_report_email`) only
creates a draft and returns a confirmation token; sending is a separate,
user-confirmed endpoint.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Callable

from ..config import settings
from ..engine import pipeline, reports
from ..engine.dedupe import audit_to_json
from ..engine.mask import mask_card, scrub_text
from ..engine.models import CardTxnType, EmailMatchStatus, TxnType, fmt_display
from ..engine.merchants import processor_hint, resolve
from ..engine.render import reasons_text, render_finding, render_findings, t
from ..mailer import cancellation_guide, create_draft
from ..monitor import reminder_list, run_scan
from ..store import store

MAX_ROWS = 40


def _today() -> date:
    return settings.today()


def _trim_finding(item: dict[str, Any]) -> dict[str, Any]:
    """Drop the raw params before handing a finding to the model."""
    return {k: v for k, v in item.items() if k != "params"}


# ------------------------------------------------------------------- tools

def get_overview(lang: str = "vi") -> dict[str, Any]:
    """High-level state: counts, label tallies, cash-flow totals, wallet gap."""
    analysis = pipeline.cached()
    summary = analysis.summary(lang, _today())
    return {
        "statement_date": summary["statement_date"],
        "account": summary["account"],
        "counts": summary["counts"],
        "labels": summary["labels"],
        "cashflow_totals": summary["cashflow"],
        "wallet": summary["wallet"],
        "email_recon": summary["email_recon"],
        "sources": summary["sources"],
        "alerts_preview": [
            {"label": f["label_text"], "title": f["title"],
             "amount": f["amount"], "deadline": f["dispute"]["dispute_deadline"]}
            for f in render_findings(analysis.alerts, lang, _today())[:5]
        ],
    }


def get_cashflow(lang: str = "vi") -> dict[str, Any]:
    """Money in / out / to-card / fees / spending, plus category split."""
    analysis = pipeline.cached()
    cashflow = analysis.cashflow
    return {
        "period": cashflow["period"],
        "account": {
            key: {**value, "label": t(lang, f"cashflow.{key}")}
            for key, value in cashflow["account"].items()
        },
        "card": {
            key: {**value, "label": t(lang, f"cashflow.{key}")}
            for key, value in cashflow["card"].items()
        },
        "totals": cashflow["totals"],
        "categories": [
            {**row, "label": t(lang, f"category.{row['category']}")}
            for row in cashflow["categories"]
        ],
        "sources": cashflow["sources"],
    }


def list_subscriptions(lang: str = "vi") -> dict[str, Any]:
    """Recurring plans, next charge dates, annual cost and price changes."""
    analysis = pipeline.cached()
    return {
        "subscriptions": [s.as_dict() for s in analysis.subs],
        "forecast": analysis.subs_forecast,
        "price_increases": [
            _trim_finding(render_finding(f, lang, _today()))
            for f in analysis.findings if f.kind.value == "price_increase"
        ],
    }


def get_findings(lang: str = "vi", kind: str | None = None,
                 label: str | None = None, alerts_only: bool = True
                 ) -> dict[str, Any]:
    """Flagged items with their three-tier label, sources and 60-day deadline."""
    analysis = pipeline.cached()
    pool = analysis.alerts if alerts_only else analysis.findings
    if kind:
        wanted = {k.strip() for k in str(kind).split(",") if k.strip()}
        pool = [f for f in pool if f.kind.value in wanted]
    if label:
        pool = [f for f in pool if f.label.value == label]
    return {
        "count": len(pool),
        "labels": {
            "recurring_confirmed": t(lang, "labels.recurring_confirmed"),
            "needs_your_confirmation": t(lang, "labels.needs_your_confirmation"),
            "insufficient_data": t(lang, "labels.insufficient_data"),
        },
        "findings": [_trim_finding(f)
                     for f in render_findings(pool, lang, _today())],
    }


def get_email_recon(lang: str = "vi", ref: str | None = None,
                    status: str | None = None, limit: int = MAX_ROWS
                    ) -> dict[str, Any]:
    """Transaction <-> email table (matched / no_email_found /
    email_suspicious) plus every look-alike sender found in the mailbox.

    The suspicious senders are returned in full, never only counted: an
    impersonation email that matches no transaction has no row in the table,
    so a count on its own would leave the one thing the user asked about
    unanswerable.
    """
    analysis = pipeline.cached()
    rows = analysis.recon.rows
    if ref:
        rows = [r for r in rows if r.ref == ref]
    if status:
        rows = [r for r in rows if r.status.value == status]
    # A matched, clean row raises no question. When the table is longer than
    # what is handed over, the unexplained rows go first, so truncation cannot
    # hide the very rows the question is about.
    ordered = sorted(rows, key=lambda r: (r.status is EmailMatchStatus.MATCHED,
                                          r.when, r.ref))
    shown = ordered[:limit]
    suspicious = analysis.recon.suspicious
    if ref:
        suspicious = [s for s in suspicious if s.matched_txn_ref == ref]
    return {
        "total_rows": len(analysis.recon.rows),
        "shown": len(shown),
        "truncated": len(rows) > len(shown),
        "summary": {
            "matched": analysis.recon.matched_count,
            "no_email_found": analysis.recon.missing_count,
            "suspicious_emails": len(analysis.recon.suspicious),
        },
        "rows": [
            {
                "ref": r.ref,
                "source": r.source.value,
                "date": r.when.isoformat(),
                "descriptor": r.descriptor,
                "merchant": r.merchant,
                "amount": fmt_display(r.amount_cents, lang),
                "status": r.status.value,
                "status_text": t(lang, f"email_status.{r.status.value}"),
                "email_from": r.email_from,
                "email_subject": r.email_subject,
                "message_id": r.message_id,
                "match_score": r.score,
            }
            for r in shown
        ],
        "suspicious": [
            {
                "message_id": s.message_id,
                "date": s.when.isoformat(),
                "from_name": s.from_name,
                "from_addr": s.from_addr,
                "reply_to": s.reply_to,
                "subject": scrub_text(s.subject),
                "claimed_brand": s.claimed_brand,
                "amounts": [fmt_display(a, lang) for a in s.amounts_cents],
                "reasons": s.reasons,
                "reasons_text": reasons_text(lang, s.reasons, s.claimed_brand),
                "matched_txn_ref": s.matched_txn_ref,
            }
            for s in suspicious
        ],
    }


def get_tri_source(lang: str = "vi") -> dict[str, Any]:
    """Account vs wallet vs card: unmatched transfers, duplicate payins, gaps."""
    analysis = pipeline.cached()
    data = analysis.tri.as_dict()
    kinds = {"transfer_not_on_card", "duplicate_payin", "wallet_balance_mismatch"}
    data["findings"] = [
        _trim_finding(render_finding(f, lang, _today()))
        for f in analysis.findings if f.kind.value in kinds
    ]
    data["transfer_summary"] = {
        "total": len(data["transfers"]),
        "matched": sum(1 for r in data["transfers"] if r["status"] == "matched"),
        "not_on_card": sum(1 for r in data["transfers"]
                           if r["status"] != "matched"),
    }
    return data


def get_report(lang: str = "vi", period: str = "month",
               key: str | None = None) -> dict[str, Any]:
    """Spending report for a month / quarter / year with period comparison."""
    analysis = pipeline.cached()
    if period not in reports.PERIODS:
        period = "month"
    report = reports.build(analysis.ds, period, key, analysis.subs_forecast)
    report["categories"] = [
        {**row, "label": t(lang, f"category.{row['category']}")}
        for row in report["categories"]
    ]
    report["trend"] = reports.monthly_series(analysis.ds, 12)
    return report


def explain_charge(lang: str = "vi", ref: str | None = None,
                   amount: float | None = None,
                   descriptor: str | None = None) -> dict[str, Any]:
    """Explain one charge: what the descriptor means, which email backs it,
    and any finding attached to it."""
    analysis = pipeline.cached()
    target_cents = int(round(amount * 100)) if amount is not None else None
    candidates: list[dict[str, Any]] = []

    for txn in analysis.ds.account:
        candidates.append({
            "ref": txn.txn_id, "source": "statement", "when": txn.when,
            "descriptor": txn.description, "amount_cents": txn.amount_cents,
            "type": txn.type.value, "merchant": txn.merchant,
        })
    for card in analysis.ds.card:
        candidates.append({
            "ref": card.card_txn_id, "source": "card", "when": card.when,
            "descriptor": card.merchant_raw, "amount_cents": card.amount_cents,
            "type": card.type.value, "merchant": card.merchant,
            "card": mask_card(card.card_number),
        })

    def matches(row: dict[str, Any]) -> bool:
        if ref and row["ref"].upper() == ref.upper():
            return True
        if target_cents is not None and abs(row["amount_cents"]) == abs(target_cents):
            if not descriptor:
                return True
            return descriptor.upper() in row["descriptor"].upper()
        if descriptor and not ref and target_cents is None:
            return descriptor.upper() in row["descriptor"].upper()
        return False

    hits = [r for r in candidates if matches(r)]
    if not hits:
        return {
            "found": False,
            "query": {"ref": ref, "amount": amount, "descriptor": descriptor},
            "note": t(lang, "common.unknown"),
        }

    recon = analysis.recon.by_ref
    out = []
    for row in sorted(hits, key=lambda r: r["when"], reverse=True)[:5]:
        merchant = resolve(row["descriptor"])
        match = recon.get(row["ref"])
        related = [
            _trim_finding(render_finding(f, lang, _today()))
            for f in analysis.findings if row["ref"] in f.txn_ids
        ]
        out.append({
            "ref": row["ref"],
            "source": row["source"],
            "date": row["when"].date().isoformat(),
            "time": row["when"].isoformat(timespec="seconds"),
            "descriptor": row["descriptor"],
            "amount": fmt_display(row["amount_cents"], lang),
            "flow_type": row["type"],
            "flow_label": t(lang, f"cashflow.{row['type']}"),
            "merchant": merchant.name if merchant else None,
            "merchant_explained": (t(lang, merchant.note_key)
                                   if merchant and merchant.note_key else None),
            "merchant_status": "resolved" if merchant else t(lang, "common.unknown"),
            "processor_hint": processor_hint(row["descriptor"]),
            "card": row.get("card"),
            "email": {
                "status": match.status.value if match else None,
                "status_text": (t(lang, f"email_status.{match.status.value}")
                                if match else None),
                "from": match.email_from if match else None,
                "subject": match.email_subject if match else None,
                "message_id": match.message_id if match else None,
            },
            "findings": related,
        })
    return {"found": True, "matches": out}


def search_transactions(lang: str = "vi", query: str | None = None,
                        min_amount: float | None = None,
                        date_from: str | None = None,
                        date_to: str | None = None,
                        flow_type: str | None = None,
                        limit: int = MAX_ROWS) -> dict[str, Any]:
    """Filter the statements. Read-only listing, newest first."""
    analysis = pipeline.cached()
    rows: list[dict[str, Any]] = []
    for txn in analysis.ds.account:
        rows.append({"ref": txn.txn_id, "source": "statement", "when": txn.when,
                     "descriptor": txn.description, "merchant": txn.merchant,
                     "amount_cents": txn.amount_cents, "type": txn.type.value})
    for card in analysis.ds.card:
        rows.append({"ref": card.card_txn_id, "source": "card", "when": card.when,
                     "descriptor": card.merchant_raw, "merchant": card.merchant,
                     "amount_cents": card.amount_cents, "type": card.type.value})

    def keep(row: dict[str, Any]) -> bool:
        if query:
            needle = query.upper()
            haystack = f"{row['descriptor']} {row['merchant'] or ''}".upper()
            if needle not in haystack:
                return False
        if min_amount is not None and abs(row["amount_cents"]) < min_amount * 100:
            return False
        if date_from and row["when"].date() < date.fromisoformat(date_from):
            return False
        if date_to and row["when"].date() > date.fromisoformat(date_to):
            return False
        if flow_type and row["type"] != flow_type:
            return False
        return True

    hits = [r for r in rows if keep(r)]
    hits.sort(key=lambda r: r["when"], reverse=True)
    return {
        "matched": len(hits),
        "shown": min(len(hits), limit),
        "total_spend_of_matches": fmt_display(
            sum(-r["amount_cents"] for r in hits if r["amount_cents"] < 0)
        , lang),
        "rows": [
            {
                "ref": r["ref"], "source": r["source"],
                "date": r["when"].date().isoformat(),
                "descriptor": r["descriptor"], "merchant": r["merchant"],
                "amount": fmt_display(r["amount_cents"], lang),
                "flow_label": t(lang, f"cashflow.{r['type']}"),
            }
            for r in hits[:limit]
        ],
    }


def get_reminders(lang: str = "vi") -> dict[str, Any]:
    """Open dispute-deadline reminders."""
    items = reminder_list(lang, _today())
    return {"count": len(items), "reminders": items}


def run_monitor_scan(lang: str = "vi") -> dict[str, Any]:
    """Re-scan and report only findings that were not reported before."""
    result = run_scan("chat", lang, _today())
    return {
        "scan_id": result["scan_id"],
        "new_count": result["new_count"],
        "suppressed_count": result["suppressed_count"],
        "reminders_created": result["reminders_created"],
        "new": [_trim_finding(f) for f in result["new"]],
    }


def draft_report_email(lang: str = "vi", period: str = "month",
                       key: str | None = None) -> dict[str, Any]:
    """Prepare a report addressed to the configured mail recipient. Sends nothing."""
    draft = create_draft(lang=lang, period_kind=period, period_key=key)
    return {
        "draft_id": draft["draft_id"],
        "confirm_token": draft["confirm_token"],
        "recipient": draft["recipient"],
        "subject": draft["subject"],
        "body_preview": draft["body"][:1200],
        "body_length": len(draft["body"]),
        "confirm_prompt": draft["confirm_prompt"],
        "sent": False,
        "note": "Nothing has been sent. The user must confirm this draft first.",
    }


def get_cancellation_guide(lang: str = "vi", merchant: str | None = None
                           ) -> dict[str, Any]:
    """Steps for the user to cancel a plan themselves. Performs no action."""
    analysis = pipeline.cached()
    subs = analysis.subs
    chosen = None
    if merchant:
        needle = merchant.upper()
        chosen = next(
            (s for s in subs
             if (s.merchant_name or "").upper().startswith(needle)
             or needle in s.descriptor.upper()),
            None,
        )
    if chosen is None and len(subs) == 1:
        chosen = subs[0]
    if chosen is None:
        return {
            "found": False,
            "available": [s.merchant_name or s.descriptor for s in subs],
        }
    guide = cancellation_guide(chosen.merchant_name or chosen.descriptor,
                               chosen.next_charge.isoformat(), lang)
    return {
        "found": True,
        "merchant": chosen.merchant_name or chosen.descriptor,
        "next_charge": chosen.next_charge.isoformat(),
        "amount": fmt_display(chosen.current_amount_cents, lang),
        "guide": guide,
        "performed_by_assistant": False,
    }


def get_audit_log(lang: str = "vi", limit: int = 20) -> dict[str, Any]:
    """The flag journal: what was flagged, why, and with what confidence."""
    rows = store.audit_entries(limit)
    return {
        "count": len(rows),
        "entries": [
            {
                "id": r["id"],
                "logged_at": r["logged_at"].isoformat()
                if isinstance(r["logged_at"], datetime) else str(r["logged_at"]),
                "event": r["event"],
                "kind": r["kind"],
                "label": r["label"],
                "confidence": float(r["confidence"]) if r["confidence"] else None,
                "reason": r["reason"],
            }
            for r in rows
        ],
    }


# --------------------------------------------------------------- registry

TOOLS: dict[str, Callable[..., dict[str, Any]]] = {
    "get_overview": get_overview,
    "get_cashflow": get_cashflow,
    "list_subscriptions": list_subscriptions,
    "get_findings": get_findings,
    "get_email_recon": get_email_recon,
    "get_tri_source": get_tri_source,
    "get_report": get_report,
    "explain_charge": explain_charge,
    "search_transactions": search_transactions,
    "get_reminders": get_reminders,
    "run_monitor_scan": run_monitor_scan,
    "draft_report_email": draft_report_email,
    "get_cancellation_guide": get_cancellation_guide,
    "get_audit_log": get_audit_log,
}

# JSON-schema style descriptions, used both for native tool calling and for the
# JSON-router prompt.
SPECS: list[dict[str, Any]] = [
    {
        "name": "get_overview",
        "description": "Overall state: transaction counts, how many items carry "
                       "each of the three labels, cash-flow totals, wallet gap.",
        "parameters": {},
    },
    {
        "name": "get_cashflow",
        "description": "Cash-flow classification: money in, money out, transfers "
                       "to card, fees, spending, and spending by category.",
        "parameters": {},
    },
    {
        "name": "list_subscriptions",
        "description": "Recurring subscriptions with next charge date, annual "
                       "cost and any price increase.",
        "parameters": {},
    },
    {
        "name": "get_findings",
        "description": "Flagged items with label, sources and dispute deadline.",
        "parameters": {
            "kind": "optional finding kind, or several separated by commas, "
                    "e.g. duplicate_charge, double_fee, "
                    "forgotten_subscription, missing_email, unknown_merchant, "
                    "suspicious_email, transfer_not_on_card, duplicate_payin, "
                    "wallet_balance_mismatch, price_increase",
            "label": "optional label filter: needs_your_confirmation, "
                     "insufficient_data, recurring_confirmed",
        },
    },
    {
        "name": "get_email_recon",
        "description": "Transaction-to-email table, plus the full list of "
                       "emails whose sender impersonates a brand (phishing "
                       "look-alikes) with the reasons for each. Use when the "
                       "user asks whether a charge has a matching receipt or "
                       "email, or asks about suspicious / fake / phishing "
                       "emails.",
        "parameters": {
            "ref": "optional transaction reference",
            "status": "optional: matched, no_email_found, email_suspicious",
        },
    },
    {
        "name": "get_tri_source",
        "description": "Compare account, wallet and card. Use for questions "
                       "about money that left the account but is not on the "
                       "card, duplicate deposits, or a wallet balance gap.",
        "parameters": {},
    },
    {
        "name": "get_report",
        "description": "Spending report for a period with comparison to the "
                       "previous one.",
        "parameters": {
            "period": "month, quarter or year",
            "key": "optional period key such as 2026-07, 2026-Q3 or 2026",
        },
    },
    {
        "name": "explain_charge",
        "description": "Explain one charge: descriptor meaning, matching email, "
                       "attached findings. Use when the user asks what a "
                       "specific amount or merchant name is.",
        "parameters": {
            "ref": "optional transaction reference",
            "amount": "optional amount as a number, e.g. 9.99",
            "descriptor": "optional merchant text",
        },
    },
    {
        "name": "search_transactions",
        "description": "Filter transactions by text, minimum amount, date range "
                       "or flow type.",
        "parameters": {
            "query": "optional text to search in the descriptor",
            "min_amount": "optional minimum amount as a number",
            "date_from": "optional ISO date",
            "date_to": "optional ISO date",
            "flow_type": "optional: payin, payout, transfer_to_card, fee, "
                         "purchase, load",
        },
    },
    {
        "name": "get_reminders",
        "description": "Open dispute-deadline reminders.",
        "parameters": {},
    },
    {
        "name": "run_monitor_scan",
        "description": "Re-scan and return only items not reported before.",
        "parameters": {},
    },
    {
        "name": "draft_report_email",
        "description": "Prepare a report email addressed to the configured "
                       "mail recipient and return it for confirmation. It "
                       "does NOT send.",
        "parameters": {
            "period": "month, quarter or year",
            "key": "optional period key",
        },
    },
    {
        "name": "get_cancellation_guide",
        "description": "Steps the user can follow to cancel a subscription "
                       "themselves. Performs no action.",
        "parameters": {"merchant": "subscription name, e.g. Chegg"},
    },
    {
        "name": "get_audit_log",
        "description": "The flag journal: what was flagged, why, confidence.",
        "parameters": {"limit": "optional row count"},
    },
]

ALLOWED_ARGS = {
    "get_findings": {"kind", "label", "alerts_only"},
    "get_email_recon": {"ref", "status", "limit"},
    "get_report": {"period", "key"},
    "explain_charge": {"ref", "amount", "descriptor"},
    "search_transactions": {"query", "min_amount", "date_from", "date_to",
                            "flow_type", "limit"},
    "draft_report_email": {"period", "key"},
    "get_cancellation_guide": {"merchant"},
    "get_audit_log": {"limit"},
}


def run_tool(name: str, args: dict[str, Any] | None = None,
             lang: str = "vi") -> dict[str, Any]:
    """Execute a registered read-only tool with only its declared arguments."""
    if name not in TOOLS:
        return {"error": f"unknown tool: {name}"}
    allowed = ALLOWED_ARGS.get(name, set())
    clean = {k: v for k, v in (args or {}).items() if k in allowed
             and v not in (None, "")}
    try:
        result = TOOLS[name](lang=lang, **clean)
    except TypeError as exc:
        return {"error": f"bad arguments for {name}: {exc}"}
    except Exception as exc:                            # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}
    return result


def audit_export(limit: int = 5000) -> str:
    return audit_to_json(store.audit_entries(limit))
