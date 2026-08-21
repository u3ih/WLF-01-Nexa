"""The conversational endpoint."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from ..llm.chat import answer
from ..schemas import (ChatRequest, ChatSessionCreateRequest,
                       ChatSessionUpdateRequest)
from ..store import store

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat")
def chat(request: ChatRequest) -> dict[str, Any]:
    return answer(request.question, request.lang)


# -- Chat history endpoints ------------------------------------------------


@router.get("/chat/history")
def list_history(limit: int = 50) -> list[dict[str, Any]]:
    return store.list_chat_sessions(limit)


@router.get("/chat/history/{session_id}")
def get_history(session_id: int) -> dict[str, Any]:
    session = store.get_chat_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.post("/chat/history")
def create_history(request: ChatSessionCreateRequest) -> dict[str, Any]:
    session_id = store.create_chat_session(
        request.title, request.lang, request.messages,
    )
    if not session_id:
        raise HTTPException(status_code=500, detail="Could not create session")
    session = store.get_chat_session(session_id)
    return session


@router.post("/chat/history/{session_id}")
def update_history(
    session_id: int, request: ChatSessionUpdateRequest,
) -> dict[str, Any]:
    ok = store.update_chat_session(
        session_id,
        title=request.title,
        messages=request.messages,
        lang=request.lang,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Session not found")
    session = store.get_chat_session(session_id)
    return session


@router.post("/chat/history/{session_id}/delete")
def delete_history(session_id: int) -> dict[str, str]:
    ok = store.delete_chat_session(session_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "deleted"}
