"""Keep the stored exchange rates current, from the application scheduler.

Ingestion lives here rather than in the engine on purpose: this is the only
part of the rate feature that touches the network, so the analysis stays
offline, pure and reproducible. Everything downstream reads Postgres.

Which pairs to fetch is read off the dataset rather than configured, so a new
currency in the export is covered without a code change; how far back is read
off the dataset too, because a report over February needs February's rates and
a 30-day window would silently leave every earlier month unconverted.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from . import fx
from .config import settings
from .engine import pipeline
from .store import store

log = logging.getLogger("nexa.fx")


def _span(ds: Any, today: date) -> tuple[date, date]:
    """The window worth holding rates for: the dataset's own period.

    Ends at today rather than at the statement date so a report run tomorrow
    already has tomorrow's rate, and starts a day early because a transaction on
    the first day of the period needs a rate published on or before it.
    """
    start = date.fromisoformat(ds.meta["period_start"]) - timedelta(days=1)
    end = max(today, ds.statement_date)
    return start, end


def run_fx_job(full: bool = False) -> dict[str, Any]:
    """Fetch the rates this dataset needs and store them.

    `full` re-fetches the whole span; the daily run only tops up from the last
    publication held, overlapping it by a day so a late ECB revision is picked
    up instead of being frozen in place by the first value we happened to see.

    Reports what it did rather than raising: a rate outage must not take the
    scheduler — or the analysis — down with it.
    """
    today = settings.today()
    try:
        analysis = pipeline.cached()
    except Exception as exc:                                # noqa: BLE001
        log.warning("fx job skipped, dataset not loadable: %s", exc)
        return {"ok": False, "error": str(exc)}

    pairs = fx.pairs_needed(analysis.ds.currencies, reporting="USD")
    if not pairs:
        # A single-currency dataset needs no rates at all, and saying so is
        # better than an empty success that looks like a failed fetch.
        return {"ok": True, "pairs": [], "note": "dataset is single-currency"}

    span_start, span_end = _span(analysis.ds, today)
    if full:
        start = span_start
    else:
        try:
            latest = store.fx_latest_quoted_on()
        except Exception as exc:                            # noqa: BLE001
            log.warning("fx job cannot read stored rates: %s", exc)
            return {"ok": False, "error": str(exc)}
        start = span_start if latest is None else max(
            span_start, fx.gap_start(latest, span_end))

    summary = fx.backfill(pairs, start, span_end)
    summary["ok"] = not summary["errors"]
    summary["pairs_requested"] = [f"{b}/{q}" for b, q in pairs]
    if summary["stored"]:
        # The analysis is cached per process and holds the rate table it was
        # built with, so newly stored rates are invisible until it reloads.
        pipeline.reset_cache()
        log.info("fx: stored %d rate(s) for %s over %s → %s",
                 summary["stored"], ", ".join(summary["pairs_requested"]),
                 summary["start"], summary["end"])
    return summary


def main() -> None:
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Fetch and store FX rates")
    parser.add_argument("--full", action="store_true",
                        help="re-fetch the dataset's whole period, not just the gap")
    args = parser.parse_args()
    print(json.dumps(run_fx_job(full=args.full), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
