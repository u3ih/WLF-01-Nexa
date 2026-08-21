"""Self-notification: draft, confirm, send to the configured mail recipient."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from ..config import settings
from ..engine.render import normalise_lang, t
from ..mailer import (
    DraftError, MailConfigError, MailDeliveryError, create_draft,
    send_confirmed, send_smtp_test,
)
from ..schemas import DraftRequest, SendRequest, SmtpTestRequest

router = APIRouter(prefix="/api/report", tags=["mail"])


@router.post("/draft")
def draft(request: DraftRequest) -> dict[str, Any]:
    lang = normalise_lang(request.lang)
    try:
        return create_draft(lang=lang, period_kind=request.period,
                            period_key=request.key)
    except MailConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/send")
def send(request: SendRequest) -> dict[str, Any]:
    """Requires an explicit confirmation; recipient is fixed by configuration."""
    lang = normalise_lang(request.lang)
    if not request.confirmed:
        raise HTTPException(
            status_code=428,
            detail=t(lang, "mail.confirm_prompt",
                     owner_email=settings.mail_to),
        )
    try:
        return send_confirmed(request.confirm_token, request.recipient, lang)
    except DraftError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except MailConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except MailDeliveryError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/smtp-test")
def smtp_test(request: SmtpTestRequest) -> dict[str, Any]:
    """Send a small SMTP-only test email to the configured recipient."""
    lang = normalise_lang(request.lang)
    try:
        return send_smtp_test(request.recipient, lang)
    except MailConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except MailDeliveryError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
