"""Health, capability and translation endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ..config import settings
from ..engine import pipeline
from ..engine.render import catalog, disclaimer, normalise_lang
from ..llm.client import client
from ..store import store

router = APIRouter(prefix="/api", tags=["meta"])


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
