"""The flag journal, and the switch that wipes stored state after the contest."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import PlainTextResponse

from ..engine.dedupe import audit_to_csv, audit_to_json
from ..engine.render import normalise_lang
from ..llm.tools import run_tool
from ..store import store
from ..serialize import to_dollars

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("")
def entries(lang: str = "vi", limit: int = Query(default=100, le=2000)
            ) -> dict[str, Any]:
    return run_tool("get_audit_log", {"limit": limit}, normalise_lang(lang))


@router.get("/export")
def export(format: str = "csv", limit: int = Query(default=5000, le=20000)):
    rows = store.audit_entries(limit)
    if format == "json":
        return PlainTextResponse(
            audit_to_json(rows), media_type="application/json",
            headers={"Content-Disposition":
                     'attachment; filename="nexa-audit.json"'},
        )
    return PlainTextResponse(
        audit_to_csv(rows), media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="nexa-audit.csv"'},
    )


@router.get("/flags")
def flags(limit: int = Query(default=200, le=1000)) -> dict[str, Any]:
    rows = store.flags(limit)
    return to_dollars({
        "count": len(rows),
        "flags": [
            {
                "fingerprint": r["fingerprint"],
                "kind": r["kind"],
                "label": r["label"],
                "confidence": float(r["confidence"]),
                "amount_cents": r["amount_cents"],
                "txn_ids": r["txn_ids"],
                "dispute_deadline": r["dispute_deadline"].isoformat()
                if r["dispute_deadline"] else None,
                "first_seen_at": r["first_seen_at"].isoformat(),
                "seen_count": r["seen_count"],
            }
            for r in rows
        ],
    })


@router.post("/purge")
def purge() -> dict[str, Any]:
    """Wipe flags, journal, reminders and drafts (contest rule 9)."""
    before = store.purge()
    return {"purged": True, "rows_removed": before}
