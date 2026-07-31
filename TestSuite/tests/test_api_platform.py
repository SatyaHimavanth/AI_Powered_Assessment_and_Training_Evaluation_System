import os
from concurrent.futures import ThreadPoolExecutor

import pytest


pytestmark = pytest.mark.api


def test_lightweight_health_is_service_readiness(api_client, api_url):
    response = api_client.get(
        f"{api_url}/health", params={"db": "false", "llm": "false"}, timeout=10
    )
    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "checks": {}}


def test_speed_test_enforces_bounds_and_size(api_client, api_url):
    response = api_client.get(f"{api_url}/speed-test", params={"size": 4096}, timeout=10)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/octet-stream")
    assert len(response.content) == 4096

    too_small = api_client.get(f"{api_url}/speed-test", params={"size": 1}, timeout=10)
    assert too_small.status_code == 422


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
