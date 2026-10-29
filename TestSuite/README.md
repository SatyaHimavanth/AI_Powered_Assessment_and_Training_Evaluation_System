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
- browser login validation, keyboard submission, network-failure feedback, and rapid double-click suppression
- browser practice-load outage/retry, large Unicode and markup-like answer persistence, refresh/resume, and interview recovery
- browser lifecycle: admin-provisioned assessment attended and submitted by two isolated candidate sessions, with integrity-event checks
- malformed and unsupported anti-cheat event API payloads, including attempt ownership boundaries

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

To run the multi-candidate browser lifecycle, enable both stateful fixtures and
browser tests. It provisions assessment content and three temporary users
through authenticated admin APIs, then two candidates log in and attend the
assessment through separate Chromium contexts. Candidate sessions run serially
and the test asserts that no focus/fullscreen integrity events were emitted.
The third candidate is available to extend the scenario without reusing an
account. Local/test teardown removes the generated attempts and evaluation
jobs. Run stateful tests only against a dedicated test environment.

```powershell
$env:RUN_STATEFUL_TESTS = "1"
$env:RUN_E2E_TESTS = "1"
uv run pytest tests/test_browser_workflows.py -k two_candidates_attend --browser chromium
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
isolated topic, four questions, batch, and individually assigned assessment through admin APIs. Users
exercise full, partial, and violation-aborted attempts and verify that learner
results agree with admin results. In local/test environments, teardown uses a
restricted TestSuite cleanup endpoint to remove the fixture, attempts,
evaluation jobs, users, and content. Other environments retain the existing
archive/deactivate behavior; run stateful tests only against a dedicated test
environment.

The backend must allow `FRONTEND_URL` through `CORS_ALLOWED_ORIGINS`. Local
development origins are enabled by default; cloud deployments must set the
deployed frontend origin explicitly.

## Coverage boundaries

Playwright browser tests use actual Chromium input, form validation, network
interception, refresh, and navigation. API-backed workflows use deterministic
responses where a live model or backend is unnecessary; the stateful and
authorization tests still require a dedicated running test environment. The
suite targets authentication, authorization, service health, payload bounds,
CORS, concurrent reads/writes, duplicate starts/submission, transient failures,
long/unicode candidate input, and recovery flows. It does not prove every
possible edge case. Further work includes human-labelled AI grading evaluation,
coding/SQL sandbox limits, imports/exports, sustained load, and additional
worker restart and registration-approval races.
