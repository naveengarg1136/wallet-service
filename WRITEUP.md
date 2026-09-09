# Wallet & P2P Transfer: Design Write-up

**The design I finalized.** I prioritized three things: money must be conserved,
retries must not duplicate a transfer, and the submission must be reproducible
within an INR 0 target. I finalized a single FastAPI service with
SQLAlchemy/asyncpg and PostgreSQL as the authority for balances and transfer
results. Wallets have unique users and nonnegative BIGINT paise balances. Strict
integer validation avoids floating-point money; guarded credits prevent overflow.
Transfers retain their idempotency key, body hash, outcome, and reversal links.

**What I chose not to build.** I rejected a global application lock because it
serializes unrelated wallets and does not coordinate multiple processes.
Distributed locks add another failure mode when PostgreSQL already owns the
transaction. I chose READ COMMITTED with explicit row locks and constraints over
blanket SERIALIZABLE with transaction retries. I also rejected in-memory balance
fallbacks: if the database is unavailable, declining availability is preferable
to accepting an unverified money movement. This deliberately trades horizontal
write scaling and primary-failure availability for a smaller correctness model.

**How the final design protects money.** Concurrent wallet creation uses
`INSERT ... ON CONFLICT`. Each transfer claims its key, locks wallets in UUID
order using `FOR NO KEY UPDATE`, conditionally debits, credits, and stores its
result in one transaction. This lock mode is compatible with the foreign-key
`KEY SHARE` locks taken by transfer inserts. Rollback removes both money changes
and the key claim. Same-key contenders wait for the committed result; changed
bodies or operation reuse return 409. New records return 201, replays 200.
Insufficient-funds declines remain replayable after funding; overflow leaves no
partial debit or retained key. Reversals lock the original transfer, reuse the
wallet order, and prevent double refunds across different keys. Spent recipient
funds cause a decline, not an overdraft.

**How I drove the work.** I set the cost constraint, managed deployment accounts,
requested repeated correctness reviews, and supplied live log exports. I did not
treat the first working endpoint as completion. Early PostgreSQL tests exposed
deadlocks in the AI-assisted implementation; the initial locking explanation
was wrong. The corrected locking strategy gained regression coverage. After
Oregon contention failed, the deployment moved to Singapore near Neon, and a
reserved health-check pool addressed request-pool starvation. The unchanged live
workload then passed. These changes preceded success; they do not prove a single
cause for every earlier failure.

**What I can demonstrate.** Singapore revision `199342b` passed 31/31 checks on
2026-09-09: 599 requests, zero retries and server/transport errors, 73.451 seconds,
8.155 requests/s, and client p99 7170.194 ms. Coverage includes 50 concurrent
creates, 30 same-key transfers, 300 contending transfers at 40 workers, reversal
races, and balance/ledger reconciliation. This is correctness evidence, not a
latency SLO. Non-root multi-stage Docker, DB-backed `HEALTHCHECK`, Compose, and
fresh-checkout CI make the checks repeatable. Correlated post-commit JSON logs and
Prometheus metrics support diagnosis, not durable auditing. My
[evidence](evidence/README.md) discloses **399/599 live access logs**: 1,220 sanitized
events, 200 missing. The strict exporter still exits 1; local/CI captures are
separate, and acceptance of partial live logs rests with the reviewer.

**AI use and boundaries.** I used GitHub Copilot substantially for design options,
implementation, tests, configuration, debugging, and drafting this write-up. My
contribution was directing scope, selecting the final approach, managing
deployment, and driving review and evidence collection; I am not claiming every
line or idea was independently authored. Render Free and Neon Free target INR 0;
billing was not audited, and sleep/quotas prevent an uptime guarantee. Simple
bearer identity and test-fund minting are assessment conveniences, not real-money
security.