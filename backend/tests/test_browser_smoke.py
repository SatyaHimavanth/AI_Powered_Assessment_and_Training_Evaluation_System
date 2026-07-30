"""Optional Playwright smoke tests for the browser login journey.

Install with ``uv sync --extra e2e`` and install a browser with
``uv run playwright install chromium``.  The frontend must be reachable at
FRONTEND_URL (default: http://localhost:5173) and configured to use the test
backend through VITE_API_BASE.
"""

import os

import pytest


pytest.importorskip("playwright.sync_api", reason="Install the optional 'e2e' dependency group")

FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5173").rstrip("/")
ADMIN_USERNAME = os.environ.get("TEST_ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "admin123")


@pytest.fixture()
def login_page(page):
    try:
        page.goto(f"{FRONTEND_URL}/login", wait_until="networkidle", timeout=15_000)
        page.wait_for_selector('input[type="text"]', timeout=10_000)
    except Exception as exc:
        pytest.skip(f"Frontend login form is not reachable at {FRONTEND_URL}: {exc}")
    return page


@pytest.mark.e2e
class TestBrowserLogin:
    def test_invalid_credentials_show_feedback(self, login_page):
        login_page.get_by_label("Username").fill("unknown-browser-user")
        login_page.get_by_label("Password").fill("invalid-password")
        login_page.get_by_role("button", name="Sign in").click()
        expect = pytest.importorskip("playwright.sync_api").expect
        expect(login_page.get_by_text("Login failed")).to_be_visible()

    def test_admin_login_reaches_dashboard(self, login_page):
        login_page.get_by_label("Username").fill(ADMIN_USERNAME)
        login_page.get_by_label("Password").fill(ADMIN_PASSWORD)
        login_page.get_by_role("button", name="Sign in").click()
        expect = pytest.importorskip("playwright.sync_api").expect
        expect(login_page).to_have_url(f"{FRONTEND_URL}/admin")
        expect(login_page.get_by_text("Admin Panel")).to_be_visible()
