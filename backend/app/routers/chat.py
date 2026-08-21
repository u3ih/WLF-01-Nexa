"""The conversational endpoint."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ..llm.chat import answer
from ..schemas import ChatRequest

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat")
def chat(request: ChatRequest) -> dict[str, Any]:
    return answer(request.question, request.lang)
