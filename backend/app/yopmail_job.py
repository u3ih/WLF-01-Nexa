"""Run the YOPmail scraper and importer from the application scheduler."""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from threading import Lock
from typing import Any

from .config import BACKEND_ROOT, settings

log = logging.getLogger("nexa.yopmail")
_job_lock = Lock()


class YopmailJobBusy(RuntimeError):
    """Raised when a manual run overlaps an existing scheduled run."""


class YopmailJobError(RuntimeError):
    """Raised when scraping or importing fails."""


def _run(command: list[str], *, cwd, timeout: float) -> subprocess.CompletedProcess[str]:
    log.info("running YOPmail step: %s", " ".join(command))
    try:
        result = subprocess.run(
            command, cwd=str(cwd), capture_output=True, text=True,
            timeout=timeout, check=False,
        )
    except FileNotFoundError as exc:
        raise YopmailJobError(f"command not found: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise YopmailJobError(f"YOPmail job timed out after {timeout:.0f}s") from exc

    if result.returncode != 0:
        details = (result.stderr or result.stdout or "").strip()
        if len(details) > 2000:
            details = details[-2000:]
        raise YopmailJobError(
            f"YOPmail step failed with exit code {result.returncode}: {details}"
        )
    return result


def run_yopmail_job(trigger: str = "schedule") -> dict[str, Any]:
    """Scrape one inbox and upsert its records into Postgres."""
    if not _job_lock.acquire(blocking=False):
        raise YopmailJobBusy("another YOPmail job is already running")

    try:
        scraper_dir = settings.yopmail_scraper_dir
        if not scraper_dir.is_absolute():
            scraper_dir = BACKEND_ROOT.parent / scraper_dir
        scraper_dir = scraper_dir.resolve()
        if not scraper_dir.is_dir():
            raise YopmailJobError(f"scraper directory not found: {scraper_dir}")

        output_dir = scraper_dir / "output" / settings.yopmail_user
        output_dir.mkdir(parents=True, exist_ok=True)
        json_path = output_dir / "emails_full.json"
        scraper_command = [
            settings.yopmail_node, "scrape_full.js",
            "--user", settings.yopmail_user,
            "--output", str(output_dir),
            "--limit", str(settings.yopmail_limit),
            "--delay", str(settings.yopmail_delay_ms),
            "--headless", "true",
            "--require-unlocked", str(settings.yopmail_require_unlocked).lower(),
        ]
        _run(scraper_command, cwd=scraper_dir, timeout=3600.0)

        if not json_path.is_file():
            raise YopmailJobError(f"scraper did not produce {json_path}")

        importer_command = [
            sys.executable, "-m", "data.import_yopmail",
            "--input", str(json_path),
            "--html-root", str(output_dir),
            "--mailbox", settings.yopmail_mailbox,
        ]
        imported = _run(importer_command, cwd=BACKEND_ROOT, timeout=120.0)
        try:
            counts = json.loads(imported.stdout)
        except json.JSONDecodeError as exc:
            raise YopmailJobError("importer returned invalid JSON") from exc

        result = {
            "trigger": trigger,
            "user": settings.yopmail_user,
            "mailbox": settings.yopmail_mailbox,
            "counts": counts,
        }
        log.info("YOPmail job completed: %s", result)
        return result
    finally:
        _job_lock.release()
