"""Scheduled / on-demand monitoring.

Both the manual endpoint and the daily job call `run_scan`, so the
no-duplicate-alerts behaviour is identical either way.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from .config import settings
from .engine import pipeline
from .engine.dedupe import flag_payload, journal_reason, split_new
from .engine.models import Finding, Label
from .engine.render import render_finding, render_findings
from .store import store

# Findings that deserve a dated reminder (the informational ones do not).
REMINDER_LABELS = {Label.NEEDS_YOUR_CONFIRMATION, Label.INSUFFICIENT_DATA}


def _reminder_title(finding: Finding, lang: str, today: date) -> str:
    return render_finding(finding, lang, today)["title"]


def run_scan(trigger: str = "manual", lang: str = "vi",
             today: date | None = None) -> dict[str, Any]:
    """Analyse, store only unseen findings, and report just those."""
    today = today or settings.today()
    analysis = pipeline.cached()
    known = store.known_fingerprints()
    scan_id = store.start_scan(trigger)

    new, repeated = split_new(analysis.findings, known)
    reminders_created = 0

    for finding in new:
        store.upsert_flag(flag_payload(finding), scan_id)
        store.log(
            "flag_raised",
            fingerprint=finding.fingerprint,
            kind=finding.kind.value,
            label=finding.label.value,
            confidence=finding.confidence,
            reason=journal_reason(finding),
            detail={
                "sources": [s.as_dict() for s in finding.sources],
                "txn_ids": finding.txn_ids,
                "dispute_deadline": finding.dispute_deadline,
                "trigger": trigger,
            },
        )
        if finding.label in REMINDER_LABELS and finding.dispute_deadline:
            if store.add_reminder(finding.fingerprint, finding.dispute_deadline,
                                  finding.kind.value,
                                  _reminder_title(finding, lang, today)):
                reminders_created += 1

    for finding in repeated:
        store.upsert_flag(flag_payload(finding), scan_id)

    if repeated:
        store.log(
            "duplicates_suppressed",
            reason=f"{len(repeated)} finding(s) already reported were not "
                   f"re-raised",
            detail={"fingerprints": [f.fingerprint for f in repeated],
                    "trigger": trigger},
        )

    store.finish_scan(scan_id, len(new), len(repeated))
    return {
        "scan_id": scan_id,
        "trigger": trigger,
        "new_count": len(new),
        "suppressed_count": len(repeated),
        "reminders_created": reminders_created,
        "new": render_findings(new, lang, today),
        "suppressed_fingerprints": [f.fingerprint for f in repeated],
    }


def reminder_list(lang: str = "vi", today: date | None = None
                  ) -> list[dict[str, Any]]:
    today = today or settings.today()
    out = []
    for row in store.reminders():
        days_left = (row["due_date"] - today).days
        out.append({
            "id": row["id"],
            "fingerprint": row["fingerprint"],
            "kind": row["kind"],
            "title": row["title"],
            "due_date": row["due_date"].isoformat(),
            "days_left": days_left,
            "expired": days_left < 0,
            "amount_cents": row["amount_cents"],
            "status": row["status"],
        })
    return out
