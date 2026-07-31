# Assessment Application TestSuite

This is a standalone Python 3.12 `uv` project. It exercises the deployed
frontend and backend as separate services, so the same tests work with Docker,
App Engine, or another cloud platform.

## Coverage

- health/readiness, payload limits, CORS, and unauthenticated access
- admin/user login, refresh, identity, role isolation, and concurrent requests
- multi-user full/partial/aborted assessment attendance, duplicate starts,
  concurrent answer saves, duplicate final submission, and scoring (`stateful`)
- learner-visible results matched against admin results, including answer
  counts, per-question text, topic percentages, and per-user isolation
- practice and interview read workflows
- browser login feedback, navigation, and rapid double-click suppression

Safe API tests run by default. Tests that start/finalize an assessment require
`RUN_STATEFUL_TESTS=1`; use a dedicated database. Browser tests require
`RUN_E2E_TESTS=1`.

`TestSuite/.env.example` lists every supported setting. Environment files are
templates only; export the values in the shell or use the PowerShell commands
below before running tests.

```powershell
Set-Location TestSuite
uv sync

$env:API_BASE_URL = "http://localhost:8000"
$env:FRONTEND_URL = "http://localhost:5173"
$env:TEST_ADMIN_USERNAME = "admin"
$env:TEST_ADMIN_PASSWORD = "admin123"
$env:TEST_USER_USERNAME = "user"
$env:TEST_USER_PASSWORD = "user123"

uv run pytest -m api

$env:RUN_STATEFUL_TESTS = "1"
uv run pytest -m stateful

uv run playwright install chromium
$env:RUN_E2E_TESTS = "1"
uv run pytest -m e2e --browser chromium
```

For CORS validation, set `CORS_TEST_ORIGIN` to the deployed frontend origin.
The stateful workflow skips when the test user has no currently startable
assessment.

## Run everything

After setting the URLs and test-account environment variables shown above, run:

```powershell
uv run python run_all.py
```

This installs Chromium if needed, enables API, CORS, stateful, and browser
tests, then runs the complete suite. Extra pytest arguments are forwarded, for
example:

```powershell
uv run python run_all.py -x -vv
```

The stateful concurrency scenario creates three temporary users plus an
isolated topic, four questions, batch, and assessment through public admin
APIs. Users concurrently exercise full, partial, and violation-aborted
attempts and verify that learner results agree with admin results. Teardown
deactivates the users and archives the content. Run it only against a
dedicated test environment because audit records remain.

The backend must allow `FRONTEND_URL` through `CORS_ALLOWED_ORIGINS`. Local
development origins are enabled by default; cloud deployments must set the
deployed frontend origin explicitly.

## Coverage boundaries

The suite targets the highest-risk known paths: authentication, authorization,
service health, payload bounds, CORS, concurrent reads, duplicate starts,
concurrent autosaves, duplicate submission, and browser login behavior. It
does not prove every possible edge case. Areas that still require dedicated
fixtures or external-service test doubles include LLM failures, coding/SQL
sandbox limits, imports/exports, evaluation-worker crash recovery, practice
generation, interviews, registration approval races, and large-scale load.
