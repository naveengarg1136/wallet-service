"""Offline validation that needs no database: imports, wiring, pure helpers.
Full concurrency validation runs via docker compose + scripts/burst.py.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://wallet:wallet@localhost:5432/wallet")

# 1. Config URL normalization handles the shapes managed hosts hand out.
from app.config import _normalize_db_url  # noqa: E402

assert _normalize_db_url("postgres://u:p@h:5432/d") == "postgresql+asyncpg://u:p@h:5432/d"
assert _normalize_db_url("postgresql://u:p@h/d") == "postgresql+asyncpg://u:p@h/d"
assert _normalize_db_url("postgresql://u:p@h/d?sslmode=require") == "postgresql+asyncpg://u:p@h/d"
assert (
    _normalize_db_url("postgres://u:p@h/d?sslmode=require&application_name=x")
    == "postgresql+asyncpg://u:p@h/d?application_name=x"
)
print("[ok] db url normalization")

# 2. Pydantic aliases: body uses `from`/`to`, and explicit names both work.
from app.schemas import TransferIn  # noqa: E402

t = TransferIn.model_validate(
    {"from": "11111111-1111-1111-1111-111111111111",
     "to": "22222222-2222-2222-2222-222222222222",
     "amount_paise": 500, "idempotency_key": "k1"}
)
assert str(t.from_wallet) == "11111111-1111-1111-1111-111111111111"
assert t.amount_paise == 500
try:
    TransferIn.model_validate(
        {"from": "11111111-1111-1111-1111-111111111111",
         "to": "22222222-2222-2222-2222-222222222222",
         "amount_paise": 0, "idempotency_key": "k1"}
    )
    raise SystemExit("amount_paise=0 should have failed validation")
except Exception:
    pass
print("[ok] transfer schema + validation")

# 3. Hash is stable and body-sensitive (drives same-key/different-body 409).
from app.store import _hash  # noqa: E402

h1 = _hash({"from": "a", "to": "b", "amount": 500, "kind": "transfer"})
h2 = _hash({"amount": 500, "to": "b", "from": "a", "kind": "transfer"})
h3 = _hash({"from": "a", "to": "b", "amount": 501, "kind": "transfer"})
assert h1 == h2 and h1 != h3
print("[ok] request hash stable + body-sensitive")

# 4. The ASGI app imports and exposes every route (engine is created but no
#    connection is made until lifespan/migrations run).
from app.main import app  # noqa: E402

paths = {r.path for r in app.routes}
for p in ["/wallets", "/wallets/{wallet_id}", "/wallets/{wallet_id}/deposit",
          "/transfers", "/transfers/{transfer_id}", "/transfers/{transfer_id}/reverse",
          "/healthz", "/metrics"]:
    assert p in paths, f"missing route {p}"
print("[ok] app imports; all routes present")

# 5. Migration SQL splits into clean statements.
from app.db import _MIGRATION  # noqa: E402

stmts = [s.strip() for s in _MIGRATION.read_text().split(";") if s.strip()]
assert any("CREATE TABLE IF NOT EXISTS wallets" in s for s in stmts)
assert any("idempotency_key TEXT   NOT NULL UNIQUE" in s or "idempotency_key" in s for s in stmts)
print(f"[ok] migration parses into {len(stmts)} statements")

print("\nALL OFFLINE CHECKS PASSED")
