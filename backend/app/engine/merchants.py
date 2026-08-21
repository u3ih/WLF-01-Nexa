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
    # Merchant-of-record resellers: the line names the reseller, not the seller.
    "PADDLE.NET*": "paddle",
    "PADDLE *": "paddle",
    "FS *": "fastspring",
    "FSPRG.COM": "fastspring",
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
          "transfer", ("wealify.com", "wealify.example.com")),
    _rule(r"^WEALIFY ACCOUNT FUNDING", "wealify_load", "Wealify card load",
          "transfer", ("wealify.com", "wealify.example.com")),
    _rule(r"^MONTHLY ACCOUNT SERVICE FEE", "wealify_monthly_fee",
          "Wealify monthly account fee", "fee", ("wealify.com", "wealify.example.com"),
          "merchant.monthly_fee"),
    _rule(r"^WIRE TRANSFER FEE", "wire_fee", "Wire transfer fee", "fee",
          ("wealify.com", "wealify.example.com"), "merchant.wire_fee"),
    _rule(r"^ATM WITHDRAWAL FEE", "atm_fee", "ATM withdrawal fee", "fee",
          ("wealify.com", "wealify.example.com")),
    _rule(r"^OUTGOING WIRE", "wire_out", "Outgoing wire transfer", "transfer"),
    _rule(r"^ACH CREDIT|^UPWORK", "upwork", "Upwork payout", "income",
          ("upwork.com",)),

    # ---------------------------------------------------------------- SaaS
    # Descriptors reach us in two shapes: the raw form the card network prints
    # ("PADDLE.NET* NOTION") and the friendly form the Wealify ledger prints
    # ("Namecheap"). Each rule has to answer to both.
    _rule(r"NOTION", "notion", "Notion", "subscription", ("notion.so",
          "paddle.com"), "merchant.paddle_prefix"),
    _rule(r"^ADOBE|CREATIVE CLD", "adobe", "Adobe Creative Cloud",
          "subscription", ("adobe.com",)),
    _rule(r"^CANVA", "canva", "Canva Pro", "subscription", ("canva.com",)),
    _rule(r"^NORDVPN", "nordvpn", "NordVPN", "subscription", ("nordvpn.com",)),
    _rule(r"^OPENAI|CHATGPT", "openai", "OpenAI ChatGPT", "subscription",
          ("openai.com",)),
    _rule(r"^FIGMA", "figma", "Figma", "subscription", ("figma.com",)),
    _rule(r"^CLOUDWAYS", "cloudways", "Cloudways hosting", "hosting",
          ("cloudways.com",)),
    _rule(r"^VULTR", "vultr", "Vultr Cloud", "hosting", ("vultr.com",)),
    _rule(r"^NAMECHEAP", "namecheap", "Namecheap", "hosting",
          ("namecheap.com",)),
    # YouTube Premium before Google Ads: both descriptors start "GOOGLE *".
    _rule(r"^GOOGLE \*?\s?YOUTUBE|^YOUTUBE", "youtube_premium",
          "YouTube Premium", "subscription", ("google.com", "youtube.com")),

    # ------------------------------------------------------------ advertising
    _rule(r"^GOOGLE \*?\s?ADS|^GOOGLE ADS", "google_ads", "Google Ads",
          "advertising", ("google.com",)),
    _rule(r"^FACEBOOK ADS|^FB ADS|^META ADS|^FACEBK", "facebook_ads",
          "Facebook Ads", "advertising",
          ("facebook.com", "facebookmail.com", "meta.com", "fb.com")),

    # ------------------------------------------- marketplaces & travel (APAC)
    _rule(r"^SHOPEE", "shopee", "Shopee", "retail", ("shopee.com",
          "shopee.vn")),
    _rule(r"^LAZADA", "lazada", "Lazada", "retail", ("lazada.com",
          "lazada.vn")),
    _rule(r"^ALIEXPRESS", "aliexpress", "AliExpress", "retail",
          ("aliexpress.com",)),
    _rule(r"^BOOKING\.COM|^BOOKING ", "booking", "Booking.com", "travel",
          ("booking.com",)),
    _rule(r"^GRAB", "grab", "Grab", "transport", ("grab.com",)),
    _rule(r"THE COFFEE HOUSE", "thecoffeehouse", "The Coffee House", "dining",
          ("thecoffeehouse.com",), "merchant.square_prefix"),
    _rule(r"^STEAMGAMES|^STEAM\b|^VALVE", "steam", "Steam", "entertainment",
          ("steampowered.com", "steamgames.com")),

    # Bare "Apple"/"Amazon" as the Wealify ledger writes them. Kept after the
    # more specific APPLE.COM/BILL and AMZN MKTP rules above so a subscription
    # line is still read as a subscription.
    _rule(r"^APPLE", "apple", "Apple", "retail", ("apple.com",)),
    _rule(r"^AMAZON|^AMZN", "amazon", "Amazon", "retail", ("amazon.com",)),
    _rule(r"^PAYPAL$|^PAYPAL PAYOUT|^PAYPAL TRANSFER", "paypal_payout",
          "PayPal payout", "income", ("paypal.com",)),
    _rule(r"^PAYONEER", "payoneer", "Payoneer payout", "income",
          ("payoneer.com",)),
    _rule(r"^ETSY", "etsy", "Etsy payout", "income", ("etsy.com",)),
    _rule(r"^PINGPONG", "pingpong", "PingPong payout", "income",
          ("pingpongx.com", "pingpongpay.com")),

    # ------------------------------------------------- Wealify internal lines
    # These are movements between the user's own balances, not spending. They
    # are resolved so the cash-flow table can name them, and carry the
    # "transfer" category so `spend_cents` never counts them.
    _rule(r"^TOP-?UP FROM WALLET|^NAP VAO THE|^NẠP VÀO THẺ",
          "wealify_card_load", "Nạp tiền vào thẻ", "transfer",
          ("wealify.com", "wealify.example.com")),
    _rule(r"^NẠP TIỀN VÀO VÍ|^NAP TIEN VAO VI", "wealify_wallet_load",
          "Nạp tiền vào ví", "transfer", ("wealify.com", "wealify.example.com")),
    _rule(r"^NHẬN & CHUYỂN VỀ VÍ|^CHUYỂN VỀ VÍ",
          "wealify_wallet_credit", "Tiền về ví Wealify", "transfer",
          ("wealify.com", "wealify.example.com")),
    _rule(r"^RÚT VỀ NGÂN HÀNG|^WITHDRAW TO BANK|^RUT VE NGAN HANG",
          "wealify_bank_withdrawal", "Rút về ngân hàng", "transfer",
          ("wealify.com", "wealify.example.com")),
    _rule(r"^NẠP THẺ|^TOP-?UP DECLINED", "wealify_card_topup",
          "Nạp thẻ", "transfer", ("wealify.com", "wealify.example.com")),
    _rule(r"^SỐ DƯ ĐẦU KỲ", "wealify_opening_balance",
          "Số dư đầu kỳ", "transfer", ("wealify.com", "wealify.example.com")),
    # The issuer itself. Registered so a genuine Wealify notice is not reported
    # as a look-alike -- and so a message *claiming* to be Wealify from any
    # other domain still is.
    _rule(r"^WEALIFY", "wealify", "Wealify", "issuer",
          ("wealify.com", "wealify.example.com")),
    _rule(r"^FX FEE$|^PHÍ CHUYỂN ĐỔI$", "fx_fee",
          "Phí chuyển đổi tiền tệ", "fee", ("wealify.com", "wealify.example.com")),
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

# A trailing note the ledger appends to a line -- "(DUPLICATE)", "(USD)",
# "(VC04)". It qualifies the entry, it is not part of the merchant, and two
# lines that differ only by such a note describe the same thing.
TRAILING_ANNOTATION = re.compile(r"\s*\([^()]*\)\s*$")

# Wording the statement puts *in front of* the merchant. Stripping it lets one
# merchant rule serve the purchase, its subscription line and its FX fee, and
# lets a duplicated fee group with the fee it duplicates.
LEADING_QUALIFIERS = re.compile(
    r"^(SUBSCRIPTION|RECURRING|FX FEE FOR|FOREIGN TRANSACTION FEE FOR"
    r"|CONVERSION FEE FOR|PHI CHUYEN DOI CHO)\s+",
    re.I,
)


def normalize_descriptor(descriptor: str) -> str:
    """Collapse a raw descriptor to a comparable form (used for grouping)."""
    text = re.sub(r"\s+", " ", descriptor).strip().upper()
    text = LEADING_QUALIFIERS.sub("", text).strip()
    while True:
        stripped = TRAILING_ANNOTATION.sub("", text).strip()
        if stripped == text or not stripped:
            break
        text = stripped
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
