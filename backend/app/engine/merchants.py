"""Descriptor -> merchant resolution.

Card and ACH descriptors are cryptic ("SQ *BLUEBOTTLE COFFEE",
"PP*ZTRDNG LLC 8552"). This module resolves the ones we actually know and
returns None for the rest — WLF-01 rule C forbids guessing a merchant name,
so an unresolved descriptor is reported as "chưa xác định được".
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Processor prefixes. These explain *how* a charge was routed, which is useful
# even when the underlying seller stays unidentified.
PREFIX_HINTS: dict[str, str] = {
    "SQ *": "square",
    "PP*": "paypal",
    "PAYPAL *": "paypal",
    "TST*": "toast",
    "SP ": "shopify",
    "WL *": "wealify",
}


@dataclass(frozen=True)
class Merchant:
    key: str
    name: str
    category: str
    domains: tuple[str, ...] = ()
    note_key: str | None = None      # i18n key for a plain-language explanation


@dataclass(frozen=True)
class Rule:
    pattern: re.Pattern[str]
    merchant: Merchant


def _rule(regex: str, key: str, name: str, category: str,
          domains: tuple[str, ...] = (), note_key: str | None = None) -> Rule:
    return Rule(re.compile(regex, re.I), Merchant(key, name, category, domains, note_key))


# Order matters: the first match wins.
RULES: list[Rule] = [
    _rule(r"^NETFLIX", "netflix", "Netflix", "subscription", ("netflix.com",),
          "merchant.netflix"),
    _rule(r"^SPOTIFY", "spotify", "Spotify", "subscription", ("spotify.com",),
          "merchant.spotify"),
    _rule(r"^APPLE\.COM/BILL", "icloud", "Apple iCloud+", "subscription",
          ("apple.com", "icloud.com"), "merchant.apple_bill"),
    _rule(r"^CHEGG", "chegg", "Chegg Study", "subscription", ("chegg.com",),
          "merchant.chegg"),
    _rule(r"^T-MOBILE", "tmobile", "T-Mobile", "telecom", ("t-mobile.com",),
          "merchant.tmobile"),
    _rule(r"^COURSERA", "coursera", "Coursera", "education", ("coursera.org",)),
    _rule(r"BLUEBOTTLE", "bluebottle", "Blue Bottle Coffee", "dining",
          ("bluebottlecoffee.com",), "merchant.square_prefix"),
    _rule(r"STARBUCKS", "starbucks", "Starbucks", "dining", ("starbucks.com",),
          "merchant.square_prefix"),
    _rule(r"^WHOLEFDS|WHOLE FOODS", "wholefoods", "Whole Foods Market", "groceries",
          ("wholefoodsmarket.com", "amazon.com"), "merchant.wholefoods"),
    _rule(r"TRADER JOE", "traderjoes", "Trader Joe's", "groceries",
          ("traderjoes.com",)),
    _rule(r"^UBER", "uber", "Uber", "transport", ("uber.com",)),
    _rule(r"^LYFT", "lyft", "Lyft", "transport", ("lyft.com",)),
    _rule(r"^SHELL", "shell", "Shell", "fuel", ("shell.com",)),
    _rule(r"^CVS", "cvs", "CVS Pharmacy", "health", ("cvs.com",)),
    _rule(r"^TARGET", "target", "Target", "retail", ("target.com",)),
    _rule(r"^DOORDASH", "doordash", "DoorDash", "dining", ("doordash.com",),
          "merchant.doordash"),
    _rule(r"^BEST BUY", "bestbuy", "Best Buy", "retail", ("bestbuy.com",)),
    _rule(r"^HOMEDEPOT", "homedepot", "The Home Depot", "retail",
          ("homedepot.com",)),
    _rule(r"^MTA\*|^MTA ", "mta", "MTA New York City Transit", "transport",
          ("mta.info",), "merchant.mta"),
    _rule(r"^AMZN MKTP|^AMAZON\.COM", "amazon", "Amazon Marketplace", "retail",
          ("amazon.com",), "merchant.amazon"),
    # Wealify's own internal lines
    _rule(r"^TRANSFER TO CARD", "wealify_transfer", "Wealify card transfer",
          "transfer", ("wealify.example.com",)),
    _rule(r"^WEALIFY ACCOUNT FUNDING", "wealify_load", "Wealify card load",
          "transfer", ("wealify.example.com",)),
    _rule(r"^MONTHLY ACCOUNT SERVICE FEE", "wealify_monthly_fee",
          "Wealify monthly account fee", "fee", ("wealify.example.com",),
          "merchant.monthly_fee"),
    _rule(r"^WIRE TRANSFER FEE", "wire_fee", "Wire transfer fee", "fee",
          ("wealify.example.com",), "merchant.wire_fee"),
    _rule(r"^ATM WITHDRAWAL FEE", "atm_fee", "ATM withdrawal fee", "fee",
          ("wealify.example.com",)),
    _rule(r"^OUTGOING WIRE", "wire_out", "Outgoing wire transfer", "transfer"),
    _rule(r"^ACH CREDIT|^UPWORK", "upwork", "Upwork payout", "income",
          ("upwork.com",)),
]

TRAILING_NOISE = re.compile(
    r"("
    r"\s+\d{3}-\d{3}-\d{4}"      # phone numbers
    r"|\s+#\d+"                   # store numbers
    r"|\s+T-\d+"
    r"|\s+\d{6,}"                 # long reference numbers
    r"|\s+\d{4}$"
    r")+$"
)


def normalize_descriptor(descriptor: str) -> str:
    """Collapse a raw descriptor to a comparable form (used for grouping)."""
    text = re.sub(r"\s+", " ", descriptor).strip().upper()
    return TRAILING_NOISE.sub("", text).strip()


def processor_hint(descriptor: str) -> str | None:
    """Return the payment processor implied by a descriptor prefix, if any."""
    upper = descriptor.upper()
    for prefix, hint in PREFIX_HINTS.items():
        if upper.startswith(prefix):
            return hint
    return None


def resolve(descriptor: str) -> Merchant | None:
    """Resolve a descriptor to a known merchant, or None when unidentified."""
    normalized = normalize_descriptor(descriptor)
    for rule in RULES:
        if rule.pattern.search(normalized) or rule.pattern.search(descriptor.upper()):
            return rule.merchant
    return None


def merchant_key(descriptor: str) -> str:
    """Grouping key: the resolved merchant key, else the normalized descriptor."""
    found = resolve(descriptor)
    return found.key if found else f"raw:{normalize_descriptor(descriptor)}"


def known_domains(descriptor: str) -> tuple[str, ...]:
    found = resolve(descriptor)
    return found.domains if found else ()


ALL_DOMAINS: frozenset[str] = frozenset(
    d for rule in RULES for d in rule.merchant.domains
)
