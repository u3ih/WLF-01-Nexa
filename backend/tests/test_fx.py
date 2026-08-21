"""Exchange rates: the lookup, the arithmetic, and what a report does with them.

Every test here is offline. `FxTable` is the half of `app.fx` the engine uses
and it never fetches, which is the property that keeps an analysis reproducible
— these tests would be worthless if they could pass or fail on network weather.
The fetching half is exercised against a fake transport, not the real host.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app import fx
from app.engine import pipeline, reports
from app.engine.render import bucket_scope_note, excluded_lines

EXPORT_DIR = Path(__file__).resolve().parent.parent.parent / "dataset"

# A Friday and the Monday after it. The market is shut over the weekend, which
# is the case every date-based lookup has to get right.
FRIDAY = date(2026, 8, 14)
MONDAY = date(2026, 8, 17)


def _table() -> fx.FxTable:
    return fx.FxTable([
        fx.FxQuote("EUR", "USD", FRIDAY, Decimal("1.1567")),
        fx.FxQuote("EUR", "USD", MONDAY, Decimal("1.1593")),
    ])


class TestLookup:
    def test_an_exact_date_uses_that_days_publication(self):
        found = _table().rate_on(FRIDAY, "EUR", "USD")
        assert found.rate == Decimal("1.1567")
        assert found.quoted_on == FRIDAY

    def test_a_closed_market_falls_back_and_says_which_day_it_used(self):
        """Saturday has no rate. Using Friday's is right; hiding that is not."""
        found = _table().rate_on(date(2026, 8, 15), "EUR", "USD")
        assert found.rate == Decimal("1.1567")
        assert found.quoted_on == FRIDAY

    def test_a_date_before_every_publication_has_no_rate(self):
        """Reaching forward would price a purchase with news it predates."""
        assert _table().rate_on(date(2026, 8, 13), "EUR", "USD") is None

    def test_a_gap_wider_than_a_long_weekend_is_declined(self):
        """Past four days the gap is a missing backfill, not a closed market.

        Applying a fortnight-old rate silently is how a converted figure ends up
        wrong by more than the rounding it pretends to be accurate to.
        """
        stale = fx.FxTable([fx.FxQuote("EUR", "USD", FRIDAY, Decimal("1.15"))])
        assert stale.rate_on(FRIDAY, "EUR", "USD") is not None
        assert stale.rate_on(date(2026, 8, 28), "EUR", "USD") is None

    def test_the_reverse_direction_is_derived_and_marked_as_derived(self):
        found = _table().rate_on(FRIDAY, "USD", "EUR")
        assert found.inverted is True
        assert found.rate == Decimal(1) / Decimal("1.1567")

    def test_a_currency_against_itself_is_one(self):
        found = fx.EMPTY.rate_on(FRIDAY, "USD", "USD")
        assert found.rate == Decimal(1) and found.source == "identity"


class TestConversion:
    def test_cents_convert_exactly_and_round_half_up(self):
        """€0.58 at 1.154 is 66.932 cents — 67, not 66 and not 66.93."""
        table = fx.FxTable([fx.FxQuote("EUR", "USD", FRIDAY, Decimal("1.154"))])
        done = table.convert(58, FRIDAY, "EUR", "USD")
        assert done.cents == 67
        assert done.quote.rate == Decimal("1.154")

    def test_the_conversion_reports_how_stale_its_rate_is(self):
        done = _table().convert(10_000, date(2026, 8, 16), "EUR", "USD")
        assert done.asked_on == date(2026, 8, 16)
        assert done.quote.quoted_on == FRIDAY
        assert done.stale_days == 2

    def test_an_empty_table_declines_rather_than_guessing(self):
        """The state before any backfill. It must cost accuracy, not truth."""
        assert fx.EMPTY.convert(58, FRIDAY, "EUR", "USD") is None


class TestIngestionHelpers:
    def test_pairs_are_read_off_the_data_not_configured(self):
        assert fx.pairs_needed(["USD", "EUR", "GBP"]) == [("EUR", "USD"),
                                                          ("GBP", "USD")]
        assert fx.pairs_needed(["USD"]) == []

    def test_a_top_up_overlaps_the_last_publication_held(self):
        """The ECB revises. Re-fetching one day is cheap; a frozen rate is not."""
        assert fx.gap_start(FRIDAY, MONDAY) == FRIDAY
        assert fx.gap_start(None, MONDAY, default_days=30) == date(2026, 7, 18)

    def test_a_pair_the_publication_anchors_the_other_way_is_flipped_back(self):
        """The ECB quotes against EUR, so USD→EUR is fetched as EUR→USD."""
        assert fx._pair_for_fetch("USD", "EUR") == ("EUR", "USD", True)
        assert fx._pair_for_fetch("EUR", "USD") == ("EUR", "USD", False)

    def test_a_failing_pair_does_not_cost_the_others_their_backfill(self,
                                                                    monkeypatch):
        written: list = []

        def fake_fetch(base, quote, start, end, timeout=20.0):
            if base == "GBP":
                raise RuntimeError("no GBP series")
            return [fx.FxQuote(base, quote, FRIDAY, Decimal("1.15"))]

        monkeypatch.setattr(fx, "fetch_range", fake_fetch)
        summary = fx.backfill([("EUR", "USD"), ("GBP", "USD")], FRIDAY, MONDAY,
                              upsert=lambda qs: written.extend(qs) or len(qs))
        assert summary["pairs"]["EUR/USD"]["stored"] == 1
        assert "GBP/USD" in summary["errors"]
        assert len(written) == 1


