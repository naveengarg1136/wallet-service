# Assessment Evidence

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

## CI and Live Verification

CI builds Docker Compose from a fresh checkout and publishes its own evidence
artifact and sanitized service logs in the **Publish sanitized service logs**
step. CI URL: https://github.com/naveengarg1136/wallet-service/actions

The live endpoint is https://wallet-service-rxfw.onrender.com. The historical
deployment failed contention tests; the fixes require a new deployment. A new
live test and exact deployed-revision check are still pending at the time this
local capture was written. Do not treat these local results as a live pass.

For Render-specific service logs, export the run's log window from the signed-in
Render dashboard, then use `scripts/export_logs.py` with the matching live
evidence directory. A private dashboard link alone is not publicly accessible
evidence. Do not publish raw logs, environment variables, or database credentials.