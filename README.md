# Wallet & P2P Transfer Service

FastAPI + SQLAlchemy/asyncpg + PostgreSQL. Money is strictly integer paise;
transactional database constraints and ordered row locks enforce correctness.

- Live API: https://wallet-service-rxfw.onrender.com
- Repository: https://github.com/naveengarg1136/wallet-service
- Public structured log capture: [evidence/local/service.jsonl](evidence/local/service.jsonl)
- Verification status and metrics: [evidence/README.md](evidence/README.md)
- CI and streaming-style job logs: https://github.com/naveengarg1136/wallet-service/actions
- One-page design: [WRITEUP.md](WRITEUP.md)

The checked-in log capture is from the local PostgreSQL validation run, not
Render production. CI publishes its own sanitized logs and downloadable evidence
on every run. A private Render dashboard URL is not a public log link.

The Oregon deployment passed wallet creation and same-key replay checks but
failed the latest contention run with gateway 502s. Local and container CI passes
do not establish a passing live deployment; Singapore verification is pending.

## Run and Test

```bash
docker compose up --build
```

This starts the non-root app on port 8000 and PostgreSQL 16, persisted in a named
volume. The database port is bound only to localhost. Docker Engine and Compose
are prerequisites; no cloud credentials are needed.

In a second terminal, from the repository root:

```bash
python scripts/burst.py http://localhost:8000 --evidence-dir evidence/run
```

The standard-library harness requires Python 3.9+ and exits nonzero on failure.
It tests 50 simultaneous wallet creates, 30 same-key transfers, changed-body
conflicts, 300 transfers with 40 workers across five wallets (including explicit
opposing transfers), per-wallet ledger reconciliation, no overdraft, reversals,
strict inputs, ownership, overflow rollback, and deposit replay. There are no
automatic HTTP retries or filtered-out failing responses. The Bash wrapper
`bash scripts/burst.sh <url>` invokes the same harness.

Test the deployed service after `/healthz` responds successfully:

```bash
python scripts/burst.py https://wallet-service-rxfw.onrender.com --evidence-dir evidence/live
```

