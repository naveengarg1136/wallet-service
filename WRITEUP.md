# Wallet & P2P Transfer: Design Write-up

**Model and atomicity.** FastAPI and SQLAlchemy/asyncpg use PostgreSQL as the
authority. Wallets have a unique user, UUID, and nonnegative BIGINT paise balance;
transfers store movement history, globally unique idempotency keys, body hashes,
status, and reversal links. Strict positive integer inputs and guarded credits
prevent invalid money and overflow. Deposits explicitly mint test funds.

**Concurrency.** Wallet creation uses `INSERT ... ON CONFLICT` and reselects the
winner. A transfer claims its key, locks both wallets in UUID order with
`FOR NO KEY UPDATE`, conditionally debits sufficient funds, credits, and records
the result in one transaction. Rollback removes all effects, including the key.
Every peer movement shares this order, preventing opposing wallet-lock cycles.
`NO KEY UPDATE` remains compatible with foreign-key `KEY SHARE` locks acquired
by movement inserts. READ COMMITTED plus these locks and constraints supports
the demonstrated invariants. Global serialization unnecessarily blocks unrelated
pairs; distributed locks add infrastructure; blanket SERIALIZABLE adds retries.

**Replay and reversal.** Same-key contenders wait for the committed result;
canonical body hashes reject changed-body or operation reuse with 409. New
completed or declined records return 201; identical replays return 200. Funding
does not change a stored insufficient-funds decline. Overflow returns 409 without
partial debit or a retained key. Reversal locks the original transfer and uses
the same wallet order with parties swapped. `reversed_by` prevents double refunds
under different keys and is mutable metadata on the original. Spent recipient
funds produce a persisted decline, never an overdraft.

**Operations and tradeoffs.** Consistency wins over availability: no offline
acceptance or in-memory balance fallback. Known DB/pool failures return 503;
unexpected errors return 500 with correlation IDs. Ambiguous timeouts require
same-key retries. One primary limits scaling and availability. A reserved,
bounded DB pool protects health checks from request-pool exhaustion. Post-commit
JSON money logs and Prometheus request/latency/business metrics are best-effort,
not an audit ledger. Multi-stage non-root Docker, DB-backed `HEALTHCHECK`, Compose,
and fresh-checkout CI provide repeatable build and test gates.

**Measured results.** On 2026-09-09, Singapore revision `199342b` passed 31/31
checks: 599 requests, no retries or server/transport errors, 73.451 seconds,
8.155 requests/s, and client p99 7170.194 ms. Tests include 50 creates, 30 same-key
transfers, 300 contending transfers at 40 workers, and reversal races. Balances
and ledgers reconciled. This is not a latency SLO or sustained-capacity claim.
[Evidence](evidence/README.md) includes full client measurements but **399/599
live access logs** (1,220 sanitized events; 200 missing). The exporter correctly
exits 1 for incomplete coverage. Local/CI logs are separate evidence. Earlier
Oregon contention failed; region and health-pool changes preceded this passing run.

**AI attribution and cost.** The developer supplied requirements, chose INR 0,
managed accounts/deployment, and requested review. GitHub Copilot proposed the
stack, design, code, tests, configuration, and documentation. Its initial deadlock
argument was wrong; CI failures drove ordered-lock corrections and regressions.
These choices are not claimed as independently derived by the developer.
Render Free and Neon Free in Singapore target INR 0; billing was not audited.
Idle sleep and shared quotas apply, so 10-15-day availability is not guaranteed.
Retire Oregon only after removing its Blueprint secret dependency and verifying
redeployment. Bearer identity and minting are assessment-only, never real-money
security. Partial live-log acceptance remains the reviewer's decision.