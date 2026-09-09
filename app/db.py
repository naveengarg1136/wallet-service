import asyncio
import pathlib
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from .config import settings

# Retain the pooled-endpoint compatibility configuration. Transaction lock order,
# not prepared-statement caching, resolved the reproduced contention deadlocks.
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

health_engine = create_async_engine(
    settings.database_url,
    isolation_level="AUTOCOMMIT",
    pool_pre_ping=True,
    pool_size=1,
    max_overflow=0,
    pool_timeout=1,
    pool_recycle=300,
    connect_args={**_connect_args, "timeout": 2, "command_timeout": 2},
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
    async with asyncio.timeout(3):
        async with health_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
