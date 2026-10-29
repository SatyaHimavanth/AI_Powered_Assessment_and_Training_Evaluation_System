import asyncio
from fastapi import Response
from types import SimpleNamespace

from api.routers_auth import ACCESS_COOKIE_NAME, REFRESH_COOKIE_NAME, _set_auth_cookies
from core.auth import create_access_token, get_current_user


def test_auth_tokens_are_issued_as_httponly_strict_cookies():
    response = Response()

    _set_auth_cookies(response, "access-value", "refresh-value")

    headers = response.headers.getlist("set-cookie")
    access = next(value.lower() for value in headers if value.startswith(ACCESS_COOKIE_NAME))
    refresh = next(value.lower() for value in headers if value.startswith(REFRESH_COOKIE_NAME))
    assert "httponly" in access and "samesite=strict" in access
    assert "httponly" in refresh and "samesite=strict" in refresh
    assert "access-value" in next(value for value in headers if value.startswith(ACCESS_COOKIE_NAME))
    assert "refresh-value" in next(value for value in headers if value.startswith(REFRESH_COOKIE_NAME))


def test_auth_dependency_accepts_the_httponly_access_cookie():
    expected_user = SimpleNamespace(username="cookie-user", is_active=True)

    class ScalarResult:
        def scalars(self):
            return self

        def first(self):
            return expected_user

    class Database:
        async def execute(self, _query):
            return ScalarResult()

    user = asyncio.run(get_current_user(
        token=None,
        access_cookie=create_access_token({"sub": "cookie-user"}),
        db=Database(),
    ))

    assert user is expected_user
