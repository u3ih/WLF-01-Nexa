"""Apply a YOPmail JSON export to the CSV dataset, without touching Postgres."""

from __future__ import annotations

import csv
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.engine.loader_wlf import read_csv

EMAIL_HEADERS = [
    "Index", "ID", "Inbox", "From", "Subject", "Date", "Page",
    "Body Text", "HTML File", "Extracted Links", "Extracted Codes",
    "Scraped At",
]


def _row(record: dict[str, Any], index: int) -> dict[str, Any]:
    links = record.get("extracted_links") or []
    codes = record.get("extracted_codes") or []
    if not isinstance(links, list):
        links = [links]
    if not isinstance(codes, list):
        codes = [codes]
    return {
        "Index": index,
        "ID": str(record.get("id") or ""),
        "Inbox": str(record.get("inbox") or ""),
        "From": str(record.get("from") or ""),
        "Subject": str(record.get("subject") or ""),
        "Date": str(record.get("date") or ""),
        "Page": record.get("page") or 1,
        "Body Text": str(record.get("body_text") or ""),
        "HTML File": str(record.get("body_html_file") or ""),
        "Extracted Links": "; ".join(str(item) for item in links if item),
        "Extracted Codes": "; ".join(str(item) for item in codes if item),
        "Scraped At": str(record.get("scraped_at") or ""),
    }


def apply_yopmail(input_path: Path, dataset_dir: Path,
                 mailbox: str) -> dict[str, Any]:
    """Merge records into ``dataset/email_<mailbox>.csv`` atomically."""
    records = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(records, list) or not all(isinstance(item, dict) for item in records):
        raise ValueError(f"Expected a JSON array of objects in {input_path}")

    dataset_dir.mkdir(parents=True, exist_ok=True)
    target = dataset_dir / f"email_{mailbox}.csv"
    existing: dict[str, dict[str, Any]] = {}
    delimiter = ","
    if target.exists():
        text = target.read_text(encoding="utf-8-sig")
        first_line = text.splitlines()[0] if text.splitlines() else ""
        delimiter = ";" if first_line.count(";") > first_line.count(",") else ","
        for row in read_csv(target):
            message_id = str(row.get("ID") or "").strip()
            if message_id:
                existing[message_id] = {
                    header: row.get(header, "") for header in EMAIL_HEADERS
                }

    crawled_ids: set[str] = set()
    merged: list[dict[str, Any]] = []
    for record in records:
        message_id = str(record.get("id") or "").strip()
        if not message_id:
            continue
        merged.append(_row(record, len(merged) + 1))
        crawled_ids.add(message_id)

    for message_id, row in existing.items():
        if message_id not in crawled_ids:
            row["Index"] = len(merged) + 1
            merged.append(row)

    backup_path: Path | None = None
    if target.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        backup_path = target.with_name(f"{target.name}.backup-{stamp}")
        shutil.copy2(target, backup_path)

    fd, temporary = tempfile.mkstemp(
        prefix=f".email_{mailbox}.", suffix=".csv", dir=dataset_dir,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(
                stream, fieldnames=EMAIL_HEADERS, delimiter=delimiter,
            )
            writer.writeheader()
            writer.writerows(merged)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

    inserted = sum(1 for row in merged if row["ID"] not in existing)
    return {
        "dataset_file": str(target),
        "backup_file": str(backup_path) if backup_path else None,
        "mailbox": mailbox,
        "records": len(merged),
        "crawled": len(crawled_ids),
        "inserted": inserted,
        "updated": len(crawled_ids) - inserted,
    }
