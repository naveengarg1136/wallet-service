# Assessment Evidence

## Live Singapore Run

On 2026-09-09, https://wallet-service-sg.onrender.com served revision
`199342be89212bd125af4daceda8efcc2b7b18d2`; GET `/healthz` returned HTTP 200 before
the full, unchanged assessment workload ran. Run ID:
`assessment-79f74ca62d334a1f870f756dc4e431d3`.

- [Summary](live-singapore-20260909-185430/summary.json): 31 checks passed, zero failed; 599 requests and zero server/transport errors, with no retries.
- [Client request timings and IDs](live-singapore-20260909-185430/requests.jsonl): every response preserved its correlation ID; no authorization headers or request bodies.
- [Metrics before](live-singapore-20260909-185430/metrics-before.txt) and [after](live-singapore-20260909-185430/metrics-after.txt): actual live Prometheus counters, latency buckets, and business metrics.

Duration was 73.451 seconds, request rate 8.155 requests/second, and client p99
7170.194 ms. Timings include network latency from the Windows test client and are
not a production SLO or sustained-capacity measurement. Expected authorization,
validation, and conflict 4xx responses are not counted as server errors.
The 300-transfer contention phase used 40 workers; all requests returned 201,
balances reconciled to the completed ledger, and the total remained 50,000 paise.
The full run also passed same-key replay and mixed transfer/reversal races.

The matching Render application-log export is still pending. These are real live
client measurements and metrics, not a substitute for server access/domain logs.
The public local and CI logs below are explicitly separate evidence sources.

## Local PostgreSQL Run

The files in [local](local) are generated from the patched API using disposable
PostgreSQL 16.14 on Windows and Python 3.13.15. They contain synthetic assessment
traffic only. They are **local runtime evidence, not Render production logs**.

- [Summary](local/summary.json): 31 checks passed, zero failed, zero server or transport errors; no HTTP retries.
- [Structured service logs](local/service.jsonl): 1,777 allowlisted JSON events; every test request has a matching access log.
- [Client request timings and IDs](local/requests.jsonl): no authorization headers or request bodies.
- [Metrics before](local/metrics-before.txt) and [after](local/metrics-after.txt): Prometheus counters and latency buckets.

Client p99 for this run was 1330.928 ms. This is a local workload observation,
not a production latency guarantee; see the summary for rate and duration.
The suite includes 50 simultaneous creates, 30 identical transfers, 300
contending transfers using 40 workers, ownership/validation/overflow tests,
and same-key/different-key/mixed reversal races.

## CI and Historical Failure

CI builds Docker Compose from a fresh checkout and publishes its own evidence
artifact and sanitized service logs in the **Publish sanitized service logs**
step. The exact live revision passed fresh-container CI before deployment:
https://github.com/naveengarg1136/wallet-service/actions/runs/34356479533

The original Oregon endpoint https://wallet-service-rxfw.onrender.com failed an
earlier contention run at revision `5bbfb29`: 285 server/transport errors among
399 requests before the harness aborted. Its failed local capture was retained
separately and was not overwritten or relabeled as passing. The Singapore result
above is a new run after deployment and health-pool changes, not proof that
region alone caused or resolved every historical gateway failure.

For Render-specific service logs, export the run's log window from the signed-in
Render dashboard, then use `scripts/export_logs.py` with the matching live
evidence directory. A private dashboard link alone is not publicly accessible
evidence. Do not publish raw logs, environment variables, or database credentials.