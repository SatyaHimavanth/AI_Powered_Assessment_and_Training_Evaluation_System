# Backend - AI Powered Assessment & Training Evaluation System

## Project Structure

```
backend/
├── main.py                      # FastAPI application entry point
├── api/
│   ├── routers_admin.py         # Admin-only endpoints (users, assessments, evaluations)
│   ├── routers_assessments.py   # Assessment CRUD & results export
│   ├── routers_auth.py          # Login / registration
│   ├── routers_user_assessments.py  # User-facing: start/save/submit/abort
│   └── ...
├── core/
│   ├── auth.py                  # JWT, password hashing, role guards
│   └── evaluation_service.py    # Background evaluator for MCQ & LLM scoring
├── db/
│   ├── database.py              # Async Postgres engine + sync session
│   ├── models.py                # SQLAlchemy ORM models
│   └── async_helpers.py         # run_db_sync helper
└── tests/
    ├── conftest.py              # Shared fixtures, seed data, cleanup
    ├── test_assessment_lifecycle.py  # Multi-user assessment scenario tests
    └── ...                       # Future test suites go here
```

## Test Suites

The `tests/` directory contains integration test suites that run against a live backend server.

### `test_assessment_lifecycle.py`

Simulates multiple users attending the same assessment simultaneously. Covers:

| Scenario | What it tests |
|---|---|
| `TestTwoUsersCompleteFullAssessment` | Two users each answer all MCQ questions correctly and submit |
| `TestOneUserPartialSubmission` | One user submits all answers; another submits only half |
| `TestUserAbortsDueToViolation` | User triggers tab violations → assessment aborted as `incomplete` |
| `TestAdminSeesRecordedAnswers` | Admin verifies that all answers are stored correctly after completion |
| `TestUnassignedUserCannotStart` | A user not assigned to the assessment gets 403/404 |
| `TestSaveAnswerDuringAttempt` | Auto-save upsert (save, overwrite, re-submit) works |

### Adding new test suites

Create a new file `tests/test_<name>.py`. All tests use the session-scoped
`seeded_assessment` fixture from `conftest.py`, which:

1. Sets up topics, questions, users and a batch in the DB
2. Creates an assessment and assigns it to the batch
3. Tears down all created data after the session

Example skeleton:

```python
def test_my_scenario(ctx):
    username = ctx.usernames[0]
    token = ctx.login(username)
    client = ctx.get_client(username)
    ...
```

## Prerequisites

- Python 3.12+
- PostgreSQL running at the URL in `DATABASE_URL` (default `postgresql://postgres:password@localhost:5432/assessment_db`)
- Backend server running and reachable at `BASE_URL` (default `http://localhost:8000`)

## Setup

```powershell
cd backend

# Create virtual environment (first time only)
python -m venv .venv
.venv\Scripts\Activate.ps1

# Install dependencies
pip install -e .

# Or if psycopg2 fails to build, install the binary variant instead:
pip install psycopg2-binary

# Start the backend server
python main.py
```

## Running Tests

```powershell
# From the backend directory, ensure the server is running first.
# Then run pytest directly (do NOT use .venv activation for collection):

# Using system python (which has pytest installed):
python -m pytest tests/ -v

# Or using the venv python explicitly:
.venv\Scripts\python.exe -m pytest tests/ -v

# Run a specific test class:
python -m pytest tests/test_assessment_lifecycle.py::TestTwoUsersCompleteFullAssessment -v

# Override defaults via environment variables:
$env:BASE_URL = "http://localhost:8000"
$env:DATABASE_URL = "postgresql://postgres:password@localhost:5432/assessment_db"
$env:TEST_ADMIN_USERNAME = "admin"
$env:TEST_ADMIN_PASSWORD = "admin123"
python -m pytest tests/ -v
```

### Test Users

The seeded assessment fixture creates the following test accounts (password: `testpass123`):

| Username | Name |
|---|---|
| `assessment_tester_1` | Alice Tester |
| `assessment_tester_2` | Bob Tester |
| `assessment_tester_3` | Carol Tester |

The admin user used for login is controlled by `TEST_ADMIN_USERNAME` / `TEST_ADMIN_PASSWORD`
(defaults: `admin` / `admin123`).

### Important Notes

1. **psycopg2 must be installed** — the `db.database` module imports it at startup. If `pip install psycopg2` fails, install `psycopg2-binary` instead (listed in `pyproject.toml`).

2. **The backend server must be running** — these are integration tests that make real HTTP calls to the backend.

3. **Test data is cleaned up automatically** — the `seeded_assessment` fixture deletes all created records (assessment, batch, users, topics) in `finally` blocks after each session completes.

4. **MCQ evaluation is asynchronous** — after submission, the `EvaluationJob` consumer thread scores MCQ answers in the background. Tests that check scores poll until evaluation finishes (up to 60 seconds). If the LLM evaluator is not configured, only auto-scored MCQ answers will receive a score.