@pytest.fixture(scope="module")
def export():
    if not (EXPORT_DIR / "transactions_card.csv").exists():
        pytest.skip(f"Wealify export not present at {EXPORT_DIR}")
    return pipeline.run(EXPORT_DIR)


class TestTheReportUsesTheRates:
    """August spent €57.54 and paid €0.58 of fees that a USD report omits."""

    AUGUST_RATE = fx.FxTable([
        fx.FxQuote("EUR", "USD", date(2026, 8, 11), Decimal("1.154")),
    ])

    def test_without_rates_the_amounts_stay_in_their_own_currency(self, export):
        report = reports.build(export.ds, "month", "2026-08",
                               export.subs_forecast, fx.EMPTY)
        eur = next(row for row in report["excluded"]["other_currencies"]
                   if row["currency"] == "EUR")
        # None, not zero: zero would read as "worth nothing" rather than
        # "not known", and that is the whole difference.
        assert eur["converted"] is None
        assert "≈" not in bucket_scope_note("fees_cents", report["excluded"],
                                            "vi")

    def test_with_rates_each_row_converts_at_its_own_days_rate(self, export):
        report = reports.build(export.ds, "month", "2026-08",
                               export.subs_forecast, self.AUGUST_RATE)
        eur = next(row for row in report["excluded"]["other_currencies"]
                   if row["currency"] == "EUR")
        assert eur["converted"]["complete"] is True
        assert eur["converted"]["fees_cents"] == 67       # €0.58 × 1.154
        assert eur["converted"]["spend_cents"] == 6640    # €57.54 × 1.154

    def test_the_rate_it_used_is_stated_not_just_the_result(self, export):
        """A converted figure the reader cannot audit is a figure to distrust."""
        report = reports.build(export.ds, "month", "2026-08",
                               export.subs_forecast, self.AUGUST_RATE)
        lines = excluded_lines(report["excluded"], "vi")
        assert any("1.154" in line and "2026-08-11" in line for line in lines)

    def test_a_partly_covered_period_says_so_instead_of_under_reporting(self,
                                                                        export):
        """July has six EUR rows; one rate covers some of them and not others.

        The danger is a total that silently omits the rows it could not price
        and still looks like a complete figure.
        """
        partial = fx.FxTable([
            fx.FxQuote("EUR", "USD", date(2026, 7, 1), Decimal("1.15")),
        ])
        report = reports.build(export.ds, "month", "2026-07",
                               export.subs_forecast, partial)
        eur = next(row for row in report["excluded"]["other_currencies"]
                   if row["currency"] == "EUR")
        assert eur["converted"]["complete"] is False
        assert eur["converted"]["missing_rows"] > 0
        assert any("chưa quy đổi" in line
                   for line in excluded_lines(report["excluded"], "vi"))

    def test_the_reporting_currency_totals_are_untouched_by_conversion(self,
                                                                       export):
        """Converting is for the caveat, never for the headline figure.

        "USD plus EUR is not a number" holds whether or not a rate exists; an
        approximate equivalent must not leak into a total the statement can be
        checked against line by line.
        """
        without = reports.build(export.ds, "month", "2026-08",
                                export.subs_forecast, fx.EMPTY)["totals"]
        with_rates = reports.build(export.ds, "month", "2026-08",
                                   export.subs_forecast,
                                   self.AUGUST_RATE)["totals"]
        assert without == with_rates


class TestRowContributions:
    """The per-row view has to agree with the per-ledger totals it mirrors."""

    def test_every_bucket_total_is_reproduced_row_by_row(self, export):
        from app.engine.classify import row_contributions
        from app.engine.reports import BUCKET_KEYS, _all_rows, period_bounds

        period = period_bounds("month", date(2026, 8, 1))
        totals = reports._core(export.ds, period, "USD")
        summed = {key: 0 for key in BUCKET_KEYS}
        for row in _all_rows(export.ds):
            if not (period.start <= row.day <= period.end
                    and row.currency == "USD" and row.status.is_settled):
                continue
            for bucket, cents in row_contributions(row):
                summed[bucket] += cents
        for key in ("spend_cents", "fees_cents", "payin_cents", "payout_cents",
                    "transfer_to_wallet_cents"):
            assert summed[key] == totals[key], key

    def test_a_row_with_a_fee_column_feeds_two_buckets(self):
        from app.engine.classify import row_contributions
        from app.engine.models import WalletEvent
        from datetime import datetime

        row = WalletEvent(event_id="X", when=datetime(2026, 8, 21, 13, 27),
                          kind="debit", amount_cents=75_000, ref=None,
                          note="payout", fee_cents=-225)
        assert sorted(row_contributions(row)) == [("fees_cents", 225),
                                                  ("payout_cents", 75_000)]
