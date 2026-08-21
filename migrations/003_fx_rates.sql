-- Daily foreign-exchange rates, so a figure in one currency can be restated in
-- another without the engine guessing a rate.
--
-- Why this table exists: the Wealify export prices 22 fee lines and 21 card
-- purchases in EUR and supplies no exchange rate at all (`exchange_rate` reads
-- the placeholder `NaN = 1 USD` on every row). A USD report therefore had to
-- leave those amounts out, and "Phí: $0.00" for a month that cost €0.58 in fees
-- reads as "you paid nothing".
--
-- One row per *published* rate, keyed by the day it was published rather than
-- the day it is asked about. The ECB quotes on business days only, so a
-- Saturday transaction has no Saturday rate; the lookup takes the most recent
-- `quoted_on` at or before the transaction date and reports which day it used.
-- Storing a copy per calendar day instead would invent a publication that
-- never happened and hide the substitution from the reader.
--
-- `rate` is NUMERIC, not double precision: money is integer cents everywhere in
-- this codebase precisely so no total drifts, and converting through a binary
-- float would put the drift back.

CREATE TABLE IF NOT EXISTS fx_rates (
    base        TEXT NOT NULL,
    quote       TEXT NOT NULL,
    quoted_on   DATE NOT NULL,
    rate        NUMERIC(20, 10) NOT NULL CHECK (rate > 0),
    -- Which publication this came from, e.g. "ecb" via Frankfurter. A rate the
    -- user is shown has to be attributable to somebody.
    source      TEXT NOT NULL,
    fetched_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (base, quote, quoted_on)
);

-- The hot query is "latest quote at or before this date for this pair".
CREATE INDEX IF NOT EXISTS fx_rates_pair_date_idx
    ON fx_rates (base, quote, quoted_on DESC);
