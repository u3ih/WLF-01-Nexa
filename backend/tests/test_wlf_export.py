"""Tests against the real Wealify export in `dataset/`.

The rest of the suite runs on the generated sample (`conftest.py` repoints
`settings.data_dir` at `data/sample`, which is the only input `ground_truth.json`
describes). Nothing currently asserts anything about the export the running app
actually serves, so the checks below pin that input directly by passing an
explicit `data_dir` to `pipeline.run` — they neither read nor mutate the
`settings.data_dir` the session fixture owns.

They are grouped by the requirement they cover:

* `TestExportLoads`      — the loader's documented decisions about this export.
* `TestFiveCashFlows`    — requirement 1: money in / out / to-card / fees / spend.
* `TestCategoryLabels`   — requirement 1's classification, as the user sees it.
* `TestCancelGuardrail`  — the read-only promise, on plural phrasings.
* `TestEveryLedgerIsReachableByReference`
                         — a lookup by reference reaches the wallet ledger too.
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path

import pytest

from app.engine import pipeline
from app.engine.classify import fee_cents, wallet_only_events
from app.engine.merchants import RULES
from app.engine.models import CardTxnType
from app.engine.render import bucket_scope_note, excluded_lines, t
from app.engine.reports import BUCKET_KEYS
from app.llm.guardrails import BlockedIntent, classify_intent
from app.llm.tools import _ledger_rows
from app.mailer import build_report_body

BACKEND_ROOT = Path(__file__).resolve().parent.parent
EXPORT_DIR = BACKEND_ROOT.parent / "dataset"
I18N_DIR = BACKEND_ROOT / "app" / "i18n"

# The export is denominated in USD and its rows span these dates; a whole-year
# window keeps the totals independent of `statement_date` drifting.
YEAR_START = date(2026, 1, 1)
YEAR_END = date(2026, 12, 31)


@lru_cache
def _export():
    """The real export, analysed once for the whole module."""
    if not (EXPORT_DIR / "transactions_card.csv").exists():
        pytest.skip(f"Wealify export not present at {EXPORT_DIR}")
    return pipeline.run(EXPORT_DIR)


@pytest.fixture(scope="module")
def analysis():
    return _export()


# --------------------------------------------------------------- loader shape


class TestExportLoads:
    """What the loader promises in its module docstring, asserted."""

    def test_card_wallet_and_mailbox_all_carry_rows(self, analysis):
        assert len(analysis.ds.card) == 244
        assert analysis.ds.wallet is not None
        assert len(analysis.ds.wallet.events) == 168
        assert len(analysis.ds.emails) == 135
        assert len(analysis.ds.cards) > 0
        assert len(analysis.ds.virtual_accounts) == 8

    def test_stale_va_file_is_skipped_rather_than_parsed(self, analysis):
        """`transactions_va.csv` duplicates the card rows in an older schema.

        Parsing it would double every card figure, so the loader drops it. The
        skip must stay visible in `notes` — an unexplained empty account ledger
        is indistinguishable from a load failure.
        """
        assert analysis.ds.account == []
        notes = " ".join(analysis.ds.notes)
        assert "transactions_va.csv was skipped" in notes

    def test_no_account_ledger_is_reported_as_insufficient_data(self, analysis):
        """The export ships account totals but no account rows.

        The brief's account-level checks therefore cannot be computed, and the
        answer owes the user that caveat instead of a silent zero.
        """
        notes = " ".join(analysis.ds.notes)
        assert "ships no transaction rows" in notes
        assert "insufficient data" in notes


# ------------------------------------------------- requirement 1: five flows


class TestFiveCashFlows:
    """Requirement 1: *tách rõ các dòng tiền*.

    Five buckets must be told apart: money in, money out, transfer to card,
    fees, and spending. `_core` in `reports.py` derives four of them from
    `ds.account`, which this export does not have — so they read $0 even though
    the wallet and card ledgers carry exactly those flows.
    """

    def test_spending_is_separated(self, analysis):
        """The one bucket that is wired to the card ledger."""
        totals = analysis.cashflow["totals"]
        assert totals["spend_cents"] == 1143940

    def test_card_ledger_does_carry_the_missing_flows(self, analysis):
        """Precondition for the three failures below — the data is present.

        49 loads worth $13,034 moved onto cards and the wallet was credited
        $87,192.95. Any report that calls these flows zero is not reporting an
        empty month, it is reading the wrong ledger.
        """
        groups = analysis.cashflow["card"]
        assert groups["load"]["count"] == 49
        assert groups["load"]["total_cents"] == 1303400
        assert analysis.tri.wallet["credits_cents"] == 8719295
        assert analysis.tri.wallet["debits_cents"] == 8570679

    def test_money_in_is_separated(self, analysis):
        """*tiền vào* — the wallet was credited $87,192.95 across 168 events."""
        assert analysis.cashflow["totals"]["payin_cents"] > 0

    def test_money_out_is_separated(self, analysis):
        """*tiền ra* — $85,706.79 of wallet debits, plus a $250 withdrawal."""
        assert analysis.cashflow["totals"]["payout_cents"] > 0

    def test_transfer_to_card_is_separated(self, analysis):
        """*chuyển sang thẻ* — must equal the card-load total, not zero.

        `tri_source` matches these transfers one by one (it is what raises the
        `transfer_not_on_card` findings), so the figure is already computed
        elsewhere in the same analysis.
        """
        totals = analysis.cashflow["totals"]
        assert totals["transfer_to_card_cents"] == \
            analysis.cashflow["card"]["load"]["total_cents"]

    def test_fees_are_separated_and_agree_with_the_fee_findings(self, analysis):
        """*phí* — a `double_fee` finding and a $0 fee total cannot both hold.

        Asserted in the finding's own currency, not in USD. Every fee in this
        export is one of the 22 EUR FX-fee lines, and the only USD fee is the
        $2.25 on `WCW082126621016`, which is still pending. `exchange_rate`
        reads `NaN = 1 USD` on every row, so there is no rate to restate the
        EUR fees with: demanding `fee_cents(..., "USD") > 0` would demand the
        engine invent one.

        What the requirement actually forbids is a fee vanishing. So the total
        in the finding's currency must count it, and `excluded` must carry it
        into a USD report — a bare "$0.00 in fees" reads as "you paid none".
        """
        fee_findings = [f for f in analysis.findings
                        if "fee" in f.kind.value]
        assert fee_findings, "expected the seeded double-fee anomaly"
        for finding in fee_findings:
            currency = finding.params["currency"]
            total = fee_cents(analysis.ds, YEAR_START, YEAR_END, currency)
            assert total >= finding.params["total_cents"], (
                f"{finding.kind.value} sees {finding.params['total_cents']} "
                f"{currency} of fees the total does not count"
            )

        report = pipeline.report_for(analysis, "month", "2026-06")
        assert report["totals"]["fees_cents"] == 0, "the seeded pair is EUR"
        hidden = {row["currency"]: row["fees_cents"]
                  for row in report["excluded"]["other_currencies"]}
        assert hidden.get("EUR", 0) > 0, \
            "a USD report showing $0.00 must still disclose the EUR fees"

    def test_the_five_buckets_are_not_all_collapsed_onto_one(self, analysis):
        """The brief asks for a separation, so at most one bucket may be empty.

        A single populated bucket out of five is a classification that has not
        happened, whatever the individual totals are.
        """
        totals = analysis.cashflow["totals"]
        buckets = ("spend_cents", "fees_cents", "payin_cents",
                   "payout_cents", "transfer_to_card_cents")
        populated = [b for b in buckets if totals[b] != 0]
        assert len(populated) >= 4, f"only {populated} carry a figure"

    def test_the_monthly_report_agrees_with_the_whole_period_classification(
            self, analysis):
        """`reports._core` and `classify._totals` must not drift apart again.

        They were separate implementations of the same five buckets, and only
        one of them was ever fixed. Summing the months has to reproduce the
        dataset-wide figure, or the report and the cash-flow table are telling
        the user two different stories about the same ledger.
        """
        months = [f"2026-{m:02d}" for m in range(1, 13)]
        for bucket in ("payin_cents", "payout_cents", "spend_cents"):
            monthly = sum(pipeline.report_for(analysis, "month", key)
                          ["totals"][bucket] for key in months)
            assert monthly == analysis.cashflow["totals"][bucket], \
                f"{bucket}: months sum to {monthly}"

    def test_card_withdrawals_leave_the_platform_like_any_payout(self,
                                                                 analysis):
        """`CardTxnType.WITHDRAW` belonged to no bucket at all.

        $250 came off a card on 2026-08-15 and appeared in no total: not spend,
        not payout, not a transfer. Money cannot leave without being reported.
        """
        withdrawals = [c for c in analysis.ds.card
                       if c.type is CardTxnType.WITHDRAW and c.is_settled]
        assert withdrawals, "expected the seeded card withdrawal"
        august = pipeline.report_for(analysis, "month", "2026-08")["totals"]
        wallet_side = sum(e.amount_cents for e in wallet_only_events(analysis.ds)
                          if e.note == "payout" and e.is_settled
                          and e.currency == "USD"
                          and e.day.strftime("%Y-%m") == "2026-08")
        assert august["payout_cents"] == wallet_side + sum(
            abs(c.amount_cents) for c in withdrawals
            if c.day.strftime("%Y-%m") == "2026-08")

    def test_wallet_top_ups_from_a_card_are_a_transfer_not_a_payin(self,
                                                                   analysis):
        """`card_to_wallet` had no bucket either, so $500 simply vanished.

        It is not a payin: the money never came from outside, it came off the
        user's own card. Filing it as one would inflate *tiền vào* with the
        user's own balance moving between two of their own pockets.
        """
        august = pipeline.report_for(analysis, "month", "2026-08")["totals"]
        assert august["transfer_to_wallet_cents"] == 50000
        payins = [e for e in wallet_only_events(analysis.ds)
                  if e.note == "payin" and e.is_settled
                  and e.day.strftime("%Y-%m") == "2026-08"]
        assert august["payin_cents"] == sum(e.amount_cents for e in payins)

    def test_the_transfer_gap_between_the_two_ledgers_stays_visible(self,
                                                                    analysis):
        """The wallet says it sent more to cards than the cards received.

        $15,686.02 out against $13,034.00 in. Reporting either figure alone as
        *chuyển sang thẻ* hides the difference, which is the part with findings
        attached to it.
        """
        totals = analysis.cashflow["totals"]
        assert totals["transfer_to_card_sent_cents"] > \
            totals["transfer_to_card_cents"]
        assert totals["transfer_to_card_gap_cents"] == \
            totals["transfer_to_card_sent_cents"] - \
            totals["transfer_to_card_cents"]


class TestNothingIsDroppedSilently:
    """A single-currency, settled-only report has to say what it set aside."""

    def test_a_usd_report_discloses_the_currencies_it_left_out(self, analysis):
        """August spent €57.54 that a USD-only report shows nowhere."""
        excluded = pipeline.report_for(analysis, "month", "2026-08")["excluded"]
        assert excluded["reporting_currency"] == "USD"
        eur = next(row for row in excluded["other_currencies"]
                   if row["currency"] == "EUR")
        assert eur["spend_cents"] == 5754

    def test_unsettled_rows_are_listed_rather_than_just_omitted(self, analysis):
        """Correctly excluded from the totals, still owed to the user."""
        excluded = pipeline.report_for(analysis, "month", "2026-08")["excluded"]
        refs = {row["ref"]: row for row in excluded["unsettled"]}
        assert refs["WCW082126621016"]["in_flight"] is True
        assert refs["WCW082126621016"]["amount_cents"] == 75000

    @pytest.mark.parametrize("lang", ["vi", "en"])
    def test_the_caveat_renders_in_both_languages(self, analysis, lang):
        """August: "Phí: $0.00" beside €0.58 of fees and $768.93 in flight.

        The zero and the caveat have to travel together, so the sentence is
        rendered from the same `excluded` block every consumer prints, in
        whichever language the totals beside it are in.
        """
        report = pipeline.report_for(analysis, "month", "2026-08")
        lines = excluded_lines(report["excluded"], lang)
        assert any("EUR" in line and "0.58" in line for line in lines)
        assert any("768.93" in line for line in lines)

    def test_the_emailed_report_prints_the_caveat(self, analysis, monkeypatch):
        """A caveat only the API payload carries is a caveat nobody reads.

        `build_report_body` reads `pipeline.cached()`, which the session fixture
        points at `data/sample` — a dataset that excludes nothing, so it cannot
        show whether the wiring works. Pointed at this export instead, where
        August hides €0.58 of fees behind a "$0.00".
        """
        monkeypatch.setattr(pipeline, "cached", lambda *a, **k: analysis)
        caveats = excluded_lines(
            pipeline.report_for(analysis, "month", "2026-08")["excluded"], "vi")
        assert caveats, "August excludes both a currency and two pending rows"
        body = build_report_body("vi", "month", "2026-08")["body"]
        assert t("vi", "excluded.head") in body
        for line in caveats:
            assert line in body

    def test_a_zero_carries_its_scope_on_its_own_line(self, analysis):
        """"Phí: $0.00" and "phí €0.58" in one report is a contradiction.

        Both are true — the first is USD-only — but the zero is read six lines
        before the explanation, and by then the user has concluded there were no
        fees. The currencies a bucket does not cover belong beside the bucket.
        """
        report = pipeline.report_for(analysis, "month", "2026-08")
        excluded = report["excluded"]
        assert report["totals"]["fees_cents"] == 0
        assert "0.58" in bucket_scope_note("fees_cents", excluded, "vi")
        assert "57.54" in bucket_scope_note("spend_cents", excluded, "vi")
        # A bucket with nothing hidden behind it stays unannotated, or the note
        # becomes noise and stops meaning anything where it does matter.
        assert bucket_scope_note("payin_cents", excluded, "vi") == ""

    def test_every_bucket_is_tracked_per_currency_not_just_spend_and_fees(
            self, analysis):
        """A EUR payin would have hidden behind "Tiền vào: $0.00" too.

        `excluded` originally carried only spend and fees, so the other four
        buckets had no way to declare a currency they did not cover.
        """
        excluded = pipeline.report_for(analysis, "month", "2026-08")["excluded"]
        eur = next(row for row in excluded["other_currencies"]
                   if row["currency"] == "EUR")
        for bucket in BUCKET_KEYS:
            assert bucket in eur, f"{bucket} cannot declare what it left out"

    def test_the_transaction_count_is_counted_like_the_money(self, analysis):
        """`txn_count` read two ledgers while the totals summed three.

        It also ignored the currency and settlement filters every figure beside
        it applies, so it reported rows the report had deliberately excluded.
        """
        report = pipeline.report_for(analysis, "month", "2026-08")
        totals = report["totals"]
        assert totals["txn_count"] < totals["all_txn_count"]
        assert (totals["all_txn_count"] - totals["txn_count"]
                == len(report["excluded"]["unsettled"])
                + sum(row["txn_count"]
                      for row in report["excluded"]["other_currencies"]))


# ---------------------------------------- requirement 1: user-visible labels


class TestCategoryLabels:
    """Every category the classifier can emit needs a translation.

    `_period_categories` labels each bucket with `category.<key>`. A key with no
    entry falls through to the UI verbatim, so the user reads
    "category.travel" where a category name belongs.
    """

    @pytest.mark.parametrize("lang", ["vi", "en"])
    def test_every_merchant_category_has_a_label(self, lang):
        import json

        strings = json.loads((I18N_DIR / f"{lang}.json").read_text())
        categories = sorted({rule.merchant.category for rule in RULES})
        missing = [c for c in categories if f"category.{c}" not in strings]
        assert missing == [], f"{lang}.json has no label for {missing}"

    def test_no_reported_category_leaks_its_key(self, analysis):
        """The same gap, observed on the export rather than on the rule table."""
        import json

        strings = json.loads((I18N_DIR / "vi.json").read_text())
        leaked = [row["category"] for row in analysis.cashflow["categories"]
                  if f"category.{row['category']}" not in strings]
        assert leaked == [], f"unlabelled categories reach the UI: {leaked}"


# ----------------------------------------------- the read-only promise


class TestCancelGuardrail:
    """"No action on money" has to survive ordinary paraphrase.

    `CANCEL_SUBSCRIPTION`'s object group is
    `\\b(subscription|plan|membership|...)\\b`. The trailing `\\b` fails on the
    plural, so "cancel my subscriptions" misses while "cancel my subscription"
    matches — and a missed hard-intent request is answered instead of refused.
    """

    @pytest.mark.parametrize("question", [
        "Cancel my unused subscriptions for me",
        "cancel my plans",
        "stop these subscriptions",
        "end my memberships",
        "Unsubscribe me from these plans",
    ])
    def test_plural_cancellation_requests_are_blocked(self, question):
        decision = classify_intent(question)
        assert decision.intent is BlockedIntent.CANCEL_SUBSCRIPTION, \
            f"not recognised as a cancellation request: {question!r}"

    @pytest.mark.parametrize("question", [
        "Cancel my subscription",
        "Cancel my Netflix plan",
        "Tự huỷ mấy gói không dùng đi",
        "Huỷ gói Netflix giúp mình",
    ])
    def test_singular_and_vietnamese_phrasings_stay_blocked(self, question):
        """Regression guard: widening the pattern must not lose these."""
        decision = classify_intent(question)
        assert decision.intent is BlockedIntent.CANCEL_SUBSCRIPTION

    @pytest.mark.parametrize("question", [
        "Mình đang có những gói đăng ký định kỳ nào?",
        "Which subscriptions raised their price?",
        "How do I cancel Netflix myself?",
    ])
    def test_questions_about_subscriptions_are_still_answered(self, question):
        """Widening the pattern must not start refusing read-only questions."""
        decision = classify_intent(question)
        assert decision.intent is not BlockedIntent.CANCEL_SUBSCRIPTION \
            or decision.guidance_request


# ------------------------------------------------------------- ref lookup


class TestEveryLedgerIsReachableByReference:
    """`search_transactions` and `explain_charge` must see all three ledgers.

    Both read the same flattened row list. When it covered only the statement
    and the card ledger, the 168 rows this export files under
    `source_type = Ví` had no row to match, so a reference the user read off
    their own statement came back as "0 giao dịch tìm thấy".
    """

    def test_every_row_of_every_ledger_is_present(self, analysis):
        rows = _ledger_rows(analysis)
        assert len(rows) == (len(analysis.ds.account) + len(analysis.ds.card)
                             + len(analysis.ds.wallet.events))

    @pytest.mark.parametrize("ref", [
        "TW082026786190",       # wallet top-up from a card
        "WCW082126621016",      # wallet payout to a crypto address
        "WLF15-WL-0004",        # wallet credit from a payout provider
        "WLF15-CD-0025",        # card ledger, the shape that always worked
    ])
    def test_reference_shapes_the_export_uses_all_resolve(self, analysis, ref):
        assert ref in {r["ref"] for r in _ledger_rows(analysis)}

    def test_wallet_debits_stay_negative(self, analysis):
        """The wallet stores a magnitude plus a direction, the row a signed
        amount. Copying `amount_cents` across would report a $750 withdrawal
        as $750 of income."""
        rows = {r["ref"]: r for r in _ledger_rows(analysis)}
        assert rows["WCW082126621016"]["amount_cents"] < 0
        assert rows["TW082026786190"]["amount_cents"] > 0

    def test_every_flow_type_has_a_label(self, analysis):
        """A row whose type has no i18n entry renders as `cashflow.<key>`."""
        for row in _ledger_rows(analysis):
            key = f"cashflow.{row['type']}"
            assert t("vi", key) != key, f"no Vietnamese label for {key}"
            assert t("en", key) != key, f"no English label for {key}"