For development without Docker, create a virtual environment, install
`requirements.txt`, provide a PostgreSQL `DATABASE_URL`, then run
`python -m uvicorn app.main:app`. Environment variables are read from the process;
`.env.example` is a template, not an automatically loaded credentials file.
Offline checks: `python -m unittest discover -s tests -v` and
`python scripts/validate_offline.py`.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/wallets` | Get or create the caller's single wallet. |
| GET | `/wallets/{id}` | Owner-only balance read. |
| POST | `/wallets/{id}/deposit` | Owner-only test funding, an explicit external mint. |
| POST | `/transfers` | Transfer with `from`, `to`, `amount_paise`, `idempotency_key`. |
| GET | `/transfers/{id}` | Status visible to either participant. |
| POST | `/transfers/{id}/reverse` | Original sender requests a reversal with a new key. |
| GET | `/healthz` | Readiness check including a database ping. |
| GET | `/metrics` | Prometheus counters and latency histogram. |
| GET | `/` | Service identity, endpoints, and deployed `revision`. |

Use `Authorization: Bearer <user-id>`. This is deliberately minimal assessment
authentication, not verified identity suitable for real money. The deposit
endpoint is test-only minting; conservation applies to peer transfers and
reversals without intervening deposits. Never expose this as a production wallet.

Money must be a JSON integer from 1 through 9223372036854775807. Strings, booleans,
floats and out-of-range values return 422. Transfers cannot use the same wallet
on both sides. New completed **or declined** movements return 201; identical
replays return 200. Keys are globally unique across all operation kinds. Same key
with a different operation/body returns 409. An insufficient-funds decline is
persisted, so funding later does not change that key's result. A balance-limit
409 rolls back the entire transaction and its key claim. `reversed_by` is current
metadata and can change on the original transfer after a successful reversal.

## Deployment and Cost

Current hosting is a Render free Docker web service plus Neon free managed
PostgreSQL. `render.yaml` contains the blueprint. Supply `DATABASE_URL` privately
in Render and set `DB_SSL=require`; never commit the real connection string.
URL `sslmode` also enables TLS; the app uses certificate-verified TLS, including
when a libpq URL only requested encryption. Render provides `PORT` and
`RENDER_GIT_COMMIT`; GET `/` exposes the revision for deployment verification.

### Singapore Deployment

Neon is in AWS Singapore; the original Render service is in Oregon. Cross-region
SQL round trips extend lock hold times and are a latency risk under contention.
The blueprint pins new services to Singapore. Render does not support changing
an existing service's region, so this setting does not move the Oregon service.

1. In Render, create a new **Web Service** from this repository's `main` branch.
2. Select **Docker**, name `wallet-service-sg`, region **Singapore**, and **Free**.
	Leave Root Directory blank and use Dockerfile path `./Dockerfile`.
3. Copy the existing `DATABASE_URL` privately in Render; retain `DB_SSL=require`
	and `LOG_LEVEL=INFO`. Set Health Check Path to `/healthz`.
4. Deploy the latest tested commit. Verify GET `/` reports that commit and
	`/healthz` returns 200 before running the full burst against the new URL.
5. Use a new evidence directory for each retest; retain the failed capture.
	Export matching Render logs and update the public API/evidence links only
	after verification. Suspend the Oregon service after the replacement passes.

No database migration or paid database is needed: both services use the existing
Neon database. They still connect over TLS on the public network, not a shared
private network. Free services share Render's monthly instance-hour allowance;
do not leave both running indefinitely. Select no paid add-ons and check usage.

Health probes use a separate one-connection pool with a three-second timeout,
so request-pool exhaustion alone does not block the database probe. A failed or
timed-out database ping still returns 503. This is not a throughput fix or proof
that every gateway failure is resolved; the unchanged live burst is the gate.

The target spend is INR 0, using only free plans with no paid add-ons selected.
Render services and Neon compute can sleep; cold starts, quotas, and service
policies apply. No universal promise is made about card requirements, permanent
free availability, or future prices. This repository does not verify billing
dashboards. Railway configuration remains an alternative, not the current host;
an expired Railway trial must not be treated as free hosting.

## Logs and Metrics

Application events are JSON with UTC millisecond timestamps and correlation IDs.
Send a bounded `X-Request-ID` (letters, digits, dot, underscore or hyphen); it is
echoed even on handled internal errors. Wallet creation, deposits, transfers,
declines, replays and reversals are logged. Money-success events are emitted only
after commit. Logs and metrics are best-effort observability, not a durable audit
ledger; the database records are authoritative.

The harness writes request timings/IDs, a summary (rate, client p99 and 5xx/transport
error rate), and before/after Prometheus snapshots. Expected 401/403/409/422
responses are checked explicitly but not counted as server errors. Server p99
uses the histogram, distinct from client timing:

```promql
sum(rate(http_requests_total[5m]))
histogram_quantile(0.99, sum by (le) (rate(http_request_duration_seconds_bucket[5m])))
sum(rate(http_requests_total{status=~"5.."}[5m])) / sum(rate(http_requests_total[5m]))
```

These expressions require a Prometheus-compatible scraper; `/metrics` by itself
is not a dashboard or historical store. Counters reset on process restart and
are per-process. No paid metrics backend is required by this implementation.

Capture shareable logs from a run:

```bash
docker compose logs --no-color --no-log-prefix app > app.log
python scripts/export_logs.py app.log evidence/run
```

The exporter includes only that run's correlation IDs and allowlisted event
fields, excludes credentials/arbitrary exception text, and fails when any
request lacks a matching access log. Never publish the unfiltered input log.
CI prints sanitized logs in **Publish sanitized service logs** and retains the
evidence artifact for 30 days; checked-in evidence does not depend on retention.

## Container and CI

The Dockerfile is multi-stage, uses uid 10001, has a DB-backed `HEALTHCHECK`, and
executes Uvicorn directly for shutdown signals. CI builds Compose from a fresh
checkout, waits for readiness, runs unit regressions and the burst, exports logs
and metrics, and tears down the database. CI is the container validation gate;
local portable-PostgreSQL results alone do not prove the image or deployment.