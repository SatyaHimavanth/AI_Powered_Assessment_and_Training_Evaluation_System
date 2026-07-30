"""Live API tests for registration, approval, authentication, and user status.

These tests use unique identifiers and remove every created registration/user in
teardown, so they can safely run repeatedly against a developer database.
"""

import os
import uuid

import pytest
import requests


BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/")
TEST_PASSWORD = "testpass123"


@pytest.fixture()
def pending_user(api_client, db_session):
    from db.models import RegistrationRequest, User

    suffix = uuid.uuid4().hex[:10]
    payload = {
        "username": f"api_user_{suffix}",
        "email": f"api_user_{suffix}@example.test",
        "contact_email": f"contact_{suffix}@example.test",
        "name": "API Test User",
        "account": "test-account",
        "password": TEST_PASSWORD,
    }
    try:
        response = api_client.post(f"{BASE_URL}/auth/register", json=payload, timeout=10)
    except requests.RequestException as exc:
        pytest.skip(f"Backend is not reachable at {BASE_URL}: {exc}")
    assert response.status_code == 200, response.text

    registration = (
        db_session.query(RegistrationRequest)
        .filter(RegistrationRequest.username == payload["username"])
        .first()
    )
    assert registration is not None
    try:
        yield payload, registration.id
    finally:
        db_session.query(User).filter(User.username == payload["username"]).delete(
            synchronize_session=False
        )
        db_session.query(RegistrationRequest).filter(
            RegistrationRequest.username == payload["username"]
        ).delete(synchronize_session=False)
        db_session.commit()


@pytest.mark.usefixtures("admin_token")
class TestRegistrationAndUserLifecycle:
    def test_pending_registration_cannot_be_duplicated(self, api_client, pending_user):
        payload, _ = pending_user
        response = api_client.post(f"{BASE_URL}/auth/register", json=payload, timeout=10)
        assert response.status_code == 400
        assert "pending" in response.json()["detail"].lower()

    def test_approved_user_can_login_refresh_and_be_deactivated(
        self, api_client, db_session, admin_token, pending_user
    ):
        if not admin_token:
            pytest.skip("Admin credentials are unavailable")

        payload, request_id = pending_user
        headers = {"Authorization": f"Bearer {admin_token}"}
        approved = api_client.post(
            f"{BASE_URL}/admin/approve/{request_id}", headers=headers, timeout=10
        )
        assert approved.status_code == 200, approved.text

        login = api_client.post(
            f"{BASE_URL}/auth/login",
            json={"username": payload["username"], "password": payload["password"]},
            timeout=10,
        )
        assert login.status_code == 200, login.text
        tokens = login.json()
        assert tokens["role"] == "user"

        me = api_client.get(
            f"{BASE_URL}/auth/me",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
            timeout=10,
        )
        assert me.status_code == 200
        assert me.json()["username"] == payload["username"]

        refreshed = api_client.post(
            f"{BASE_URL}/auth/refresh",
            json={"refresh_token": tokens["refresh_token"]},
            timeout=10,
        )
        assert refreshed.status_code == 200
        assert refreshed.json()["access_token"]

        from db.models import User

        user = db_session.query(User).filter(User.username == payload["username"]).first()
        assert user is not None
        disabled = api_client.post(
            f"{BASE_URL}/admin/users/{user.id}/toggle-active", headers=headers, timeout=10
        )
        assert disabled.status_code == 200, disabled.text

        blocked_login = api_client.post(
            f"{BASE_URL}/auth/login",
            json={"username": payload["username"], "password": payload["password"]},
            timeout=10,
        )
        assert blocked_login.status_code == 403
