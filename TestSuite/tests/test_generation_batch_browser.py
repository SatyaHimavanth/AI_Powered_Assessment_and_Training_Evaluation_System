"""Real Chromium controls with deterministic batch APIs and no external models."""

from urllib.parse import urlparse

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


@pytest.mark.parametrize("action", ["retry", "delete"])
def test_admin_sees_generation_context_and_confirms_failed_action(
    require_e2e, page, frontend_url, api_url, action
):
    batch = {
        "id": "browser-failed-batch", "status": "failed", "topic_id": "topic",
        "topic_name": "PostgreSQL transactions", "question_type": "single_mcq", "difficulty": "hard",
        "requested_count": 25, "total_generated": 0, "total_approved": 0, "total_rejected": 0,
        "active_saved_count": 0, "archived_saved_count": 0, "error_message": "Synthetic provider failure",
        "can_retry": True, "retry_blocked_reason": None, "created_at": "2026-01-01T10:00:00Z",
        "completed_at": None, "filename": None,
    }
    actions = []
    deleted = False

    def api(route):
        nonlocal deleted
        path = urlparse(route.request.url).path
        if path == "/auth/me":
            data = {"username": "browser-admin", "name": "Browser Admin", "role": "admin"}
        elif path == "/admin/dashboard/counters":
            data = {}
        elif path == "/questions/topics":
            data = [{"id": "topic", "name": batch["topic_name"], "description": None}]
        elif path == "/admin/questions/generation/batches":
            data = {"items": [] if deleted else [batch], "total": 0 if deleted else 1}
        elif path == "/admin/questions/generation/batches/browser-failed-batch/retry":
            actions.append("retry")
            batch.update(status="pending", error_message=None, can_retry=False)
            data = batch
        elif path == "/admin/questions/generation/batches/browser-failed-batch" and route.request.method == "DELETE":
            actions.append("delete")
            deleted = True
            data = {"message": "Batch deleted. Saved questions were not changed."}
        else:
            data = {"items": [], "total": 0}
        route.fulfill(json=data)

    page.route(f"{api_url}/**", api)
    page.goto(f"{frontend_url}/admin")
    page.get_by_role("button", name="AI Generate", exact=True).click()
    expect(page.get_by_text("PostgreSQL transactions · Single MCQ · 25 questions", exact=True)).to_be_visible()
    expect(page.get_by_text("Synthetic provider failure", exact=True)).to_be_visible()
    page.get_by_role("button", name="Retry" if action == "retry" else "Delete", exact=True).click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_be_visible()
    assert actions == []
    dialog.get_by_role("button", name="Cancel", exact=True).click()
    assert actions == []
    page.get_by_role("button", name="Retry" if action == "retry" else "Delete", exact=True).click()
    dialog.get_by_role("button", name="Retry generation" if action == "retry" else "Delete batch", exact=True).click()
    expect(dialog).not_to_be_visible()
    assert actions == [action]
    if action == "retry":
        expect(page.get_by_text("pending", exact=True)).to_be_visible()
        expect(page.get_by_text("Synthetic provider failure", exact=True)).to_have_count(0)
    else:
        expect(page.get_by_text("No batches yet. Generate some questions above.", exact=True)).to_be_visible()
