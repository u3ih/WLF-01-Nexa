"""Generate the WLF-01 sample dataset plus its ground-truth answer key.

Everything here is synthetic. The generator is fully deterministic (fixed
seed + hand-authored anchor transactions) so `ground_truth.json` is a stable
answer key the engine tests can assert against.

Run:  python -m data.generate      (from the backend/ directory)
"""

from __future__ import annotations

import csv
import json
import random
import hashlib
import statistics
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path

SEED = 20260805
STATEMENT_DATE = date(2026, 8, 5)
PERIOD_START = date(2025, 7, 1)

OWNER_NAME = "MINH ANH NGUYEN"
OWNER_EMAIL = "vaithieu0605@gmail.com"
ACCOUNT_NUMBER = "8830041926390"      # synthetic
CARD_NUMBER = "4157889923144821"      # synthetic, never displayed unmasked
WALLET_ID = "WLT-DEMO-4471"
OPENING_ACCOUNT_CENTS = 125_000
OPENING_WALLET_CENTS = 25_000

# The wallet's own reported balance is short by this much -> planted mismatch.
WALLET_REPORTED_GAP_CENTS = 3_840

OUT = Path(__file__).resolve().parent / "sample"
MAILBOX = OUT / "mailbox"

rng = random.Random(SEED)


def dt(y: int, m: int, d: int, h: int = 12, mi: int = 0, s: int = 0) -> datetime:
    return datetime(y, m, d, h, mi, s)


def months(start: tuple[int, int], end: tuple[int, int]):
    """Inclusive month walker: (2025, 11) .. (2026, 7)."""
    y, m = start
    while (y, m) <= end:
        yield y, m
        m += 1
        if m == 13:
            y, m = y + 1, 1


# --------------------------------------------------------------- subscriptions

CARD_SUBS = [
    {
        "key": "netflix",
        "name": "Netflix",
        "raw": "NETFLIX.COM 866-579-7172",
        "mcc": "4899",
        "day": 16,
        "amount": 1549,
        "start": (2025, 7),
        "end": (2026, 7),
        "price_changes": {(2026, 5): 1799},
        "domain": "netflix.com",
    },
    {
        "key": "spotify",
        "name": "Spotify",
        "raw": "SPOTIFY USA 877-778-1161",
        "mcc": "5815",
        "day": 8,
        "amount": 1199,
        "start": (2025, 7),
        "end": (2026, 8),
        "price_changes": {},
        "domain": "spotify.com",
    },
    {
        "key": "icloud",
        "name": "Apple iCloud+",
        "raw": "APPLE.COM/BILL 866-712-7753",
        "mcc": "5817",
        "day": 21,
        "amount": 999,
        "start": (2025, 7),
        "end": (2026, 7),
        "price_changes": {},
        "domain": "apple.com",
    },
    {
        # Planted "forgot to cancel": signed up Nov 2025, receipts stop after Dec.
        "key": "chegg",
        "name": "Chegg Study",
        "raw": "CHEGG STUDY 855-861-1300",
        "mcc": "8299",
        "day": 27,
        "amount": 1995,
        "start": (2025, 11),
        "end": (2026, 7),
        "price_changes": {},
        "domain": "chegg.com",
        "receipts_until": (2025, 12),
    },
]

ACCOUNT_SUB = {
    "key": "tmobile",
    "name": "T-Mobile",
    "raw": "T-MOBILE POSTPAID ACH",
    "day": 12,
    "amount": 6500,
    "start": (2025, 7),
    "end": (2026, 7),
    "domain": "t-mobile.com",
}

# Ordinary card spending: (raw descriptor, mcc, min cents, max cents, brand, domain)
NOISE_MERCHANTS = [
    ("SQ *BLUEBOTTLE COFFEE", "5814", 550, 975, "Blue Bottle Coffee",
     "bluebottlecoffee.com"),
    ("SQ *STARBUCKS 0428", "5814", 425, 725, "Starbucks", "starbucks.com"),
    ("WHOLEFDS MKT #10233", "5411", 2_200, 9_800, "Whole Foods Market",
     "wholefoodsmarket.com"),
    ("TRADER JOE'S #451", "5411", 1_800, 7_400, "Trader Joe's", "traderjoes.com"),
    ("UBER   *TRIP HELP.UBER.COM", "4121", 800, 3_200, "Uber", "uber.com"),
    ("LYFT   *RIDE", "4121", 700, 2_600, "Lyft", "lyft.com"),
    ("SHELL OIL 57443216", "5541", 2_500, 6_500, "Shell", "shell.com"),
    ("CVS/PHARMACY #04122", "5912", 900, 4_800, "CVS Pharmacy", "cvs.com"),
    ("TARGET T-2291", "5310", 1_500, 12_500, "Target", "target.com"),
    ("DOORDASH*WENDYS", "5812", 1_200, 4_200, "DoorDash", "doordash.com"),
    ("BEST BUY #1042", "5732", 3_500, 29_900, "Best Buy", "bestbuy.com"),
    ("HOMEDEPOT.COM 6152", "5200", 2_200, 18_900, "The Home Depot",
     "homedepot.com"),
    ("MTA*NYCT PAYGO", "4111", 275, 275, "MTA New York City Transit", "mta.info"),
    ("AMZN MKTP US*RTL9", "5942", 1_400, 14_800, "Amazon Marketplace",
     "amazon.com"),
]

