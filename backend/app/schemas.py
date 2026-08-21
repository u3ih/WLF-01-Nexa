"""Request models. Responses are plain dicts built by the engine."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    lang: str = "vi"


class DraftRequest(BaseModel):
    lang: str = "vi"
    period: str = "month"
    key: str | None = None


class SendRequest(BaseModel):
    confirm_token: str = Field(min_length=8, max_length=128)
    # Kept for backwards compatibility; delivery always uses NEXA_MAIL_TO.
    recipient: str | None = None
    lang: str = "vi"
    confirmed: bool = False


class SmtpTestRequest(BaseModel):
    # Kept for backwards compatibility; delivery always uses NEXA_MAIL_TO.
    recipient: str | None = None
    lang: str = "vi"


class ScanRequest(BaseModel):
    lang: str = "vi"
    trigger: str = "manual"


class ChatSessionCreateRequest(BaseModel):
    title: str = ""
    lang: str = "vi"
    messages: list[dict] = []


class ChatSessionUpdateRequest(BaseModel):
    title: str | None = None
    messages: list[dict] | None = None
    lang: str | None = None
