import asyncio
from functools import partial
from typing import Any, Callable, TypeVar

T = TypeVar("T")


async def run_db_sync(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Run a synchronous DB-bound callable in a threadpool and return its result.

    Use this from async FastAPI endpoints to offload blocking DB work to a
    thread so the event loop is not blocked. The callable should create and
    manage its own sync `Session` from `db.database.SessionLocal` (do not pass
    a Session instance created on the main thread into the worker thread).
    """
    loop = asyncio.get_running_loop()
    p = partial(fn, *args, **kwargs)
    return await loop.run_in_executor(None, p)
