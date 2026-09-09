# Wallet & P2P Transfer Service

FastAPI + SQLAlchemy/asyncpg + PostgreSQL. Money is strictly integer paise;
transactional database constraints and ordered row locks enforce correctness.

- Live API: https://wallet-service-sg.onrender.com
- Repository: https://github.com/naveengarg1136/wallet-service
- Public Render logs (partial): [live capture](evidence/live-singapore-20260909-185430/service.jsonl)
- Complete local logs: [local capture](evidence/local/service.jsonl)
- Verification status and metrics: [evidence/README.md](evidence/README.md)
- CI and streaming-style job logs: https://github.com/naveengarg1136/wallet-service/actions
- One-page design: [WRITEUP.md](WRITEUP.md)

The Render capture contains 1,220 sanitized events, including access logs for
399 of 599 live requests (66.61%). The supplied export lacks the initial portion
of the run: 200 request access logs are unavailable. This is partial server-log
evidence, not a full trace. Local and CI logs are separate evidence sources;
they do not replace missing Render records. A private dashboard is not a public
log link. Acceptance of partial live logs is the assessment reviewer's decision.

The Singapore deployment passed all 31 live checks on 2026-09-09 at revision
`199342b`: 599 requests, zero server/transport errors, no retries, and client p99
7170.194 ms. [Live capture](evidence/live-singapore-20260909-185430/summary.json).
This is a measured correctness pass, not a latency guarantee. The earlier Oregon
deployment failed contention with gateway 502s; that failure is not a live pass.
All 599 client responses were checked independently of server-log coverage.

## Submission Checklist

