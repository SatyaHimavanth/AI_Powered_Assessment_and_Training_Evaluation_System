# Docker Setup

## Prerequisites

- Docker & Docker Compose installed
- A `backend/.env` file with your configuration

## Environment File

Create `backend/.env` and set unique values for the database and application credentials. Use this same file for Compose interpolation with `--env-file`:

```env
# Database (used by both db and backend containers)
POSTGRES_USER=assessment_app
POSTGRES_PASSWORD=replace-with-a-long-random-database-password
POSTGRES_DB=assessment_db
DATABASE_URL=postgresql://assessment_app:replace-with-a-long-random-database-password@db:5432/assessment_db
ASYNC_DATABASE_URL=postgresql+asyncpg://assessment_app:replace-with-a-long-random-database-password@db:5432/assessment_db

# JWT
JWT_SECRET_KEY=replace-with-a-different-long-random-secret
DEFAULT_ADMIN_PASSWORD=replace-with-a-unique-admin-password

# Azure OpenAI
AZURE_OPENAI_API_KEY=your-key
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
CHAT_DEPLOYMENT_NAME=gpt-4
OPENAI_API_VERSION=2024-12-01-preview
```

---

## Option 1: Docker Compose (Recommended)

Starts PostgreSQL, the API, a dedicated background worker, and the frontend together:

```bash
# Build and start all services
docker compose --env-file backend/.env up --build

# Run in background
docker compose --env-file backend/.env up --build -d

# Stop all services
docker compose down

# Stop and remove volumes (wipes database)
docker compose down -v
```

**Access:**
- Frontend: http://localhost
- Backend API (host loopback for local development): http://localhost:8000
- API Docs: http://localhost:8000/docs

Compose runs a one-shot migration service before starting the API. It bootstraps
new databases and applies the ordered, idempotent PostgreSQL upgrades under an
advisory lock. Outside Compose, run `python -m db.migrate` from the backend
application directory before starting the API. The API checks that the migration
set is applied and refuses to start if upgrades are pending.

The Compose worker processes assessment evaluations, persisted question-generation
batches, embedding backfill, and assessment-window expirations. In local
development, the API starts an in-process worker by default; set
`RUN_WORKER_IN_API=false` when running a separate worker. Non-Compose production
deployments may run `python -m worker` as a managed service, or use the
container image's embedded worker default to keep API and worker in one backend
service. Interrupted
evaluation jobs are recovered by the worker. Interrupted question-generation
batches with partial staged output are marked failed for review rather than
replayed automatically.

### Cloud SQL console-only upgrade from a02c14f

When only Cloud SQL Studio/SQL console access is available, use
[`backend/migrations/20261029_cloudsql_from_a02c14f.sql`](backend/migrations/20261029_cloudsql_from_a02c14f.sql).
It is a SQL-only equivalent of the migration set introduced in `659690f`,
prepared by comparing the deployed `a02c14f` models with the new models. This
is not a generic upgrade script for arbitrary older installations.

1. Take a Cloud SQL backup/snapshot. Prefer rehearsing on a restored clone.
2. Finish active candidate sessions and stop the old API and workers so they
   cannot write during the upgrade.
3. In Cloud SQL Studio, connect to the **application database** as a role with
   schema/table/index modification permissions. Confirm `SELECT
   current_database(), current_schema();` points to the application's schema.
4. Open the linked SQL file and execute its **entire `DO ... $upgrade$;`
   statement**, not individual lines. It is one atomic transaction. A lock
   timeout, duplicate data, invalid ownership, or other SQL error rolls back all
   of this script's changes, including migration history. Do not ignore errors
   or manually insert migration versions.
5. After successful completion, verify:

   ```sql
   SELECT version, applied_at
   FROM app_schema_migrations
   ORDER BY version;
   ```

   The script records all 12 versions in the `659690f` migration set. Future
   application releases may require additional migrations.
