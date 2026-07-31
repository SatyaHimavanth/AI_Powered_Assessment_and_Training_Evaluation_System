import os
import csv
import io
import uuid
from collections.abc import Iterator

import pytest
import requests


API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173").rstrip("/")


def _enabled(name: str) -> bool:
    return os.getenv(name, "").lower() in {"1", "true", "yes"}


@pytest.fixture(scope="session")
def api_url() -> str:
    return API_BASE_URL


@pytest.fixture(scope="session")
def frontend_url() -> str:
    return FRONTEND_URL


@pytest.fixture(scope="session")
def api_client(api_url: str) -> Iterator[requests.Session]:
    client = requests.Session()
    try:
        response = client.get(f"{api_url}/health", params={"db": "false", "llm": "false"}, timeout=10)
    except requests.RequestException as exc:
        pytest.skip(f"Backend is not reachable at {api_url}: {exc}")
    if response.status_code != 200:
        pytest.skip(f"Backend health endpoint returned {response.status_code}")
    yield client
    client.close()


def _login(client: requests.Session, api_url: str, username: str, password: str) -> dict:
    response = client.post(
        f"{api_url}/auth/login",
        json={"username": username, "password": password},
        timeout=10,
    )
    if response.status_code != 200:
        pytest.skip(f"Configured test account {username!r} cannot log in")
    return response.json()


@pytest.fixture(scope="session")
def user_tokens(api_client: requests.Session, api_url: str) -> dict:
    return _login(
        api_client,
        api_url,
        os.getenv("TEST_USER_USERNAME", "user"),
        os.getenv("TEST_USER_PASSWORD", "user123"),
    )


@pytest.fixture(scope="session")
def admin_tokens(api_client: requests.Session, api_url: str) -> dict:
    return _login(
        api_client,
        api_url,
        os.getenv("TEST_ADMIN_USERNAME", "admin"),
        os.getenv("TEST_ADMIN_PASSWORD", "admin123"),
    )


@pytest.fixture(scope="session")
def user_headers(user_tokens: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {user_tokens['access_token']}"}


@pytest.fixture(scope="session")
def admin_headers(admin_tokens: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {admin_tokens['access_token']}"}


@pytest.fixture(scope="session")
def require_stateful() -> None:
    if not _enabled("RUN_STATEFUL_TESTS"):
        pytest.skip("Set RUN_STATEFUL_TESTS=1 to run state-changing workflows")


@pytest.fixture(scope="session")
def require_e2e() -> None:
    if not _enabled("RUN_E2E_TESTS"):
        pytest.skip("Set RUN_E2E_TESTS=1 to run browser workflows")


@pytest.fixture()
def provisioned_assessment(
    require_stateful,
    api_client,
    api_url,
    admin_headers,
):
    suffix = uuid.uuid4().hex[:10]
    topic_name = f"testsuite_topic_{suffix}"
    batch_name = f"testsuite_batch_{suffix}"
    assessment_id = None
    batch_id = None
    topic_id = None
    created_users = []
    test_password = "TestSuite123!"

    for index in range(3):
        username = f"testsuite_user_{suffix}_{index}"
        created = api_client.post(
            f"{api_url}/admin/users",
            headers=admin_headers,
            json={
                "username": username,
                "email": f"{username}@example.test",
                "contact_email": f"contact_{username}@example.test",
                "name": f"TestSuite User {index + 1}",
                "account": "automated-tests",
                "password": test_password,
                "role": "user",
            },
            timeout=10,
        )
        assert created.status_code == 200, created.text
        created_users.append(
            {
                "id": created.json()["id"],
                "username": username,
                "password": test_password,
            }
        )

    csv_buffer = io.StringIO()
    writer = csv.DictWriter(
        csv_buffer,
        fieldnames=[
            "type",
            "difficulty",
            "question",
            "option_a",
            "option_b",
            "correct_options",
        ],
    )
    writer.writeheader()
    for index in range(4):
        writer.writerow(
            {
                "type": "single_mcq",
                "difficulty": "easy",
                "question": f"TestSuite concurrency question {suffix}-{index}?",
                "option_a": "Correct",
                "option_b": "Incorrect",
                "correct_options": "A",
            }
        )

    try:
        uploaded = api_client.post(
            f"{api_url}/questions/upload",
            headers=admin_headers,
            params={"topic_name": topic_name},
            files={"file": ("questions.csv", csv_buffer.getvalue(), "text/csv")},
            timeout=30,
        )
        assert uploaded.status_code == 200, uploaded.text
        assert uploaded.json()["imported"] == 4

        topics = api_client.get(
            f"{api_url}/questions/topics", headers=admin_headers, timeout=10
        )
        assert topics.status_code == 200, topics.text
        topic_id = next(
            item["id"] for item in topics.json() if item["name"] == topic_name
        )

        batch = api_client.post(
            f"{api_url}/batches/create",
            headers=admin_headers,
            json={
                "name": batch_name,
                "description": "Isolated TestSuite batch",
                "status": "current",
            },
            timeout=10,
        )
        assert batch.status_code == 200, batch.text
        batch_id = batch.json()["id"]

        added = api_client.post(
            f"{api_url}/batches/{batch_id}/users",
            headers=admin_headers,
            json={"user_ids": [user["id"] for user in created_users]},
            timeout=10,
        )
        assert added.status_code == 200, added.text
        assert added.json()["added"] == 3

        assessment = api_client.post(
            f"{api_url}/assessments/create",
            headers=admin_headers,
            json={
                "title": f"TestSuite concurrency assessment {suffix}",
                "description": "Automatically provisioned and archived by TestSuite",
                "duration": 30,
                "negative_marking": False,
                "topics": [
                    {
                        "topic_id": topic_id,
                        "question_type": "single_mcq",
                        "difficulty": "easy",
                        "question_count": 4,
                        "section_name": "Concurrency",
                    }
                ],
                "batch_ids": [batch_id],
            },
            timeout=30,
        )
        assert assessment.status_code == 200, assessment.text
        assessment_id = assessment.json()["id"]

        for user in created_users:
            tokens = _login(
                api_client,
                api_url,
                user["username"],
                user["password"],
            )
            user["headers"] = {
                "Authorization": f"Bearer {tokens['access_token']}"
            }

        yield {
            "assessment_id": assessment_id,
            "users": created_users,
            "admin_headers": admin_headers,
        }
    finally:
        if assessment_id:
            api_client.delete(
                f"{api_url}/assessments/{assessment_id}",
                headers=admin_headers,
                timeout=10,
            )
        if batch_id:
            api_client.delete(
                f"{api_url}/batches/{batch_id}",
                headers=admin_headers,
                timeout=10,
            )
        if topic_id:
            api_client.delete(
                f"{api_url}/questions/topics/{topic_id}",
                headers=admin_headers,
                timeout=10,
            )
        for user in created_users:
            api_client.post(
                f"{api_url}/admin/users/{user['id']}/toggle-active",
                headers=admin_headers,
                timeout=10,
            )
