"""Turn a Finding into a storable flag, and describe why it was flagged.

The fingerprint (kind + transaction ids + amount + period) is what stops a
scheduled re-scan from reporting the same item twice.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from .models import Finding, fmt_money

# Which params are worth putting in the journal line for each kind.
REASON_FIELDS: dict[str, tuple[str, ...]] = {
    "recurring_subscription": ("merchant", "cadence", "charge_count"),
    "forgotten_subscription": ("merchant", "charges_without_receipt", "since"),
    "price_increase": ("merchant", "old_amount_cents", "new_amount_cents",
                       "effective_on"),
    "duplicate_charge": ("descriptor", "seconds_apart", "occurred_on"),
    "double_fee": ("descriptor", "count", "occurred_on"),
    "duplicate_payin": ("counterparty", "count", "occurred_on"),
    "transfer_not_on_card": ("occurred_on", "searched_window_days"),
    "wallet_balance_mismatch": ("computed_cents", "reported_cents", "reported_at"),
    "unknown_merchant": ("descriptor", "processor_hint", "charge_count"),
    "missing_email": ("descriptor", "occurred_on", "threshold_cents"),
    "suspicious_email": ("from_addr", "claimed_brand", "reasons"),
}


def journal_reason(finding: Finding) -> str:
    """One-line, human-readable reason — this is what lands in the audit log."""
    fields = REASON_FIELDS.get(finding.kind.value, ())
    parts: list[str] = []
    for field in fields:
        value = finding.params.get(field)
        if value in (None, "", [], {}):
            continue
        if field.endswith("_cents") and isinstance(value, int):
            value = fmt_money(value)
        if isinstance(value, list):
            value = ",".join(str(v) for v in value)
        parts.append(f"{field}={value}")
    head = f"{finding.kind.value} {fmt_money(finding.amount_cents)}"
    tail = "; ".join(parts)
    refs = ",".join(finding.txn_ids) or "-"
    return f"{head} [{tail}] refs={refs}"


def flag_payload(finding: Finding) -> dict[str, Any]:
    return {
        "fingerprint": finding.fingerprint,
        "kind": finding.kind.value,
        "label": finding.label.value,
        "confidence": finding.confidence,
        "amount_cents": finding.amount_cents,
        "txn_ids": json.dumps(finding.txn_ids),
        "period_key": finding.period_key,
        "occurred_on": finding.occurred_on,
        "statement_date": finding.statement_date,
        "dispute_deadline": finding.dispute_deadline,
        "params": json.dumps(finding.params, default=str),
        "sources": json.dumps([s.as_dict() for s in finding.sources]),
    }


def split_new(findings: list[Finding], known: set[str]
              ) -> tuple[list[Finding], list[Finding]]:
    """Split into (new, already reported) using the stored fingerprints."""
    new = [f for f in findings if f.fingerprint not in known]
    seen = [f for f in findings if f.fingerprint in known]
    return new, seen


AUDIT_COLUMNS = ("id", "logged_at", "event", "fingerprint", "kind", "label",
                 "confidence", "reason")


def audit_to_csv(rows: list[dict[str, Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=AUDIT_COLUMNS,
                            extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: row.get(k) for k in AUDIT_COLUMNS})
    return buffer.getvalue()


def audit_to_json(rows: list[dict[str, Any]]) -> str:
    return json.dumps(rows, indent=2, default=str)
