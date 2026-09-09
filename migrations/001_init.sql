-- Money is always integer paise (BIGINT). No floats, ever.

CREATE TABLE IF NOT EXISTS wallets (
    id            UUID PRIMARY KEY,
    user_id       TEXT   NOT NULL UNIQUE,                       -- race-free get-or-create hinges on this
    balance_paise BIGINT NOT NULL DEFAULT 0 CHECK (balance_paise >= 0),  -- DB-level no-overdraft backstop
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
)
;

CREATE TABLE IF NOT EXISTS transfers (
    id              UUID PRIMARY KEY,
    idempotency_key TEXT   NOT NULL UNIQUE,                     -- exactly-once hinges on this
    from_wallet     UUID   REFERENCES wallets(id),             -- NULL only for deposits (external mint)
    to_wallet       UUID   NOT NULL REFERENCES wallets(id),
    amount_paise    BIGINT NOT NULL CHECK (amount_paise > 0),
    status          TEXT   NOT NULL CHECK (status IN ('pending', 'completed', 'declined')),
    kind            TEXT   NOT NULL DEFAULT 'transfer' CHECK (kind IN ('transfer', 'reversal', 'deposit')),
    reversal_of     UUID   REFERENCES transfers(id),
    reversed_by     UUID   REFERENCES transfers(id),
    request_hash    TEXT   NOT NULL,                            -- detects same-key / different-body replays
    decline_reason  TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
)
;

CREATE INDEX IF NOT EXISTS idx_transfers_from ON transfers(from_wallet)
;
CREATE INDEX IF NOT EXISTS idx_transfers_to ON transfers(to_wallet)
;
CREATE INDEX IF NOT EXISTS idx_transfers_reversal_of ON transfers(reversal_of)
;
