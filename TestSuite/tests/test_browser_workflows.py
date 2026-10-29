from urllib.parse import urlparse

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
    page.route(
        f"{api_url}/auth/login",
        lambda route: route.fulfill(status=401, json={"detail": "Invalid credentials"}),
    )
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
            body='{"access_token":"test","role":"user"}',
        )

    page.route("**/auth/login", login_route)
    _open_login(page, frontend_url)
    page.get_by_label("Username").fill("user")
    page.get_by_label("Password").fill("password")
    button = page.get_by_role("button", name="Sign in")
    button.evaluate("(element) => { element.click(); element.click(); }")
    page.wait_for_timeout(100)
    assert requests_seen == 1


def test_login_network_failure_has_actionable_feedback(
    require_e2e, page, frontend_url, api_url
):
    page.route(
        f"{api_url}/auth/login",
        lambda route: route.fulfill(
            status=503,
            content_type="application/json",
            body='{"detail":"Authentication service is temporarily unavailable"}',
        ),
    )
    _open_login(page, frontend_url)
    page.get_by_label("Username").fill("candidate")
    page.get_by_label("Password").fill("correct-horse-battery")
    page.get_by_role("button", name="Sign in").click()
    expect(page.get_by_text("Login failed")).to_be_visible()
    expect(page.get_by_label("Username")).to_be_editable()


def test_login_empty_required_fields_do_not_send_request(
    require_e2e, page, frontend_url, api_url
):
    requests_seen = 0

    def count_login(route):
        nonlocal requests_seen
        requests_seen += 1
        route.fulfill(status=401, json={"detail": "Invalid credentials"})

    page.route(f"{api_url}/auth/login", count_login)
    _open_login(page, frontend_url)
    page.get_by_role("button", name="Sign in").click()
    expect(page.get_by_label("Username")).to_be_focused()
    assert requests_seen == 0


def test_login_form_submits_from_keyboard(
    require_e2e, page, frontend_url, api_url
):
    requests_seen = 0

    def reject_login(route):
        nonlocal requests_seen
        requests_seen += 1
        route.fulfill(status=401, json={"detail": "Invalid credentials"})

    page.route(f"{api_url}/auth/login", reject_login)
    _open_login(page, frontend_url)
    page.get_by_label("Username").fill("keyboard-user")
    password = page.get_by_label("Password")
    password.fill("incorrect-password")
    password.press("Enter")
    expect(page.get_by_text("Login failed")).to_be_visible()
    assert requests_seen == 1


def test_practice_load_failure_can_be_retried_in_browser(
    require_e2e, page, frontend_url, api_url
):
    access_requests = 0

    def mock_api(route):
        nonlocal access_requests
        path = urlparse(route.request.url).path
        if path == "/auth/login":
            route.fulfill(json={"role": "user"})
        elif path == "/auth/me":
            route.fulfill(json={"username": "browser-user", "name": "Browser User", "role": "user"})
        elif path == "/user/assessments/":
            route.fulfill(json=[])
        elif path == "/practice/access":
            access_requests += 1
            if access_requests == 1:
                route.fulfill(status=503, json={"detail": "Temporary practice service failure"})
            else:
                route.fulfill(json={"has_access": False, "expires_at": None, "pending_request": False})
        else:
            route.fulfill(json=[])

    page.route(f"{api_url}/**", mock_api)
    _open_login(page, frontend_url)
    page.get_by_label("Username").fill("browser-user")
    page.get_by_label("Password").fill("password")
    page.get_by_role("button", name="Sign in").click()
    expect(page).to_have_url(f"{frontend_url}/user")
    page.get_by_role("button", name="Practice Test").click()

    expect(page.get_by_role("alert")).to_contain_text("Temporary practice service failure")
    expect(page.get_by_role("button", name="Retry")).to_be_visible()
    expect(page.get_by_text("Practice Test Access Required")).to_have_count(0)
    page.get_by_role("button", name="Retry").click()
    expect(page.get_by_text("Practice Test Access Required")).to_be_visible()
    assert access_requests == 2


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
    assert page.evaluate("localStorage.getItem('access_token')") is None

    page.reload(wait_until="networkidle")
    expect(page).to_have_url(f"{frontend_url}/admin")
    expect(page.get_by_text("Admin Panel")).to_be_visible()


def test_admin_assignment_mode_defaults_to_batches_and_can_switch_to_users(
    require_e2e, page, frontend_url, api_url
):
    """The assignment selector exposes one active recipient type at a time."""
    page.route(
        "http://localhost:8000/**",
        lambda route: route.continue_(
            url=route.request.url.replace("http://localhost:8000", api_url)
        ),
    )
    import os

    _open_login(page, frontend_url)
    page.get_by_label("Username").fill(os.getenv("TEST_ADMIN_USERNAME", "admin"))
    page.get_by_label("Password").fill(os.getenv("TEST_ADMIN_PASSWORD", "admin123"))
    page.get_by_role("button", name="Sign in").click()
    expect(page).to_have_url(f"{frontend_url}/admin")
    page.get_by_role("button", name="Assessments").click()

    batch_tab = page.get_by_role("tab", name="Batches")
    user_tab = page.get_by_role("tab", name="Users")
    expect(batch_tab).to_have_attribute("aria-selected", "true")
    expect(page.get_by_text("Assign to Batches")).to_be_visible()
    expect(page.get_by_text("Assign to Individual Users")).to_have_count(0)

    page.get_by_role("button", name="Add Section").click()
    expect(page.get_by_role("button", name="Delete section Section-1")).to_be_visible()

    user_tab.click()
    expect(user_tab).to_have_attribute("aria-selected", "true")
    expect(page.get_by_text("Assign to Individual Users")).to_be_visible()
    expect(page.get_by_text("Assign to Batches")).to_have_count(0)


