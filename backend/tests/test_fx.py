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
from app.engine.render import bucket_note, conversion_lines, excluded_lines

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
        assert eur["folded_in"] is False
        assert "≈" not in bucket_note("fees_cents", report, "vi")

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
        lines = conversion_lines(report["totals"], "vi")
        assert any("1.154" in line and "2026-08-11" in line for line in lines)

    def test_a_partly_covered_period_says_so_instead_of_under_reporting(self,
                                                                        export):
        """July has six EUR rows; one rate covers some of them and not others.

        The danger is a total that silently omits the rows it could not price
        and still looks like a complete figure. So a partial conversion is not
        folded in at all: the currency stays outside the totals and says why.
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
        assert eur["folded_in"] is False
        assert report["totals"]["converted_from"] == []
        assert report["totals"]["conversion_complete"] is False
        assert any("chưa quy đổi" in line
                   for line in excluded_lines(report["excluded"], "vi"))

    def test_a_fully_priced_currency_is_added_to_the_headline_figures(
            self, export):
        """"$986.81 — chưa gồm €57.54 (≈$66.40)" made the reader do the sum.

        Once every euro row has a published rate for its own date there is
        nothing left to hold them out of the total, so August's spending is one
        figure: $986.81 of USD rows plus $66.40 restated from euro.
        """
        without = reports.build(export.ds, "month", "2026-08",
                                export.subs_forecast, fx.EMPTY)["totals"]
        totals = reports.build(export.ds, "month", "2026-08",
                               export.subs_forecast,
                               self.AUGUST_RATE)["totals"]
        assert without["spend_cents"] == 98681
        assert totals["spend_cents"] == 98681 + 6640
        assert totals["fees_cents"] == 0 + 67
        assert totals["conversion_complete"] is True
        # The count moves with the money, or the two describe different periods.
        assert totals["txn_count"] == without["txn_count"] + 2

    def test_the_parts_of_a_combined_total_stay_beside_it(self, export):
        """A restated total still has to be checkable against the statement.

        The statement will show €57.54, not $66.40, so the total names both the
        figure the ledger carries and the amount conversion contributed rather
        than replacing one with the other.
        """
        totals = reports.build(export.ds, "month", "2026-08",
                               export.subs_forecast,
                               self.AUGUST_RATE)["totals"]
        assert totals["native"]["spend_cents"] == 98681
        assert totals["converted_in"]["spend_cents"] == 6640
        assert totals["native"]["spend_cents"] \
            + totals["converted_in"]["spend_cents"] == totals["spend_cents"]
        eur = next(row for row in totals["converted_from"]
                   if row["currency"] == "EUR")
        assert eur["native"]["spend_cents"] == 5754
        assert eur["converted"]["spend_cents"] == 6640
        # Said on the figure's own line, not four bullets below it.
        note = bucket_note("spend_cents", {"totals": totals}, "vi")
        assert "57.54" in note and "66.40" in note

    def test_the_comparison_puts_both_periods_on_one_basis(self, export):
        """A converted month against an unconverted one is not a change.

        July and August both carry euro rows. If only the current period folded
        them in, the month-on-month figure would move by the conversion rather
        than by any spending.
        """
        july_and_august = fx.FxTable([
            fx.FxQuote("EUR", "USD", date(2026, 7, 1), Decimal("1.15")),
            fx.FxQuote("EUR", "USD", date(2026, 8, 11), Decimal("1.154")),
        ])
        report = reports.build(export.ds, "month", "2026-08",
                               export.subs_forecast, july_and_august)
        july = reports.build(export.ds, "month", "2026-07",
                             export.subs_forecast, july_and_august)["totals"]
        spend = report["comparison"]["spend"]
        assert spend["previous_cents"] == july["spend_cents"]
        assert spend["delta_cents"] == \
            report["totals"]["spend_cents"] - july["spend_cents"]

    def test_a_converted_currency_stops_being_called_excluded(self, export):
        """It is in the totals now, so the caveat must not still deny it.

        The row stays in `excluded` as an audit trail — the wording is what
        changes, or the report would print the euro spend inside the total and
        underneath it that the total does not include it.
        """
        report = reports.build(export.ds, "month", "2026-08",
                               export.subs_forecast, self.AUGUST_RATE)
        eur = next(row for row in report["excluded"]["other_currencies"]
                   if row["currency"] == "EUR")
        assert eur["folded_in"] is True
        caveats = excluded_lines(report["excluded"], "vi")
        assert not any("EUR" in line for line in caveats)
        # The unsettled rows are a different exclusion and still stand.
        assert any("768.93" in line for line in caveats)
        assert "chưa gồm" not in bucket_note("spend_cents", report, "vi")


class TestTheApiPublishesEachFigureInItsOwnCurrency:
    """Folding euro rows into a total put euro cents in the payload.

    Every `*_cents` used to be published as dollars, which was true while the
    report was single-currency and stopped being true the moment it named the
    original amount beside the restated one.
    """

    def test_a_block_that_names_a_currency_is_formatted_in_it(self):
        from app.serialize import to_dollars

        out = to_dollars({"currency": "EUR", "spend_cents": 5754}, "vi")
        assert out["spend"] == "€57.54"
        # Not `spend_usd`: the number is euros, and the field name is read as a
        # claim about which.
        assert out["spend_amount"] == 57.54
        assert "spend_usd" not in out

    def test_a_nested_block_may_state_a_different_currency(self):
        """€57.54 and its $66.40 equivalent are siblings in the payload."""
        from app.serialize import to_dollars

        out = to_dollars({
            "currency": "EUR",
            "spend_cents": 5754,
            "converted": {"currency": "USD", "spend_cents": 6640},
        }, "en")
        assert out["spend"] == "€57.54"
        assert out["converted"]["spend"] == "$66.40"

    def test_a_block_with_no_currency_still_publishes_dollars(self):
        """The existing shape, unchanged: this export is denominated in USD."""
        from app.serialize import to_dollars

        out = to_dollars({"spend_cents": 98681}, "en")
        assert out["spend_usd"] == 986.81
        assert out["spend_usd_text"] == "$986.81"


class TestTheEmailCarriesTheRestatedFigures:
    def test_the_draft_prints_the_total_and_the_rate_behind_it(self, export,
                                                              monkeypatch):
        """A restated total only the API payload can justify is unauditable.

        August's spending line is $1,053.21 — $986.81 of USD rows plus €57.54
        restated — and the email has to carry the rate that made it one figure.
        """
        from app.engine import pipeline as pipeline_module
        from app.mailer import build_report_body

        rates = TestTheReportUsesTheRates.AUGUST_RATE
        priced = reports.build(export.ds, "month", "2026-08",
                               export.subs_forecast, rates)
        # Restored afterwards: the export fixture is shared by every test in
        # this module, and one that quietly left rates on it would decide
        # whether the others convert.
        monkeypatch.setattr(export, "fx", rates)
        monkeypatch.setattr(pipeline_module, "cached", lambda *a, **k: export)
        body = build_report_body("vi", "month", "2026-08")["body"]

        assert "$1,053.21" in body
        assert priced["totals"]["spend_cents"] == 105321
        for line in conversion_lines(priced["totals"], "vi"):
            assert line in body
        assert "1.154" in body


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


class TestTheDongDisplayRate:
    """The ₫ beside every USD amount, and what it is allowed to claim.

    A different problem from the report's row-by-row restatement. That one is
    dated by the transaction and refuses to guess; this one is a reading aid on
    a figure whose real currency is printed right beside it, so it may use the
    newest rate held — but it may never let a reader believe a constant from a
    settings file is a market rate.
    """

    QUOTE = fx.FxQuote("USD", "VND", FRIDAY, Decimal("25891.59"),
                       source="currency-api")

    @pytest.fixture(autouse=True)
    def _clean_hold(self):
        fx.reset_display_cache()
        yield
        fx.reset_display_cache()

    def test_the_newest_rate_is_used_however_old_it_is(self):
        """`rate_on` would decline this; a display conversion should not.

        A fortnight-old publication still beats a number compiled into the
        settings file, and the note carries the date either way.
        """
        table = fx.FxTable([self.QUOTE])
        assert table.rate_on(date(2026, 9, 30), "USD", "VND") is None
        assert table.latest("USD", "VND").rate == Decimal("25891.59")

    def test_the_reverse_direction_is_derived_not_refetched(self):
        table = fx.FxTable([self.QUOTE])
        found = table.latest("VND", "USD")
        assert found.inverted is True
        assert found.rate == Decimal(1) / Decimal("25891.59")

    def test_an_unreachable_store_falls_back_instead_of_raising(self):
        """Postgres down must cost the ₫ figure its basis, not the ₫ figure."""
        class Broken:
            def fx_quotes(self):
                raise RuntimeError("no database")

        assert fx.display_quote(store=Broken()) is None

    def test_the_store_is_read_once_per_process(self):
        reads = []

        class Counting:
            def fx_quotes(self):
                reads.append(1)
                return [{"base": "USD", "quote": "VND", "quoted_on": FRIDAY,
                         "rate": Decimal("25891.59"), "source": "currency-api"}]

        assert fx.display_quote(store=Counting()).rate == Decimal("25891.59")
        assert fx.display_quote(store=Counting()).rate == Decimal("25891.59")
        assert len(reads) == 1

    def test_a_fetched_rate_carries_the_publications_own_date(self, monkeypatch):
        """Not the date asked for: the two differ, and the difference matters."""
        import httpx

        class Response:
            def raise_for_status(self): pass
            def json(self):
                return {"date": "2026-08-14", "usd": {"vnd": 25891.59169751}}

        monkeypatch.setattr(httpx, "get", lambda *a, **k: Response())
        found = fx.fetch_display_quote("USD", "VND", day=date(2026, 8, 15))
        assert found.quoted_on == FRIDAY
        assert found.rate == Decimal("25891.59169751")
        assert found.source == fx.DISPLAY_SOURCE

    def test_a_dead_host_is_tried_past_not_raised_through(self, monkeypatch):
        """One publication behind two addresses. A dead one costs a retry."""
        import httpx

        tried = []

        class Response:
            def raise_for_status(self): pass
            def json(self):
                return {"date": "2026-08-14", "usd": {"vnd": 25891.59}}

        def flaky(url, **kwargs):
            tried.append(url)
            if len(tried) == 1:
                raise RuntimeError("cdn unreachable")
            return Response()

        monkeypatch.setattr(httpx, "get", flaky)
        assert fx.fetch_display_quote().rate == Decimal("25891.59")
        assert len(tried) == 2

    def test_every_host_failing_declines_rather_than_raising(self, monkeypatch):
        import httpx

        def dead(url, **kwargs):
            raise RuntimeError("offline")

        monkeypatch.setattr(httpx, "get", dead)
        assert fx.fetch_display_quote() is None


class TestWhatTheDongFigureClaims:
    """The sentence under the ₫ figures has to match where the rate came from."""

    @pytest.fixture(autouse=True)
    def _clean_hold(self):
        fx.reset_display_cache()
        yield
        fx.reset_display_cache()

    def test_a_published_rate_is_named_with_its_source_and_date(self):
        from app.engine.render import fx_block

        fx.hold_display_quote(fx.FxQuote("USD", "VND", FRIDAY,
                                         Decimal("25891.59"),
                                         source="currency-api"))
        block = fx_block("vi")
        assert block["published"] is True
        assert block["quoted_on"] == "2026-08-14"
        # Grouped with dots, like every other ₫ figure in a Vietnamese answer.
        assert "25.892" in block["note"]
        assert "currency-api" in block["note"] and "2026-08-14" in block["note"]
        # The configured rate is not what is in use, so it is not what is named.
        assert "NEXA_USD_VND_RATE" not in block["note"]

    def test_without_one_the_note_says_the_rate_is_a_configured_constant(self):
        """The failure mode worth a separate string: a constant read as a rate."""
        from app.config import settings
        from app.engine.render import fx_block

        fx.hold_display_quote(None)
        block = fx_block("vi")
        assert block["published"] is False
        assert block["quoted_on"] is None
        assert block["vnd_rate"] == settings.usd_vnd_rate
        assert "NEXA_USD_VND_RATE" in block["note"]
        assert "Chưa lấy được tỷ giá công bố" in block["note"]

    def test_both_languages_say_the_same_thing_about_the_same_rate(self):
        from app.engine.render import fx_block

        fx.hold_display_quote(fx.FxQuote("USD", "VND", FRIDAY,
                                         Decimal("25891.59"),
                                         source="currency-api"))
        for lang, grouped in (("vi", "25.892"), ("en", "25,892")):
            note = fx_block(lang)["note"]
            assert grouped in note and "2026-08-14" in note

    def test_the_amount_is_converted_at_the_published_rate_not_the_constant(self):
        from app.engine.models import fmt_display

        fx.hold_display_quote(fx.FxQuote("USD", "VND", FRIDAY,
                                         Decimal("25891.59"),
                                         source="currency-api"))
        # $19.95 × 25,891.59 = 516,537 ₫, shown to the nearest thousand.
        assert fmt_display(1995, "vi") == "≈517.000 ₫ ($19.95)"

    def test_english_never_shows_dong_whatever_the_rate(self):
        from app.engine.models import fmt_display

        fx.hold_display_quote(fx.FxQuote("USD", "VND", FRIDAY,
                                         Decimal("25891.59")))
        assert fmt_display(1995, "en") == "$19.95"