| Deliverable | Evidence and Limitations |
| --- | --- |
| Public repository and deployed API | Links above; Render Free and Neon managed PostgreSQL in Singapore. |
| Correctness and concurrency | 31/31 live checks, including wallet creation, same-key replay, contention, and reversal races. |
| Public structured logs | Partial live capture: 399/599 access logs; complete local capture and separate CI logs. |
| Rate, p99, errors, business metrics | [Live evidence](evidence/README.md): 8.155 requests/s, client p99 7170.194 ms, zero server/transport errors, Prometheus snapshots. |
| One-command run and test | Compose and burst commands below; multi-stage, non-root image with `HEALTHCHECK`. |
| Fresh-checkout CI | [Passing CI for the tested application](https://github.com/naveengarg1136/wallet-service/actions/runs/34356479533). |
| Design, tradeoffs, AI attribution, cost | [Write-up](WRITEUP.md); assessment-only auth/funding, intended INR 0, billing not audited. |

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
python scripts/burst.py https://wallet-service-sg.onrender.com --evidence-dir evidence/live-retest
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
PostgreSQL. `render.yaml` contains the Singapore replacement blueprint. Render
copies `DATABASE_URL` from the existing `wallet-service` in the same workspace;
the secret value never enters Git. The blueprint also sets `DB_SSL=require`.
URL `sslmode` also enables TLS; the app uses certificate-verified TLS, including
when a libpq URL only requested encryption. Render provides `PORT` and
`RENDER_GIT_COMMIT`; GET `/` exposes the revision for deployment verification.

### Singapore Deployment

Neon is in AWS Singapore; the original Render service is in Oregon. Cross-region
SQL round trips extend lock hold times and are a latency risk under contention.
The blueprint pins new services to Singapore. Render does not support changing
an existing service's region, so this setting does not move the Oregon service.

1. In the same Render workspace as `wallet-service`, select **New > Blueprint**.
2. Connect this repository, select branch `main`, and use path `render.yaml`.
3. Review the plan: `wallet-service-sg`, **Docker**, **Singapore**, **Free**, and
	`/healthz`. The database URL is inherited, so no environment values need typing.
	If Render proposes changing the Oregon service or adding paid resources, stop.
4. Deploy the Blueprint. Verify GET `/` reports the expected tested commit and
	`/healthz` returns 200 before running the full burst against the new URL.
5. Use a new evidence directory for each retest; retain the failed capture.
	Export matching Render logs and update the public API/evidence links only
	after verification. Suspend the Oregon service after the replacement passes.

The source service must be named exactly `wallet-service`, must exist in the same
workspace, and must have a valid `DATABASE_URL`. If its name differs, change only
`fromService.name`. Do not delete it while this Blueprint references it; first
make the database configuration independent using the retirement steps below.
Referenced values refresh on Blueprint sync, not immediately on source changes.
If `wallet-service-sg` already exists, Render attempts to apply this configuration
to it; its region must already be Singapore. A Blueprint standardizes settings
but does not fix an unrelated image-build, startup, or database failure.

For a fresh workspace without the original service, replace `fromService` with
`sync: false` under `DATABASE_URL` and provide the Neon URL once in Render's
initial Blueprint form. Never put the secret in the YAML or chat.

No database migration or paid database is needed: both services use the existing
Neon database. They still connect over TLS on the public network, not a shared
private network. Free services share Render's monthly instance-hour allowance;
do not leave both running indefinitely. Select no paid add-ons and check usage.

### Retiring the Oregon Service

The current Blueprint still reads `DATABASE_URL` from `wallet-service`.
Deleting that service now can break future Blueprint syncs, even if the current
Singapore process continues running. No cloud resource was deleted here.

1. In Singapore's Render **Environment** settings, verify `DATABASE_URL` exists
	with the correct Neon value. Keep a private backup; never put it in Git or chat.
2. Change the Blueprint's `DATABASE_URL` entry from `fromService` to `sync: false`.
	Render ignores `sync: false` on existing Blueprint updates and preserves
	existing environment variables. For a new service, it prompts for the secret.
3. Sync the Blueprint and check Singapore's environment still has the value.
	If it is missing, set it privately in the dashboard before redeploying.
4. Redeploy Singapore, verify GET `/` and `/healthz`, and run a fresh burst into
	a new evidence directory. Confirm no Blueprint reference to Oregon remains.
5. Only then delete the Oregon **web service**, not Neon or the Singapore service.

Until then, suspend the old service to stop its compute usage while preserving
its configuration. The dependency-removal change has not been applied in this
repository. See [Render's environment-variable rules](https://render.com/docs/blueprint-spec#setting-environment-variables).

### Availability During Review

Render Free web services have no stated 10-15-day expiry, but no continuous
uptime guarantee. They sleep after 15 minutes without inbound traffic and wake
on the next request, normally in about a minute. Before testing, wait for
`/healthz` to return 200. The 30-day free Render Postgres expiry does not apply
to this deployment's Neon database.

Render grants 750 running instance-hours per workspace per calendar month.
One continuously running service uses at most 240 hours in 10 days or 360 in
15; two use 480 or 720, plus hours already consumed this month. Sleeping services
do not consume instance-hours. Exhaustion suspends free web services until the
next month. Bandwidth limits can also suspend services without a payment method;
with one, overages may incur charges. Build-minute exhaustion can block new
deploys. Check Render **Billing > Monthly Included Usage** and Neon usage/limits;
neither dashboard has been audited here. Avoid automated keep-alive pings and
repeated load runs during review. These conditions make a 10-15-day assessment
window feasible, not guaranteed. [Current Render limits](https://render.com/docs/free).

Neon Free currently includes 100 CU-hours per project/month, 0.5 GB storage, and
5 GB public network transfer. At a constant 0.25 CU, 15 days of continuous DB
activity uses 90 CU-hours before earlier usage; larger compute consumes more.
Queries from health checks can keep compute active while the app is running.
Neon scales to zero after five idle minutes, but exhausted compute/transfer
allowances suspend it until the next billing period; exceeding storage prevents
storage-increasing operations. Check the remaining allowance rather than assuming
calendar duration alone guarantees access. [Current Neon limits](https://neon.com/docs/introduction/plans).

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
The published partial Render capture retains that coverage failure: the exporter
reported 200 missing request logs and exited 1. Its safe output is shared with
the limitation disclosed; the exporter and CI coverage gate were not weakened.
CI prints sanitized logs in **Publish sanitized service logs** and retains the
evidence artifact for 30 days; checked-in evidence does not depend on retention.

## Container and CI

The Dockerfile is multi-stage, uses uid 10001, has a DB-backed `HEALTHCHECK`, and
executes Uvicorn directly for shutdown signals. CI builds Compose from a fresh
checkout, waits for readiness, runs unit regressions and the burst, exports logs
and metrics, and tears down the database. CI is the container validation gate;
local portable-PostgreSQL results alone do not prove the image or deployment.