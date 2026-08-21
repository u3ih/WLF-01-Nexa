"""Self-notification: draft, confirm, send — owner address only."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from ..config import settings
from ..engine.render import normalise_lang, t
from ..mailer import DraftError, OwnerOnlyError, create_draft, send_confirmed
from ..schemas import DraftRequest, SendRequest

router = APIRouter(prefix="/api/report", tags=["mail"])


@router.post("/draft")
def draft(request: DraftRequest) -> dict[str, Any]:
    lang = normalise_lang(request.lang)
    try:
        return create_draft(lang=lang, period_kind=request.period,
                            period_key=request.key)
    except OwnerOnlyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/send")
def send(request: SendRequest) -> dict[str, Any]:
    """Requires an explicit confirmation and the owner's own address."""
    lang = normalise_lang(request.lang)
    if not request.confirmed:
        raise HTTPException(
            status_code=428,
            detail=t(lang, "mail.confirm_prompt",
                     owner_email=settings.owner_email),
        )
    try:
        return send_confirmed(request.confirm_token, request.recipient, lang)
    except OwnerOnlyError as exc:
        raise HTTPException(
            status_code=403,
            detail=f"{t(lang, 'mail.owner_only', owner_email=settings.owner_email)}"
                   f" ({exc})",
        ) from exc
    except DraftError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
