import pytest
from playwright.sync_api import Page, expect


pytestmark = pytest.mark.e2e


def _open_login(page: Page, frontend_url: str):
    page.goto(f"{frontend_url}/login", wait_until="networkidle")
    expect(page.get_by_role("button", name="Sign in")).to_be_visible()


def _proxy_api(page: Page, api_url: str):
    def forward(route):
        route.fulfill(response=route.fetch())

    page.route(f"{api_url}/**", forward)


def test_invalid_login_has_visible_feedback(
    require_e2e, page, frontend_url, api_url
):
    _proxy_api(page, api_url)
    _open_login(page, frontend_url)
    page.get_by_label("Username").fill("missing-browser-user")
    page.get_by_label("Password").fill("invalid-password")
    page.get_by_role("button", name="Sign in").click()
    expect(page.get_by_text("Login failed")).to_be_visible()


def test_rapid_login_click_sends_one_request(require_e2e, page, frontend_url):
    requests_seen = 0

    def login_route(route):
        nonlocal requests_seen
        requests_seen += 1
        route.fulfill(
            status=200,
            content_type="application/json",
            body='{"access_token":"test","refresh_token":"test","role":"user"}',
        )

    page.route("**/auth/login", login_route)
    _open_login(page, frontend_url)
    page.get_by_label("Username").fill("user")
    page.get_by_label("Password").fill("password")
    button = page.get_by_role("button", name="Sign in")
    button.evaluate("(element) => { element.click(); element.click(); }")
    page.wait_for_timeout(100)
    assert requests_seen == 1


def test_admin_login_reaches_admin_shell(
    require_e2e, page, frontend_url, api_url, admin_tokens
):
    _proxy_api(page, api_url)
    _open_login(page, frontend_url)
    import os

    page.get_by_label("Username").fill(os.getenv("TEST_ADMIN_USERNAME", "admin"))
    page.get_by_label("Password").fill(os.getenv("TEST_ADMIN_PASSWORD", "admin123"))
    page.get_by_role("button", name="Sign in").click()
    expect(page).to_have_url(f"{frontend_url}/admin")
    expect(page.get_by_text("Admin Panel")).to_be_visible()
