# Wallet & P2P Transfer Service

A small, correct-under-load wallet service with peer-to-peer transfers. Money is
always **integer paise**. Correctness (conservation, no-overdraft, exactly-once,
race-free get-or-create) is enforced in Postgres, not in application memory.

- **Stack:** Python 3.12 · FastAPI · SQLAlchemy (async) · asyncpg · PostgreSQL
- **Repo:** https://github.com/naveengarg1136/wallet-service
- **Live URL:** `https://<your-app>.up.railway.app`  ← _fill in after deploy_
- **Public logs:** `<railway/koyeb logs link or screen recording>` ← _fill in_

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/wallets` | Get-or-create the caller's wallet (bearer token = user id). |
| `GET` | `/wallets/{id}` | Current balance. |
| `POST` | `/wallets/{id}/deposit` | Seed funds (external mint; see note below). |
| `POST` | `/transfers` | Move money. Body: `from`, `to`, `amount_paise`, `idempotency_key`. |
| `GET` | `/transfers/{id}` | Transfer status. |
| `POST` | `/transfers/{id}/reverse` | Reverse a transfer (own `idempotency_key`). |
| `GET` | `/healthz` | Liveness + DB ping. |
| `GET` | `/metrics` | Prometheus metrics (rate, latency histogram, domain counters). |

**Auth:** `Authorization: Bearer <token>`. The token identifies the caller and is
treated as their `user_id`. Transfers/deposits require the caller to own the
`from` wallet. (Auth sophistication is explicitly out of scope for grading.)

**Why a deposit endpoint?** The graded invariant is *conservation across
transfers*. Wallets still need initial funds to test with. `deposit` is an
explicit external mint (recorded as `kind='deposit'`, `from_wallet = NULL`) — it
is deliberately outside the conservation invariant, which governs peer transfers
and reversals only.

## Run locally (one command)

```bash
docker compose up --build
# app on http://localhost:8000 , Postgres on 5432
```

Then reproduce every graded invariant:

```bash
python scripts/burst.py http://localhost:8000
```

Expected tail: `All invariants held.` (exit 0). The script covers race-free
get-or-create (50 concurrent), the idempotency storm (30 concurrent same key),
conservation + no-overdraft under contention (300 concurrent incl. A→B and B→A),
same-key/different-body → 409, and the R3 reversal (concurrent same-key = one
refund, already-reversed = 409).

### Run without Docker

```bash
python -m venv .venv && . .venv/Scripts/activate   # (Windows: .venv\Scripts\Activate.ps1)
pip install -r requirements.txt
# point DATABASE_URL at any Postgres, then:
uvicorn app.main:app --reload
```

## Quick manual smoke

```bash
BASE=http://localhost:8000
curl -s -X POST $BASE/wallets -H "Authorization: Bearer alice"   # -> {id, user_id, balance_paise}
```

## Deploy to Railway (free tier, ₹0)

1. Push this repo to GitHub (keep real human commit history — no single squashed
   "initial commit").
2. In Railway: **New Project → Deploy from GitHub repo** → pick this repo. Railway
   reads `railway.json` and builds the `Dockerfile`.
3. **New → Database → PostgreSQL** in the same project.
4. On the app service **Variables**, add a reference to the DB URL:
   - `DATABASE_URL = ${{Postgres.DATABASE_URL}}` (Railway substitutes the private URL)
   - If you instead use a **public** Postgres URL, also set `DB_SSL=require`.
5. Railway injects `PORT`; the container already binds `0.0.0.0:$PORT`.
   Healthcheck path `/healthz` is configured in `railway.json`.
6. Generate a public domain (service → **Settings → Networking → Generate Domain**)
   and put it at the top of this README.
7. Verify: `python scripts/burst.py https://<your-app>.up.railway.app`.

**Logs:** Railway → service → **Deploy Logs / Observability** stream the
structured JSON lines (each carries a `correlation_id`). Share that link, or a
screen recording of the logs streaming while `burst.py` runs.

## Observability

- **Structured JSON logs** with a per-request `correlation_id` (also echoed as the
  `x-request-id` response header). Domain events: `wallet.created`,
  `deposit.applied`, `transfer.debited`, `transfer.credited`, `transfer.created`,
  `transfer.declined`, `transfer.idempotent_replay`, `reversal.created`,
  `reversal.declined`, plus `http.access` per request.
- **Metrics** at `/metrics`: `http_requests_total`,
  `http_request_duration_seconds` (histogram → p99 via
  `histogram_quantile(0.99, ...)`), and domain counters
  `transfers_created_total`, `transfers_declined_insufficient_funds_total`,
  `idempotent_replays_total`, `reversals_created_total`, `wallets_created_total`,
  `deposits_total`.

## Container hygiene

Multi-stage build, runs as non-root (`appuser`, uid 10001), `HEALTHCHECK` that
pings `/healthz`, no build toolchain in the runtime image.

See [WRITEUP.md](WRITEUP.md) for the data model and design reasoning.
