-- Nexa database schema.
--
-- The first five tables are application state.  The remaining tables are the
-- canonical, writeable representation of dataset/.  Raw rows are retained in
-- dataset_rows so an import can be audited without making the analysis depend
-- on the quirks of a CSV export.

CREATE TABLE IF NOT EXISTS scans (
    id               BIGSERIAL PRIMARY KEY,
    started_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at      TIMESTAMPTZ,
    trigger          TEXT NOT NULL DEFAULT 'manual',
    new_count        INTEGER NOT NULL DEFAULT 0,
    suppressed_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS flags (
    fingerprint     TEXT PRIMARY KEY,
    kind            TEXT NOT NULL,
    label           TEXT NOT NULL,
    confidence      NUMERIC(4,2) NOT NULL,
    amount_cents    BIGINT NOT NULL DEFAULT 0,
    txn_ids         JSONB NOT NULL DEFAULT '[]'::jsonb,
    period_key      TEXT NOT NULL DEFAULT '',
    occurred_on     DATE,
    statement_date  DATE,
    dispute_deadline DATE,
    params          JSONB NOT NULL DEFAULT '{}'::jsonb,
    sources         JSONB NOT NULL DEFAULT '[]'::jsonb,
    first_seen_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    seen_count      INTEGER NOT NULL DEFAULT 1,
    first_scan_id   BIGINT REFERENCES scans(id)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id            BIGSERIAL PRIMARY KEY,
    logged_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    event         TEXT NOT NULL,
    fingerprint   TEXT,
    kind          TEXT,
    label         TEXT,
    confidence    NUMERIC(4,2),
    reason        TEXT NOT NULL DEFAULT '',
    detail        JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS reminders (
    id            BIGSERIAL PRIMARY KEY,
    fingerprint   TEXT NOT NULL REFERENCES flags(fingerprint) ON DELETE CASCADE,
    due_date      DATE NOT NULL,
    kind          TEXT NOT NULL,
    title         TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'open',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (fingerprint, due_date)
);

CREATE TABLE IF NOT EXISTS report_drafts (
    id            BIGSERIAL PRIMARY KEY,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    recipient     TEXT NOT NULL,
    subject       TEXT NOT NULL,
    body          TEXT NOT NULL,
    period_key    TEXT NOT NULL DEFAULT '',
    lang          TEXT NOT NULL DEFAULT 'vi',
    confirm_token TEXT NOT NULL UNIQUE,
    status        TEXT NOT NULL DEFAULT 'draft',
    confirmed_at  TIMESTAMPTZ,
    sent_at       TIMESTAMPTZ,
    delivery      TEXT NOT NULL DEFAULT 'smtp',
    file_path     TEXT
);

CREATE TABLE IF NOT EXISTS dataset_imports (
    id             BIGSERIAL PRIMARY KEY,
    source_dir     TEXT NOT NULL,
    selected_mailbox TEXT NOT NULL DEFAULT '',
    status         TEXT NOT NULL DEFAULT 'completed',
    started_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at    TIMESTAMPTZ,
    file_count     INTEGER NOT NULL DEFAULT 0,
    row_count      INTEGER NOT NULL DEFAULT 0,
    notes          JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata       JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS dataset_files (
    id             BIGSERIAL PRIMARY KEY,
    import_id      BIGINT NOT NULL REFERENCES dataset_imports(id) ON DELETE CASCADE,
    file_name      TEXT NOT NULL,
    file_kind      TEXT NOT NULL,
    sha256         TEXT NOT NULL,
    encoding       TEXT,
    delimiter      TEXT,
    row_count      INTEGER NOT NULL DEFAULT 0,
    is_canonical   BOOLEAN NOT NULL DEFAULT TRUE,
    skip_reason    TEXT,
    header         JSONB NOT NULL DEFAULT '[]'::jsonb,
    UNIQUE (import_id, file_name)
);

CREATE TABLE IF NOT EXISTS dataset_rows (
    id             BIGSERIAL PRIMARY KEY,
    file_id        BIGINT NOT NULL REFERENCES dataset_files(id) ON DELETE CASCADE,
    row_number     INTEGER NOT NULL,
    payload        JSONB NOT NULL,
    is_canonical   BOOLEAN NOT NULL DEFAULT TRUE,
    skip_reason    TEXT,
    UNIQUE (file_id, row_number)
);

CREATE TABLE IF NOT EXISTS cards (
    card_id              TEXT PRIMARY KEY,
    card_code            TEXT,
    card_name            TEXT NOT NULL,
    last4                TEXT,
    card_number_masked   TEXT,
    expiry_date          DATE,
    status               TEXT NOT NULL DEFAULT 'active',
    balance_cents        BIGINT,
    currency             CHAR(3) NOT NULL DEFAULT 'USD',
    total_deposit_cents  BIGINT,
    total_withdrawal_cents BIGINT,
    purpose              TEXT,
    email                TEXT,
    phone                TEXT,
    card_network         TEXT,
    created_at           TIMESTAMP,
    source_import_id     BIGINT REFERENCES dataset_imports(id) ON DELETE SET NULL,
    raw_payload          JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (card_code)
);

CREATE TABLE IF NOT EXISTS virtual_accounts (
    id                   BIGSERIAL PRIMARY KEY,
    external_key         TEXT NOT NULL UNIQUE,
    account_name         TEXT NOT NULL,
    account_nickname     TEXT,
    account_number       TEXT,
    account_number_masked TEXT NOT NULL,
    payout_source        TEXT,
    bank_name            TEXT,
    swift_bic            TEXT,
    total_received_cents BIGINT,
    currency             CHAR(3) NOT NULL DEFAULT 'USD',
    fee_note             TEXT,
    status               TEXT NOT NULL DEFAULT 'active',
    managed_by           TEXT,
    created_at           TIMESTAMP,
    source_import_id     BIGINT REFERENCES dataset_imports(id) ON DELETE SET NULL,
    raw_payload          JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE UNIQUE INDEX IF NOT EXISTS virtual_accounts_number_uq
    ON virtual_accounts (account_number)
    WHERE account_number IS NOT NULL AND account_number <> '';

CREATE TABLE IF NOT EXISTS wallets (
    id                   BIGSERIAL PRIMARY KEY,
    wallet_key           TEXT NOT NULL UNIQUE,
    currency             CHAR(3) NOT NULL DEFAULT 'USD',
    opening_balance_cents BIGINT NOT NULL DEFAULT 0,
    opening_date         DATE,
    reported_balance_cents BIGINT,
    reported_at          DATE,
    source_import_id     BIGINT REFERENCES dataset_imports(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS financial_transactions (
    id                   BIGSERIAL PRIMARY KEY,
    transaction_id       TEXT NOT NULL,
    ledger                TEXT NOT NULL,
    source_file_id       BIGINT REFERENCES dataset_files(id) ON DELETE SET NULL,
    source_import_id     BIGINT REFERENCES dataset_imports(id) ON DELETE SET NULL,
    card_id              TEXT REFERENCES cards(card_id) ON DELETE SET NULL,
    virtual_account_id   BIGINT REFERENCES virtual_accounts(id) ON DELETE SET NULL,
    wallet_id            BIGINT REFERENCES wallets(id) ON DELETE SET NULL,
    created_at           TIMESTAMP NOT NULL,
    completed_at         TIMESTAMP,
    posted_date          DATE NOT NULL,
    raw_type             TEXT,
    normalized_type      TEXT,
    source_type          TEXT,
    card_name            TEXT,
    card_last4           TEXT,
    reference            TEXT,
    amount_cents         BIGINT NOT NULL DEFAULT 0,
    user_amount_cents    BIGINT,
    settled_amount_cents BIGINT,
    exchange_rate        NUMERIC(30,12),
    currency             CHAR(3) NOT NULL DEFAULT 'USD',
    status               TEXT NOT NULL DEFAULT 'success',
    linked_transaction_id TEXT,
    fee_cents            BIGINT,
    merchant             TEXT,
    mcc                  TEXT,
    gateway_ref          TEXT,
    notes                TEXT,
    raw_payload          JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (ledger, transaction_id)
);

CREATE TABLE IF NOT EXISTS wallet_events (
    event_id             TEXT PRIMARY KEY,
    wallet_id            BIGINT NOT NULL REFERENCES wallets(id) ON DELETE CASCADE,
    source_import_id     BIGINT REFERENCES dataset_imports(id) ON DELETE SET NULL,
    source_transaction_id TEXT,
    event_at             TIMESTAMP NOT NULL,
    kind                 TEXT NOT NULL,
    amount_cents         BIGINT NOT NULL,
    reference            TEXT,
    note                 TEXT,
    descriptor           TEXT,
    currency             CHAR(3) NOT NULL DEFAULT 'USD',
    status               TEXT NOT NULL DEFAULT 'success',
    target_card_id       TEXT REFERENCES cards(card_id) ON DELETE SET NULL,
    counterparty         TEXT,
    raw_payload          JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS emails (
    id                   BIGSERIAL PRIMARY KEY,
    mailbox              TEXT NOT NULL,
    message_id           TEXT NOT NULL,
    inbox                TEXT,
    from_name            TEXT,
    from_addr            TEXT,
    reply_to             TEXT,
    to_addr              TEXT,
    relay_from_name      TEXT,
    relay_from_addr      TEXT,
    subject              TEXT NOT NULL DEFAULT '',
    sent_at              TIMESTAMP NOT NULL,
    body_text            TEXT NOT NULL DEFAULT '',
    genre                TEXT NOT NULL DEFAULT 'other',
    transaction_ref      TEXT,
    card_id              TEXT REFERENCES cards(card_id) ON DELETE SET NULL,
    currency             CHAR(3) NOT NULL DEFAULT 'USD',
    html_file            TEXT,
    source_file_id       BIGINT REFERENCES dataset_files(id) ON DELETE SET NULL,
    source_import_id     BIGINT REFERENCES dataset_imports(id) ON DELETE SET NULL,
    raw_payload          JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (mailbox, message_id)
);

CREATE TABLE IF NOT EXISTS email_amounts (
    email_id             BIGINT NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
    ordinal              INTEGER NOT NULL,
    amount_cents         BIGINT NOT NULL,
    PRIMARY KEY (email_id, ordinal)
);

CREATE TABLE IF NOT EXISTS email_links (
    email_id             BIGINT NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
    url                  TEXT NOT NULL,
    PRIMARY KEY (email_id, url)
);

CREATE TABLE IF NOT EXISTS email_codes (
    email_id             BIGINT NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
    code                 TEXT NOT NULL,
    PRIMARY KEY (email_id, code)
);

CREATE INDEX IF NOT EXISTS flags_kind_idx ON flags (kind);
CREATE INDEX IF NOT EXISTS audit_log_fingerprint_idx ON audit_log (fingerprint);
CREATE INDEX IF NOT EXISTS reminders_due_idx ON reminders (due_date, status);
CREATE INDEX IF NOT EXISTS dataset_files_import_idx ON dataset_files (import_id);
CREATE INDEX IF NOT EXISTS dataset_rows_file_idx ON dataset_rows (file_id);
CREATE INDEX IF NOT EXISTS financial_transactions_date_idx
    ON financial_transactions (created_at DESC);
CREATE INDEX IF NOT EXISTS financial_transactions_reference_idx
    ON financial_transactions (reference);
CREATE INDEX IF NOT EXISTS financial_transactions_card_idx
    ON financial_transactions (card_id, created_at DESC);
CREATE INDEX IF NOT EXISTS wallet_events_date_idx ON wallet_events (event_at DESC);
CREATE INDEX IF NOT EXISTS emails_sent_at_idx ON emails (sent_at DESC);
CREATE INDEX IF NOT EXISTS emails_from_addr_idx ON emails (from_addr);
