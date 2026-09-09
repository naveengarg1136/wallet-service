# Wallet & P2P Transfer: Design Write-up

## Model and Money

`wallets` has a UUID primary key, unique `user_id`, BIGINT `balance_paise` with a
nonnegative check, and timestamps. `transfers` stores the UUID, globally unique
idempotency key, source/destination foreign keys, positive BIGINT amount, request
hash, kind, status, decline reason, and reversal links. It is both movement
history and the idempotency store. Deposits explicitly mint test funds and are
outside transfer/reversal conservation. Inputs are strict positive JSON integers;
credits also check the remaining BIGINT capacity.

## Simplest Correct Concurrency

Get-or-create uses `INSERT ... ON CONFLICT (user_id) DO NOTHING` and reselects the
winner. A transfer first claims its idempotency key, then locks both wallet rows
with `ORDER BY id FOR NO KEY UPDATE`. Every peer movement, including reversal,
uses this same UUID order. Under those locks, a conditional debit requires
`balance_paise >= amount`; the credit and final movement status commit in the
same PostgreSQL transaction. Failures roll back all changes. No in-memory lock
or read-modify-write balance calculation is used.

The original implementation incorrectly assumed that a conditional debit locked
only one row. The subsequent credit locks the other row too, and CI reproduced
opposing-direction deadlocks. Ordered two-wallet locking is the correction, not
an unnecessary alternative. `NO KEY UPDATE` is deliberate: it conflicts with
other balance writers but remains compatible with foreign-key `KEY SHARE`
locks acquired by movement inserts, avoiding a key-share-to-update lock cycle.

Rejected heavier alternatives are global/advisory serialization of all transfers
(unnecessarily limits unrelated wallet pairs), distributed locks (extra failure
modes and infrastructure), and blanket SERIALIZABLE isolation (adds retryable
serialization failures). READ COMMITTED plus database uniqueness, ordered row
locks, and atomic balance updates suffices for the demonstrated invariants.

## Idempotency and Reversal

`INSERT ... ON CONFLICT (idempotency_key) DO NOTHING RETURNING id` happens in the
same transaction as the movement. Concurrent losers wait for the winner and read
its committed result. A stored canonical body hash rejects changed-body/key reuse
with 409. Committed insufficient-funds declines are replayed too; a transaction
that rolls back leaves no key claim. Replays return 200 versus 201 for a new
record. The original transfer's `reversed_by` remains mutable status metadata.

A reversal first locks its original transfer row, claims its own key, then uses
the same ordered wallet movement with sender/recipient swapped. The original's
`reversed_by` prevents a second refund under another key. Spent recipient funds
produce a persisted decline instead of a negative balance. The original lock
serializes only reversals of that transfer; all wallet writers share one order.

## Consistency, Operations, and Limits

Writes favor durable consistency over availability during a database outage:
there is no offline acceptance queue or in-memory balance fallback. Known
connection/pool failures return 503; unexpected internal failures return 500,
both with correlation IDs. A timeout can have an ambiguous commit outcome, so
clients should retry with the same key. A single primary database remains a
write-availability and scaling limit. This is not a general claim of partition
tolerance beyond PostgreSQL's deployment guarantees.

JSON domain logs are emitted after money commits; correlation IDs connect them
to access logs and responses. Prometheus exposes request counts, latency buckets,
and domain counters. Logs/counters are best-effort, not a durable audit system.
The burst verifies every response, exact replay bodies, per-wallet reconciliation,
opposing traffic and reversal races without HTTP retries; evidence records the
actual target/revision and client p99 separately from server histogram metrics.

## AI Attribution and Cost

The developer supplied the assessment, required an INR 0 solution, carried out
account/deployment setup, and requested review and retesting. GitHub Copilot
proposed the stack, schema, concurrency design, implementation, tests, operations
configuration, and this documentation. The initial AI deadlock argument was
wrong; observed CI deadlocks drove the correction and regression tests. These
design choices are not represented as independently derived by the developer.

Deployment uses Render free Docker hosting and Neon free managed PostgreSQL, not
the expired Railway trial. Intended spend is INR 0 with no paid resources added;
billing dashboards were not independently audited. Free services may sleep and
have quotas, changing prices, or account verification requirements. Authentication
and funding are assessment-only and must not be used for real money.