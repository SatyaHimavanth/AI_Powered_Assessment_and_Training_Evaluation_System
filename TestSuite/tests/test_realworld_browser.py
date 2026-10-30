"""Browser recovery scenarios with deterministic API failures and persisted data."""

from datetime import datetime, timezone
from urllib.parse import urlparse

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


def sign_in(page, frontend_url):
    page.goto(f"{frontend_url}/login")
    page.get_by_label("Username").fill("scenario-user")
    page.get_by_label("Password").fill("scenario-password")
    page.get_by_role("button", name="Sign in").click()
    expect(page).to_have_url(f"{frontend_url}/user")


def base_response(path):
    if path == "/auth/login":
        return {"role": "user"}
    if path == "/auth/me":
        return {"username": "scenario-user", "name": "Scenario User", "role": "user"}
    return []


@pytest.mark.parametrize("old_status", ["ready", "in_progress", "failed"])
def test_older_practice_remains_accessible_after_midnight_or_a_new_test(
    require_e2e, page, frontend_url, api_url, old_status
):
    seen = []
    older = {
        "id": "older", "job_title": "Yesterday's practice", "difficulty": "easy", "topics": "SQL",
        "question_count": 1, "status": old_status, "score": None, "created_at": "2020-01-01T10:00:00Z",
        "submitted_at": None,
    }
    newer = {
        **older, "id": "newer", "job_title": "Today's practice", "status": "completed", "score": 100,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    def api(route):
        path = urlparse(route.request.url).path
        seen.append((route.request.method, path))
        if path == "/practice/access":
            data = {"has_access": True, "expires_at": None, "pending_request": False, "tests_per_day_granted": 3}
        elif path == "/practice/today":
            data = newer
        elif path == "/practice/history":
            data = [newer, older]
        elif path == "/practice/older":
            data = {
                **older,
                "questions": [{"id": "answer", "position": 0, "type": "text", "question": "Explain a join", "options": None}],
                "saved_answers": {"answer": "My persisted answer"},
            }
        elif path == "/practice/older/start":
            data = {"message": "Started"}
        elif path == "/practice/older/retry-generation":
            older["status"] = "generating"
            data = {"message": "Restarted"}
        elif path == "/practice/older/submit":
            route.fulfill(status=503, json={"detail": "Temporary evaluator outage. Retry submission."})
            return
        else:
            data = base_response(path)
        route.fulfill(json=data)

    page.route(f"{api_url}/**", api)
    sign_in(page, frontend_url)
    page.get_by_role("button", name="Practice Test", exact=True).click()
    row = page.get_by_role("row").filter(has_text="Yesterday's practice")
    if old_status == "failed":
        row.get_by_role("button", name="Retry generation").click()
        expect(row).to_contain_text("Generating...")
        assert ("POST", "/practice/older/retry-generation") in seen
    else:
        row.get_by_role("button", name="Resume Test" if old_status == "in_progress" else "Start Test").click()
        expect(page.get_by_role("textbox")).to_have_value("My persisted answer")
        page.get_by_role("button", name="Submit Test", exact=True).click()
        expect(page.get_by_role("status")).to_contain_text("Temporary evaluator outage")
        expect(page.get_by_role("textbox")).to_have_value("My persisted answer")
        assert seen.count(("POST", "/practice/older/start")) == 1


def test_interview_countdown_reaches_results_instead_of_an_expiry_error(
    require_e2e, page, frontend_url, api_url
):
    closed = False
    template = {
        "id": "template", "title": "Timed interview", "role": "Developer", "experience_level": "mid",
        "difficulty": "easy", "duration_minutes": 1, "question_count": 1, "focus_areas": [],
        "default_questions_or_topics": [], "max_pauses_allowed": 3, "is_archived": False,
    }
    session = {
        "id": "session", "template_id": "template", "template_title": "Timed interview",
        "status": "in_progress", "attempt_number": 2, "pause_count": 0, "max_pauses_allowed": 3,
        "started_at": datetime.now(timezone.utc).isoformat(), "completed_at": None, "total_score": None,
        "remaining_seconds": 1,
    }

    def api(route):
        nonlocal closed
        path = urlparse(route.request.url).path
        if path == "/interviews/templates":
            data = [template]
        elif path == "/interviews/my-requests":
            data = [{"id": "retry", "template_id": "template", "status": "approved", "request_type": "retry", "used": False}]
        elif path == "/interviews/my-sessions":
            data = [{**session, "id": "previous", "status": "missed", "total_score": None}]
        elif path == "/interviews/start":
            data = session
        elif path == "/interviews/session/end":
            closed = True
            data = {"message": "Interview completed"}
        elif path == "/interviews/session/results":
            data = {
                **session, "status": "completed" if closed else "in_progress",
                "transcript": [], "evaluations": [], "topic_scores": [], "feedback": {},
            }
        else:
            data = base_response(path)
        route.fulfill(json=data)

    page.route(f"{api_url}/**", api)
    sign_in(page, frontend_url)
    page.get_by_role("button", name="Interviews", exact=True).click()
    page.get_by_role("button", name="Start Interview", exact=True).click()
    page.get_by_role("button", name="Start Interview", exact=True).click()
    expect(page.get_by_role("heading", name="Interview Completed")).to_be_visible(timeout=10_000)
    assert closed


def test_ai_outage_preserves_answer_across_reload_and_resumes_without_timer_loss(
    require_e2e, page, frontend_url, api_url
):
    template = {
        "id": "outage-template", "title": "Outage recovery interview", "role": "Engineer",
        "experience_level": "junior", "difficulty": "easy", "duration_minutes": 1,
        "question_count": 2, "focus_areas": [], "default_questions_or_topics": [],
        "max_pauses_allowed": 3, "is_archived": False,
    }
    session = {
        "id": "outage-session", "template_id": template["id"], "template_title": template["title"],
        "status": "in_progress", "attempt_number": 1, "pause_count": 0, "max_pauses_allowed": 3,
        "started_at": datetime.now(timezone.utc).isoformat(), "completed_at": None, "total_score": None,
        "remaining_seconds": 50, "feedback": {},
        "transcript": [{"role": "assistant", "content": "Explain transactions", "timestamp": "2026-01-01T00:00:00Z"}],
    }
    messages = []
    ended = []
    drafts = []

    def api(route):
        path = urlparse(route.request.url).path
        if path == "/interviews/templates":
            data = [template]
        elif path == "/interviews/my-requests":
            data = []
        elif path == "/interviews/my-sessions":
            data = [session]
        elif path == "/interviews/outage-session/results":
            data = session
        elif path == "/interviews/outage-session/draft":
            session["feedback"]["draft_answer"] = route.request.post_data_json["response_text"]
            drafts.append(session["feedback"]["draft_answer"])
            data = {"message": "Draft saved"}
        elif path == "/interviews/outage-session/message":
            text = route.request.post_data_json["response_text"]
            messages.append(text)
            if len(messages) == 1:
                session["transcript"].append({"role": "user", "content": text, "timestamp": "2026-01-01T00:00:01Z"})
                session["status"] = "paused"
                session["feedback"] = {"pending_evaluation": True}
                route.fulfill(status=503, json={"detail": "AI unavailable. Your answers are saved in the database. Please try again after some time."})
                return
            session["status"] = "in_progress"
            session["feedback"] = {"turns": [{"score": 8}]}
            session["transcript"].append({"role": "assistant", "content": "How does rollback work?", "timestamp": "2026-01-01T00:00:02Z"})
            data = {"score": 8}
        elif path == "/interviews/outage-session/end":
            ended.append(True)
            data = {"message": "Closed"}
        else:
            data = base_response(path)
        route.fulfill(json=data)

    page.route(f"{api_url}/**", api)
    sign_in(page, frontend_url)
    page.get_by_role("button", name="Interviews", exact=True).click()
    page.get_by_role("button", name="Resume", exact=True).click()
    answer = "All changes commit together or roll back together."
    page.get_by_role("textbox").fill(answer)
    expect(page.get_by_text("Draft saved in the database.", exact=True)).to_be_visible()
    assert drafts[-1] == answer
    page.get_by_role("button", name="Submit Response", exact=True).click()
    expect(page.get_by_role("alert")).to_contain_text("try again after some time")
    expect(page.get_by_role("textbox")).to_be_disabled()
    page.reload()
    page.get_by_role("button", name="Interviews", exact=True).click()
    page.get_by_role("button", name="Resume", exact=True).click()
    expect(page.get_by_role("textbox")).to_have_value(answer)
    expect(page.get_by_role("button", name="Retry AI and continue")).to_be_visible()
    page.clock.install()
    page.clock.run_for(90_000)
    expect(page.get_by_text("0:50", exact=True)).to_be_visible()
    assert not ended
    page.get_by_role("button", name="Retry AI and continue").click()
    expect(page.get_by_text("How does rollback work?", exact=True)).to_be_visible()
    expect(page.get_by_role("textbox")).to_be_editable()
    assert messages == [answer, answer]
    assert sum(turn["role"] == "user" for turn in session["transcript"]) == 1
