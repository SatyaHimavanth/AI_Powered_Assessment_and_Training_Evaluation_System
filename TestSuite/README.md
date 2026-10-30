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
- repeated question pools across separate assessment sections, with unique question selection
- isolated regression scenarios for versioned question edits, partial/negative grading,
  import answer keys and validation, registration cooldowns, interview retries and
  delayed evaluation, offline deadline sync, and practice-provider outages
- Chromium scenarios for previous-day practice start/resume/generation retry,
  visible submission failures without draft loss, and normal interview countdown completion

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

## Deterministic real-world regressions

From the repository root, use the backend environment for scenarios that exercise
actual route functions, ORM constraints, transactions, and grading with a fresh
in-memory SQLite database per test:

```powershell
uv sync --project backend --extra local
.\backend\.venv\Scripts\python.exe -m pytest -q -c TestSuite\pyproject.toml TestSuite\tests\test_realworld_regressions.py
```

These scenarios do not start background workers or call external models. By
default they do not connect to the configured application database. They cover:

| Situation | Required outcome |
| --- | --- |
| An administrator edits a question while a candidate is answering it | Original option IDs and grading survive; future assessments use the edited version |
| Two sections draw from the same topic/type/difficulty | One aggregated configuration, distinct questions, stable section positions |
| Imports contain unknown/blank topics, option gaps, spaces or full-text answer keys | Valid rows create usable per-assessment questions without global-topic pollution |
| Imports contain invalid keys/types/difficulty or coding without tests | Actionable row errors; invalid rows cannot silently become graded questions |
| A candidate submits only part of an assessment | Missing answers count as zero consistently across all topic reports |
| A rejected applicant reapplies before/after cooldown | Early requests fail explicitly; eligible reapplications reuse the original request safely |
| An admin approves a retry after a completed/missed/abandoned interview | Approval starts exactly one new attempt; consumed approvals cannot be reused |
| An interview ends at its deadline or the end request is retried | Completion is successful and idempotent |
| Evaluation finishes after an accepted interview answer and session end | The accepted answer keeps its evaluation |
| Interview AI fails to initialize or returns malformed evaluation | Start failures keep approval unused; accepted answers pause durably and show a retry-later message |
| A process/browser restarts while AI evaluation is pending | Reopen the database-backed transcript and retry the same answer, without duplicate turns or consuming downtime |
| A candidate types or dictates an interview draft | Save to database; restore server draft without relying on browser answer storage |
| An assessment reconnects after deadline within its offline-sync grace | One draft is applied; subsequent retries cannot overwrite finalized answers |
| Practice evaluation fails after submission | Answers remain persisted; a later submission can complete successfully |
| The third bank-generated single-choice question has zero or multiple correct options | Regenerate with validation feedback; only a valid complete batch reaches staging |
| Repeated bank-generation responses remain invalid | Stop after three attempts for the affected chunk, retain a failed status, and never call downstream embedding/staging |
| Interview start or registration resubmission arrives twice concurrently | Only one attempt/request is accepted |
| A successful interview resume is retried | Pause counters and accumulated duration remain unchanged |
| Several administrators publish assessments from overlapping section pools | Each assessment retains distinct questions and creation completes without database errors |

`tests/test_generation_batch_management.py` covers generation metadata in all
states, create/list response consistency, failed-only retry/delete, ownership,
partial-staging and temporary-embedding cleanup, bank-question preservation,
retry through the worker, and simultaneous retry/delete requests. It uses
synthetic embedding values solely for lifecycle checks, not similarity quality.
Run with the backend Python environment; concurrency cases require
`REALWORLD_TEST_DATABASE_URL`. Retry is deliberately blocked if the batch has
approved output; deletion still retains saved bank content.

When run in the standalone TestSuite environment, local regression scenarios
skip if backend dependencies are absent. PostgreSQL-only concurrency scenarios
skip in SQLite mode. The stateful API fixture also uses two sections sharing the
same question pool.

### PostgreSQL validation

