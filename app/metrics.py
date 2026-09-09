from prometheus_client import Counter, Histogram

# HTTP-level metrics (request rate, latency for p99, error rate all derive from these).
http_requests_total = Counter(
    "http_requests_total", "Total HTTP requests", ["method", "path", "status"]
)
http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "path"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0),
)

# Domain counters (the business signal the exercise asks for explicitly).
wallets_created_total = Counter("wallets_created_total", "Wallets newly created")
deposits_total = Counter("deposits_total", "Deposits (external mint) applied")
transfers_created_total = Counter("transfers_created_total", "Transfers completed")
transfers_declined_insufficient_funds_total = Counter(
    "transfers_declined_insufficient_funds_total",
    "Transfers/reversals declined for insufficient funds",
)
idempotent_replays_total = Counter(
    "idempotent_replays_total", "Idempotent replays served from the stored result"
)
reversals_created_total = Counter("reversals_created_total", "Reversals completed")
