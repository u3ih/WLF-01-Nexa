"""The entity model against the Wealify CSV export in `dataset/`.

These tests pin the parts of that export that are easy to read wrong: the file
whose name does not match its contents, the placeholder text sitting in numeric
columns, the two decimal conventions, the status spellings, the type column
worded from the platform's side, and the mailbox where every message was
delivered by the same relay. Each assertion below corresponds to one of those.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.engine import anomaly, classify, email_match, pipeline, tri_source
from app.engine.loader_wlf import (
    _money,
    _rate,
    _status,
    _when,
    is_stale_duplicate,
    load_export_dataset,
)
from app.engine.merchants import resolve
from app.engine.models import CardTxnType, TxnStatus

DATA_DIR = Path(__file__).resolve().parents[2] / "dataset"

pytestmark = pytest.mark.skipif(
    not (DATA_DIR / "cards.csv").exists(),
    reason="dataset/ export not present",
)


@pytest.fixture(scope="module")
def ds():
    return load_export_dataset(DATA_DIR)


@pytest.fixture(scope="module")
def analysis():
    return pipeline.run(DATA_DIR)


# ------------------------------------------------------------------- parsing

def test_placeholders_never_become_numbers():
    """`NaN undefined` and `NaN = 1 USD` are absent data, not values."""
    assert _money("NaN undefined") is None
    assert _money("") is None
    assert _money("-") is None
    assert _rate("NaN = 1 USD") is None
    assert _rate("-") is None
    # A real figure still parses, thousands separator and currency suffix and all.
    assert _money("1,936.92 USD") == 193692
    assert _money("-2.25 USD") == -225


def test_the_two_decimal_conventions_are_kept_apart():
    """Transactions write `1,936.92`; the card table writes `49,7`."""
    assert _money("49,7", decimal_comma=True) == 4970
    assert _money("1617,02", decimal_comma=True) == 161702
    assert _money("49.7") == 4970


def test_every_date_shape_in_the_export_parses():
    assert _when("21/08/2026 | 01:27 PM").isoformat() == "2026-08-21T13:27:00"
    assert _when("14/8/26 14:00").isoformat() == "2026-08-14T14:00:00"
    assert _when("2026-06-07T21:10:00.000Z").isoformat() == "2026-06-07T21:10:00"
    # Day-first, always: 12/04 is April, not December.
    assert _when("12/04/2026 | 09:00 AM").month == 4
    assert _when("") is None
    assert _when("not a date") is None


def test_unrecognised_status_fails_closed():
    """A status this build does not know must not be counted as real money."""
    assert _status("Failure") is TxnStatus.FAILED
    assert _status("Cancel") is TxnStatus.CANCELLED
    assert _status("Processing") is TxnStatus.PROCESSING
    assert not _status("Quantum-superposed").is_settled


def test_stale_duplicate_is_detected_by_content_not_by_name():
    known = {"A-1", "A-2"}
    assert is_stale_duplicate([{"transaction_id": "A-1"}], known)
    assert is_stale_duplicate([], known)
    # A real receiving-account ledger under the same filename is still read.
    assert not is_stale_duplicate([{"transaction_id": "WLF15-VA-0001"}], known)
    assert not is_stale_duplicate([{"transaction_id": "B-9"}], known)


# ------------------------------------------------------------------ structure

def test_entity_tables_are_loaded(ds):
    assert len(ds.cards) == 7
    assert len(ds.virtual_accounts) == 8
    assert [c.code for c in ds.cards] == [f"VC0{n}" for n in range(1, 8)]
    eu = ds.card_by_code("VC04")
    assert eu.card_id == "CARD_0004" and eu.name == "Volcano EU"
    assert ds.card_by_code("VC05").status == "frozen"
    assert ds.card_by_code("VC06").status == "cancelled"


def test_card_table_money_uses_the_decimal_comma(ds):
    """`49,7` in the file is $49.70 — reading it as 497 cents loses a factor of ten."""
    old = ds.card_by_code("VC05")
    assert old.total_deposit_cents == 4970
    assert old.balance_cents == 200


def test_no_pan_and_no_phone_are_stored(ds):
    assert all(not c.card_number for c in ds.cards)
    assert all(c.masked.startswith("****") for c in ds.cards)
    assert not hasattr(ds.cards[0], "phone")


def test_masked_only_account_keeps_no_fake_number(ds):
    """One account ships a mask and no real number; the mask is not stored as one."""
    old = next(a for a in ds.virtual_accounts if a.label == "ETSY OLD")
    assert old.account_number == ""
    assert old.masked == "**************001"


def test_two_ledgers_are_split_from_one_file(ds):
    assert len(ds.card) == 244
    assert ds.wallet is not None and len(ds.wallet.events) == 168
    assert {c.ledger.value for c in ds.card} == {"card"}


def test_receiving_account_ledger_is_reported_as_absent(ds):
    """The export has account entities but no account rows, and says so."""
    assert ds.account == []
    assert all(not a.has_ledger for a in ds.virtual_accounts)
    assert any("no transaction rows" in n for n in ds.notes)
    assert any("transactions_va.csv was skipped" in n for n in ds.notes)


def test_placeholder_columns_land_as_none_on_every_row(ds):
    """`fee` and `exchange_rate` hold placeholders on every row that has them."""
    assert all(c.fee_cents is None for c in ds.card if c.card_code)
    assert all(c.fx_rate is None for c in ds.card)
    # The one row with a real fee is a wallet payout, not a card row.
    assert any(c.settled_amount_cents is not None for c in ds.card)


def test_self_referential_link_is_not_used_as_a_match_basis(ds):
    """`linked_transaction_id` points at the row itself, so it proves nothing."""
    assert all(not c.load_ref for c in ds.card)


def test_new_status_spellings_are_all_mapped(ds):
    statuses = {c.status for c in ds.card} | {e.status for e in ds.wallet.events}
    assert TxnStatus.FAILED in statuses        # "Failure"
    assert TxnStatus.CANCELLED in statuses     # "Cancel"
    assert TxnStatus.PROCESSING in statuses    # "Processing"
    assert TxnStatus.PENDING in statuses
    assert sum(1 for c in ds.card if not c.is_settled) == 19


def test_wallet_lines_are_typed_from_the_reference_not_the_label(ds):
    """`Tham chiếu` says nothing and `Rút tiền về ví` is money leaving."""
    notes = {e.note for e in ds.wallet.events}
    assert notes == {"payin", "transfer_to_card", "payout", "fee", "card_to_wallet"}
    to_card = [e for e in ds.wallet.events if e.note == "transfer_to_card"]
    assert len(to_card) == 48
    assert all(e.kind == "debit" and e.target_card_code for e in to_card)
    # The crypto payout is a payout, not a card load, despite the same type.
    crypto = next(e for e in ds.wallet.events if "Tron" in e.descriptor)
    assert crypto.note == "payout" and crypto.counterparty == "Tron"


def test_fx_fees_are_fees_not_purchases(ds):
    fx = [c for c in ds.card if c.type is CardTxnType.FEE]
    assert all(c.merchant_raw.lower().startswith("fx fee") for c in fx)
    assert len([e for e in ds.wallet.events if e.note == "fee"]) == 22


def test_currencies_are_kept_apart(ds):
    assert set(ds.currencies) == {"USD", "EUR"}
    cf = classify.classify(ds)
    assert cf["totals_by_currency"]["EUR"]["fees_cents"] > 0
    assert cf["totals_by_currency"]["USD"]["spend_cents"] > 0


def test_unsettled_rows_are_excluded_from_totals_but_still_listed(ds):
    cf = classify.classify(ds)
    purchases = cf["card"]["purchase"]
    assert purchases["settled_count"] < purchases["count"]
    assert purchases["unsettled"]
    assert all(u["status"] != "success" for u in purchases["unsettled"])


# --------------------------------------------------------------------- mailbox

def test_mailboxes_are_kept_apart_and_one_is_chosen(ds):
    assert set(ds.mailboxes) == {"tester", "senior", "junior"}
    # The inbox registered against the cards is the one analysed.
    assert ds.meta["mailbox"] == "tester"
    assert ds.owner_email == "wealifytester@yopmail.com"
    assert len(ds.emails) == len(ds.mailboxes["tester"]) == 135
    assert any("also present" in n for n in ds.notes)


def test_a_different_mailbox_can_be_selected():
    other = load_export_dataset(DATA_DIR, mailbox="junior")
    assert other.meta["mailbox"] == "junior"
    assert len(other.emails) == 152


def test_sender_is_read_from_the_body_not_the_envelope(ds):
    assert all(e.relay_from_addr == "no-reply@wealify.com" for e in ds.emails)
    senders = {e.from_addr for e in ds.emails}
    assert "no-reply@wea1ify-support.com" in senders
    assert "noreply@booking.com.com" in senders
    assert sum(1 for e in ds.emails if e.is_relayed) == 128


def test_recipient_is_not_swallowed_into_the_sender():
    """Bodies gained a `Người nhận:` line after the sender."""
    junior = load_export_dataset(DATA_DIR, mailbox="junior")
    assert all("@" in e.from_addr for e in junior.emails)
    assert all("Người nhận" not in e.from_addr for e in junior.emails)
    assert all(" " not in e.from_addr for e in junior.emails)
    dhl = next(e for e in junior.emails
               if e.from_addr == "delivery@dhl-express-track.com")
    assert dhl.to_addr == "wealifyjunior@yopmail.com"


def test_receipts_carry_their_reference_and_card(ds):
    refs = {e.txn_ref for e in ds.emails if e.txn_ref}
    assert len(refs) > 100
    assert {e.card_code for e in ds.emails if e.card_code} <= {
        "VC01", "VC02", "VC03", "VC04", "VC05", "VC06"
    }


def test_receipt_amounts_survive_a_missing_dollar_sign(ds):
    """Amounts read "192.52 EUR (~207.92 USD)" — no symbol anywhere."""
    assert sum(1 for e in ds.emails if e.amounts_cents) == 127
    eur = next(e for e in ds.emails if e.currency == "EUR")
    assert len(eur.amounts_cents) == 2      # charged currency and USD settled


def test_lookalike_senders_are_flagged_and_the_real_one_is_not(ds):
    flagged = {s.from_addr for s in email_match.find_suspicious_emails(ds)}
    assert "no-reply@wea1ify-support.com" in flagged
    assert "noreply@booking.com.com" in flagged
    # Wealify's own notices must never be reported as look-alikes.
    assert "no-reply@wealify.com" not in flagged


def test_matching_uses_the_reference_when_the_receipt_gives_one(ds):
    recon = email_match.reconcile(ds)
    matched = [r for r in recon.rows if r.message_id]
    assert matched
    assert all("txn_ref_exact" in r.reasons for r in matched)


# ------------------------------------------------------------------- merchants

def test_the_dictionary_covers_this_statement(ds):
    rows = list(ds.card) + list(ds.wallet.events)
    descriptors = [getattr(r, "merchant_raw", None) or r.descriptor for r in rows]
    resolved = sum(1 for d in descriptors if resolve(d))
    assert resolved / len(descriptors) > 0.95


def test_unnamed_lines_stay_unresolved():
    """WLF-01 forbids guessing a merchant, so these must stay unidentified."""
    for descriptor in ("Unrecognized", "Old card", "Trial card spend"):
        assert resolve(descriptor) is None


# -------------------------------------------------------------- the whole scan

def test_money_that_left_the_wallet_without_landing_is_flagged(ds):
    tri = tri_source.reconcile(ds)
    gaps = [t for t in tri.transfers if not t.is_matched]
    # Four card loads are not settled, so four wallet debits have no landing.
    assert len(gaps) == 4
    assert all(t.match_basis == "unsettled" for t in gaps)
    assert "WLF15-WL-0058" in {t.txn_id for t in gaps}
    # A EUR load against a USD wallet debit still matches, basis marked.
    assert any(t.match_basis == "card_code_fx" for t in tri.transfers)
    # A declined top-up is not money that arrived from nowhere.
    assert tri.unmatched_loads == []


def test_duplicated_credits_are_found_across_midnight(ds):
    """The UTC stamps put one pair three hours apart on two calendar days."""
    tri = tri_source.reconcile(ds)
    groups = {tuple(e.event_id for e in g) for g in tri.duplicate_wallet_credits}
    assert ("WLF15-WL-0032", "WLF15-WL-0059") in groups
    assert ("TW082026186228", "TW082026786190") in groups


def test_duplicate_charge_and_duplicate_fee_are_found(ds):
    assert [f.txn_ids for f in anomaly.duplicate_charges(ds)] == [
        ["WLF15-CD-0213", "WLF15-CD-0214"]
    ]
    fees = anomaly.double_fees(ds)
    assert [f.txn_ids for f in fees] == [["WLF15-CD-0216", "WLF15-CD-0217"]]
    assert fees[0].params["currency"] == "EUR"


def test_wallet_gap_is_unknown_rather_than_zero(ds):
    tri = tri_source.reconcile(ds)
    assert tri.wallet["reported_cents"] is None
    assert tri.wallet["gap_cents"] is None


def test_subscriptions_and_the_price_rise(analysis):
    names = {s.merchant_name for s in analysis.subs}
    assert {"Netflix", "Spotify", "Notion", "Figma", "Canva Pro"} <= names
    netflix = next(s for s in analysis.subs if s.merchant_name == "Netflix")
    assert [(p.from_cents, p.to_cents) for p in netflix.price_changes] == [(1549, 1799)]


def test_summary_exposes_the_input_it_had_to_interpret(analysis):
    from datetime import date

    summary = analysis.summary("vi", date(2026, 8, 21))
    assert summary["counts"]["virtual_accounts"] == 8
    assert summary["counts"]["cards"] == 7
    assert summary["input_notes"]
    assert summary["mailbox"] == "tester"
    profile = analysis.account_profile()
    assert profile["card_masked"] == "•••• ????"     # no PAN anywhere
    assert all(c["masked"].startswith("****") for c in profile["cards"])
    assert len(profile["virtual_accounts"]) == 8