def test_two_candidates_attend_admin_provisioned_assessment_without_integrity_alerts(
    require_e2e, browser, frontend_url, api_url, provisioned_assessment
):
    """Exercise the same real assessment in isolated candidate browser sessions.

    The assessment, batch, questions, and users are provisioned with admin
    credentials by the fixture. Candidate sessions use separate contexts and
    run serially, so automation never backgrounds a page while its exam is live.
    """
    assessment_id = provisioned_assessment["assessment_id"]
    assessment_title = provisioned_assessment["assessment_title"]
    candidate_users = provisioned_assessment["users"][:2]

    for candidate in candidate_users:
        context = browser.new_context()
        candidate_page = context.new_page()
        integrity_events = []
        candidate_page.on(
            "request",
            lambda request: integrity_events.append(request.url)
            if "/save-violations" in request.url
            else None,
        )
        try:
            _open_login(candidate_page, frontend_url)
            candidate_page.get_by_label("Username").fill(candidate["username"])
            candidate_page.get_by_label("Password").fill(candidate["password"])
            candidate_page.get_by_role("button", name="Sign in").click()
            expect(candidate_page).to_have_url(f"{frontend_url}/user")

            expect(candidate_page.get_by_text(assessment_title)).to_be_visible()
            candidate_page.get_by_role("button", name="Start Exam").click()
            candidate_page.get_by_role("button", name="Start Assessment").click()
            expect(
                candidate_page.get_by_text("TestSuite concurrency question", exact=False)
            ).to_be_visible()

            for question_index in range(4):
                candidate_page.get_by_role("radio").first.check()
                if question_index < 3:
                    candidate_page.get_by_role("button", name="Next").click()

            candidate_page.get_by_role("button", name="Submit Assessment").click()
            candidate_page.get_by_role("button", name="Yes, Submit").click()
            expect(candidate_page.get_by_role("heading", name="Assessment Submitted")).to_be_visible(timeout=30_000)
            assert not integrity_events, (
                f"Automation emitted integrity events for {candidate['username']}: "
                f"{integrity_events}"
            )
        finally:
            context.close()


def test_practice_answers_restore_after_browser_reload(
    require_e2e, page, frontend_url, api_url
):
    test_id = "browser-practice-test"
    question_id = "browser-practice-question"
    saved_answer = {"value": "saved before reload"}
    edge_case_answer = ("Unicode: λ 漢字 😊; markup-like input: <script>alert(1)</script>; " * 256)

    def mock_practice(route):
        request = route.request
        path = urlparse(request.url).path
        if path == "/auth/login" and request.method == "POST":
            route.fulfill(json={"role": "user"})
        elif path == "/auth/me":
            route.fulfill(json={"username": "browser-user", "name": "Browser User", "role": "user"})
        elif path == "/user/assessments/":
            route.fulfill(json=[])
        elif path == "/interviews/dashboard-counts":
            route.fulfill(json={"interviews_to_attend": 0, "interviews_in_progress": 0})
        elif path == "/practice/access":
            route.fulfill(json={"has_access": True, "expires_at": None, "pending_request": False})
        elif path == "/practice/today":
            route.fulfill(json={
                "id": test_id,
                "job_title": "Browser persistence test",
                "topics": "Reliability",
                "difficulty": "easy",
                "question_count": 1,
                "status": "in_progress",
                "score": None,
                "created_at": "2026-10-28T00:00:00Z",
                "submitted_at": None,
            })
        elif path == "/practice/history":
            route.fulfill(json=[])
        elif path == f"/practice/{test_id}/start":
            route.fulfill(json={"message": "Practice test started"})
        elif path == f"/practice/{test_id}" and request.method == "GET":
            route.fulfill(json={
                "id": test_id,
                "job_title": "Browser persistence test",
                "topics": "Reliability",
                "difficulty": "easy",
                "question_count": 1,
                "status": "in_progress",
                "score": None,
                "created_at": "2026-10-28T00:00:00Z",
                "questions": [{
                    "id": question_id,
                    "position": 1,
                    "type": "text",
                    "question": "Describe a safe recovery strategy.",
                    "options": None,
                    "topic": "Reliability",
                }],
                "saved_answers": {question_id: saved_answer["value"]},
            })
        elif path == f"/practice/{test_id}/answer" and request.method == "PUT":
            saved_answer["value"] = request.post_data_json["answer"]
            route.fulfill(json={"message": "Answer saved"})
        else:
            route.continue_()

    page.route(f"{api_url}/**", mock_practice)
    _open_login(page, frontend_url)
    page.get_by_label("Username").fill("user")
    page.get_by_label("Password").fill("AuditUser123!")
    page.get_by_role("button", name="Sign in").click()
    expect(page).to_have_url(f"{frontend_url}/user")
    page.get_by_role("button", name="Practice Test").click()
    page.get_by_role("button", name="Resume Test").click()

    answer_box = page.get_by_placeholder("Type your answer here...")
    expect(answer_box).to_have_value("saved before reload")
    with page.expect_response(
        lambda response: response.request.method == "PUT"
        and response.url.endswith(f"/practice/{test_id}/answer")
    ):
        answer_box.fill(edge_case_answer)
    assert saved_answer["value"] == edge_case_answer

    page.reload(wait_until="networkidle")
    expect(page).to_have_url(f"{frontend_url}/user")
    page.get_by_role("button", name="Practice Test").click()
    page.get_by_role("button", name="Resume Test").click()
    expect(page.get_by_placeholder("Type your answer here...")).to_have_value(edge_case_answer)