6. Deploy the new backend and worker with the **same embedding storage backend
   and dimension as the existing database**. Check `/health?db=true&llm=false`,
   login, historical results, and one new assessment flow.

The script adds tables/columns/indexes and backfills missing question positions.
It does not delete application records, reconcile duplicates automatically, or
convert embeddings. Compatible re-execution is supported. Constraint failures
require explicit review of historical data before retrying. Normal duration
accounting starts with the new columns' defaults, so do not perform this upgrade
mid-exam. Existing login sessions may need a fresh login for the new persisted
refresh-session flow.

The accompanying regression tests build the exact `a02c14f` schema from Git,
seed historical rows, and verify preservation, repeated execution, target
column/nullability compatibility, migration history, and rollback on invalid
data. They require a disposable PostgreSQL database:

```powershell
.\backend\.venv\Scripts\python.exe -m pytest -q -c TestSuite\pyproject.toml TestSuite\tests\test_cloudsql_console_migration.py
```

Set `REALWORLD_TEST_DATABASE_URL` and matching `DATABASE_URL` /
`DATABASE_URL_ASYNC` as described in [TestSuite](TestSuite/README.md). Local
rehearsal used JSON embedding storage; the SQL retains pgvector columns and
dimensions and creates the cosine index only when its dimensions support HNSW.
The actual Cloud SQL data and its vector-specific branch must still be verified
on a Cloud SQL clone.

### Candidate code execution

The default `PYTHON_RUNNER_MODE=local` runs candidate Python in a subprocess
using the backend service's own Python environment. This keeps the deployed
architecture to one backend service and one frontend service; no Python runner
container or network route is required. Candidate-facing runs still use only
public sample test cases; hidden cases are reserved for server-side evaluation.
The runner applies source/input/output limits, a wall-clock timeout, a small
concurrency cap, a cleaned child environment, and POSIX CPU/memory/file limits
where available. When the backend runs as root on POSIX, candidate subprocesses
drop to an unprivileged UID. The existing static checks run before execution.

**This is a temporary compatibility mode, not a security sandbox.** Candidate
code runs with the backend process's OS permissions and may be able to access
files, network services, installed packages, or resources that static checks do
not detect. The cleaned environment and temporary working directory do not
remove those permissions. Use it only where this accepted risk is appropriate;
move execution to a real OS/container sandbox before exposing the service to
untrusted users or sensitive infrastructure. Windows does not get the POSIX
resource limits, only the subprocess timeout, output/input limits, and
concurrency cap; on Windows the subprocess also inherits the backend account's
permissions.

An optional isolated Docker runner remains available for local Compose testing.
Set `PYTHON_RUNNER_MODE=queue` in `backend/.env` and start Compose with the
profile enabled:

```bash
docker compose --env-file backend/.env --profile isolated-python up --build
```

It uses a networkless container with a read-only root filesystem and explicit
CPU, memory, process, and filesystem limits. Optional coding dependencies can
be added to the `testvenv` dependency group and installed by rebuilding this
runner image. This mode is not required for the single-backend deployment.

### Deploying the two images separately

The backend image listens on the platform-provided `PORT` (defaults to 8000
locally), starts the in-process worker by default, and defaults to
`PYTHON_RUNNER_MODE=local`. Set production secrets and database/provider
configuration through the platform's secret/environment settings; do not copy
`.env` into an image. `SQL_SANDBOX_DATABASE_URL` must still point to the
dedicated read-only database role and configured allowed schema/tables.

The frontend image serves the SPA and reverse-proxies `/api` to
`BACKEND_UPSTREAM`. For Cloud Run, deploy the backend image first, then deploy
the frontend image with `BACKEND_UPSTREAM=https://<backend-service-url>`; Cloud
Run supplies the container `PORT`. Browser requests remain same-origin at the
frontend, so they do not need a separate API URL or cross-origin cookie setup.
The backend endpoint must be reachable by the frontend proxy; application
authentication continues to be enforced by the backend.

