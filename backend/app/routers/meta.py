"""Health, capability and translation endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from .. import fx
from ..config import settings
from ..engine import pipeline
from ..engine.render import catalog, disclaimer, normalise_lang
from ..llm.client import client
from ..store import store

router = APIRouter(prefix="/api", tags=["meta"])


def display_basis() -> dict[str, Any]:
    """Where the ₫ figures beside USD amounts get their rate."""
    from ..engine.models import vnd_basis

    rate, source, quoted_on = vnd_basis()
    return {
        "pair": "/".join(fx.DISPLAY_PAIR),
        "enabled": settings.show_vnd,
        "rate": rate,
        "source": source,
        "quoted_on": quoted_on,
        "published": quoted_on is not None,
        "configured_fallback": settings.usd_vnd_rate,
    }


@router.get("/fx")
def fx_status() -> dict[str, Any]:
    """What rates are held, and which pairs this dataset needs.

    A conversion the user sees has to be auditable: this says where the numbers
    came from, when they were published and which days are still uncovered.
    """
    analysis = pipeline.cached()
    needed = [f"{base}/{quote}"
              for base, quote in fx.pairs_needed(analysis.ds.currencies)]
    try:
        coverage = [
            {**row,
             "first_quoted_on": row["first_quoted_on"].isoformat(),
             "last_quoted_on": row["last_quoted_on"].isoformat(),
             "fetched_at": row["fetched_at"].isoformat()}
            for row in store.fx_coverage()
        ]
        available = True
        detail = ""
    except Exception as exc:                                # noqa: BLE001
        coverage, available, detail = [], False, str(exc)
    held = {f"{row['base']}/{row['quote']}" for row in coverage}
    return {
        "enabled": settings.fx_enabled,
        "source": fx.SOURCE,
        "pairs_needed": needed,
        # Named rather than merely absent from `coverage`: a pair the data needs
        # and the store lacks is the reason a report shows amounts unconverted.
        "pairs_missing": [pair for pair in needed if pair not in held],
        "database_available": available,
        "detail": detail,
        "loaded_quotes": len(analysis.fx),
        "latest_quoted_on": (analysis.fx.latest_quoted_on.isoformat()
                             if analysis.fx.latest_quoted_on else None),
        "coverage": coverage,
        "scheduled_at": f"{settings.fx_hour:02d}:{settings.fx_minute:02d}",
        # The ₫ conversion shown beside USD amounts. Reported separately from
        # the pairs above because it comes from a different publication and,
        # unlike them, has a fallback: when it says "configured", every ₫ on
        # screen is a constant, and that is worth being able to see.
        "display": display_basis(),
    }


@router.post("/fx/refresh")
def fx_refresh(full: bool = False) -> dict[str, Any]:
    """Fetch rates now instead of waiting for the daily run.

    Read-only with respect to the user's money — it writes exchange rates, not
    transactions — so it needs no confirmation token the way a report send does.
    """
    from ..fx_job import run_fx_job

    return run_fx_job(full=full)


@router.get("/health")
def health() -> dict[str, Any]:
    analysis = pipeline.cached()
    return {
        "status": "ok",
        "app": settings.app_name,
        "today": settings.today().isoformat(),
        "data_dir": str(settings.data_dir),
        "dataset": {
            "statement_date": analysis.ds.meta.get("statement_date"),
            "account_txns": len(analysis.ds.account),
            "card_txns": len(analysis.ds.card),
            "emails": len(analysis.ds.emails),
            "findings": len(analysis.findings),
        },
        "database": store.health(),
        "llm": client.status(refresh=True).as_dict(),
        "mail_mode": settings.mail_mode,
        "smtp": {
            "configured": bool(settings.smtp_host.strip()),
            "host": settings.smtp_host,
            "port": settings.smtp_port,
            "starttls": settings.smtp_starttls,
            "ssl": settings.smtp_ssl,
            "from": settings.smtp_from or settings.smtp_user,
            "to": settings.mail_to,
        },
        "owner_email": settings.owner_email,
        "read_only": True,
    }


@router.get("/i18n/{lang}")
def translations(lang: str) -> dict[str, Any]:
    lang = normalise_lang(lang)
    return {"lang": lang, "strings": catalog(lang)}


@router.get("/disclaimer")
def disclaimer_text(lang: str = "vi") -> dict[str, str]:
    lang = normalise_lang(lang)
    return {"lang": lang, "text": disclaimer(lang)}
