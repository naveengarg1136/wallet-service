import os
from dataclasses import dataclass


def _normalize_db_url(url: str) -> str:
    """Accept the many shapes a managed Postgres URL can take and return an
    asyncpg-compatible SQLAlchemy URL."""
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://") and "+asyncpg" not in url:
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]
    # libpq params like sslmode/channel_binding are not understood by asyncpg.
    if "?" in url:
        base, query = url.split("?", 1)
        dropped = ("sslmode=", "channel_binding=")
        kept = [p for p in query.split("&") if not p.lower().startswith(dropped)]
        url = base + ("?" + "&".join(kept) if kept else "")
    return url


@dataclass(frozen=True)
class Settings:
    database_url: str = _normalize_db_url(
        os.getenv("DATABASE_URL", "postgresql+asyncpg://wallet:wallet@localhost:5432/wallet")
    )
    log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()
    # Set DB_SSL=require when talking to a Postgres that mandates TLS (e.g. a
    # public Railway/Neon endpoint). The private in-project URL does not need it.
    db_ssl: bool = os.getenv("DB_SSL", "").lower() in ("1", "true", "require", "yes")
    port: int = int(os.getenv("PORT", "8000"))


settings = Settings()