`tests/test_cloudsql_console_migration.py` additionally rehearses the standalone
Cloud SQL console migration from the exact `a02c14f` model source in Git. It
checks historical data preservation, reruns, target columns and migration
history, and atomic rollback when old data contains invalid ownership, null
relationships, or duplicate topic configurations. Run it with the backend
Python environment and `REALWORLD_TEST_DATABASE_URL` set as below; Git must
contain commit `a02c14f`. See [console migration instructions](../DOCKER.md#cloud-sql-console-only-upgrade-from-a02c14f).

Create a separate, disposable PostgreSQL database. Never point stateful tests at
your normal application database. From the repository root:

```powershell
$env:REALWORLD_TEST_DATABASE_URL = "postgresql://TEST_USER:TEST_PASSWORD@localhost:5432/assessment_validation"
$env:DATABASE_URL = $env:REALWORLD_TEST_DATABASE_URL
$env:DATABASE_URL_ASYNC = "postgresql+asyncpg://TEST_USER:TEST_PASSWORD@localhost:5432/assessment_validation"
# Use json when the local PostgreSQL server does not have pgvector installed.
$env:EMBEDDING_STORAGE_BACKEND = "json"
$env:JWT_SECRET_KEY = "local-validation-only-key-replace-before-deployment"

.\backend\.venv\Scripts\python.exe -m pytest -q -c TestSuite\pyproject.toml TestSuite\tests\test_realworld_regressions.py
```

In this mode every regression test creates a uniquely named PostgreSQL schema,
uses independent connections with that schema as its search path, and drops only
its own schema during teardown. The regression fixture creates ORM tables;
validate the actual database migrations and worker recovery separately:

```powershell
Push-Location backend
.\.venv\Scripts\python.exe -m db.migrate
$env:AUDIT_TEST_DATABASE_URL = $env:DATABASE_URL
.\.venv\Scripts\python.exe -m pytest -q tests\test_schema_constraints.py
Pop-Location
```

Stop other workers connected to this disposable database before running the
worker-recovery tests: they deliberately requeue interrupted jobs. Run the live
HTTP/stateful and browser workflows described above after starting the API and
worker against that same disposable database. Ensure the frontend's
`VITE_API_BASE` matches `API_BASE_URL` when using non-default ports. Authenticated
test accounts use separate cookie sessions so fixture logins cannot corrupt
refresh tests or turn anonymous checks into authenticated requests.

Run the new browser scenarios against a running frontend from the repository root:

```powershell
uv sync --project TestSuite
uv run --project TestSuite playwright install chromium
$env:RUN_E2E_TESTS = "1"
$env:FRONTEND_URL = "http://localhost:5173"
$env:API_BASE_URL = "http://localhost:8000"
uv run --project TestSuite pytest TestSuite\tests\test_realworld_browser.py --browser chromium
```

Their API responses are intercepted deterministically; no running backend is
required. They test real Chromium navigation/input and UI recovery, not live
provider or PostgreSQL integration.

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

### Optional Cisco LLM integration

The test-only factory in `client_llms/llms.py` loads the adjacent ignored `.env`
when first requested; importing it does not authenticate or contact a model.
Set `MBR_AI_CANVAS_Ingest_Client_ID`, `MBR_AI_CANVAS_Ingest_Client_Secret`, and
`MBR_AI_CANVAS_APP_KEY` in that local file. Existing shell values take precedence.
Optional variables from the supplied client include
`MBR_AI_CANVAS_AZURE_ENDPOINT`, `MBR_AI_CANVAS_SSO_TOKEN_API`,
`MBR_AI_CANVAS_AZURE_API_VERSION`, and `MBR_AI_CANVAS_AZURE_MODEL_4_1`
(otherwise the client's default model is used).

Run from the repository root using the backend environment:

```powershell
uv sync --project backend --extra local
.\backend\.venv\Scripts\python.exe -m pytest -q -c TestSuite\pyproject.toml TestSuite\tests\test_llm_client_adapter.py
$env:RUN_LIVE_LLM_TESTS = "1"
.\backend\.venv\Scripts\python.exe -m pytest -q -c TestSuite\pyproject.toml TestSuite\tests\test_live_llm_workflows.py --tb=short
Remove-Item Env:\RUN_LIVE_LLM_TESTS
```

The live tests temporarily replace chat factories only inside the pytest process;
pytest restores them after each test. Normal backend provider configuration is
unchanged. Calls send synthetic questions, reference answers, candidate answers,
and interview context, not stored candidate records or uploaded documents.
The persistence scenario uses an isolated SQLite database by default, or its own
PostgreSQL schema if `REALWORLD_TEST_DATABASE_URL` is explicitly supplied.
Do not run live tests as a load test: they incur real provider requests/costs.

Coverage includes:

- native structured-output grading with correct, incorrect, and partial answers;
- interview evaluation and follow-up schema compatibility;
- generation of text, single-choice and multiple-choice questions with 2- and
  10-question batches, plus a 25-question hard single-choice request;
- recovery from an injected invalid third answer key using a real Cisco
  correction response, with exact count and answer-key assertions;
- ten-question practice generation and actual worker persistence;
- offline verification that structured calls obtain current OAuth tokens;
- provider failure preserving an empty question set, exposing a failed state,
  and allowing explicit generation retry.

Generated bank multi-choice questions must have two or three correct options,
and both bank and practice options must have distinct trimmed, case-insensitive
labels. Practice multi-choice also requires at least one incorrect option.
Deterministic tests cover these constraints and do not infer factual correctness
from the marked answer key.

**No embedding model is required for these checks.** Question generation stops
before the embedding/similarity stages. The tests do not fabricate embeddings,
validate semantic duplicate detection, or certify end-to-end staged bank
generation. Small grading examples are smoke checks, not a statistically
meaningful human-labelled grading benchmark. These tests also do not establish
long-duration OAuth expiry behavior or provider rate-limit capacity.

Playwright browser tests use actual Chromium input, form validation, network
interception, refresh, and navigation. API-backed workflows use deterministic
responses where a live model or backend is unnecessary; the stateful and
authorization tests still require a dedicated running test environment. The
suite targets authentication, authorization, service health, payload bounds,
CORS, concurrent reads/writes, duplicate starts/submission, transient failures,
long/unicode candidate input, and recovery flows. It does not prove every
possible edge case. Further work includes human-labelled AI grading evaluation,
coding/SQL sandbox limits, live imports/exports, sustained load, and additional
worker restart and registration-approval races.
