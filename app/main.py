import logging
import re
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from . import metrics, store
from .config import settings
from .db import engine, ping, run_migrations
from .logging_conf import configure_logging, correlation_id, log_event
from .schemas import DepositIn, ReverseIn, TransferIn
from .store import ApiError

logger = logging.getLogger("wallet")
_UUID_IN_PATH = re.compile(r"/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging(settings.log_level)
    await run_migrations()
    log_event(logger, "service.started")
    yield
    await engine.dispose()


app = FastAPI(title="Wallet & P2P Transfer", version="1.0.0", lifespan=lifespan)


# --------------------------------------------------------------------------- #
# Observability middleware: correlation id + latency + metrics + access log.
# --------------------------------------------------------------------------- #
@app.middleware("http")
async def observability(request, call_next):
    cid = request.headers.get("x-request-id") or uuid.uuid4().hex
    token = correlation_id.set(cid)
    path_label = _UUID_IN_PATH.sub("/{id}", request.url.path)
    start = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        response.headers["x-request-id"] = cid
        return response
    finally:
        elapsed = time.perf_counter() - start
        if path_label != "/metrics":
            metrics.http_requests_total.labels(request.method, path_label, str(status)).inc()
            metrics.http_request_duration_seconds.labels(request.method, path_label).observe(elapsed)
            log_event(
                logger, "http.access",
                method=request.method, path=path_label, status=status,
                latency_ms=round(elapsed * 1000, 2),
            )
        correlation_id.reset(token)


@app.exception_handler(ApiError)
async def api_error_handler(_, exc: ApiError):
    return JSONResponse(
        status_code=exc.status,
        content={"error": exc.code, "message": exc.message, "correlation_id": correlation_id.get()},
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(_, exc: Exception):
    # Log the traceback as a structured event so a 500 is traceable by correlation id.
    log_event(logger, "request.error", level=logging.ERROR,
              error_type=type(exc).__name__, error=str(exc))
    logger.exception("unhandled error")
    return JSONResponse(
        status_code=500,
        content={"error": "internal_error", "correlation_id": correlation_id.get()},
    )


# --------------------------------------------------------------------------- #
# Auth: a bearer token identifies the caller. The token IS the user id.
# --------------------------------------------------------------------------- #
async def require_user(authorization: str = Header(default="")) -> str:
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing or malformed bearer token")
    token = authorization[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="empty bearer token")
    return token


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@app.get("/")
async def root():
    return {
        "service": "wallet-p2p-transfer",
        "endpoints": ["/wallets", "/wallets/{id}", "/transfers", "/transfers/{id}",
                      "/transfers/{id}/reverse", "/wallets/{id}/deposit", "/healthz", "/metrics"],
    }


@app.get("/healthz")
async def healthz():
    try:
        await ping()
    except Exception:
        raise HTTPException(status_code=503, detail="database unavailable")
    return {"status": "ok"}


@app.get("/metrics")
async def prometheus_metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/wallets")
async def post_wallet(user: str = Depends(require_user)):
    return await store.get_or_create_wallet(user)


@app.get("/wallets/{wallet_id}")
async def get_wallet(wallet_id: uuid.UUID, _: str = Depends(require_user)):
    return await store.get_wallet(wallet_id)


@app.post("/wallets/{wallet_id}/deposit")
async def post_deposit(wallet_id: uuid.UUID, body: DepositIn, response: Response,
                       user: str = Depends(require_user)):
    result, created = await store.deposit(user, wallet_id, body.amount_paise, body.idempotency_key)
    response.status_code = 201 if created else 200
    return result


@app.post("/transfers")
async def post_transfer(body: TransferIn, response: Response, user: str = Depends(require_user)):
    result, created = await store.create_transfer(
        user, body.from_wallet, body.to_wallet, body.amount_paise, body.idempotency_key
    )
    response.status_code = 201 if created else 200
    return result


@app.get("/transfers/{transfer_id}")
async def get_transfer(transfer_id: uuid.UUID, _: str = Depends(require_user)):
    return await store.get_transfer(transfer_id)


@app.post("/transfers/{transfer_id}/reverse")
async def post_reverse(transfer_id: uuid.UUID, body: ReverseIn, response: Response,
                       user: str = Depends(require_user)):
    result, created = await store.reverse_transfer(user, transfer_id, body.idempotency_key)
    response.status_code = 201 if created else 200
    return result
