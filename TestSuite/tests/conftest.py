import os
import uuid
from io import BytesIO
from collections.abc import Iterator

from openpyxl import Workbook
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
        headers={"X-Token-Response": "bearer"},
        timeout=10,
    )
    if response.status_code != 200:
        pytest.skip(f"Configured test account {username!r} cannot log in")
    return response.json()


@pytest.fixture(scope="session")
def user_session(api_client: requests.Session) -> Iterator[requests.Session]:
    with requests.Session() as client:
        yield client


@pytest.fixture(scope="session")
def user_tokens(user_session: requests.Session, api_url: str) -> dict:
    return _login(
        user_session,
        api_url,
        os.getenv("TEST_USER_USERNAME", "user"),
        os.getenv("TEST_USER_PASSWORD", "user123"),
    )


@pytest.fixture(scope="session")
def admin_tokens(api_client: requests.Session, api_url: str) -> dict:
    with requests.Session() as client:
        return _login(
            client,
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
    assessment_title = f"TestSuite concurrency assessment {suffix}"
    mixed_assessment_title = f"TestSuite mixed assessment {suffix}"
    assessment_id = None
    mixed_assessment_id = None
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

    workbook = Workbook()
    questions_sheet = workbook.active
    questions_sheet.title = "questions"
    questions_sheet.append([
        "type", "difficulty", "question", "option_a", "option_b",
        "option_c", "correct_options", "reference_answer", "default_code",
    ])
    for index in range(4):
        questions_sheet.append([
            "single_mcq", "easy", f"TestSuite concurrency question {suffix}-{index}?",
            "Correct", "Incorrect", None, "A", None, None,
        ])
    questions_sheet.append([
        "single_mcq", "medium", f"TestSuite mixed question {suffix}-wrong-answer",
        "Expected answer", "Wrong answer", None, "A", None, None,
    ])
    questions_sheet.append([
        "multi_mcq", "easy", f"TestSuite mixed question {suffix}-multi-select",
        "First correct", "Incorrect", "Second correct", "A|C", None, None,
    ])
    questions_sheet.append([
        "coding", "easy", f"TestSuite mixed question {suffix}-coding",
        None, None, None, None, "Read two integers and print their sum.",
        "# --- EDITABLE START ---\n# Write your solution here\n# --- EDITABLE END ---",
    ])
    questions_sheet.append([
        "text", "easy", f"TestSuite mixed question {suffix}-text",
        None, None, None, None,
        "An operating system manages hardware, memory, processes, and files.", None,
    ])
    test_cases_sheet = workbook.create_sheet("test_cases")
    test_cases_sheet.append(["question_number", "input", "expected_output", "is_sample"])
    test_cases_sheet.append([7, "2 3", "5", True])
    test_cases_sheet.append([7, "4 4", "8", False])
    xlsx_buffer = BytesIO()
    workbook.save(xlsx_buffer)
    xlsx_bytes = xlsx_buffer.getvalue()

    try:
        uploaded = api_client.post(
            f"{api_url}/questions/upload",
            headers=admin_headers,
            params={"topic_name": topic_name},
            files={"file": ("questions.xlsx", xlsx_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            timeout=30,
        )
        assert uploaded.status_code == 200, uploaded.text
        assert uploaded.json()["imported"] == 8

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
                "title": assessment_title,
                "description": "Automatically provisioned and removed by TestSuite",
                "duration": 30,
                "negative_marking": False,
                "topics": [
                    {
                        "topic_id": topic_id,
                        "question_type": "single_mcq",
                        "difficulty": "easy",
                        "question_count": 2,
                        "section_name": "Foundations",
                    },
                    {
                        "topic_id": topic_id,
                        "question_type": "single_mcq",
                        "difficulty": "easy",
                        "question_count": 2,
                        "section_name": "Applied skills",
                    },
                ],
                # Exercise direct recipient assignment independently of batches.
                "user_ids": [user["id"] for user in created_users],
            },
            timeout=30,
        )
        assert assessment.status_code == 200, assessment.text
        assessment_id = assessment.json()["id"]

        mixed_assessment = api_client.post(
            f"{api_url}/assessments/create",
            headers=admin_headers,
            json={
                "title": mixed_assessment_title,
                "description": "Mixed question types for answer and evaluation coverage",
                "duration": 30,
                "negative_marking": False,
                "topics": [
                    {"topic_id": topic_id, "question_type": "single_mcq", "difficulty": "medium", "question_count": 1, "section_name": "Objective"},
                    {"topic_id": topic_id, "question_type": "multi_mcq", "difficulty": "easy", "question_count": 1, "section_name": "Objective"},
                    {"topic_id": topic_id, "question_type": "coding", "difficulty": "easy", "question_count": 1, "section_name": "Coding"},
                    {"topic_id": topic_id, "question_type": "text", "difficulty": "easy", "question_count": 1, "section_name": "Written response"},
                ],
                "user_ids": [user["id"] for user in created_users],
            },
            timeout=30,
        )
        assert mixed_assessment.status_code == 200, mixed_assessment.text
        mixed_assessment_id = mixed_assessment.json()["id"]

        for user in created_users:
            with requests.Session() as client:
                tokens = _login(
                    client,
                    api_url,
                    user["username"],
                    user["password"],
                )
            user["headers"] = {
                "Authorization": f"Bearer {tokens['access_token']}"
            }

        yield {
            "assessment_id": assessment_id,
            "assessment_title": assessment_title,
            "mixed_assessment_id": mixed_assessment_id,
            "mixed_assessment_title": mixed_assessment_title,
            "batch_id": batch_id,
            "topic_id": topic_id,
            "users": created_users,
            "admin_headers": admin_headers,
        }
    finally:
        fixture_deleted = False
        if assessment_id or mixed_assessment_id:
            cleanup_assessment_id = assessment_id or mixed_assessment_id
            cleanup = api_client.delete(
                f"{api_url}/admin/testsuite/fixtures/{cleanup_assessment_id}",
                headers=admin_headers,
                timeout=30,
            )
            fixture_deleted = cleanup.status_code == 200
            if not fixture_deleted:
                # Older or non-local servers intentionally do not expose the
                # hard-delete route; retain their archival safety behavior.
                for current_assessment_id in (assessment_id, mixed_assessment_id):
                    if current_assessment_id:
                        api_client.delete(
                            f"{api_url}/assessments/{current_assessment_id}",
                            headers=admin_headers,
                            timeout=10,
                        )
        if batch_id and not fixture_deleted:
            api_client.delete(
                f"{api_url}/batches/{batch_id}",
                headers=admin_headers,
                timeout=10,
            )
        if topic_id and not fixture_deleted:
            api_client.delete(
                f"{api_url}/questions/topics/{topic_id}",
                headers=admin_headers,
                timeout=10,
            )
        for user in (created_users if not fixture_deleted else []):
            api_client.post(
                f"{api_url}/admin/users/{user['id']}/toggle-active",
                headers=admin_headers,
                timeout=10,
            )
