import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Async imports
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

load_dotenv()


def _resolve_database_url(app_env: str, configured_url: str | None) -> str:
    if configured_url:
        return configured_url
    if app_env.lower() in {"production", "prod"}:
        raise RuntimeError("DATABASE_URL is required when APP_ENV is production")
    return "postgresql://postgres:password@localhost:5432/assessment_db"


DATABASE_URL = _resolve_database_url(
    os.environ.get("APP_ENV", "development"), os.environ.get("DATABASE_URL")
)


def _pool_options() -> dict[str, int | bool]:
    """Keep each process's database connection budget explicit and bounded."""
    pool_size = int(os.environ.get("DB_POOL_SIZE", "5"))
    max_overflow = int(os.environ.get("DB_MAX_OVERFLOW", "5"))
    pool_timeout = int(os.environ.get("DB_POOL_TIMEOUT_SECONDS", "30"))
    if pool_size < 1 or max_overflow < 0 or pool_timeout < 1:
        raise RuntimeError(
            "DB_POOL_SIZE must be positive; DB_MAX_OVERFLOW must be nonnegative; "
            "DB_POOL_TIMEOUT_SECONDS must be positive"
        )
    return {
        "pool_size": pool_size,
        "max_overflow": max_overflow,
        "pool_timeout": pool_timeout,
        "pool_recycle": 1800,
        "pool_pre_ping": True,
    }


def _validate_connection_budget() -> int | None:
    """Validate peak sync+async connections across all configured API processes."""
    maximum = os.getenv("DB_SERVER_MAX_CONNECTIONS")
    if maximum is None or not maximum.strip():
        return None  # Local development has no known server capacity.
    try:
        maximum_i = int(maximum)
        reserve = int(os.getenv("DB_CONNECTION_RESERVE", "10"))
        replicas = int(os.getenv("DB_REPLICA_COUNT", "1"))
        processes = int(os.getenv("DB_WORKER_PROCESSES", "1"))
    except ValueError as exc:
        raise RuntimeError("Database connection budget settings must be integers") from exc
    pool = _pool_options()
    if maximum_i < 1 or reserve < 0 or replicas < 1 or processes < 1:
        raise RuntimeError("DB server capacity, reserve, replicas and worker processes must be valid positive counts")
    # This application creates both engines in every process. Include overflow,
    # since bursts can open it concurrently on both pools.
    peak = 2 * (int(pool["pool_size"]) + int(pool["max_overflow"])) * replicas * processes
    available = maximum_i - reserve
    if peak > available:
        raise RuntimeError(
            f"Configured SQLAlchemy pools may use {peak} connections across "
            f"{replicas} replica(s) x {processes} process(es), but the database "
            f"budget after {reserve} reserved connections is {available}. "
            "Reduce DB_POOL_SIZE/DB_MAX_OVERFLOW or correct the deployment budget."
        )
    return peak


_validate_connection_budget()


def _resolve_async_database_url(database_url: str) -> str:
    configured = os.environ.get("DATABASE_URL_ASYNC") or os.environ.get(
        "ASYNC_DATABASE_URL"
    )
    if configured:
        return configured
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return database_url

# Keep the configured sync driver explicit. SQLAlchemy 2.1 defaults the generic
# PostgreSQL URL to psycopg (v3), while this project installs psycopg2.
SYNC_DATABASE_URL = DATABASE_URL
if SYNC_DATABASE_URL.startswith("postgresql://"):
    SYNC_DATABASE_URL = SYNC_DATABASE_URL.replace(
        "postgresql://", "postgresql+psycopg2://", 1
    )

# Synchronous engine & session (existing)
engine = create_engine(
    SYNC_DATABASE_URL,
    **_pool_options(),
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


# ---------- Async support ---------- #
# Provide an async engine and an async sessionmaker so we can gradually
# migrate endpoints to true async DB usage. By default we try to infer
# an async URL for common drivers (Postgres + asyncpg). You can also
# set `DATABASE_URL_ASYNC` (or the legacy `ASYNC_DATABASE_URL`) if needed.

ASYNC_DATABASE_URL = _resolve_async_database_url(DATABASE_URL)

async_engine = create_async_engine(
    ASYNC_DATABASE_URL, future=True, **_pool_options(),
)

AsyncSessionLocal = async_sessionmaker(bind=async_engine, expire_on_commit=False, class_=AsyncSession)


async def get_async_db():
    """Async DB session dependency for new/async endpoints.

    Usage in FastAPI endpoints:
      async def endpoint(db: AsyncSession = Depends(get_async_db)):
          await db.execute(...)
    """
    async with AsyncSessionLocal() as session:
        yield session
