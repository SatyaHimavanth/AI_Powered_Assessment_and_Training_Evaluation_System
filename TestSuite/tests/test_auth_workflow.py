from concurrent.futures import ThreadPoolExecutor

import pytest
import requests


pytestmark = pytest.mark.api


def test_invalid_login_does_not_issue_tokens(api_client, api_url):
    response = api_client.post(
        f"{api_url}/auth/login",
        json={"username": "missing-testsuite-user", "password": "wrong-password"},
        timeout=10,
    )
    assert response.status_code in {401, 403}
    assert "access_token" not in response.text


def test_login_identity_and_refresh(user_session, api_url, user_tokens):
    assert {"access_token", "role"} <= user_tokens.keys()
    assert "refresh_token" not in user_tokens
    assert user_session.cookies.get("assessment_refresh")
    me = user_session.get(
        f"{api_url}/auth/me",
        headers={"Authorization": f"Bearer {user_tokens['access_token']}"},
        timeout=10,
    )
    assert me.status_code == 200
    assert me.json()["role"] == "user"

    refreshed = user_session.post(
        f"{api_url}/auth/refresh",
        headers={"X-Token-Response": "bearer"},
        timeout=10,
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["access_token"]


def test_parallel_logins_do_not_fail(api_client, api_url):
    import os

    payload = {
        "username": os.getenv("TEST_USER_USERNAME", "user"),
        "password": os.getenv("TEST_USER_PASSWORD", "user123"),
    }

    def login():
        return requests.post(f"{api_url}/auth/login", json=payload, timeout=10)

    with ThreadPoolExecutor(max_workers=6) as pool:
        responses = list(pool.map(lambda _: login(), range(6)))
    assert {response.status_code for response in responses} == {200}


def test_candidate_provisioning_does_not_replace_another_users_refresh_cookie(
    provisioned_assessment, api_client, api_url, user_session, user_tokens
):
    assert user_tokens["role"] == "user"
    assert not api_client.cookies
    anonymous = api_client.get(f"{api_url}/auth/me", timeout=10)
    assert anonymous.status_code == 401
    refreshed = user_session.post(f"{api_url}/auth/refresh", timeout=10)
    assert refreshed.status_code == 200
    assert refreshed.json()["role"] == "user"
