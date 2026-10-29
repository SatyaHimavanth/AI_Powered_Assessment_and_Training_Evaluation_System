import asyncio
import os
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import HTTPException

os.environ.setdefault("JWT_SECRET_KEY", "unit-test-secret-that-is-at-least-32-bytes-long")

from core.auth import (  # noqa: E402
    ACCESS_TOKEN_EXPIRE_MINUTES,
    ALGORITHM,
    SECRET_KEY,
    create_access_token,
    create_refresh_token,
    get_current_user,
)


def test_access_and_refresh_tokens_have_distinct_purposes():
    access = jwt.decode(
        create_access_token({"sub": "candidate"}), SECRET_KEY, algorithms=[ALGORITHM]
    )
    refresh = jwt.decode(
        create_refresh_token({"sub": "candidate"}), SECRET_KEY, algorithms=[ALGORITHM]
    )

    assert access["token_use"] == "access"
    assert refresh["token_use"] == "refresh"
    latest_expiry = datetime.now(timezone.utc).timestamp() + ACCESS_TOKEN_EXPIRE_MINUTES * 60 + 1
    assert access["exp"] <= latest_expiry


@pytest.mark.parametrize(
    "token_factory",
    [
        create_refresh_token,
        lambda data: jwt.encode(data, SECRET_KEY, algorithm=ALGORITHM),
    ],
)
def test_refresh_or_untyped_token_is_rejected_before_database_access(token_factory):
    token = token_factory({"sub": "candidate"})

    class NoQueryDB:
        async def execute(self, *_args, **_kwargs):
            pytest.fail("invalid token purpose must be rejected before querying users")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(get_current_user(token=token, db=NoQueryDB()))

    assert exc.value.status_code == 401


def test_access_token_expiry_can_be_bounded_by_override():
    before = datetime.now(timezone.utc).timestamp()
    token = create_access_token({"sub": "candidate"}, timedelta(seconds=45))
    claims = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    assert claims["exp"] <= before + 46