def _mock_user_with_paused_interview(page: Page, frontend_url: str):
    template_id = "browser-interview-template"
    session_id = "browser-paused-interview"
    resume_calls = []
    template = {
        "id": template_id,
        "title": "Browser interview recovery",
        "role": "Engineer",
        "experience_level": "mid",
        "difficulty": "medium",
        "duration_minutes": 20,
        "question_count": 3,
        "focus_areas": ["reliability"],
        "default_questions_or_topics": ["Recovery"],
        "max_pauses_allowed": 2,
        "is_archived": False,
    }
    session = {
        "id": session_id,
        "template_id": template_id,
        "template_title": template["title"],
        "status": "paused",
        "attempt_number": 1,
        "pause_count": 1,
        "max_pauses_allowed": 2,
        "started_at": "2026-10-28T12:00:00Z",
        "completed_at": None,
        "total_score": None,
    }
    result = {
        "id": session_id,
        "template_id": template_id,
        "status": "paused",
        "started_at": "2026-10-28T12:00:00Z",
        "remaining_seconds": 120,
        "pause_count": 1,
        "transcript": [{
            "role": "assistant",
            "content": "Describe your recovery plan.",
            "timestamp": "2026-10-28T12:01:00Z",
        }],
    }

    def mock_api(route):
        request = route.request
        path = urlparse(request.url).path
        if path == "/auth/login" and request.method == "POST":
            route.fulfill(json={"role": "user"})
        elif path == "/auth/me":
            route.fulfill(json={"username": "browser-user", "name": "Browser User", "role": "user"})
        elif path == "/user/assessments/":
            route.fulfill(json=[])
        elif path == "/interviews/dashboard-counts":
            route.fulfill(json={"interviews_to_attend": 0, "interviews_in_progress": 1})
        elif path == "/interviews/templates":
            route.fulfill(json=[template])
        elif path == "/interviews/my-requests":
            route.fulfill(json=[])
        elif path == "/interviews/my-sessions":
            route.fulfill(json=[session])
        elif path == f"/interviews/{session_id}/results":
            route.fulfill(json=result)
        elif path == f"/interviews/{session_id}/resume" and request.method == "POST":
            resume_calls.append(True)
            route.fulfill(json={"message": "Interview resumed"})
        else:
            route.fulfill(json=[])

    page.route("**/api/**", mock_api)
    page.route("**/auth/**", mock_api)
    page.route("**/interviews/**", mock_api)
    _open_login(page, frontend_url)
    page.get_by_label("Username").fill("browser-user")
    page.get_by_label("Password").fill("password")
    page.get_by_role("button", name="Sign in").click()
    expect(page).to_have_url(f"{frontend_url}/user")
    page.get_by_role("button", name="Interviews").click()
    expect(page.get_by_role("heading", name="My Interview Sessions")).to_be_visible()
    return session_id, resume_calls


def test_paused_interview_resumes_with_server_time_and_pause_count(
    require_e2e, page, frontend_url
):
    session_id, resume_calls = _mock_user_with_paused_interview(page, frontend_url)

    page.get_by_role("button", name="Resume").click()
    expect(page.get_by_text("Describe your recovery plan.")).to_be_visible()
    expect(page.get_by_text("2:00")).to_be_visible()
    expect(page.get_by_text("1/2")).to_be_visible()
    assert resume_calls == [True]


def test_interview_resume_load_failure_has_visible_recovery(
    require_e2e, page, frontend_url
):
    session_id, _ = _mock_user_with_paused_interview(page, frontend_url)
    page.route(
        f"**/interviews/{session_id}/results",
        lambda route: route.fulfill(status=503, json={"detail": "temporarily unavailable"}),
    )

    page.get_by_role("button", name="Resume").click()
    expect(page.get_by_role("alert")).to_have_text("Failed to resume interview")
    expect(page.get_by_role("button", name="Return to interviews")).to_be_visible()
