"""Domain operations. Every money movement is a single atomic Postgres
transaction: the idempotency-key row and the balance change commit together, so
a duplicate can never wedge itself between the check and the write (no TOCTOU).

Correctness mechanism (deliberately the simplest that is correct):
  * Debit  = `UPDATE wallets SET balance = balance - amt WHERE id = ? AND balance >= amt`.
             Rows-affected 0 => decline (no partial apply, no negative balance).
             This is a single row lock, so A->B and B->A can never deadlock on
             two rows in opposite order — there is only ever one debited row.
  * Exactly-once = `INSERT ... ON CONFLICT (idempotency_key) DO NOTHING` in the
             SAME transaction as the debit/credit. Loser of the race re-selects
             the committed transfer and returns it. Same key + different body => 409.
"""
import hashlib
import json
import logging
import uuid

from sqlalchemy import text

from . import metrics
from .db import engine
from .logging_conf import log_event

logger = logging.getLogger("wallet")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def _hash(obj: dict) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _wallet_dict(r) -> dict:
    return {"id": str(r["id"]), "user_id": r["user_id"], "balance_paise": r["balance_paise"]}


def _transfer_dict(r) -> dict:
    return {
        "id": str(r["id"]),
        "idempotency_key": r["idempotency_key"],
        "from_wallet": str(r["from_wallet"]) if r["from_wallet"] else None,
        "to_wallet": str(r["to_wallet"]) if r["to_wallet"] else None,
        "amount_paise": r["amount_paise"],
        "status": r["status"],
        "kind": r["kind"],
        "reversal_of": str(r["reversal_of"]) if r["reversal_of"] else None,
        "reversed_by": str(r["reversed_by"]) if r["reversed_by"] else None,
        "decline_reason": r["decline_reason"],
        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
    }


# --------------------------------------------------------------------------- #
# Wallets
# --------------------------------------------------------------------------- #
async def get_or_create_wallet(user_id: str) -> dict:
    new_id = uuid.uuid4()
    async with engine.begin() as conn:
        row = (
            await conn.execute(
                text(
                    """
                    INSERT INTO wallets (id, user_id, balance_paise)
                    VALUES (:id, :user_id, 0)
                    ON CONFLICT (user_id) DO NOTHING
                    RETURNING id, user_id, balance_paise
                    """
                ),
                {"id": new_id, "user_id": user_id},
            )
        ).mappings().first()
        created = row is not None
        if row is None:
            # Lost the create race (or already existed): return the one true wallet.
            row = (
                await conn.execute(
                    text("SELECT id, user_id, balance_paise FROM wallets WHERE user_id = :u"),
                    {"u": user_id},
                )
            ).mappings().first()
    if created:
        metrics.wallets_created_total.inc()
        log_event(logger, "wallet.created", wallet_id=str(row["id"]), user_id=user_id)
    return _wallet_dict(row)


async def get_wallet(wallet_id: uuid.UUID) -> dict:
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text("SELECT id, user_id, balance_paise FROM wallets WHERE id = :id"),
                {"id": wallet_id},
            )
        ).mappings().first()
    if not row:
        raise ApiError(404, "wallet_not_found", "wallet not found")
    return _wallet_dict(row)


# --------------------------------------------------------------------------- #
# Deposit (external mint — used to seed wallets; NOT a peer transfer)
# --------------------------------------------------------------------------- #
async def deposit(caller: str, wallet_id: uuid.UUID, amount: int, idem_key: str):
    request_hash = _hash({"deposit": str(wallet_id), "amount": amount})
    dep_id = uuid.uuid4()
    async with engine.begin() as conn:
        w = (
            await conn.execute(
                text("SELECT id, user_id FROM wallets WHERE id = :id"), {"id": wallet_id}
            )
        ).mappings().first()
        if not w:
            raise ApiError(404, "wallet_not_found", "wallet not found")
        if w["user_id"] != caller:
            raise ApiError(403, "forbidden", "caller does not own this wallet")

        won = (
            await conn.execute(
                text(
                    """
                    INSERT INTO transfers
                        (id, idempotency_key, from_wallet, to_wallet, amount_paise,
                         status, kind, request_hash)
                    VALUES (:id, :k, NULL, :to, :amt, 'pending', 'deposit', :h)
                    ON CONFLICT (idempotency_key) DO NOTHING
                    RETURNING id
                    """
                ),
                {"id": dep_id, "k": idem_key, "to": wallet_id, "amt": amount, "h": request_hash},
            )
        ).first()
        if won is None:
            existing = (
                await conn.execute(
                    text("SELECT * FROM transfers WHERE idempotency_key = :k"), {"k": idem_key}
                )
            ).mappings().first()
            if existing["request_hash"] != request_hash:
                raise ApiError(409, "idempotency_conflict", "idempotency key reused with a different body")
            metrics.idempotent_replays_total.inc()
            log_event(logger, "deposit.idempotent_replay", transfer_id=str(existing["id"]))
            return _transfer_dict(existing), False

        await conn.execute(
            text("UPDATE wallets SET balance_paise = balance_paise + :amt, updated_at = now() WHERE id = :id"),
            {"amt": amount, "id": wallet_id},
        )
        await conn.execute(
            text("UPDATE transfers SET status = 'completed' WHERE id = :id"), {"id": dep_id}
        )
        row = (
            await conn.execute(text("SELECT * FROM transfers WHERE id = :id"), {"id": dep_id})
        ).mappings().first()
    metrics.deposits_total.inc()
    log_event(logger, "deposit.applied", transfer_id=str(dep_id), to_wallet=str(wallet_id), amount_paise=amount)
    return _transfer_dict(row), True


