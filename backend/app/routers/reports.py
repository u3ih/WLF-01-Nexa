"""Period reports."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ..engine import pipeline, reports as reports_engine
from ..engine.render import normalise_lang
from ..llm.tools import run_tool
from ..serialize import to_dollars

router = APIRouter(prefix="/api", tags=["reports"])


@router.get("/report")
def report(lang: str = "vi", period: str = "month",
           key: str | None = None) -> dict[str, Any]:
    lang = normalise_lang(lang)
    return to_dollars(run_tool("get_report", {"period": period, "key": key},
                               lang), lang)


@router.get("/report/all")
def all_periods(lang: str = "vi") -> dict[str, Any]:
    """Month, quarter and year in one call — used by the report tab."""
    lang = normalise_lang(lang)
    analysis = pipeline.cached()
    data = reports_engine.all_periods(analysis.ds, analysis.subs_forecast,
                                      analysis.fx)
    data["trend"] = reports_engine.monthly_series(analysis.ds, 12, analysis.fx)
    return to_dollars(data, lang)
