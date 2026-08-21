"""One entry point that runs the whole read-only analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..config import settings
from . import anomaly, classify, email_match, reports, subscriptions, tri_source
from .loader import Dataset, load_dataset
from .mask import last4, mask_account, mask_card
from .models import Finding, Label
from .render import label_counts, render_findings

# Alerts first, background information last.
LABEL_ORDER = {
    Label.NEEDS_YOUR_CONFIRMATION: 0,
    Label.INSUFFICIENT_DATA: 1,
    Label.RECURRING_CONFIRMED: 2,
}


@dataclass
class Analysis:
    ds: Dataset
    cashflow: dict[str, Any]
    recon: email_match.EmailReconResult
    subs: list[subscriptions.Subscription]
    subs_forecast: dict[str, Any]
    tri: tri_source.TriSourceResult
    findings: list[Finding] = field(default_factory=list)

    @property
    def statement_date(self) -> date:
        return self.ds.statement_date

    @property
    def alerts(self) -> list[Finding]:
        """Everything except the plain "this is a subscription" entries."""
        return [f for f in self.findings
                if f.label is not Label.RECURRING_CONFIRMED
                or f.kind.value == "price_increase"]

    def account_profile(self) -> dict[str, Any]:
        card = self.ds.card[0].card_number if self.ds.card else ""
        return {
            "owner_name": self.ds.meta.get("owner_name"),
            "owner_email": self.ds.owner_email,
            "account_masked": mask_account(self.ds.meta.get("account_number")),
            "card_masked": mask_card(card or self.ds.meta.get("card_number")),
            "card_last4": last4(card or self.ds.meta.get("card_number")),
            "statement_date": self.ds.meta.get("statement_date"),
            "period_start": self.ds.meta.get("period_start"),
            "currency": self.ds.meta.get("currency", "USD"),
        }

    def summary(self, lang: str, today: date) -> dict[str, Any]:
        return {
            "account": self.account_profile(),
            "counts": {
                "account_txns": len(self.ds.account),
                "card_txns": len(self.ds.card),
                "wallet_events": len(self.ds.wallet.events) if self.ds.wallet else 0,
                "emails": len(self.ds.emails),
                "findings": len(self.findings),
                "alerts": len(self.alerts),
                "subscriptions": len(self.subs),
            },
            "labels": label_counts(self.findings),
            "email_recon": email_match.summary(self.recon),
            "cashflow": self.cashflow["totals"],
            "wallet": self.tri.wallet,
            "sources": self.ds.source_files,
            "statement_date": self.ds.meta.get("statement_date"),
            "findings": render_findings(self.findings, lang, today),
        }


def _sort_key(f: Finding) -> tuple:
    return (
        LABEL_ORDER[f.label],
        -f.amount_cents,
        f.occurred_on.isoformat() if f.occurred_on else "",
        f.kind.value,
    )


def run(data_dir: Path | None = None, use_pdf: bool = False) -> Analysis:
    ds = load_dataset(data_dir or settings.data_dir, use_pdf=use_pdf)
    cashflow = classify.classify(ds)
    recon = email_match.reconcile(ds)
    subs = subscriptions.detect(ds, recon)
    tri = tri_source.reconcile(ds)

    findings: list[Finding] = []
    findings += subscriptions.findings(ds, subs)
    findings += anomaly.detect(ds, recon)
    findings += tri_source.findings(ds, tri)

    return Analysis(
        ds=ds,
        cashflow=cashflow,
        recon=recon,
        subs=subs,
        subs_forecast=subscriptions.forecast(subs),
        tri=tri,
        findings=sorted(findings, key=_sort_key),
    )


@lru_cache
def cached(use_pdf: bool = False) -> Analysis:
    """The dataset is static sample data, so one analysis per process is enough."""
    return run(use_pdf=use_pdf)


def reset_cache() -> None:
    cached.cache_clear()


def report_for(analysis: Analysis, kind: str = "month",
               key: str | None = None) -> dict[str, Any]:
    return reports.build(analysis.ds, kind, key, analysis.subs_forecast)
