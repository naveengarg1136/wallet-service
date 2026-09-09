import os
from dataclasses import dataclass
from sqlalchemy.engine import make_url


def _parse_db_url(url: str):
    parsed = make_url(url)
    if parsed.drivername in {"postgres", "postgresql"}:
        parsed = parsed.set(drivername="postgresql+asyncpg")
    return parsed


def _normalize_db_url(url: str) -> str:
    """Accept the many shapes a managed Postgres URL can take and return an
    asyncpg-compatible SQLAlchemy URL."""
    parsed = _parse_db_url(url).difference_update_query(["sslmode", "channel_binding"])
    return parsed.render_as_string(hide_password=False)


def _requires_tls(url: str, setting: str) -> bool:
    return setting.lower() in {"1", "true", "require", "yes"} or (
        _parse_db_url(url).query.get("sslmode", "disable") != "disable"
    )


_DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://wallet:wallet@localhost:5432/wallet")


@dataclass(frozen=True)
class Settings:
    database_url: str = _normalize_db_url(_DATABASE_URL)
    log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()
    # Set DB_SSL=require when talking to a Postgres that mandates TLS (e.g. a
    # public Railway/Neon endpoint). The private in-project URL does not need it.
    db_ssl: bool = _requires_tls(_DATABASE_URL, os.getenv("DB_SSL", ""))
    port: int = int(os.getenv("PORT", "8000"))
    revision: str = os.getenv("RENDER_GIT_COMMIT") or os.getenv("APP_REVISION", "local")


settings = Settings()
