# Test Suites

This directory contains integration test suites that run against a live backend server.
Each file is a self-contained test suite covering a specific scenario area.

## Directory Layout

```
backend/tests/
├── __init__.py
├── conftest.py                     # Shared fixtures, helpers, and cleanup logic
├── test_assessment_lifecycle.py # Multi-user assessment attendance scenarios
└── <future_test_suite>.py            # New suites go here
```

## Writing a New Test Suite

### Naming Convention

- `test_<area>.py` — one file per functional area
- `Test<ScenarioName>` — one class per scenario
- `test_<behavior>` — one method per test case within a class

### Key Fixture: `ctx`

Every test file uses the `ctx` fixture (session-scoped) provided by `conftest.py`. It is built on top of `seeded_assessment`, which:

1. Creates test topics and MCQ questions in the DB
2. Creates 3 test users (`assessment_tester_1/2/3`, password `testpass123`)
3. Creates a batch `assessment_test_batch` and assigns all users to it
4. Creates an assessment called "Multi-User Assessment Lifecycle Test" assigned to that batch
5. Cleans up all test data on fixture teardown

### Helper: `AssessmentContext`

Available as `ctx`, it provides:

| Attribute / Method | Description |
|---|---|
| `ctx.assessment` | Full assessment creation response (includes `id`, `title`, etc.) |
| `ctx.assessment_id` | UUID string of the created assessment |
| `ctx.usernames` | List of test usernames |
| `ctx.admin_token` | JWT token for admin (use for admin API calls) |
| `ctx.login(username)` | Cached login per user; returns JWT token |
| `ctx.get_client(username)` | Returns a `requests.Session` for the user |
| `ctx.question_correct_options` | `{question_id: correct_option_id}` map for MCQ answers |
| `ctx.wait_for_evaluation(attempt_id, client, token)` | Polls until evaluator finishes (max 60 s) |

### Minimal Test Example

```python
import pytest
import requests

BASE_URL = "http://localhost:8000"
TEST_PASSWORD = "testpass123"


def _login(client, username, password):
    resp = client.post(f"{BASE_URL}/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200
    return resp.json()["access_token"]


class TestMyNewScenario:
    def test_something(self, ctx):
        client = ctx.get_client(ctx.usernames[0])
        token = ctx.login(ctx.usernames[0])

        # Start the assessment
        start = requests.post(
            f"{BASE_URL}/user/assessments/start/{ctx.assessment_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert start.status_code == 200
        start_data = start.json()
        attempt_id = start_data["attempt_id"]
        questions = start_data["questions"]

        # Answer all questions
        answers = []
        for q in questions:
            qid = str(q["id"])
            correct = ctx.question_correct_options[qid]
            answers.append({"question_id": qid, "answer": correct})

        # Submit
        resp = requests.post(
            f"{BASE_URL}/user/assessments/submit/{attempt_id}",
            json={"answers": answers},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

        # Wait for evaluation and check score
        result = ctx.wait_for_evaluation(attempt_id, client, ctx.admin_token)
        assert result is not None
        assert result["score"] == 100.0
```

## Running Tests

### Prerequisites

1. Backend server running and reachable at `BASE_URL` (default `http://localhost:8000`)
2. PostgreSQL accessible at `DATABASE_URL` (default `postgresql://postgres:password@localhost:5432/assessment_db`)
3. `psycopg2` or `psycopg2-binary` installed

### Commands

```powershell
# From the backend directory:
python -m pytest tests/ -v

# Run a specific test class:
python -m pytest tests/test_assessment_lifecycle.py::TestTwoUsersCompleteFullAssessment -v

# Run a specific test method:
python -m pytest tests/test_assessment_lifecycle.py::TestTwoUsersCompleteFullAssessment::test_both_users_start_submit_and_answers_recorded -v

# Run only tests matching a keyword:
python -m pytest tests/ -k "partial" -v
```

### Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `BASE_URL` | `http://localhost:8000` | Backend server URL |
| `DATABASE_URL` | `postgresql://postgres:password@localhost:5432/assessment_db` | Postgres connection |
| `TEST_ADMIN_USERNAME` | `admin` | Admin username for test setup |
| `TEST_ADMIN_PASSWORD` | `admin123` | Admin password for test setup |
| `TEST_ADMIN_NAME` | `System Admin` | Admin display name |

### Test Accounts (created by fixture)

| Username | Password | Role |
|---|---|---|
| `assessment_tester_1` | `testpass123` | user |
| `assessment_tester_2` | `testpass123` | user |
| `assessment_tester_3` | `testpass123` | user |

## Scenarios Covered (`test_assessment_lifecycle.py`)

| Test Class | What It Tests |
|---|---|
| `TestTwoUsersCompleteFullAssessment` | Two users answer all questions correctly and submit |
| `TestOneUserPartialSubmission` | One user submits everything; another submits only half |
| `TestUserAbortsDueToViolation` | User triggers tab violations → assessment aborted as `incomplete` |
| `TestAdminSeesRecordedAnswers` | Admin polls until evaluator finishes; checks all answers recorded |
| `TestUnassignedUserCannotStart` | Using a fake UUID returns 403/404 |
| `TestSaveAnswerDuringAttempt` | Auto-save upsert (save once, overwrite, re-submit) |
| `TestAssessmentInputValidation` | Rejects answers for questions outside the assessment |
| `TestPartialAttemptScoring` | Ensures unanswered questions count as zero in the final score |

## Authentication and user coverage

`test_authentication_and_users.py` verifies registration, duplicate-pending rejection,
admin approval, login, refresh-token rotation, current-user lookup, and account
deactivation. It creates uniquely named records and removes them in fixture teardown.

## Optional Playwright browser tests

`test_browser_smoke.py` validates the browser login journey, including visible
invalid-login feedback and successful admin routing. It is marked `e2e` and is
not included unless Playwright is installed.

```powershell
uv sync --extra e2e
uv run playwright install chromium
$env:FRONTEND_URL = "http://localhost:5173"
uv run pytest -m e2e -v
```

Start the frontend with `VITE_API_BASE` pointing to the backend before running
these tests. The suite skips cleanly when the optional dependency is absent.
