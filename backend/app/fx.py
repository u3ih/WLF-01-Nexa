"""Foreign-exchange rates: fetch them, store them, look them up by date.

Split deliberately in two halves.

`fetch_*` talks to the network and belongs to ingestion — the scheduler and the
CLI. `FxTable` does arithmetic on rates already in hand and belongs to the
engine, which stays offline, pure and deterministic: an analysis must produce
the same numbers on a machine with no internet as on one with, or a report
cannot be reproduced or tested.

Three things about rates need saying.

1. **A rate has a publication date, not a validity date.** The ECB quotes on
   business days. A Saturday purchase has no Saturday rate, so the lookup takes
   the most recent quote at or before the transaction and *says which day it
   used*. Silently substituting Friday's rate and printing Saturday's date
   would be a small lie that compounds across a month.

2. **Only one direction is stored.** EUR→USD is fetched; USD→EUR is the
   reciprocal of the same publication, not a second observation. Inverting is
   marked as inverted so a reader can tell a fetched rate from a derived one.

3. **Converting is opt-in and labelled.** A converted amount is never mixed
   into a native-currency total silently. `convert` returns the rate it used
   alongside the figure so every restated amount can name its basis, and
   returns None rather than a guess when no rate covers the date.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Iterable

log = logging.getLogger("nexa.fx")

# European Central Bank reference rates, served without an API key. The host
# reports the date it actually answered with, which is what makes the
# business-day substitution in rule 1 visible instead of silent.
FRANKFURTER_URL = "https://api.frankfurter.dev/v1"
SOURCE = "ecb"

# The ECB publishes no đồng rate, and ₫ is the figure a Vietnamese reader
# actually reads. A second keyless publication covers it. Deliberately kept
# beside the ECB feed rather than replacing it: the report's row-by-row
# restatement stays on the central-bank series, and only the ₫ display — which
# is a reading aid, never a reported total — comes from here. Two hosts because
# a display rate that fails to fetch falls all the way back to a hardcoded
# number, which is the outcome worth spending one retry to avoid.
# Both serve the same tree, addressed differently: the CDN pins the version in
# the package name, the mirror in the subdomain.
CURRENCY_API_URLS = (
    "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@{version}/v1/currencies/{base}.json",
    "https://{version}.currency-api.pages.dev/v1/currencies/{base}.json",
)
DISPLAY_SOURCE = "currency-api"

# The pair the ₫ display converts. Named rather than passed around so the
# store, the job and the note all agree on which rate is "the" display rate.
DISPLAY_PAIR = ("USD", "VND")

# The ECB publishes against EUR, so that is the pair actually fetched whatever
# direction the caller wants.
ANCHOR = "EUR"

# How far back a transaction date may reach for a published rate. Four days
# covers a weekend plus a public holiday. Beyond that the gap is more likely a
# missing backfill than a closed market, and reporting "no rate" is the honest
# answer.
MAX_LOOKBACK_DAYS = 4


@dataclass(frozen=True)
class FxQuote:
    """One published rate: `rate` units of `quote` per one unit of `base`."""

    base: str
    quote: str
    quoted_on: date
    rate: Decimal
    source: str = SOURCE
    # True when this was derived by inverting the stored direction rather than
    # fetched in this direction.
    inverted: bool = False

    @property
    def pair(self) -> str:
        return f"{self.base}/{self.quote}"

    def invert(self) -> FxQuote:
        return FxQuote(base=self.quote, quote=self.base, quoted_on=self.quoted_on,
                       rate=Decimal(1) / self.rate, source=self.source,
                       inverted=not self.inverted)

    def apply(self, cents: int) -> int:
        """`cents` of `base` restated as `quote`, half-up to whole cents.

        The only place the arithmetic happens. A caller that already holds the
        quote for a row — the report converts row by row, so it does — must not
        round a second way, or a bucket and the figure beside it disagree by a
        cent for no reason a reader could ever find.
        """
        return int((Decimal(cents) * self.rate).quantize(Decimal(1),
                                                         rounding=ROUND_HALF_UP))

    def as_dict(self) -> dict[str, Any]:
        return {
            "base": self.base,
            "quote": self.quote,
            "quoted_on": self.quoted_on.isoformat(),
            # A string, not a float: the caller may be JSON, and a rate that
            # has survived NUMERIC all the way here should not lose digits on
            # the last hop.
            "rate": format(self.rate.normalize(), "f"),
            "source": self.source,
            "inverted": self.inverted,
        }


@dataclass
class Conversion:
    """A restated amount and the exact basis for restating it."""

    cents: int
    quote: FxQuote
    # The date asked about, which differs from `quote.quoted_on` whenever the
    # market was closed that day.
    asked_on: date

    @property
    def stale_days(self) -> int:
        return (self.asked_on - self.quote.quoted_on).days

    def as_dict(self) -> dict[str, Any]:
        return {
            "cents": self.cents,
            "asked_on": self.asked_on.isoformat(),
            "stale_days": self.stale_days,
            "rate": self.quote.as_dict(),
        }


def _decimal(raw: Any) -> Decimal | None:
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return value if value > 0 else None


# ------------------------------------------------------------------- lookup

class FxTable:
    """Published rates in memory, with the as-of lookback dated publication implies.

    Offline by construction: it never fetches. An empty table is a valid table —
    it makes every `convert` return None, which is how the engine behaves before
    any backfill has run and why a missing rate can never become a wrong figure.
    """

    def __init__(self, quotes: Iterable[FxQuote] = ()) -> None:
        # Keyed by pair, each list kept newest-first so the as-of scan stops at
        # the first candidate.
        self._by_pair: dict[tuple[str, str], list[FxQuote]] = {}
        for quote in quotes:
            self._by_pair.setdefault((quote.base, quote.quote), []).append(quote)
        for series in self._by_pair.values():
            series.sort(key=lambda q: q.quoted_on, reverse=True)

    def __len__(self) -> int:
        return sum(len(series) for series in self._by_pair.values())

    @property
    def pairs(self) -> list[str]:
        return sorted(f"{base}/{quote}" for base, quote in self._by_pair)

    @property
    def latest_quoted_on(self) -> date | None:
        days = [series[0].quoted_on for series in self._by_pair.values() if series]
        return max(days) if days else None

    def _as_of(self, day: date, base: str, quote: str) -> FxQuote | None:
        for candidate in self._by_pair.get((base, quote), ()):
            if candidate.quoted_on > day:
                continue
            if (day - candidate.quoted_on).days > MAX_LOOKBACK_DAYS:
                return None
            return candidate
        return None

    def latest(self, base: str, quote: str) -> FxQuote | None:
        """The newest rate held for a pair, however old it is.

        For display only, and the one place the lookback in `_as_of` is
        deliberately not applied: the ₫ figure beside a USD amount is not dated
        by the transaction, so a fortnight-old publication is still a better
        answer than a number compiled into the settings file. Anything that
        goes into a reported total must use `rate_on` and be told "no rate".
        """
        series = self._by_pair.get((base, quote))
        if series:
            return series[0]
        reverse = self._by_pair.get((quote, base))
        return reverse[0].invert() if reverse else None

    def rate_on(self, day: date, base: str, quote: str) -> FxQuote | None:
        """The rate to use for `day`, or None when nothing published covers it."""
        if base == quote:
            return FxQuote(base, quote, day, Decimal(1), source="identity")
        direct = self._as_of(day, base, quote)
        if direct is not None:
            return direct
        # Same publication, read the other way round. Cheaper and more honest
        # than fetching a second series that would only ever be its reciprocal.
        reverse = self._as_of(day, quote, base)
        return reverse.invert() if reverse is not None else None

    def convert(self, cents: int, day: date, base: str,
                quote: str) -> Conversion | None:
        """Restate `cents` of `base` as `quote`, or None if no rate covers `day`.

        Rounded half-up to whole cents, through `Decimal` throughout: every
        amount in this codebase is integer cents so that no total drifts, and
        converting via a binary float would reintroduce exactly that drift.
        """
        found = self.rate_on(day, base, quote)
        if found is None:
            return None
        return Conversion(cents=found.apply(cents), quote=found, asked_on=day)


EMPTY = FxTable()


def table_from_rows(rows: Iterable[dict[str, Any]]) -> FxTable:
    """Build a table from stored rows, skipping any that lost their rate."""
    quotes = []
    for row in rows:
        rate = _decimal(row.get("rate"))
        quoted_on = row.get("quoted_on")
        if rate is None or not isinstance(quoted_on, date):
            continue
        quotes.append(FxQuote(base=str(row["base"]), quote=str(row["quote"]),
                              quoted_on=quoted_on, rate=rate,
                              source=str(row.get("source") or SOURCE)))
    return FxTable(quotes)


def load_table(store: Any = None) -> FxTable:
    """Every stored rate, or an empty table if the database is unreachable.

    Degrading to empty rather than raising is the point: an analysis has to run
    without Postgres, and a missing rate already means "state the amount in its
    own currency" rather than "guess". A database outage therefore costs the
    conversions and nothing else.
    """
    if store is None:
        from .store import store as default_store

        store = default_store
    try:
        return table_from_rows(store.fx_quotes())
    except Exception as exc:                                # noqa: BLE001
        log.warning("fx rates unavailable, reporting in native currencies: %s",
                    exc)
        return EMPTY


# ------------------------------------------------------------------ fetching

def _pair_for_fetch(base: str, quote: str) -> tuple[str, str, bool]:
    """Which direction to actually request.

    The ECB quotes everything against the euro, so a GBP→USD request is served
    as EUR→{GBP,USD} and cross-computed by the host. Asking for the anchor as
    the base whenever it is one of the two currencies keeps the stored series in
    the direction the publication itself uses.
    """
    if quote == ANCHOR and base != ANCHOR:
        return quote, base, True
    return base, quote, False


def fetch_range(base: str, quote: str, start: date, end: date,
                timeout: float = 20.0) -> list[FxQuote]:
    """Every published rate for a pair between two dates, inclusive.

    One request for a whole span rather than one per day: a year of backfill is
    a single call, and the response tells us which days the market was open.
    """
    import httpx

    if start > end:
        return []
    src, dst, flip = _pair_for_fetch(base, quote)
    if src == dst:
        return []
    url = f"{FRANKFURTER_URL}/{start.isoformat()}..{end.isoformat()}"
    response = httpx.get(url, params={"base": src, "symbols": dst},
                         timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    out: list[FxQuote] = []
    for day_text, rates in sorted((payload.get("rates") or {}).items()):
        rate = _decimal((rates or {}).get(dst))
        if rate is None:
            continue
        try:
            quoted_on = date.fromisoformat(day_text)
        except ValueError:
            continue
        found = FxQuote(base=src, quote=dst, quoted_on=quoted_on, rate=rate)
        out.append(found.invert() if flip else found)
    return out


def fetch_display_quote(base: str = DISPLAY_PAIR[0], quote: str = DISPLAY_PAIR[1],
                        day: date | None = None,
                        timeout: float = 20.0) -> FxQuote | None:
    """The published rate for a pair the ECB does not carry, e.g. USD→VND.

    `day` pins the publication so a past date can be re-fetched and still give
    the number it gave then; omitting it takes the newest. Either way the
    quote carries the date the publication itself reports, not the date asked
    for — the same rule the ECB feed follows, for the same reason.

    Returns None rather than raising on a bad response: a display rate that
    cannot be fetched costs the ₫ figure its published basis, and the caller
    falls back to the configured rate. It must never cost the ₫ figure.
    """
    import httpx

    version = day.isoformat() if day is not None else "latest"
    for template in CURRENCY_API_URLS:
        url = template.format(version=version, base=base.lower())
        try:
            response = httpx.get(url, timeout=timeout, follow_redirects=True)
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:                            # noqa: BLE001
            log.warning("display rate fetch failed at %s: %s", url, exc)
            continue
        rate = _decimal((payload.get(base.lower()) or {}).get(quote.lower()))
        if rate is None:
            continue
        try:
            quoted_on = date.fromisoformat(str(payload.get("date", "")))
        except ValueError:
            quoted_on = day or date.today()
        return FxQuote(base=base, quote=quote, quoted_on=quoted_on, rate=rate,
                       source=DISPLAY_SOURCE)
    return None


# The display rate is read on every formatted amount — hundreds of times per
# response — and changes once a day, so it is resolved from the store once per
# process and held. `reset_display_cache` is what the fetch job calls after
# storing a new one; without it a running process would show yesterday's rate
# until restarted.
_display_cache: dict[tuple[str, str], FxQuote | None] = {}


def display_quote(base: str = DISPLAY_PAIR[0], quote: str = DISPLAY_PAIR[1],
                  store: Any = None) -> FxQuote | None:
    """The stored rate the ₫ display should use, or None to fall back.

    None covers every way this can be unavailable — rates disabled, Postgres
    down, nothing fetched yet — because the caller's response to all of them is
    the same: use the configured rate and say so.
    """
    key = (base, quote)
    if key in _display_cache:
        return _display_cache[key]
    from .config import settings

    found: FxQuote | None = None
    if settings.fx_enabled:
        if store is None:
            from .store import store as default_store

            store = default_store
        try:
            found = table_from_rows(store.fx_quotes()).latest(base, quote)
        except Exception as exc:                            # noqa: BLE001
            log.warning("display rate unavailable, using the configured one: %s",
                        exc)
    _display_cache[key] = found
    return found


def hold_display_quote(found: FxQuote | None,
                       pair: tuple[str, str] = DISPLAY_PAIR) -> None:
    """Put a rate straight into the hold, without a trip to the store.

    The fetch job already has the quote in hand, and a test has no store at
    all. Passing None holds "there is none", which is what makes the
    configured-rate fallback testable without a database.
    """
    _display_cache[pair] = found


def reset_display_cache() -> None:
    _display_cache.clear()


def fetch_day(base: str, quote: str, day: date,
              timeout: float = 20.0) -> FxQuote | None:
    """The rate covering one date.

    The host answers a closed-market date with the previous business day and
    says so in its `date` field, which is stored as-is — the substitution stays
    visible instead of being recorded as a publication on a day the market
    never opened.
    """
    import httpx

    src, dst, flip = _pair_for_fetch(base, quote)
    if src == dst:
        return None
    response = httpx.get(f"{FRANKFURTER_URL}/{day.isoformat()}",
                         params={"base": src, "symbols": dst}, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    rate = _decimal((payload.get("rates") or {}).get(dst))
    if rate is None:
        return None
    try:
        quoted_on = date.fromisoformat(payload.get("date", ""))
    except ValueError:
        quoted_on = day
    found = FxQuote(base=src, quote=dst, quoted_on=quoted_on, rate=rate)
    return found.invert() if flip else found


# ---------------------------------------------------------------- ingestion

def pairs_needed(currencies: Iterable[str], reporting: str = "USD"
                 ) -> list[tuple[str, str]]:
    """Which pairs this dataset actually needs, read off the data.

    Derived rather than configured: the export decides which currencies appear,
    and a hardcoded EUR/USD would go stale the first time a GBP row arrives.
    """
    return [(code, reporting) for code in sorted(set(currencies))
            if code and code != reporting]


def backfill(pairs: Iterable[tuple[str, str]], start: date, end: date,
             upsert: Any = None, timeout: float = 20.0) -> dict[str, Any]:
    """Fetch each pair over a span and hand the quotes to `upsert`.

    Returns a per-pair report rather than raising on the first failure: one pair
    the publication does not cover must not cost the others their backfill, and
    a partial result the caller can see beats an exception that hides which part
    succeeded.
    """
    from .store import store as default_store

    write = upsert if upsert is not None else default_store.upsert_fx_quotes
    summary: dict[str, Any] = {"start": start.isoformat(), "end": end.isoformat(),
                               "pairs": {}, "stored": 0, "errors": {}}
    for base, quote in pairs:
        label = f"{base}/{quote}"
        try:
            quotes = fetch_range(base, quote, start, end, timeout=timeout)
        except Exception as exc:                            # noqa: BLE001
            log.warning("fx backfill failed for %s: %s", label, exc)
            summary["errors"][label] = str(exc)
            continue
        stored = write(quotes) if quotes else 0
        summary["pairs"][label] = {"fetched": len(quotes), "stored": stored}
        summary["stored"] += stored
    return summary


def gap_start(latest: date | None, today: date,
              default_days: int = 30) -> date:
    """Where a daily top-up should resume from.

    Overlaps the last stored publication by a day. The ECB revises late on
    occasion, and re-fetching one day costs one row in an upsert while missing
    a revision leaves a wrong rate in place for good.
    """
    if latest is None:
        return today - timedelta(days=default_days)
    return min(latest, today)
