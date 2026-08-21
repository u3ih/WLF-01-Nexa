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
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path

import pytest

from app.engine import pipeline
from app.engine.classify import fee_cents
from app.engine.merchants import RULES
from app.llm.guardrails import BlockedIntent, classify_intent

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

        The anomaly pass flags WLF15-CD-0216/0217 as the same fee charged twice,
        so at least those cents are fees; `fee_cents` nonetheless returns 0
        because no card row carries `fee_cents` (the export writes
        `NaN undefined` in the column, which the loader correctly reads as
        absent). The fee a finding can see must be a fee the total counts.
        """
        fee_findings = [f for f in analysis.findings
                        if "fee" in f.kind.value]
        assert fee_findings, "expected the seeded double-fee anomaly"
        assert fee_cents(analysis.ds, YEAR_START, YEAR_END, "USD") > 0

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
