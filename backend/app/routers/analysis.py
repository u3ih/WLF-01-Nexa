"""Read-only analysis endpoints. Every response is masked at this boundary."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from ..config import settings
from ..engine import pipeline
from ..engine.mask import mask_card
from ..engine.models import fmt_display, fx_note
from ..engine.render import disclaimer, normalise_lang, t
from ..llm.tools import run_tool
from ..serialize import to_dollars

router = APIRouter(prefix="/api", tags=["analysis"])


@router.get("/summary")
def summary(lang: str = "vi") -> dict[str, Any]:
    lang = normalise_lang(lang)
    analysis = pipeline.cached()
    data = analysis.summary(lang, settings.today())
    data["disclaimer"] = disclaimer(lang)
    data["fx"] = {**fx_note(lang),
                  "note": t(lang, "fx.note",
                            rate=f"{settings.usd_vnd_rate:,.0f}")}
    return to_dollars(data, lang)


@router.get("/cashflow")
def cashflow(lang: str = "vi") -> dict[str, Any]:
    lang = normalise_lang(lang)
    return to_dollars(run_tool("get_cashflow", {}, lang), lang)


@router.get("/subscriptions")
def subscriptions(lang: str = "vi") -> dict[str, Any]:
    lang = normalise_lang(lang)
    return to_dollars(run_tool("list_subscriptions", {}, lang), lang)


@router.get("/findings")
def findings(lang: str = "vi", kind: str | None = None, label: str | None = None,
             alerts_only: bool = True) -> dict[str, Any]:
    lang = normalise_lang(lang)
    result = run_tool("get_findings",
                      {"kind": kind, "label": label, "alerts_only": alerts_only},
                      lang)
    return to_dollars(result, lang)


@router.get("/email-recon")
def email_recon(lang: str = "vi", ref: str | None = None,
                status: str | None = None,
                limit: int = Query(default=200, le=1000)) -> dict[str, Any]:
    lang = normalise_lang(lang)
    result = run_tool("get_email_recon",
                      {"ref": ref, "status": status, "limit": limit}, lang)
    return to_dollars(result, lang)


@router.get("/tri-source")
def tri_source(lang: str = "vi") -> dict[str, Any]:
    lang = normalise_lang(lang)
    return to_dollars(run_tool("get_tri_source", {}, lang), lang)


@router.get("/statement")
def statement(lang: str = "vi", source: str = "account",
              limit: int = Query(default=300, le=2000)) -> dict[str, Any]:
    """The statement itself, masked. `source` is 'account' or 'card'."""
    lang = normalise_lang(lang)
    analysis = pipeline.cached()
    if source == "card":
        rows = [
            {
                "ref": c.card_txn_id,
                "date": c.day.isoformat(),
                "time": c.when.isoformat(timespec="seconds"),
                "descriptor": c.merchant_raw,
                "merchant": c.merchant,
                "type": c.type.value,
                "type_label": t(lang, f"cashflow.{c.type.value}"),
                "amount_cents": c.amount_cents,
                "amount": fmt_display(c.amount_cents, lang),
                "card": mask_card(c.card_number),
                "mcc": c.mcc,
            }
            for c in analysis.ds.card
        ]
    else:
        rows = [
            {
                "ref": tx.txn_id,
                "date": tx.day.isoformat(),
                "time": tx.when.isoformat(timespec="seconds"),
                "descriptor": tx.description,
                "merchant": tx.merchant,
                "counterparty": tx.counterparty,
                "type": tx.type.value,
                "type_label": t(lang, f"cashflow.{tx.type.value}"),
                "amount_cents": tx.amount_cents,
                "amount": fmt_display(tx.amount_cents, lang),
                "balance_after": fmt_display(tx.balance_after_cents, lang),
            }
            for tx in analysis.ds.account
        ]
    rows.sort(key=lambda r: r["time"], reverse=True)
    return to_dollars({
        "source": source,
        "total": len(rows),
        "shown": min(len(rows), limit),
        "rows": rows[:limit],
        "account": analysis.account_profile(),
    }, lang)


@router.get("/search")
def search(lang: str = "vi", query: str | None = None,
           min_amount: float | None = None, date_from: str | None = None,
           date_to: str | None = None, flow_type: str | None = None,
           limit: int = Query(default=100, le=500)) -> dict[str, Any]:
    lang = normalise_lang(lang)
    return to_dollars(run_tool("search_transactions", {
        "query": query, "min_amount": min_amount, "date_from": date_from,
        "date_to": date_to, "flow_type": flow_type, "limit": limit,
    }, lang), lang)


@router.get("/explain")
def explain(lang: str = "vi", ref: str | None = None,
            amount: float | None = None,
            descriptor: str | None = None) -> dict[str, Any]:
    lang = normalise_lang(lang)
    result = run_tool("explain_charge",
                      {"ref": ref, "amount": amount, "descriptor": descriptor},
                      lang)
    return to_dollars(result, lang)
