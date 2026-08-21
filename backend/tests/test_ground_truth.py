"""The graded core: engine output must equal the answer key, and must not flag
the near-miss transactions planted to catch over-flagging."""

from __future__ import annotations

from datetime import date

import pytest

from app.engine import anomaly, classify, reports
from app.engine.loader import load_account_pdf, load_dataset
from app.config import settings
from conftest import TODAY


def test_dataset_counts(analysis, truth):
    counts = truth["counts"]
    assert len(analysis.ds.account) == counts["account_txns"]
    assert len(analysis.ds.card) == counts["card_txns"]
    assert len(analysis.ds.wallet.events) == counts["wallet_events"]
    assert len(analysis.ds.emails) == counts["emails"]


def test_cashflow_totals_match(analysis, truth):
    buckets = classify.account_buckets(analysis.ds.account)
    for kind, expected in truth["cashflow_totals_cents"].items():
        assert buckets[kind]["total_cents"] == expected, kind
    card = classify.card_buckets(analysis.ds.card)
    for kind, expected in truth["card_totals_cents"].items():
        if expected == 0:
            assert kind not in card
        else:
            assert card[kind]["total_cents"] == expected, kind


def test_purchase_percentile_matches(analysis, truth):
    assert anomaly.purchase_p90_cents(analysis.ds) == truth["purchase_p90_cents"]


def test_wallet_gap_matches(analysis, truth):
    wallet = truth["wallet"]
    assert analysis.ds.wallet.computed_balance_cents == wallet["computed_cents"]
    assert analysis.ds.wallet.reported_balance_cents == wallet["reported_cents"]
    assert (analysis.ds.wallet.computed_balance_cents
            - analysis.ds.wallet.reported_balance_cents) == wallet["gap_cents"]


def test_every_expected_finding_is_present(analysis, truth):
    """Recall: all 15 planted findings, each with the expected label."""
    by_kind: dict[str, list] = {}
    for finding in analysis.findings:
        by_kind.setdefault(finding.kind.value, []).append(finding)

    for expected in truth["expected_findings"]:
        kind = expected["kind"]
        candidates = by_kind.get(kind, [])
        assert candidates, f"no finding of kind {kind}"

        def picked(field: str, value):
            return [f for f in candidates if f.params.get(field) == value]

        if "merchant" in expected:
            candidates = picked("merchant", expected["merchant"]) or candidates
        if "descriptor" in expected:
            candidates = [f for f in candidates
                          if expected["descriptor"] in str(
                              f.params.get("descriptor", ""))] or candidates
        if "from_addr" in expected:
            candidates = picked("from_addr", expected["from_addr"]) or candidates

        match = candidates[0]
        assert match.label.value == expected["label"], f"{kind} label"
        if "amount_cents" in expected:
            assert match.amount_cents == expected["amount_cents"], f"{kind} amount"
        if "txn_ids" in expected and expected["txn_ids"]:
            assert set(expected["txn_ids"]).issubset(set(match.txn_ids)), \
                f"{kind} refs"
        if "occurred_on" in expected:
            assert match.occurred_on.isoformat() == expected["occurred_on"]
        for field in ("charge_count", "charges_without_receipt", "next_charge",
                      "old_amount_cents", "new_amount_cents", "effective_on",
                      "seconds_apart", "counterparty", "count"):
            if field in expected:
                assert match.params.get(field) == expected[field], f"{kind}.{field}"


def test_no_extra_findings(analysis, truth):
    """Precision: nothing beyond the answer key is flagged."""
    assert len(analysis.findings) == truth["counts"]["expected_findings"]


def test_near_misses_are_not_flagged(analysis, truth):
    """The planted look-alikes must stay unflagged."""
    alert_refs: set[str] = set()
    for finding in analysis.findings:
        if finding.kind.value in {"recurring_subscription"}:
            continue
        alert_refs.update(finding.txn_ids)
    for group in truth["must_not_flag"]:
        overlap = alert_refs & set(group["txn_ids"])
        assert not overlap, f"{group['reason']}: {sorted(overlap)} was flagged"


def test_labels_are_only_the_three_allowed(analysis):
    allowed = {"recurring_confirmed", "needs_your_confirmation",
               "insufficient_data"}
    assert {f.label.value for f in analysis.findings} <= allowed


def test_every_finding_has_sources_and_deadline(analysis):
    for finding in analysis.findings:
        assert finding.sources, f"{finding.kind} has no source"
        assert finding.dispute_deadline == date(2026, 10, 4)
        assert finding.days_left(TODAY) == 46


@pytest.mark.parametrize("period_key", ["2026-06", "2026-07"])
def test_monthly_reports_match(analysis, truth, period_key):
    expected = truth["reports"][period_key]
    report = reports.build(analysis.ds, "month", period_key)
    totals = report["totals"]
    assert totals["spend_cents"] == expected["spend_cents"]
    assert totals["fees_cents"] == expected["fees_cents"]
    assert totals["payin_cents"] == expected["payin_cents"]
    assert totals["payout_cents"] == expected["payout_cents"]
    assert [(row["ref"], row["amount_cents"]) for row in report["top_purchases"]] \
        == [(row["ref"], row["amount_cents"]) for row in expected["top3"]]


def test_quarter_and_year_are_consistent_with_months(analysis):
    """A quarter must equal the sum of its months — catches period-boundary bugs."""
    quarter = reports.build(analysis.ds, "quarter", "2026-Q2")
    months = [reports.build(analysis.ds, "month", key)
              for key in ("2026-04", "2026-05", "2026-06")]
    assert quarter["totals"]["spend_cents"] == sum(
        m["totals"]["spend_cents"] for m in months)
    assert quarter["totals"]["fees_cents"] == sum(
        m["totals"]["fees_cents"] for m in months)


def test_subscription_forecasts_match(analysis, truth):
    expected = {row["merchant"]: row for row in truth["expected_findings"]
                if row["kind"] == "recurring_subscription"}
    assert len(analysis.subs) == len(expected)
    for sub in analysis.subs:
        row = expected[sub.merchant_name]
        assert sub.current_amount_cents == row["amount_cents"]
        assert len(sub.charges) == row["charge_count"]
        assert sub.next_charge.isoformat() == row["next_charge"]


def test_pdf_statement_matches_the_csv(analysis):
    """The PDF path is real: same rows, same amounts as the CSV."""
    pdf_rows = load_account_pdf(settings.data_dir / "account_statement.pdf")
    assert [t.txn_id for t in pdf_rows] == [t.txn_id for t in analysis.ds.account]
    assert (sum(t.amount_cents for t in pdf_rows)
            == sum(t.amount_cents for t in analysis.ds.account))


def test_analysis_from_pdf_finds_the_same_account_side_items():
    """Loading the statement from PDF instead of CSV yields the same findings."""
    from app.engine import pipeline as pipeline_module

    pdf_analysis = pipeline_module.run(use_pdf=True)
    account_kinds = {"double_fee", "duplicate_payin", "transfer_not_on_card",
                     "wallet_balance_mismatch"}
    found = {f.kind.value for f in pdf_analysis.findings} & account_kinds
    assert found == account_kinds