PAYIN_COUNTERPARTY = "UPWORK GLOBAL INC ACH"
PAYOUT_COUNTERPARTY = "WIRE OUT VIETCOMBANK"


class Builder:
    def __init__(self) -> None:
        self.account: list[dict] = []
        self.card: list[dict] = []
        self.emails: list[dict] = []
        self.truth_txn: dict[str, list[str]] = {}
        self._acc_seq = 0
        self._card_seq = 0

    # -- row factories ----------------------------------------------------

    def acc(
        self,
        when: datetime,
        type_: str,
        description: str,
        counterparty: str,
        amount_cents: int,
        posted_offset: int = 0,
        tag: str | None = None,
    ) -> dict:
        self._acc_seq += 1
        row = {
            "txn_id": f"ACC-{self._acc_seq:04d}",
            "datetime": when.isoformat(timespec="seconds"),
            "posted_date": (when.date() + timedelta(days=posted_offset)).isoformat(),
            "type": type_,
            "description": description,
            "counterparty": counterparty,
            "amount": f"{amount_cents / 100:.2f}",
            "currency": "USD",
            "balance_after": "",
            "_when": when,
            "_cents": amount_cents,
        }
        self.account.append(row)
        if tag:
            self.truth_txn.setdefault(tag, []).append(row["txn_id"])
        return row

    def card_row(
        self,
        when: datetime,
        type_: str,
        merchant_raw: str,
        mcc: str,
        amount_cents: int,
        load_ref: str = "",
        posted_offset: int = 1,
        tag: str | None = None,
    ) -> dict:
        self._card_seq += 1
        row = {
            "card_txn_id": f"CRD-{self._card_seq:04d}",
            "datetime": when.isoformat(timespec="seconds"),
            "posted_date": (when.date() + timedelta(days=posted_offset)).isoformat(),
            "type": type_,
            "merchant_raw": merchant_raw,
            "mcc": mcc,
            "amount": f"{amount_cents / 100:.2f}",
            "currency": "USD",
            "card_number": CARD_NUMBER,
            "load_ref": load_ref,
            "_when": when,
            "_cents": amount_cents,
        }
        self.card.append(row)
        if tag:
            self.truth_txn.setdefault(tag, []).append(row["card_txn_id"])
        return row

    def email(
        self,
        when: datetime,
        from_name: str,
        from_addr: str,
        subject: str,
        body: str,
        genre: str = "receipt",
        reply_to: str | None = None,
        tag: str | None = None,
    ) -> dict:
        digest = hashlib.sha256(
            f"{when.isoformat()}|{from_addr}|{subject}".encode()
        ).hexdigest()[:16]
        msg = {
            "message_id": f"<{digest}@mail.example.com>",
            "when": when,
            "from_name": from_name,
            "from_addr": from_addr,
            "reply_to": reply_to,
            "subject": subject,
            "body": body,
            "genre": genre,
        }
        self.emails.append(msg)
        if tag:
            self.truth_txn.setdefault(tag, []).append(msg["message_id"])
        return msg

    # -- timeline ---------------------------------------------------------

    def build(self) -> None:
        self.build_payins()
        self.build_transfers_and_loads()
        self.build_fees()
        self.build_payouts()
        self.build_account_subscription()
        self.build_card_subscriptions()
        self.build_noise_purchases()
        self.build_anchors()
        self.finalise_account_balances()
        self.build_bank_notices()

    def build_payins(self) -> None:
        """Monthly freelance payin on the 3rd; June 2026 is posted twice."""
        amounts = {
            (2025, 7): 246_000, (2025, 8): 289_500, (2025, 9): 271_000,
            (2025, 10): 302_000, (2025, 11): 258_000, (2025, 12): 331_500,
            (2026, 1): 264_000, (2026, 2): 247_500, (2026, 3): 288_000,
            (2026, 4): 296_500, (2026, 5): 274_000, (2026, 6): 120_000,
            (2026, 7): 293_000, (2026, 8): 151_000,
        }
        for (y, m), cents in amounts.items():
            day = 3 if not (y == 2026 and m == 8) else 4
            self.acc(dt(y, m, day, 9, 14, 22), "payin", "ACH CREDIT FREELANCE PAYOUT",
                     PAYIN_COUNTERPARTY, cents)
            if (y, m) == (2026, 6):
                # PLANTED: the same $1,200.00 deposit lands twice the same day.
                self.acc(dt(y, m, day, 9, 51, 8), "ACH CREDIT FREELANCE PAYOUT".lower()
                         and "payin", "ACH CREDIT FREELANCE PAYOUT",
                         PAYIN_COUNTERPARTY, cents, tag="duplicate_payin")
        # tag both legs of the duplicate pair
        dupes = [r for r in self.account
                 if r["_when"].date() == date(2026, 6, 3) and r["type"] == "payin"]
        self.truth_txn["duplicate_payin"] = sorted(r["txn_id"] for r in dupes)

    def build_transfers_and_loads(self) -> None:
        """Account -> card transfers, each mirrored by a card load except one."""
        plan = [
            (2025, 7, 6, 40_000), (2025, 8, 5, 55_000), (2025, 9, 7, 45_000),
            (2025, 10, 6, 60_000), (2025, 11, 5, 50_000), (2025, 12, 8, 75_000),
            (2026, 1, 6, 48_000), (2026, 2, 5, 52_000), (2026, 3, 7, 58_000),
            (2026, 4, 6, 61_000), (2026, 5, 5, 54_000), (2026, 6, 6, 57_000),
            (2026, 7, 6, 62_000), (2026, 7, 22, 50_000), (2026, 8, 4, 45_000),
        ]
        for y, m, d, cents in plan:
            when = dt(y, m, d, 10, 5, 0)
            planted = (y, m, d) == (2026, 7, 22)
            row = self.acc(
                when, "transfer_to_card", "TRANSFER TO CARD FUNDING",
                f"WEALIFY CARD {CARD_NUMBER[-4:]}", -cents,
                tag="transfer_not_on_card" if planted else None,
            )
            if planted:
                # PLANTED: money leaves the account, no matching card load exists.
                continue
            self.card_row(when + timedelta(hours=1), "load", "WEALIFY ACCOUNT FUNDING",
                          "0000", cents, load_ref=row["txn_id"], posted_offset=0)

    def build_fees(self) -> None:
        for y, m in months((2025, 7), (2026, 8)):
            day = 1 if not (y == 2025 and m == 7) else 2
            self.acc(dt(y, m, day, 0, 5, 0), "fee", "MONTHLY ACCOUNT SERVICE FEE",
                     "WEALIFY", -495)
        # ordinary one-off fees
        self.acc(dt(2025, 9, 19, 16, 20, 0), "fee", "ATM WITHDRAWAL FEE", "WEALIFY", -250)
        self.acc(dt(2026, 3, 10, 11, 2, 0), "fee", "WIRE TRANSFER FEE", "WEALIFY", -2_500)
        self.acc(dt(2026, 5, 14, 15, 40, 0), "fee", "ATM WITHDRAWAL FEE", "WEALIFY", -250)
        # near-miss: a different fee type on the same day as the planted double fee
        self.acc(dt(2026, 6, 25, 17, 12, 0), "fee", "ATM WITHDRAWAL FEE", "WEALIFY",
                 -250, tag="must_not_flag_distinct_fee")

    def build_payouts(self) -> None:
        plan = [
            (2025, 9, 19, 120_000), (2025, 12, 20, 180_000), (2026, 3, 10, 150_000),
            (2026, 5, 14, 90_000), (2026, 6, 25, 200_000), (2026, 7, 28, 110_000),
        ]
        for y, m, d, cents in plan:
            self.acc(dt(y, m, d, 11, 0, 0), "payout", "OUTGOING WIRE TRANSFER",
                     PAYOUT_COUNTERPARTY, -cents)

    def build_account_subscription(self) -> None:
        sub = ACCOUNT_SUB
        for y, m in months(sub["start"], sub["end"]):
            when = dt(y, m, sub["day"], 8, 30, 0)
            self.acc(when, "purchase", sub["raw"], "T-MOBILE USA", -sub["amount"],
                     tag="recurring_tmobile")
            self.email(
                when + timedelta(hours=2), "T-Mobile", f"billing@{sub['domain']}",
                f"Your T-Mobile bill payment of ${sub['amount'] / 100:.2f} was received",
                f"Thanks. We received your payment of ${sub['amount'] / 100:.2f} "
                f"for account ending 4417 on {when:%B %d, %Y}.",
            )

    def build_card_subscriptions(self) -> None:
        for sub in CARD_SUBS:
            amount = sub["amount"]
            for y, m in months(sub["start"], sub["end"]):
                if (y, m) in sub["price_changes"]:
                    amount = sub["price_changes"][(y, m)]
                when = dt(y, m, sub["day"], 6, 12, 0)
                tag = f"recurring_{sub['key']}"
                row = self.card_row(when, "purchase", sub["raw"], sub["mcc"], -amount,
                                    tag=tag)
                if (y, m) in sub["price_changes"]:
                    # Only the charge where the new price took effect.
                    self.truth_txn.setdefault(
                        f"price_increase_{sub['key']}", []
                    ).append(row["card_txn_id"])
                cutoff = sub.get("receipts_until")
                if cutoff and (y, m) > cutoff:
                    continue          # PLANTED: receipts stop, charges continue
                self.email(
                    when + timedelta(minutes=25), sub["name"],
                    f"receipts@{sub['domain']}",
                    f"Your {sub['name']} receipt — ${amount / 100:.2f}",
                    f"Your {sub['name']} subscription was charged ${amount / 100:.2f} "
                    f"on {when:%B %d, %Y}. Card ending {CARD_NUMBER[-4:]}.",
                )
            if sub["key"] == "chegg":
                first = dt(*sub["start"], sub["day"], 6, 0, 0)
                self.email(
                    first - timedelta(minutes=30), sub["name"],
                    f"no-reply@{sub['domain']}",
                    "Welcome to Chegg Study — your subscription is active",
                    "Your Chegg Study subscription is now active at $19.95 per month. "
                    "It renews automatically until you cancel.",
                    genre="subscription_confirmation",
                    tag="signup_chegg",
                )
            if sub["price_changes"]:
                self.email(
                    dt(2026, 4, 20, 9, 0, 0), sub["name"], f"info@{sub['domain']}",
                    "An update to your Netflix price",
                    "Starting with your May billing date, your plan will be "
                    "$17.99 per month instead of $15.49.",
                    genre="subscription_confirmation",
                    tag="price_notice_netflix",
                )

    def build_noise_purchases(self) -> None:
        """Ordinary spending: irregular merchants, irregular gaps, no planted
        patterns. Receipts are emitted for anything >= $80."""
        for y, m in months((2025, 7), (2026, 8)):
            count = 8 if (y, m) != (2026, 8) else 3
            used: list[tuple[str, datetime]] = []
            for _ in range(count):
                raw, mcc, lo, hi, brand, domain = rng.choice(NOISE_MERCHANTS)
                day = rng.randint(1, 27 if (y, m) != (2026, 8) else 4)
                hour = rng.randint(8, 21)
                minute = rng.choice([3, 11, 17, 24, 33, 41, 48, 56])
                when = dt(y, m, day, hour, minute, rng.randint(0, 59))
                # keep same-merchant visits far apart so nothing looks duplicated
                if any(r == raw and abs((when - w).total_seconds()) < 3_600
                       for r, w in used):
                    continue
                used.append((raw, when))
                cents = rng.randrange(lo, hi + 1, 5) if hi > lo else lo
                self.card_row(when, "purchase", raw, mcc, -cents)
                if cents >= 8_000:
                    self.email(
                        when + timedelta(minutes=12), brand,
                        f"receipts@{domain}",
                        f"Receipt: ${cents / 100:.2f} at {brand}",
                        f"Thanks for your purchase of ${cents / 100:.2f} on "
                        f"{when:%B %d, %Y} at {raw}. Card ending "
                        f"{CARD_NUMBER[-4:]}.",
                    )

    def build_anchors(self) -> None:
        # PLANTED 2: same merchant, same amount, 94 seconds apart.
        first = self.card_row(dt(2026, 7, 18, 9, 12, 3), "purchase",
                              "SQ *BLUEBOTTLE COFFEE", "5814", -675,
                              tag="duplicate_charge")
        self.card_row(dt(2026, 7, 18, 9, 13, 37), "purchase",
                      "SQ *BLUEBOTTLE COFFEE", "5814", -675, tag="duplicate_charge")
        self.email(
            dt(2026, 7, 18, 9, 20, 0), "Blue Bottle Coffee",
            "receipts@bluebottlecoffee.com", "Your Blue Bottle receipt — $6.75",
            "Thanks for visiting. Total $6.75 on July 18, 2026.",
        )

        # PLANTED 3: the same wire fee charged twice on the same day.
        self.acc(dt(2026, 6, 25, 11, 1, 0), "fee", "WIRE TRANSFER FEE", "WEALIFY",
                 -2_500, tag="double_fee")
        self.acc(dt(2026, 6, 25, 11, 3, 0), "fee", "WIRE TRANSFER FEE", "WEALIFY",
                 -2_500, tag="double_fee")

        # PLANTED 8: descriptor that resolves to nothing in the merchant dictionary.
        self.card_row(dt(2026, 7, 30, 20, 41, 12), "purchase", "PP*ZTRDNG LLC 8552",
                      "5999", -8_900, tag="unknown_merchant")
        self.email(
            dt(2026, 7, 30, 20, 44, 0), "PayPal", "service@paypal.com",
            "You sent a payment of $89.00 USD",
            "You sent $89.00 USD. This charge will appear as PP*ZTRDNG LLC 8552.",
        )

        # PLANTED 9: high-value charge with no receipt email anywhere.
        self.card_row(dt(2026, 7, 27, 15, 6, 44), "purchase", "AMZN MKTP US*2K91",
                      "5942", -24_813, tag="missing_email")

        # PLANTED 10: look-alike sender, no transaction matches it.
        self.email(
            dt(2026, 7, 24, 3, 18, 0), "Netflix Billing",
            "no-reply@netfl1x-billing.com",
            "Payment declined — update your card to avoid suspension",
            "We could not process your payment of $89.99. Confirm your card "
            "details within 24 hours to keep your account active.",
            genre="receipt", reply_to="billing@secure-pay-desk.example",
            tag="suspicious_email",
        )

        # Near-miss: same merchant, same amount, same day but hours apart.
        self.card_row(dt(2026, 7, 11, 8, 5, 30), "purchase", "SQ *STARBUCKS 0428",
                      "5814", -525, tag="must_not_flag_same_day_far_apart")
        self.card_row(dt(2026, 7, 11, 14, 40, 12), "purchase", "SQ *STARBUCKS 0428",
                      "5814", -525, tag="must_not_flag_same_day_far_apart")

        # Near-miss: identical amount at the same merchant, 46 days apart.
        self.card_row(dt(2026, 5, 4, 18, 22, 0), "purchase", "WHOLEFDS MKT #10233",
                      "5411", -6_420, tag="must_not_flag_far_apart")
        self.card_row(dt(2026, 6, 19, 19, 3, 0), "purchase", "WHOLEFDS MKT #10233",
                      "5411", -6_420, tag="must_not_flag_far_apart")

        # Near-miss: only two charges -> not enough for a recurring pattern.
        for y, m in [(2026, 2), (2026, 3)]:
            self.card_row(dt(y, m, 14, 7, 30, 0), "purchase", "COURSERA.ORG",
                          "8299", -4_900, tag="must_not_flag_only_two")

    def build_bank_notices(self) -> None:
        dup_payins = sorted(
            (r for r in self.account
             if r["type"] == "payin" and r["_when"].date() == date(2026, 6, 3)),
            key=lambda r: r["txn_id"],
        )
        # The bank notified once even though the deposit posted twice -> extra
        # evidence for the duplicate-payin finding.
        skip_notice = {dup_payins[-1]["txn_id"]} if len(dup_payins) > 1 else set()
        for row in self.account:
            if row["type"] == "payin" and row["txn_id"] not in skip_notice:
                self.email(
                    row["_when"] + timedelta(minutes=6), "Wealify",
                    "notifications@wealify.example.com",
                    f"Deposit received — ${row['_cents'] / 100:.2f}",
                    f"${row['_cents'] / 100:.2f} from {row['counterparty']} was "
                    f"credited to your account on {row['_when']:%B %d, %Y}.",
                    genre="bank_notice",
                )
            elif row["type"] == "payout":
                self.email(
                    row["_when"] + timedelta(minutes=9), "Wealify",
                    "notifications@wealify.example.com",
                    f"Wire transfer sent — ${abs(row['_cents']) / 100:.2f}",
                    f"Your wire of ${abs(row['_cents']) / 100:.2f} to "
                    f"{row['counterparty']} was sent on "
                    f"{row['_when']:%B %d, %Y}.",
                    genre="bank_notice",
                )
        for row in self.card:
            if row["type"] != "load":
                continue
            when = row["_when"]
            self.email(
                when + timedelta(minutes=8), "Wealify",
                "notifications@wealify.example.com",
                f"Card load confirmed — ${row['_cents'] / 100:.2f}",
                f"${row['_cents'] / 100:.2f} was added to your card ending "
                f"{CARD_NUMBER[-4:]} on {when:%B %d, %Y}.",
                genre="bank_notice",
            )
        for y, m in months((2025, 8), (2026, 8)):
            self.email(
                dt(y, m, 5, 7, 0, 0), "Wealify", "statements@wealify.example.com",
                "Your monthly statement is ready",
                "Your account statement is available in the Wealify app. "
                "Review it and report anything unfamiliar within 60 days.",
                genre="bank_notice",
            )

    def finalise_account_balances(self) -> None:
        self.account.sort(key=lambda r: (r["_when"], r["txn_id"]))
        self.card.sort(key=lambda r: (r["_when"], r["card_txn_id"]))
        balance = OPENING_ACCOUNT_CENTS
        for row in self.account:
            balance += row["_cents"]
            row["balance_after"] = f"{balance / 100:.2f}"


