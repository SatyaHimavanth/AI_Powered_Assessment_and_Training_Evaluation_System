import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest


pytestmark = pytest.mark.api


def test_lightweight_health_is_service_readiness(api_client, api_url):
    response = api_client.get(
        f"{api_url}/health", params={"db": "false", "llm": "false"}, timeout=10
    )
    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "checks": {}}


def test_speed_test_is_unavailable_by_default(api_client, api_url):
    response = api_client.get(
        f"{api_url}/speed-test", params={"size": 4096}, timeout=10
    )
    assert response.status_code == 404


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/admin/users"),
        ("GET", "/user/assessments/"),
        ("GET", "/practice/access"),
        ("GET", "/interviews/templates"),
    ],
)
def test_protected_workflows_reject_anonymous_requests(api_client, api_url, method, path):
    response = api_client.request(method, f"{api_url}{path}", timeout=10)
    assert response.status_code in {401, 403}


def test_user_cannot_enter_admin_workflow(api_client, api_url, user_headers):
    response = api_client.get(f"{api_url}/admin/users", headers=user_headers, timeout=10)
    assert response.status_code == 403


def test_user_read_workflows_return_contracts(api_client, api_url, user_headers):
    paths_and_types = [
        ("/user/assessments/", list),
        ("/practice/access", dict),
        ("/interviews/templates", list),
        ("/interviews/my-sessions", list),
    ]
    for path, expected_type in paths_and_types:
        response = api_client.get(f"{api_url}{path}", headers=user_headers, timeout=15)
        assert response.status_code == 200, response.text
        assert isinstance(response.json(), expected_type)


def test_directly_assigned_assessment_is_visible_once_and_can_be_started(
    api_client, api_url, provisioned_assessment, user_headers
):
    """A direct user assignment grants access even when no assigned batch exists."""
    user = provisioned_assessment["users"][0]
    response = api_client.get(
        f"{api_url}/user/assessments/", headers=user["headers"], timeout=10
    )
    assert response.status_code == 200, response.text
    matching = [
        item for item in response.json()
        if item["id"] == provisioned_assessment["assessment_id"]
    ]
    assert len(matching) == 1
    assert matching[0]["status"] == "pending"

    admin_headers = provisioned_assessment["admin_headers"]
    assessment_detail = api_client.get(
        f"{api_url}/assessments/{provisioned_assessment['assessment_id']}",
        headers=admin_headers,
        timeout=10,
    )
    assert assessment_detail.status_code == 200, assessment_detail.text
    assert assessment_detail.json()["individual_user_count"] == 3

    results = api_client.get(
        f"{api_url}/assessments/{provisioned_assessment['assessment_id']}/results",
        headers=admin_headers,
        timeout=10,
    )
    assert results.status_code == 200, results.text
    assert results.json()["total_participants"] == 3
    assert {row["status"] for row in results.json()["user_results"]} == {"pending"}

    unassigned_list = api_client.get(
        f"{api_url}/user/assessments/", headers=user_headers, timeout=10
    )
    assert unassigned_list.status_code == 200, unassigned_list.text
    assert all(
        item["id"] != provisioned_assessment["assessment_id"]
        for item in unassigned_list.json()
    )
    forbidden_start = api_client.post(
        f"{api_url}/user/assessments/start/{provisioned_assessment['assessment_id']}",
        headers=user_headers,
        timeout=10,
    )
    assert forbidden_start.status_code == 403

    started = api_client.post(
        f"{api_url}/user/assessments/start/{provisioned_assessment['assessment_id']}",
        headers=user["headers"],
        timeout=20,
    )
    assert started.status_code == 200, started.text
    assert len(started.json()["questions"]) == 4


def test_assessment_creation_rejects_mixed_batch_and_user_assignment(
    api_client, api_url, provisioned_assessment
):
    payload = {
        "title": "TestSuite invalid mixed assignment",
        "duration": 30,
        "topics": [{
            "topic_id": provisioned_assessment["topic_id"],
            "question_type": "single_mcq",
            "difficulty": "easy",
            "question_count": 1,
        }],
        "batch_ids": [provisioned_assessment["batch_id"]],
        "user_ids": [provisioned_assessment["users"][0]["id"]],
    }
    response = api_client.post(
        f"{api_url}/assessments/create",
        headers=provisioned_assessment["admin_headers"],
        json=payload,
        timeout=10,
    )
    assert response.status_code == 400, response.text
    assert "not both" in response.json()["detail"]

    imported_response = api_client.post(
        f"{api_url}/admin/assessments/create-from-import",
        headers=provisioned_assessment["admin_headers"],
        json={
            "import_id": str(uuid.uuid4()),
            "title": "TestSuite invalid mixed imported assignment",
            "batch_ids": payload["batch_ids"],
            "user_ids": payload["user_ids"],
        },
        timeout=10,
    )
    assert imported_response.status_code == 400, imported_response.text
    assert "not both" in imported_response.json()["detail"]


@pytest.mark.parametrize(
    "payload",
    [
        {"event_id": str(uuid.uuid4()), "event_type": "invented_signal"},
        {"event_type": "focus_lost"},
        {"event_id": "not-a-uuid", "event_type": "focus_lost"},
    ],
)
def test_integrity_event_api_rejects_malformed_or_unsupported_signals(
    api_client, api_url, user_headers, payload
):
    response = api_client.post(
        f"{api_url}/user/assessments/save-violations",
        params={"attempt_id": str(uuid.uuid4())},
        json=payload,
        headers=user_headers,
        timeout=10,
    )
    assert response.status_code == 422


def test_integrity_event_api_does_not_reveal_another_attempt(api_client, api_url, user_headers):
    response = api_client.post(
        f"{api_url}/user/assessments/save-violations",
        params={"attempt_id": str(uuid.uuid4())},
        json={"event_id": str(uuid.uuid4()), "event_type": "focus_lost"},
        headers=user_headers,
        timeout=10,
    )
    assert response.status_code == 404


def test_concurrent_authenticated_reads_are_stable(api_url, user_headers):
    import requests

    def fetch_identity():
        return requests.get(f"{api_url}/auth/me", headers=user_headers, timeout=10)

    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(lambda _: fetch_identity(), range(16)))
    assert {response.status_code for response in responses} == {200}
    assert len({response.json()["username"] for response in responses}) == 1


def test_configured_cors_origin(api_client, api_url):
    origin = os.getenv("CORS_TEST_ORIGIN")
    if not origin:
        pytest.skip("Set CORS_TEST_ORIGIN to validate deployed CORS")
    response = api_client.options(
        f"{api_url}/auth/login",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
        timeout=10,
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == origin
