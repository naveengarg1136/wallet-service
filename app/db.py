import pathlib
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from .config import settings

# Neon's pooled endpoint (and any PgBouncer in transaction mode) is incompatible
# with asyncpg's default server-side prepared-statement cache: cached statements
# leak across pooled backends and collide under concurrency, surfacing as 500s.
# Disabling the caches and giving every prepared statement a unique name makes us
# safe behind PgBouncer while remaining correct on a plain Postgres too.
_connect_args = {
    "statement_cache_size": 0,
    "prepared_statement_cache_size": 0,
    "prepared_statement_name_func": lambda: f"__asyncpg_{uuid4()}__",
}
if settings.db_ssl:
    _connect_args["ssl"] = True

engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,
    pool_recycle=300,
    connect_args=_connect_args,
)

_MIGRATION = pathlib.Path(__file__).resolve().parent.parent / "migrations" / "001_init.sql"


async def run_migrations() -> None:
    """Apply the idempotent schema DDL on startup (CREATE TABLE IF NOT EXISTS ...)."""
    script = _MIGRATION.read_text(encoding="utf-8")
    statements = [s.strip() for s in script.split(";") if s.strip()]
    async with engine.begin() as conn:
        for stmt in statements:
            await conn.exec_driver_sql(stmt)


async def ping() -> None:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
