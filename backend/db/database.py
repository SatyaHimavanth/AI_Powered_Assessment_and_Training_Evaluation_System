import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Async imports
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

load_dotenv()

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:password@localhost:5432/assessment_db",
)

# Synchronous engine & session (existing)
engine = create_engine(
    DATABASE_URL,
    pool_size=20,
    max_overflow=10,
    pool_timeout=30,
    pool_recycle=1800,
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


# ---------- Async support ---------- #
# Provide an async engine and an async sessionmaker so we can gradually
# migrate endpoints to true async DB usage. By default we try to infer
# an async URL for common drivers (Postgres + asyncpg). You can also
# set a separate `DATABASE_URL_ASYNC` env var if needed.

ASYNC_DATABASE_URL = os.environ.get("DATABASE_URL_ASYNC")
if not ASYNC_DATABASE_URL:
    if DATABASE_URL.startswith("postgresql://"):
        ASYNC_DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
    else:
        # Fallback: reuse same URL (user should prefer setting DATABASE_URL_ASYNC)
        ASYNC_DATABASE_URL = DATABASE_URL

async_engine = create_async_engine(
    ASYNC_DATABASE_URL, future=True, pool_size=20, max_overflow=10,
    pool_timeout=30, pool_recycle=1800, pool_pre_ping=True,
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
