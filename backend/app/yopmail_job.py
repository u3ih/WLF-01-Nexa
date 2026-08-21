"""Run the YOPmail scraper and update the CSV dataset from the scheduler."""

from __future__ import annotations

import logging
import shutil
import subprocess
from threading import Lock
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from data.apply_yopmail import apply_yopmail

from .config import BACKEND_ROOT, settings
from .engine import pipeline

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


def _targets() -> list[tuple[str, str]]:
    users = [item.strip() for item in settings.yopmail_users.split(",") if item.strip()]
    mailboxes = [item.strip() for item in settings.yopmail_mailboxes.split(",") if item.strip()]
    if not users or len(users) != len(mailboxes):
        raise YopmailJobError(
            "NEXA_YOPMAIL_USERS and NEXA_YOPMAIL_MAILBOXES must have the same "
            "number of comma-separated entries"
        )
    return list(zip(users, mailboxes))


def _run_one(user: str, mailbox: str, scraper_dir, dataset_dir) -> dict[str, Any]:
    output_dir = scraper_dir / "output" / user
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "emails_full.json"
    scraper_command = [
        settings.yopmail_node, "scrape_full.js",
        "--user", user,
        "--output", str(output_dir),
        "--limit", str(settings.yopmail_limit),
        "--delay", str(settings.yopmail_delay_ms),
        "--headless", "true",
        "--require-unlocked", str(settings.yopmail_require_unlocked).lower(),
    ]
    _run(scraper_command, cwd=scraper_dir, timeout=3600.0)
    if not json_path.is_file():
        raise YopmailJobError(f"scraper did not produce {json_path}")
    counts = apply_yopmail(json_path, dataset_dir, mailbox)
    # The dataset is the durable output. Keep scraper artifacts only when a
    # run fails, so a successful five-minute cycle does not accumulate JSON,
    # reports and hundreds of HTML files.
    shutil.rmtree(output_dir)
    return {"user": user, "mailbox": mailbox, "dataset": counts}


def run_yopmail_job(trigger: str = "schedule") -> dict[str, Any]:
    """Scrape all configured inboxes concurrently and update the dataset."""
    if not _job_lock.acquire(blocking=False):
        raise YopmailJobBusy("another YOPmail job is already running")

    try:
        scraper_dir = settings.yopmail_scraper_dir
        if not scraper_dir.is_absolute():
            scraper_dir = BACKEND_ROOT.parent / scraper_dir
        scraper_dir = scraper_dir.resolve()
        if not scraper_dir.is_dir():
            raise YopmailJobError(f"scraper directory not found: {scraper_dir}")

        dataset_dir = settings.yopmail_dataset_dir
        if not dataset_dir.is_absolute():
            dataset_dir = BACKEND_ROOT.parent / dataset_dir
        dataset_dir = dataset_dir.resolve()
        targets = _targets()
        results: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        with ThreadPoolExecutor(max_workers=len(targets), thread_name_prefix="yopmail") as pool:
            futures = {
                pool.submit(_run_one, user, mailbox, scraper_dir, dataset_dir): (user, mailbox)
                for user, mailbox in targets
            }
            for future in as_completed(futures):
                user, mailbox = futures[future]
                try:
                    results.append(future.result())
                except Exception as exc:  # noqa: BLE001
                    log.exception("YOPmail mailbox failed: %s", user)
                    errors.append({"user": user, "mailbox": mailbox, "error": str(exc)})

        if results:
            pipeline.reset_cache()
        if errors and not results:
            raise YopmailJobError(
                "all YOPmail mailboxes failed: "
                + "; ".join(f"{item['user']}: {item['error']}" for item in errors)
            )

        result = {
            "trigger": trigger,
            "results": sorted(results, key=lambda item: item["mailbox"]),
            "errors": sorted(errors, key=lambda item: item["mailbox"]),
        }
        log.info("YOPmail job completed: %s", result)
        return result
    finally:
        _job_lock.release()
