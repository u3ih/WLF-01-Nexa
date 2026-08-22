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


def refresh_display_rate() -> dict[str, Any]:
    """Top up the rate the ₫ figures are converted at.

    Its own step, and its own publication: the ECB carries no đồng, so without
    this the ₫ beside every USD amount would stay at a number compiled into the
    settings — right on the day it was written and drifting from then on.

    Only the newest rate is kept. Unlike the report's row-by-row restatement,
    the ₫ display is not dated by the transaction, so a history of đồng rates
    would be a table nothing ever reads.
    """
    base, quote = fx.DISPLAY_PAIR
    label = f"{base}/{quote}"
    quoted = fx.fetch_display_quote(base, quote)
    if quoted is None:
        return {"pair": label, "stored": 0,
                "note": "no published rate, ₫ stays on the configured one"}
    try:
        stored = store.upsert_fx_quotes([quoted])
    except Exception as exc:                                # noqa: BLE001
        log.warning("display rate could not be stored: %s", exc)
        return {"pair": label, "stored": 0, "error": str(exc)}
    # The rate is held per process; a fresh one stays invisible until the hold
    # is replaced, and it is already in hand here — no need to read it back.
    fx.hold_display_quote(quoted)
    log.info("fx: display rate %s = %s (%s, %s)", label,
             format(quoted.rate.normalize(), "f"), quoted.source,
             quoted.quoted_on)
    return {"pair": label, "stored": stored, "rate": quoted.as_dict()}


def run_fx_job(full: bool = False) -> dict[str, Any]:
    """Fetch the rates this dataset needs and store them.

    `full` re-fetches the whole span; the daily run only tops up from the last
    publication held, overlapping it by a day so a late ECB revision is picked
    up instead of being frozen in place by the first value we happened to see.

    Reports what it did rather than raising: a rate outage must not take the
    scheduler — or the analysis — down with it.
    """
    today = settings.today()
    # First, and independent of the dataset: the ₫ display rate is needed even
    # by a statement that is USD from end to end.
    display = refresh_display_rate() if settings.show_vnd else None

    try:
        analysis = pipeline.cached()
    except Exception as exc:                                # noqa: BLE001
        log.warning("fx job skipped, dataset not loadable: %s", exc)
        return {"ok": False, "error": str(exc), "display": display}

    pairs = fx.pairs_needed(analysis.ds.currencies, reporting="USD")
    if not pairs:
        # A single-currency dataset needs no rates at all, and saying so is
        # better than an empty success that looks like a failed fetch.
        return {"ok": True, "pairs": [], "display": display,
                "note": "dataset is single-currency"}

    span_start, span_end = _span(analysis.ds, today)
    if full:
        start = span_start
    else:
        try:
            # Filtered to the reporting currency on purpose. The display rate
            # is refreshed to today every run and lives in the same table, so
            # an unfiltered "latest" would read as "nothing to backfill" and
            # leave the statement's own months without rates for ever.
            latest = store.fx_latest_quoted_on(quote="USD")
        except Exception as exc:                            # noqa: BLE001
            log.warning("fx job cannot read stored rates: %s", exc)
            return {"ok": False, "error": str(exc), "display": display}
        start = span_start if latest is None else max(
            span_start, fx.gap_start(latest, span_end))

    summary = fx.backfill(pairs, start, span_end)
    summary["ok"] = not summary["errors"]
    summary["pairs_requested"] = [f"{b}/{q}" for b, q in pairs]
    summary["display"] = display
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
