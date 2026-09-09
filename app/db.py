import pathlib

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from .config import settings

_connect_args = {}
if settings.db_ssl:
    _connect_args["ssl"] = True

engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
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
