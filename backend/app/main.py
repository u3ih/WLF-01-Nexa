"""Nexa backend — WLF-01 statement review assistant.

Read-only by construction: no route in this application can move money, cancel
a subscription, open a dispute or lock a card, and report email goes to the
configured notification address after an explicit confirmation.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .engine import pipeline
from .routers import analysis, audit, chat, mail, meta, monitor, reports
from .store import store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("nexa")

scheduler = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    if store.init_schema():
        log.info("postgres ready at %s", settings.database_url.rsplit("@", 1)[-1])
    else:
        log.warning("postgres unavailable (%s) — analysis works, but the flag "
                    "journal, de-duplication and reminders need it",
                    store.last_error)
    try:
        analysis_result = pipeline.cached()
        log.info("dataset loaded: %d account rows, %d card rows, %d emails, "
                 "%d findings",
                 len(analysis_result.ds.account), len(analysis_result.ds.card),
                 len(analysis_result.ds.emails), len(analysis_result.findings))
    except Exception as exc:                            # noqa: BLE001
        log.error("could not load the sample dataset: %s — run "
                  "`python -m data.generate`", exc)

    from .llm.client import client as llm_client

    llm_status = llm_client.status(refresh=True)
    if llm_status.available:
        log.info("AI ready: %s (%s) at %s",
                 llm_status.model, llm_status.mode, settings.ai_url)
    else:
        # This is an AI product; a missing model is a headline, not a footnote.
        log.error("AI NOT AVAILABLE: %s — answers will fall back to the "
                  "deterministic engine until the model is reachable",
                  llm_status.detail)

    global scheduler
    if settings.scheduler_enabled:
        try:
            from apscheduler.schedulers.background import BackgroundScheduler

            from .monitor import run_scan

            scheduler = BackgroundScheduler(daemon=True)
            scheduler.add_job(
                lambda: run_scan("schedule", "vi"),
                "cron", hour=settings.scan_hour, minute=0, id="daily-scan",
            )
            scheduler.start()
            log.info("daily monitoring scan scheduled at %02d:00",
                     settings.scan_hour)
        except Exception as exc:                        # noqa: BLE001
            log.warning("scheduler not started: %s", exc)

    yield

    if scheduler:
        scheduler.shutdown(wait=False)


app = FastAPI(
    title="Nexa — Wealify statement review assistant (WLF-01)",
    description="Read-only review of sample statements, emails, wallet and card "
                "data. Suggestions only; the user decides.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

for module in (meta, analysis, reports, chat, mail, monitor, audit):
    app.include_router(module.router)


@app.get("/")
def root() -> dict[str, str]:
    return {
        "app": settings.app_name,
        "docs": "/docs",
        "health": "/api/health",
        "read_only": "true",
    }
