# Application Workflows and Runtime

This document summarizes behavior currently implemented in the repository. The
running FastAPI OpenAPI schema at `/docs` is the authoritative API contract.

## Architecture

- **Frontend:** React 19, TypeScript, Vite, served by Nginx in the production image.
- **Backend:** FastAPI and SQLAlchemy, with synchronous and asynchronous PostgreSQL
  engines.
- **Database:** PostgreSQL. Embeddings use pgvector by default, with a JSON
  fallback for deployments without the vector extension.
- **Model providers:** Azure OpenAI or Ollama, selected independently for chat
  and embeddings through environment settings.
- **Background work:** A persistent database-backed worker handles assessment
  evaluation, practice-test generation, embedding backfill, and scheduled
  assessment expiry. Local startup and the backend image run it in-process by
  default; Compose uses a separate worker service.

The frontend can run separately from the backend. Its Nginx `/api` proxy takes
the backend URL from `BACKEND_UPSTREAM`. See [DOCKER.md](DOCKER.md) for the
single-backend/single-frontend deployment configuration.

## Authentication and browser storage

Registration creates a pending request for admin approval. Login and refresh
issue HttpOnly, SameSite cookies for access and refresh tokens. The browser API
client sends credentials and refreshes an expired access token once. Legacy
token values are removed from localStorage.

Assessment answer drafts are stored temporarily in localStorage under keys
scoped to the user, assessment, and attempt. Starting or resuming a different
attempt does not reuse those drafts; successful sync or submission clears that
attempt's draft. Browser storage is recovery support, not the authoritative
answer record.

## Assessment assignment and lifecycle

Admins create assessments from configured question-bank sections. Assignment is
either to batches or to individual users; the UI defaults to batches and switches
between the two modes. The API rejects a request that combines the two assignment
types. User assignment rows are deduplicated so batch and direct assignment do
not create duplicate visible assessments.

An attempt's duration accumulates while the user is actively in the assessment;
it is not simply elapsed wall time since first start. The server checkpoints
active time using browser heartbeats and caps unobserved active time with a
five-minute lease. The scheduled assessment end time is also enforced, so the
effective deadline is whichever occurs first: remaining active duration or
assessment close time. At the scheduled close, active attempts are finalized by
the backend worker. Users may resume an eligible attempt before it closes.

The browser autosaves answers and keeps a scoped local draft for network
recovery. It permits a short offline interval, then locks answer entry and pauses
the active clock; after reconnect, the UI syncs pending answer data. A failed
submission shows its network state instead of silently treating the attempt as
submitted. The server remains the source of truth and validates attempt state,
question membership, and deadlines.

Admins can retest users whose attempt is completed or missed/aborted. The action
warns that existing attempt and result data will be cleared before creating a
fresh attempt.

## Evaluation and results

- Single- and multi-select questions use exact option-set comparison.
- If negative marking is enabled, a wrong answered objective question loses its
  full point; unanswered questions score zero.
- Coding questions run against configured test cases and receive a pass-rate
  score. Candidate preview runs expose public sample cases; hidden cases are
  reserved for server evaluation.
- Text answers are evaluated against the configured rubric/reference answer by
  the selected chat provider.
- Evaluation jobs persist in the database and are claimed by the worker. Failed
  provider/execution operations are retried rather than silently scored as zero.
- Result details distinguish unattempted, awaiting evaluation, incorrect,
  partially correct, and correct answers. Results are withheld until submission
  and evaluation access rules allow them.

## Python and SQL execution

`PYTHON_RUNNER_MODE=local` is the single-backend default. It runs candidate code
in a bounded subprocess using the backend Python environment, applies source,
input, output, concurrency, and wall-time limits, and uses POSIX resource limits
where available. When the backend runs as root on POSIX, the child drops to an
unprivileged UID. Static checks are an additional filter.

The local runner is **not an OS security sandbox**: code may still access
resources permitted to its operating-system account. In particular, Windows
does not receive POSIX resource limits. The optional `queue` runner uses a
separate networkless Docker sandbox for local testing; the deployment guidance
does not require that extra service.

SQL uses `SQL_SANDBOX_DATABASE_URL`, a dedicated restricted database login, a
configured schema/table allowlist, read-only transactions, query timeouts, and
result caps. Do not configure that URL with the application database account.
See [DOCKER.md](DOCKER.md#sql-execution-setup) for provisioning instructions.

## Practice tests and interviews

Practice tests require approved access. The system generates and persists test
questions, saves answers as the user proceeds, and supports result review and
history. Multi-select scoring is exact match; free-text answers require AI
evaluation. Generation and evaluation use the configured model providers.

Interview sessions have their own access approval, persisted session state,
duration and recovery rules, and result views. They use the configured chat
provider; availability therefore depends on that provider being configured.

## Database and deployment operations

Run `python -m db.migrate` before starting a new or upgraded deployment. The
migrations are ordered and idempotent, and API startup checks that the required
versions are applied. The demo SQL schema is provisioned separately with
`python -m core.setup_demo_db`; it is not automatically created on API startup.

The Docker backend image uses the platform-provided `PORT`, defaults to local
Python execution, and starts the in-process worker. Cloud Run background
evaluation requires CPU outside request processing and at least one running
instance. App Engine Flexible custom-runtime files are included; App Engine
Standard is not supported for the local Python runner. Deployment settings and
the temporary execution risk are described in [DOCKER.md](DOCKER.md).

## Tests

- Backend unit/API tests live in `backend/tests/` and run with
  `uv run pytest -p no:cacheprovider -q tests` from `backend/`.
- Frontend unit tests and production build use `npm test` and `npm run build`
  from `frontend/`.
- `TestSuite/` is a separate black-box API and Playwright suite. Stateful tests
  mutate an explicitly configured test environment and remove their generated
  fixtures through a restricted cleanup endpoint when available. Read
  [TestSuite/README.md](TestSuite/README.md) before enabling those tests.
