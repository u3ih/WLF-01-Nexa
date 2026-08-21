"""Periodic monitoring and dispute-deadline reminders."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from ..engine.render import normalise_lang
from ..monitor import reminder_list, run_scan
from ..schemas import ScanRequest
from ..store import store
from ..serialize import to_dollars
from ..yopmail_job import YopmailJobBusy, YopmailJobError, run_yopmail_job

router = APIRouter(prefix="/api/monitor", tags=["monitor"])


@router.post("/scan")
def scan(request: ScanRequest) -> dict[str, Any]:
    """Runs the full analysis but reports only findings not seen before."""
    lang = normalise_lang(request.lang)
    return to_dollars(run_scan(request.trigger, lang), lang)


@router.post("/yopmail")
def yopmail() -> dict[str, Any]:
    """Run the scheduled YOPmail scrape immediately inside the backend."""
    try:
        return run_yopmail_job("manual")
    except YopmailJobBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except YopmailJobError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/reminders")
def reminders(lang: str = "vi") -> dict[str, Any]:
    lang = normalise_lang(lang)
    items = reminder_list(lang)
    return to_dollars({"count": len(items), "reminders": items}, lang)


@router.get("/history")
def history(limit: int = 20) -> dict[str, Any]:
    rows = store.scan_history(limit)
    return {
        "count": len(rows),
        "scans": [
            {
                "id": r["id"],
                "trigger": r["trigger"],
                "started_at": r["started_at"].isoformat(),
                "finished_at": r["finished_at"].isoformat()
                if r["finished_at"] else None,
                "new_count": r["new_count"],
                "suppressed_count": r["suppressed_count"],
            }
            for r in rows
        ],
    }