# ------------------------------------------------------------------- writers

def write_account_csv(rows: list[dict]) -> None:
    cols = ["txn_id", "datetime", "posted_date", "type", "description",
            "counterparty", "amount", "currency", "balance_after"]
    with (OUT / "account_statement.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def write_card_csv(rows: list[dict]) -> None:
    cols = ["card_txn_id", "datetime", "posted_date", "type", "merchant_raw", "mcc",
            "amount", "currency", "card_number", "load_ref"]
    with (OUT / "card_statement.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def write_account_pdf(rows: list[dict]) -> None:
    """Same rows as the CSV, rendered as a pipe-delimited monospace PDF so the
    pdfplumber path is exercised for real."""
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    masked_account = "*" * (len(ACCOUNT_NUMBER) - 4) + ACCOUNT_NUMBER[-4:]
    c = canvas.Canvas(str(OUT / "account_statement.pdf"), pagesize=letter)
    width, height = letter
    y = height - 50

    def header() -> float:
        nonlocal y
        c.setFont("Helvetica-Bold", 12)
        c.drawString(40, y, "WEALIFY (SAMPLE) — ACCOUNT STATEMENT")
        y -= 16
        c.setFont("Helvetica", 8)
        c.drawString(40, y, f"Account holder: {OWNER_NAME}   Account: {masked_account}")
        y -= 12
        c.drawString(40, y, f"Statement date: {STATEMENT_DATE.isoformat()}   "
                            f"Period: {PERIOD_START.isoformat()} to "
                            f"{STATEMENT_DATE.isoformat()}   Currency: USD")
        y -= 18
        c.setFont("Courier-Bold", 7)
        c.drawString(40, y, "DATE | TXN_ID | TYPE | DESCRIPTION | AMOUNT | BALANCE")
        y -= 11
        c.setFont("Courier", 7)
        return y

    y = header()
    for row in rows:
        if y < 50:
            c.showPage()
            y = height - 50
            y = header()
        line = " | ".join([
            row["datetime"], row["txn_id"], row["type"],
            row["description"][:34], row["amount"], row["balance_after"],
        ])
        c.drawString(40, y, line)
        y -= 10
    c.save()


def write_wallet(account_rows: list[dict]) -> dict:
    events = []
    for i, row in enumerate(account_rows, start=1):
        cents = row["_cents"]
        events.append({
            "event_id": f"WEV-{i:04d}",
            "datetime": row["datetime"],
            "kind": "credit" if cents > 0 else "debit",
            "amount": f"{abs(cents) / 100:.2f}",
            "ref": row["txn_id"],
            "note": row["type"],
        })
    computed = OPENING_WALLET_CENTS + sum(r["_cents"] for r in account_rows)
    payload = {
        "wallet_id": WALLET_ID,
        "currency": "USD",
        "opening_date": PERIOD_START.isoformat(),
        "opening_balance": f"{OPENING_WALLET_CENTS / 100:.2f}",
        # PLANTED: the wallet's own reported balance is short of the ledger sum.
        "reported_balance": f"{(computed - WALLET_REPORTED_GAP_CENTS) / 100:.2f}",
        "reported_at": STATEMENT_DATE.isoformat(),
        "events": events,
    }
    (OUT / "wallet_ledger.json").write_text(json.dumps(payload, indent=2))
    return payload


def write_mailbox(emails: list[dict]) -> None:
    for old in MAILBOX.glob("*.eml"):
        old.unlink()
    for i, item in enumerate(sorted(emails, key=lambda e: e["when"]), start=1):
        msg = EmailMessage()
        msg["Message-ID"] = item["message_id"]
        msg["From"] = f'{item["from_name"]} <{item["from_addr"]}>'
        msg["To"] = f"{OWNER_NAME.title()} <{OWNER_EMAIL}>"
        msg["Subject"] = item["subject"]
        msg["Date"] = format_datetime(item["when"])
        msg["X-Nexa-Genre"] = item["genre"]
        if item["reply_to"]:
            msg["Reply-To"] = item["reply_to"]
        msg.set_content(item["body"])
        (MAILBOX / f"{i:03d}.eml").write_bytes(msg.as_bytes())


def write_account_meta() -> None:
    payload = {
        "owner_name": OWNER_NAME,
        "owner_email": OWNER_EMAIL,
        "account_number": ACCOUNT_NUMBER,
        "card_number": CARD_NUMBER,
        "card_brand": "Wealify Visa (sample)",
        "statement_date": STATEMENT_DATE.isoformat(),
        "period_start": PERIOD_START.isoformat(),
        "currency": "USD",
        "opening_balance": f"{OPENING_ACCOUNT_CENTS / 100:.2f}",
        "note": "Synthetic sample data for the WLF-01 exercise. No real person.",
    }
    (OUT / "account_meta.json").write_text(json.dumps(payload, indent=2))


# --------------------------------------------------------------- ground truth

def build_ground_truth(b: Builder, wallet: dict) -> dict:
    t = b.truth_txn
    purchases = ([r for r in b.card if r["type"] == "purchase"]
                 + [r for r in b.account if r["type"] == "purchase"])
    purchase_mags = sorted(abs(r["_cents"]) for r in purchases)
    p90 = purchase_mags[min(len(purchase_mags) - 1,
                           int(len(purchase_mags) * 0.9))]

    def totals(rows: list[dict], kind: str) -> int:
        return sum(r["_cents"] for r in rows if r["type"] == kind)

    cashflow = {
        "payin": totals(b.account, "payin"),
        "payout": totals(b.account, "payout"),
        "transfer_to_card": totals(b.account, "transfer_to_card"),
        "fee": totals(b.account, "fee"),
        "purchase": totals(b.account, "purchase"),
    }
    card_totals = {
        "load": totals(b.card, "load"),
        "purchase": totals(b.card, "purchase"),
        "fee": totals(b.card, "fee"),
    }

    def month_report(ym: str) -> dict:
        acc = [r for r in b.account if r["datetime"].startswith(ym)]
        crd = [r for r in b.card if r["datetime"].startswith(ym)]
        spend = -(totals(acc, "purchase") + totals(crd, "purchase"))
        fees = -(totals(acc, "fee") + totals(crd, "fee"))
        top = sorted(
            [r for r in acc if r["type"] == "purchase"]
            + [r for r in crd if r["type"] == "purchase"],
            key=lambda r: r["_cents"],
        )[:3]
        return {
            "spend_cents": spend,
            "fees_cents": fees,
            "payin_cents": totals(acc, "payin"),
            "payout_cents": -totals(acc, "payout"),
            "top3": [
                {
                    "ref": r.get("txn_id") or r["card_txn_id"],
                    "amount_cents": -r["_cents"],
                    "descriptor": r.get("description") or r["merchant_raw"],
                }
                for r in top
            ],
        }

    expected = [
        {
            "kind": "recurring_subscription", "merchant": "Netflix",
            "label": "recurring_confirmed", "amount_cents": 1799,
            "charge_count": 13, "next_charge": "2026-08-16",
        },
        {
            "kind": "recurring_subscription", "merchant": "Spotify",
            "label": "recurring_confirmed", "amount_cents": 1199,
            "charge_count": 14, "next_charge": "2026-09-08",
        },
        {
            "kind": "recurring_subscription", "merchant": "Apple iCloud+",
            "label": "recurring_confirmed", "amount_cents": 999,
            "charge_count": 13, "next_charge": "2026-08-21",
        },
        {
            "kind": "recurring_subscription", "merchant": "Chegg Study",
            "label": "recurring_confirmed", "amount_cents": 1995,
            "charge_count": 9, "next_charge": "2026-08-27",
        },
        {
            "kind": "recurring_subscription", "merchant": "T-Mobile",
            "label": "recurring_confirmed", "amount_cents": 6500,
            "charge_count": 13, "next_charge": "2026-08-12",
        },
        {
            "kind": "forgotten_subscription", "merchant": "Chegg Study",
            "label": "needs_your_confirmation", "amount_cents": 1995,
            "charges_without_receipt": 7,
        },
        {
            "kind": "price_increase", "merchant": "Netflix",
            "label": "recurring_confirmed",
            "old_amount_cents": 1549, "new_amount_cents": 1799,
            "effective_on": "2026-05-16",
            "txn_ids": t.get("price_increase_netflix", []),
        },
        {
            "kind": "duplicate_charge", "merchant": "Blue Bottle Coffee",
            "label": "needs_your_confirmation", "amount_cents": 675,
            "txn_ids": sorted(t["duplicate_charge"]), "seconds_apart": 94,
        },
        {
            "kind": "double_fee", "descriptor": "WIRE TRANSFER FEE",
            "label": "needs_your_confirmation", "amount_cents": 2500,
            "txn_ids": sorted(t["double_fee"]), "occurred_on": "2026-06-25",
        },
        {
            "kind": "duplicate_payin", "counterparty": PAYIN_COUNTERPARTY,
            "label": "needs_your_confirmation", "amount_cents": 120_000,
            "txn_ids": sorted(t["duplicate_payin"]), "occurred_on": "2026-06-03",
        },
        {
            "kind": "transfer_not_on_card", "label": "needs_your_confirmation",
            "amount_cents": 50_000, "txn_ids": sorted(t["transfer_not_on_card"]),
            "occurred_on": "2026-07-22",
        },
        {
            "kind": "wallet_balance_mismatch", "label": "insufficient_data",
            "amount_cents": WALLET_REPORTED_GAP_CENTS,
        },
        {
            "kind": "unknown_merchant", "descriptor": "PP*ZTRDNG LLC 8552",
            "label": "insufficient_data", "amount_cents": 8_900,
            "txn_ids": sorted(t["unknown_merchant"]),
        },
        {
            "kind": "missing_email", "descriptor": "AMZN MKTP US*2K91",
            "label": "needs_your_confirmation", "amount_cents": 24_813,
            "txn_ids": sorted(t["missing_email"]),
        },
        {
            "kind": "suspicious_email", "from_addr": "no-reply@netfl1x-billing.com",
            "label": "insufficient_data", "amount_cents": 8_999,
            "message_ids": t["suspicious_email"],
        },
    ]

    must_not_flag = [
        {"reason": "same merchant and amount but 6.5 hours apart",
         "txn_ids": sorted(t["must_not_flag_same_day_far_apart"])},
        {"reason": "same merchant and amount but 46 days apart",
         "txn_ids": sorted(t["must_not_flag_far_apart"])},
        {"reason": "only two charges — not enough for a recurring pattern",
         "txn_ids": sorted(t["must_not_flag_only_two"])},
        {"reason": "a different fee type on the same day as the double fee",
         "txn_ids": sorted(t["must_not_flag_distinct_fee"])},
    ]

    return {
        "statement_date": STATEMENT_DATE.isoformat(),
        "dispute_deadline": (STATEMENT_DATE + timedelta(days=60)).isoformat(),
        "owner_email": OWNER_EMAIL,
        "counts": {
            "account_txns": len(b.account),
            "card_txns": len(b.card),
            "wallet_events": len(wallet["events"]),
            "emails": len(b.emails),
            "expected_findings": len(expected),
        },
        "cashflow_totals_cents": cashflow,
        "card_totals_cents": card_totals,
        "purchase_p90_cents": p90,
        "wallet": {
            "opening_cents": OPENING_WALLET_CENTS,
            "computed_cents": OPENING_WALLET_CENTS
            + sum(r["_cents"] for r in b.account),
            "reported_cents": OPENING_WALLET_CENTS
            + sum(r["_cents"] for r in b.account) - WALLET_REPORTED_GAP_CENTS,
            "gap_cents": WALLET_REPORTED_GAP_CENTS,
        },
        "reports": {ym: month_report(ym) for ym in ["2026-06", "2026-07"]},
        "expected_findings": expected,
        "must_not_flag": must_not_flag,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    MAILBOX.mkdir(parents=True, exist_ok=True)

    b = Builder()
    b.build()
    write_account_csv(b.account)
    write_card_csv(b.card)
    write_account_pdf(b.account)
    wallet = write_wallet(b.account)
    write_mailbox(b.emails)
    write_account_meta()
    truth = build_ground_truth(b, wallet)
    (OUT / "ground_truth.json").write_text(json.dumps(truth, indent=2))

    print(f"account txns : {len(b.account)}")
    print(f"card txns    : {len(b.card)}")
    print(f"wallet events: {len(wallet['events'])}")
    print(f"emails       : {len(b.emails)}")
    print(f"findings     : {truth['counts']['expected_findings']}")
    print(f"p90 purchase : {truth['purchase_p90_cents'] / 100:.2f}")
    print(f"written to   : {OUT}")


if __name__ == "__main__":
    main()