`backend/app.yaml` and `frontend/app.yaml` target App Engine Flexible custom
runtimes. Before deploying the frontend service, replace `BACKEND_UPSTREAM` in
`frontend/app.yaml` with the deployed backend service's HTTPS host. Set database
URLs, signing keys, model credentials, `APP_ENV=production`, and
`SQL_SANDBOX_DATABASE_URL` as protected runtime configuration. App Engine
Flexible keeps at least one manually configured instance for each service, so
account for its ongoing instance cost.

Apply database migrations against the managed database before routing traffic
to a new backend revision by running `python -m db.migrate` from the backend
image with the deployment's database configuration. This is a one-off deploy
step and does not require a permanent third service.

The embedded worker needs CPU outside active HTTP requests. On Cloud Run,
configure instance-based billing/always-allocated CPU and keep at least one
backend instance running if evaluations must complete without a later request.
Cloud Run instances can restart or scale independently, so evaluation jobs must
remain persisted in the database (as they are now). If the service scales out,
multiple worker loops can run; database job claiming remains the coordination
mechanism.

App Engine Standard is not a supported target for this local execution mode:
it has a read-only filesystem except `/tmp` and a restricted runtime. Use Cloud
Run containers or App Engine Flexible. See [Cloud Run container filesystem and
CPU behavior](https://cloud.google.com/run/docs/overview/what-is-cloud-run),
[App Engine Python runtime filesystem behavior](https://cloud.google.com/appengine/docs/standard/python3/runtime),
and [App Engine Flexible runtime differences](https://cloud.google.com/appengine/docs/flexible/flexible-for-standard-users).

### SQL execution setup

SQL execution requires `SQL_SANDBOX_DATABASE_URL` to use a dedicated PostgreSQL
login. Do not point it at `DATABASE_URL`. The URL's role must have no elevated
attributes or role memberships and `SELECT` access only to the tables listed in
`SQL_SANDBOX_SCHEMA` and `SQL_SANDBOX_ALLOWED_TABLES`. The runner checks those
permissions, starts a read-only transaction, sets the schema search path, and
applies statement, lock, row-count, and output limits. Only one `SELECT` or
`WITH ... SELECT` statement is accepted.

For the example `demo.employees` and `demo.departments` tables:

1. Provision the demo schema if it is not already present by running
   `python -m core.setup_demo_db` from `backend/` with the application database
   configuration.
2. From a secure terminal, set `SQL_SANDBOX_ADMIN_DATABASE_URL` temporarily to
   an administrative connection URL, set a unique `SQL_SANDBOX_PASSWORD` of at
   least 24 characters, and run `python -m tools.setup_sql_sandbox_role` from
   `backend/`. The command creates a new restricted role and refuses to alter
   an existing role. Do not put the administrative URL in the app's runtime
   environment or commit it.
3. Set `SQL_SANDBOX_DATABASE_URL` in `backend/.env` to the new login. Use host
   `db` under Compose and `localhost` when the backend runs directly on the
   host. The user and schema/table settings must match the role that was
   provisioned.
4. Restart Compose so the API and evaluation worker load the restricted URL.

The example role script grants access only to the named tables and does not
change application tables or data. Add newly required SQL tables to the
allowlist, recreate/provision a dedicated role, and rebuild/restart as needed.

---

## Option 2: Run Containers Individually

### 1. Create a Docker network

```bash
docker network create assessment-net
```

### 2. Start PostgreSQL

```bash
docker run -d \
  --name assessment-db \
  --network assessment-net \
  -e POSTGRES_USER=assessment_app \
  -e POSTGRES_PASSWORD=<unique-database-password> \
  -e POSTGRES_DB=assessment_db \
  -p 127.0.0.1:5432:5432 \
  -v pgdata:/var/lib/postgresql/data \
  pgvector/pgvector:pg16
```

### 3. Build & Run Backend

```bash
# Build
docker build -t assessment-backend ./backend

# Migrate before starting the API (repeat after application upgrades)
docker run --rm \
  --network assessment-net \
  --env-file ./backend/.env \
  -e DATABASE_URL=postgresql://assessment_app:<unique-database-password>@assessment-db:5432/assessment_db \
  assessment-backend python -m db.migrate

# Run (update DATABASE_URL to point to the db container)
docker run -d \
  --name backend \
  --network assessment-net \
  --env-file ./backend/.env \
  -e DATABASE_URL=postgresql://assessment_app:<unique-database-password>@assessment-db:5432/assessment_db \
  -e RUN_WORKER_IN_API=false \
  -p 127.0.0.1:8000:8000 \
  assessment-backend
```

Start the background worker on the same network after the API has initialized
the database:

```bash
docker run -d \
  --name assessment-worker \
  --network assessment-net \
  --env-file ./backend/.env \
  -e DATABASE_URL=postgresql://assessment_app:<unique-database-password>@assessment-db:5432/assessment_db \
  assessment-backend python -m worker
```

### 4. Build & Run Frontend

```bash
# Build
docker build -t assessment-frontend ./frontend

# Run
docker run -d \
  --name assessment-frontend \
  --network assessment-net \
  -p 80:80 \
  assessment-frontend
```

### Cleanup

```bash
docker stop assessment-frontend backend assessment-worker assessment-db
docker rm assessment-frontend backend assessment-worker assessment-db
docker network rm assessment-net
```

---

## Notes

- The frontend nginx config proxies `/api/*` requests to the backend container
- Database data persists in a Docker volume (`pgdata`)
- A system administrator is created only from the configured `DEFAULT_ADMIN_*`
  values. Set a unique password before starting the application.
- Compose publishes the API and database on host loopback. Keep the backend
  private behind the frontend gateway in deployed environments and terminate
  TLS at the public ingress. Set `APP_ENV=production` so the refresh cookie is
  marked `Secure`.
- The frontend Nginx gateway applies shared request limits. When another
  reverse proxy sits in front of it, configure trusted client-IP forwarding and
  rate limits at that ingress; do not trust arbitrary `X-Forwarded-For` input.
- For local development without Docker, see [README.md](README.md)
# Database sizing and audit benchmarks

Each API process currently creates both synchronous and asynchronous SQLAlchemy
engines. Peak API connections are therefore
`2 * (DB_POOL_SIZE + DB_MAX_OVERFLOW) * DB_REPLICA_COUNT * DB_WORKER_PROCESSES`.
Set `DB_SERVER_MAX_CONNECTIONS` to the server's configured `max_connections`
and `DB_CONNECTION_RESERVE` to leave capacity for migrations, workers, monitoring,
and administration. Startup fails if the configured peak exceeds the available
budget. The default reserve is 10; choose values from the actual deployment.

For query-plan evidence, provision and seed a disposable PostgreSQL database with
representative cardinalities, set `BENCHMARK_DATABASE_DISPOSABLE=1` and its
`DATABASE_URL`, then run `python -m tools.seed_query_benchmark` followed by
`python -m tools.query_plan_benchmark` from `backend/`. The seed command refuses
non-empty workflow/parent tables and inserts synthetic rows only into that DB.
Save the JSON plans and compare latency, buffers, index selection, and write
overhead before adding indexes. The script refuses to run without the explicit
disposable-database acknowledgement and performs read-only SELECT plans.

For grading quality, prepare an access-controlled JSONL corpus with independent
human scores and rubric dimensions, then run `python -m tools.grading_benchmark
path/to/labels.jsonl`. Keep personally identifying data out of the file, blind
reviewers to model scores, preserve model/provider/version and rubric metadata
alongside results, and do not use synthetic labels to claim grading validity.