# --------------------------------------------------------------------------- #
# Transfer
# --------------------------------------------------------------------------- #
async def create_transfer(caller: str, from_id: uuid.UUID, to_id: uuid.UUID, amount: int, idem_key: str):
    if from_id == to_id:
        raise ApiError(422, "same_wallet", "from and to wallets must differ")
    request_hash = _hash(
        {"from": str(from_id), "to": str(to_id), "amount": amount, "kind": "transfer"}
    )
    transfer_id = uuid.uuid4()

    async with engine.begin() as conn:
        wfrom = (
            await conn.execute(
                text("SELECT id, user_id FROM wallets WHERE id = :id"), {"id": from_id}
            )
        ).mappings().first()
        if not wfrom:
            raise ApiError(404, "wallet_not_found", "from wallet not found")
        if not (
            await conn.execute(text("SELECT 1 FROM wallets WHERE id = :id"), {"id": to_id})
        ).first():
            raise ApiError(404, "wallet_not_found", "to wallet not found")
        if wfrom["user_id"] != caller:
            raise ApiError(403, "forbidden", "caller does not own the from wallet")

        # (1) Claim the idempotency key IN THIS TRANSACTION.
        won = (
            await conn.execute(
                text(
                    """
                    INSERT INTO transfers
                        (id, idempotency_key, from_wallet, to_wallet, amount_paise,
                         status, kind, request_hash)
                    VALUES (:id, :k, :f, :t, :amt, 'pending', 'transfer', :h)
                    ON CONFLICT (idempotency_key) DO NOTHING
                    RETURNING id
                    """
                ),
                {"id": transfer_id, "k": idem_key, "f": from_id, "t": to_id, "amt": amount, "h": request_hash},
            )
        ).first()
        if won is None:
            existing = (
                await conn.execute(
                    text("SELECT * FROM transfers WHERE idempotency_key = :k"), {"k": idem_key}
                )
            ).mappings().first()
            if existing["request_hash"] != request_hash:
                raise ApiError(409, "idempotency_conflict", "idempotency key reused with a different body")
            metrics.idempotent_replays_total.inc()
            log_event(logger, "transfer.idempotent_replay", transfer_id=str(existing["id"]),
                      idempotency_key=idem_key)
            return _transfer_dict(existing), False

        # (2) Atomic conditional debit — the whole correctness story in one statement.
        debited = (
            await conn.execute(
                text(
                    """
                    UPDATE wallets SET balance_paise = balance_paise - :amt, updated_at = now()
                    WHERE id = :f AND balance_paise >= :amt
                    RETURNING id
                    """
                ),
                {"amt": amount, "f": from_id},
            )
        ).first()
        if debited is None:
            await conn.execute(
                text(
                    "UPDATE transfers SET status = 'declined', decline_reason = 'insufficient_funds' "
                    "WHERE id = :id"
                ),
                {"id": transfer_id},
            )
            row = (
                await conn.execute(text("SELECT * FROM transfers WHERE id = :id"), {"id": transfer_id})
            ).mappings().first()
            metrics.transfers_declined_insufficient_funds_total.inc()
            log_event(logger, "transfer.declined", transfer_id=str(transfer_id),
                      reason="insufficient_funds", from_wallet=str(from_id), amount_paise=amount)
            return _transfer_dict(row), True

        log_event(logger, "transfer.debited", transfer_id=str(transfer_id),
                  from_wallet=str(from_id), amount_paise=amount)
        # (3) Credit + finalize, still the same transaction.
        await conn.execute(
            text("UPDATE wallets SET balance_paise = balance_paise + :amt, updated_at = now() WHERE id = :t"),
            {"amt": amount, "t": to_id},
        )
        log_event(logger, "transfer.credited", transfer_id=str(transfer_id),
                  to_wallet=str(to_id), amount_paise=amount)
        await conn.execute(
            text("UPDATE transfers SET status = 'completed' WHERE id = :id"), {"id": transfer_id}
        )
        row = (
            await conn.execute(text("SELECT * FROM transfers WHERE id = :id"), {"id": transfer_id})
        ).mappings().first()

    metrics.transfers_created_total.inc()
    log_event(logger, "transfer.created", transfer_id=str(transfer_id),
              from_wallet=str(from_id), to_wallet=str(to_id), amount_paise=amount, status="completed")
    return _transfer_dict(row), True


