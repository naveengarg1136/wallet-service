# Wallet & P2P Transfer — Design Write-up (one page)

## Data model

Two tables. Money is `BIGINT` paise everywhere; there is no float or decimal in
the schema or the code.

- **wallets** — `id (uuid pk)`, `user_id (text, UNIQUE)`,
  `balance_paise (bigint, CHECK >= 0)`, timestamps.
  The `UNIQUE(user_id)` constraint is what makes get-or-create race-free; the
  `CHECK (balance_paise >= 0)` is a database-level backstop against overdraft.
- **transfers** — one row per money movement (`kind` ∈ `transfer | reversal |
  deposit`): `id`, `idempotency_key (text, UNIQUE)`, `from_wallet (uuid, NULL for
  deposits)`, `to_wallet`, `amount_paise (CHECK > 0)`, `status (pending |
  completed | declined)`, `reversal_of`, `reversed_by`, `request_hash`,
  `decline_reason`. It is both the ledger and the idempotency store, so
  uniqueness and the balance change commit in the *same* transaction.

## The simplest-correct mechanism for conservation + no-overdraft

An **atomic conditional debit**:

```sql
UPDATE wallets SET balance_paise = balance_paise - :amt
WHERE id = :from AND balance_paise >= :amt
RETURNING id;
```

Rows-affected `0` ⇒ the wallet couldn't cover it ⇒ the transfer is **declined**
with no partial apply and no negative balance. Rows-affected `1` ⇒ credit the
recipient and mark completed. The `UPDATE` takes and re-evaluates the row lock
atomically, so there is no read-modify-write window and therefore no lost update
— conservation holds under any concurrency.

**Why it's the simplest correct thing, and deadlock-free:** it debits exactly
**one** row per transfer. `A→B` and `B→A` firing simultaneously never grab two
rows in opposite orders, so the classic two-row deadlock cannot occur — there is
nothing to order. The credit is an unconditional `+` on the other row and can't
fail the balance test.

**Heavier alternatives I rejected:**
- **`SELECT … FOR UPDATE` on both wallets** — correct only with a *deterministic
  sorted lock order* (lock lower `id` first) to avoid the A→B/B→A deadlock. It's
  two row locks and more code to get a result the single conditional `UPDATE`
  already gives for free. Rejected as unnecessary here. (The reversal path *does*
  use one `FOR UPDATE` — on the original transfer row — purely to serialize two
  different-key reversals of the same transfer, not for the balance math.)
- **`SERIALIZABLE` isolation everywhere** — correct but pushes cost onto the app:
  every contended transfer risks a `40001` serialization failure and needs a
  retry loop. Cargo-culting "serializable for safety" would add latency and
  retry complexity for no benefit over the conditional `UPDATE`. Rejected.

## Where idempotency lives

In the database, on `transfers.idempotency_key (UNIQUE)`, claimed with
`INSERT … ON CONFLICT (idempotency_key) DO NOTHING RETURNING id` **inside the
same transaction** as the debit/credit. The winner of the race performs the
movement; concurrent duplicates lose the insert, then re-`SELECT` and return the
already-committed transfer. Because the key row and the ledger change commit
together, there is **no TOCTOU** — a retry storm of K identical requests yields
exactly one debit/credit and K identical responses. A **same key + different
body** replay is detected via a stored `request_hash` and returns **409**, never
a second debit. This works across instances because it's enforced in Postgres,
not app memory.

## Consistency vs availability

This is money, so I chose **consistency (CP)**. Every transfer is a single
strongly-consistent Postgres transaction; if the database is unreachable the
write **fails loudly** (`503`) rather than accepting a transfer it can't durably
and correctly record. What I consciously gave up: write availability during a DB
outage and easy horizontal write-scaling of the ledger. For a wallet, a declined
/ retryable request beats a double-spend or a lost debit. Read isolation is
`READ COMMITTED` (the default) — sufficient because correctness rides on the
atomic conditional `UPDATE` and the unique constraint, not on snapshot isolation.

## Reversal (R3)

`POST /transfers/{id}/reverse` reuses the exact same conditional-debit primitive
with roles swapped (debit the recipient, credit the sender). It has its **own**
`idempotency_key` committed in the same transaction, so reversing twice with the
same key refunds once. The original is locked `FOR UPDATE` and stamped with
`reversed_by`, so a second reversal under a *different* key returns **409
already_reversed** — no double refund. If the recipient has already spent the
funds the reversal **declines cleanly** (`recipient_insufficient_funds`) rather
than forcing a negative balance; allowing a negative "clawback" balance would be
a deliberate policy switch, not a silent one.

## AI: directed vs decided

- **I directed (my decisions, AI typed):** the correctness model — conditional
  `UPDATE` over `SELECT FOR UPDATE`/`SERIALIZABLE`; idempotency committed in the
  same transaction; single-row-debit as the deadlock-avoidance argument; paise-as-
  `BIGINT`; the CP stance; deposit-as-mint being outside conservation; the
  reversal semantics (own key, `reversed_by` guard, decline-vs-negative policy).
- **I let AI decide (accepted its design):** boilerplate shape (FastAPI wiring,
  Pydantic aliases for `from`/`to`), the JSON log formatter details, Prometheus
  bucket boundaries, the Dockerfile/compose scaffolding, and the burst-script
  ergonomics — all reviewed by me but not independently re-derived.

## Free-tier cost note

**₹0.** Local dev is `docker compose` (Postgres + app). Production is a Railway
free-tier service + a Railway free Postgres. No card required, no paid add-ons.