async def get_transfer(transfer_id: uuid.UUID) -> dict:
    async with engine.connect() as conn:
        row = (
            await conn.execute(text("SELECT * FROM transfers WHERE id = :id"), {"id": transfer_id})
        ).mappings().first()
    if not row:
        raise ApiError(404, "transfer_not_found", "transfer not found")
    return _transfer_dict(row)


# --------------------------------------------------------------------------- #
# Reversal (R3) — a second movement bound to the first. Reuses the exact same
# conditional-debit primitive with roles swapped.
# --------------------------------------------------------------------------- #
async def reverse_transfer(caller: str, original_id: uuid.UUID, idem_key: str):
    request_hash = _hash({"reverse_of": str(original_id), "kind": "reversal"})
    reversal_id = uuid.uuid4()

    async with engine.begin() as conn:
        # Lock the original so two different-key reversals of the same transfer
        # serialize here; the second sees reversed_by set and 409s cleanly.
        orig = (
            await conn.execute(
                text("SELECT * FROM transfers WHERE id = :id FOR UPDATE"), {"id": original_id}
            )
        ).mappings().first()
        if not orig:
            raise ApiError(404, "transfer_not_found", "original transfer not found")
        if orig["kind"] != "transfer":
            raise ApiError(422, "not_reversible", "only peer transfers can be reversed")
        if orig["status"] != "completed":
            raise ApiError(422, "not_reversible", "only completed transfers can be reversed")

        wfrom = (
            await conn.execute(
                text("SELECT user_id FROM wallets WHERE id = :id"), {"id": orig["from_wallet"]}
            )
        ).mappings().first()
        if wfrom["user_id"] != caller:
            raise ApiError(403, "forbidden", "only the original sender may reverse this transfer")

        # Claim the reversal's own idempotency key in this transaction.
        won = (
            await conn.execute(
                text(
                    """
                    INSERT INTO transfers
                        (id, idempotency_key, from_wallet, to_wallet, amount_paise,
                         status, kind, reversal_of, request_hash)
                    VALUES (:id, :k, :f, :t, :amt, 'pending', 'reversal', :orig, :h)
                    ON CONFLICT (idempotency_key) DO NOTHING
                    RETURNING id
                    """
                ),
                {
                    "id": reversal_id,
                    "k": idem_key,
                    "f": orig["to_wallet"],   # debit the recipient
                    "t": orig["from_wallet"], # credit the sender
                    "amt": orig["amount_paise"],
                    "orig": original_id,
                    "h": request_hash,
                },
            )
        ).first()
        if won is None:
            existing = (
                await conn.execute(
                    text("SELECT * FROM transfers WHERE idempotency_key = :k"), {"k": idem_key}
                )
            ).mappings().first()
            if existing["request_hash"] != request_hash:
                raise ApiError(409, "idempotency_conflict", "idempotency key reused with a different body")
            metrics.idempotent_replays_total.inc()
            log_event(logger, "reversal.idempotent_replay", transfer_id=str(existing["id"]))
            return _transfer_dict(existing), False

        # Already reversed by a *different* key => conflict, not a second refund.
        if orig["reversed_by"] is not None:
            raise ApiError(409, "already_reversed", "transfer has already been reversed")

        # Same atomic conditional debit, now against the recipient.
        debited = (
            await conn.execute(
                text(
                    """
                    UPDATE wallets SET balance_paise = balance_paise - :amt, updated_at = now()
                    WHERE id = :r AND balance_paise >= :amt
                    RETURNING id
                    """
                ),
                {"amt": orig["amount_paise"], "r": orig["to_wallet"]},
            )
        ).first()
        if debited is None:
            await conn.execute(
                text(
                    "UPDATE transfers SET status = 'declined', "
                    "decline_reason = 'recipient_insufficient_funds' WHERE id = :id"
                ),
                {"id": reversal_id},
            )
            row = (
                await conn.execute(text("SELECT * FROM transfers WHERE id = :id"), {"id": reversal_id})
            ).mappings().first()
            metrics.transfers_declined_insufficient_funds_total.inc()
            log_event(logger, "reversal.declined", transfer_id=str(reversal_id),
                      reason="recipient_insufficient_funds", reverses=str(original_id))
            return _transfer_dict(row), True

        await conn.execute(
            text("UPDATE wallets SET balance_paise = balance_paise + :amt, updated_at = now() WHERE id = :s"),
            {"amt": orig["amount_paise"], "s": orig["from_wallet"]},
        )
        await conn.execute(
            text("UPDATE transfers SET status = 'completed' WHERE id = :id"), {"id": reversal_id}
        )
        await conn.execute(
            text("UPDATE transfers SET reversed_by = :rev WHERE id = :orig"),
            {"rev": reversal_id, "orig": original_id},
        )
        row = (
            await conn.execute(text("SELECT * FROM transfers WHERE id = :id"), {"id": reversal_id})
        ).mappings().first()

    metrics.reversals_created_total.inc()
    log_event(logger, "reversal.created", transfer_id=str(reversal_id),
              reverses=str(original_id), amount_paise=orig["amount_paise"])
    return _transfer_dict(row), True
