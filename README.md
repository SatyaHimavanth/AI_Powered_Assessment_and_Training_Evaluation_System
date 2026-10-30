# AI-Powered Assessment & Training Evaluation System

A full-stack platform for managing assessments, training evaluations, AI-assisted question generation, practice tests, coding/SQL questions, interviews, and results exports. Built with FastAPI, React, PostgreSQL, and configurable Azure OpenAI or Ollama model providers.

## Tech Stack

| Layer | Technology |
| --- | --- |
| Backend | Python 3.12+, FastAPI, SQLAlchemy, Uvicorn |
| Frontend | React 19, TypeScript, Vite 8, Tailwind CSS v4 |
| Database | PostgreSQL with optional pgvector (JSON fallback available) |
| LLM | Azure OpenAI or local Ollama via LangChain |
| Auth | JWT access and refresh tokens in HttpOnly, SameSite cookies; bcrypt |

## Prerequisites

- Python 3.12+
- `uv` for locked Python dependency setup
- Node.js 20.19+ or 22.12+ (Vite 8 requirement)
- PostgreSQL 14+
- pgvector installed on the PostgreSQL server, or JSON fallback mode enabled
- Azure OpenAI API access or an Ollama server/model

## Quick Setup

### 1. Create Database

Create a PostgreSQL database and install the `vector` extension, or choose the
JSON embedding fallback below. Docker Compose provisions PostgreSQL 16 with
pgvector automatically. Enable pgvector once if your app DB user cannot create
extensions:

```sql
\c assessment_db
CREATE EXTENSION IF NOT EXISTS vector;
```

The default mode requires pgvector. Run the versioned database migrations once
before starting the API. Use `EMBEDDING_STORAGE_BACKEND=json` only when the
database has been provisioned in JSON mode.

### 2. Backend Setup

```bash
cd backend

uv sync --extra local
Copy-Item .env.example .env # PowerShell; use cp on macOS/Linux

# Edit DATABASE_URL for localhost and set unique passwords/secrets.
# Select Azure OpenAI or Ollama with CHAT_PROVIDER / EMBEDDING_PROVIDER.

# Apply database schema migrations before the API starts
uv run python -m db.migrate

# The API starts its local background worker automatically in development.
uv run uvicorn main:app --reload --port 8000
```

Example backend `.env`:

```env
DATABASE_URL=postgresql://postgres:yourpassword@localhost:5432/assessment_db
DATABASE_URL_ASYNC=postgresql+asyncpg://postgres:yourpassword@localhost:5432/assessment_db
JWT_SECRET_KEY=replace-with-a-long-random-secret
CORS_ALLOWED_ORIGINS=http://localhost:5173
PYTHON_RUNNER_MODE=local
RUN_WORKER_IN_API=true

# Set Azure credentials/deployment names, or configure Ollama provider/model names.
CHAT_PROVIDER=azure_openai
EMBEDDING_PROVIDER=azure_openai

EMBEDDING_DEPLOYMENT_NAME=text-embedding-3-small
SIMILARITY_THRESHOLD_HIGH_DUP=0.85
SIMILARITY_THRESHOLD_REVIEW=0.70

SQL_SANDBOX_SCHEMA=demo
SQL_SANDBOX_ALLOWED_TABLES=employees,departments
```

### 3. Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

Frontend runs at `http://localhost:5173`, backend at `http://localhost:8000`.

## Bootstrap Accounts

| Role | Username | Password |
| --- | --- | --- |
| Admin | `DEFAULT_ADMIN_USERNAME` | `DEFAULT_ADMIN_PASSWORD` |
| User | `DEFAULT_USER_USERNAME` | `DEFAULT_USER_PASSWORD` |

Set unique passwords in `backend/.env` before first startup. The example file
contains placeholders; do not use those values in a deployed environment.

## Key Features

- Multi-role system with Admin and User roles.
- Admin-created users/admins from the Admin -> Users page.
- Two-stage public registration with admin approval.
- Question bank upload and management by topic, type, and difficulty.
- Assessment builder with a mutually exclusive batch or individual-user assignment mode.
- User assessment dashboard with attempted assessment exports.
- Admin results dashboard with per-user and filtered all-users Excel exports.
- Automatic objective and coding-test evaluation, with AI evaluation for text answers.
- AI-generated practice tests.
- AI question generation with duplicate detection, staged review, archive, and unarchive-to-review flow.
- pgvector- or JSON-based similarity search for question embeddings.
- SQL assessment sandbox using demo tables inside the main assessment database.

## Assessment and Recovery Behavior

- AI Generation Batches show the topic, question type, difficulty, requested
  question count, saved generation totals, and failure reason. Active batches
  refresh automatically. Failed batches can be retried with their original
  inputs or deleted after confirmation. Retrying clears partial staging and is
  blocked once questions have been approved; deleting a failed batch never
  deletes saved bank questions or assessment answers. No schema migration is
  required for these controls.

- The assessment creation page is a single form. Required fields and selections
  are marked with `*`; description and scheduled start/end times are optional.
  Choose at least one batch/user and either question-bank sections or an Excel
  import before creating the assessment.

- Editing a bank question already linked to an assessment creates a new active
  version and archives the bank entry for the original. Existing assessments,
  option IDs, saved answers, and grading retain the original version.
- Sections may share the same topic/type/difficulty pool. Requested counts are
  aggregated while question selection remains unique across sections.
- Assessment Excel imports validate rows and report errors before creation.
  Answer keys accept option letters separated by spaces, commas, pipes, or
  semicolons, and full option text (separate multiple full-text keys with pipes,
  commas, or semicolons). Blank/unknown topic names remain local to the imported
  assessment rather than creating question-bank topics.
- The assessment-import format supports text and MCQ questions. Upload coding
  questions through the question bank with their templates and test cases;
  assessment imports reject coding rows rather than assigning unavoidable zeroes.
- Interview approvals are single-use. Approved retries work after completed,
  missed, or abandoned sessions. Normal duration expiry completes the session;
  repeating an end request is harmless.
- Unfinished and failed practice tests remain accessible from history, including
  tests created on previous days. Failed submissions show feedback without
  discarding the candidate's answers.
- Missing assessment answers count as zero in topic reporting. Rejected
  registration requests can be resubmitted after the configured cooldown.
- AI interviews store their full transcript and evaluations in PostgreSQL.
  The agent is reconstructed from the stored conversation on each request; it
  does not depend on process-local chat memory. Model prompts use the most
  recent stored history within a bounded context, without deleting older turns.
- Interview text/voice drafts autosave to the database after 500 ms. Wait for
  "Draft saved in the database" before closing: unsynced text can still be lost
  if the browser/device crashes before a save reaches the server.
- Once an interview answer is accepted, its pending-evaluation marker and timer
  pause are committed before calling AI. Provider/format failures return a
  retry-later message; reopening the session restores the same answer and retry
  action. Successful evaluation resumes the timer without using pause allowance.
  No new database migration is needed; existing transcript/feedback JSON and
  paused-session fields hold this state.
- Practice questions and saved answers also live in PostgreSQL. An evaluation
  outage preserves submitted answers and leaves the test resumable from history.
  Browser local storage contains only interview interruption markers, not the
  interview transcript. Timed exams separately retain local offline drafts as
  well as server-saved answers.

See [TestSuite](TestSuite/README.md) for executable recovery, failure-injection,
browser, and live concurrency scenarios and their validation boundaries.

## Project Structure

```text
backend/
  main.py                         # App entry, lifespan, seed data
  api/
    routers_auth.py               # Register, login, refresh
    routers_admin.py              # Admin management, users, results, exports
    routers_questions.py          # Question bank upload/management
    routers_assessments.py        # Assessment CRUD and result exports
    routers_batches.py            # Batch management
    routers_user_assessments.py   # User assessment flow
    routers_practice.py           # Practice test flow
    routers_question_generation.py# AI question generation and staged review
  app/
    llms.py                       # Azure OpenAI / Ollama model providers
    prompts.py                    # LLM prompt templates
  core/
    auth.py                       # JWT and password utilities
    evaluation_service.py         # Background eval job consumer
    setup_demo_db.py              # Demo SQL schema/table setup
    sql_runner.py                 # Read-only SQL sandbox runner
    vector_store.py               # Embedding storage setup and similarity helpers
    embedding_service.py          # Embedding computation and storage
    question_generation.py        # LLM question generation pipeline
    embedding_backfill.py         # Worker backfill for missing embeddings
  db/
    database.py                   # SQLAlchemy engine and session
    models.py                     # ORM models

frontend/
  src/
    App.tsx                       # Root routes
    api.ts                        # Axios instance with auth
    pages/
      Login.tsx / Register.tsx
      admin/                      # Admin dashboard tabs
      user/                       # User dashboard tabs
    components/
  package.json
```

## Embedding Storage

Question embeddings use pgvector by default. When PostgreSQL does
not provide the vector extension, set:

```env
EMBEDDING_STORAGE_BACKEND=json
```

JSON mode stores embeddings as JSON arrays and performs cosine similarity in
the backend process. It is intended as a temporary fallback for small question
banks; pgvector remains preferable for indexed, database-side similarity at
scale. Select the backend before creating `question_embeddings`; changing an
existing column between vector and JSON requires a database migration.

In the default `pgvector` mode, the migration command:

1. Runs `CREATE EXTENSION IF NOT EXISTS vector`.
2. Creates missing tables and applies the ordered schema migrations.
3. Ensures `question_embeddings.embedding` uses the configured storage type
   (`vector(EMBEDDING_DIM)` in pgvector mode).

The worker backfills embeddings for active questions that do not have one. The
configured embedding provider (Azure OpenAI or Ollama) must be available for
that operation.

If pgvector is unavailable in the default mode, startup fails. Either install
the extension or select JSON mode.

Relevant env vars:

```env
EMBEDDING_PROVIDER=azure_openai
EMBEDDING_DEPLOYMENT_NAME=text-embedding-3-small
EMBEDDING_DIM=1536
SIMILARITY_THRESHOLD_HIGH_DUP=0.85
SIMILARITY_THRESHOLD_REVIEW=0.70
```

## SQL Assessment Sandbox

SQL coding questions use a dedicated restricted login against the configured
demo schema in the application database; this is a separate role and permission
boundary, not a separate database instance.

Provision the example tables with `uv run python -m core.setup_demo_db` from
`backend/` after configuring the application database. The command creates and
seeds:

- `demo.departments`
- `demo.employees`

Candidate SQL runs use `SQL_SANDBOX_DATABASE_URL`; it must not reuse
the application's `DATABASE_URL`. Configure a dedicated PostgreSQL role with
`SELECT` access only to the allowlisted `demo` tables. The runner verifies the
role privileges, starts a read-only transaction, applies statement and lock
timeouts, and caps result size. Only one `SELECT` or `WITH ... SELECT` is
accepted. See [DOCKER.md](DOCKER.md#sql-execution-setup) for provisioning steps.

The runner sets the transaction-local search path to:

```sql
SET LOCAL search_path TO demo, pg_catalog;
```

So a user query like:

```sql
SELECT * FROM employees;
```

resolves to:

```sql
SELECT * FROM demo.employees;
```

The runner accepts one read-only `SELECT`/`WITH ... SELECT`, checks the role's
privileges and table allowlist, and applies query/output limits. Python coding
execution is separate and defaults to the temporary local subprocess mode
described in [DOCKER.md](DOCKER.md#candidate-code-execution).

## AI Question Generation

Admins can generate questions from source text in Admin -> AI Generate.

Flow:

1. Generate questions by topic, type, difficulty, and count.
2. Compute embeddings for generated questions.
3. Compare generated questions against the existing question bank with cosine similarity.
4. Stage generated questions with match bands:
   - High duplicate
   - Review
   - Unique
5. Admin approves or rejects staged questions.
6. Approved questions are added to the question bank.

AI Generate also supports:

- Archiving saved questions from a generated batch.
- Unarchiving archived/rejected generated questions back to pending staged review, so admins can re-approve only the required questions.

## Results Export

Admin results exports include:

- Per-user assessment export from the result view modal.
- Filtered all-users export by selected batch/assessment filters.
- Overall average information and per-user average scores.
- User result detail sheets/tables in the same format as the user dashboard attempted assessment export.

## API Documentation

Once the backend is running:

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## Automated TestSuite

`TestSuite/` is an isolated Python 3.12 `uv` project covering API contracts,
authentication, authorization, CORS, multi-user assessment concurrency,
full/partial/aborted attempts, learner-result accuracy, and Playwright browser
workflows.

Configure the variables shown in `TestSuite/.env.example`, start the frontend
and backend, then run the complete suite:

```powershell
Set-Location TestSuite
uv sync
uv run python run_all.py
```

Stateful tests provision three temporary users, a topic, four questions, a
batch, and an assessment through public APIs. In local/test environments,
teardown deletes fixtures through a restricted cleanup endpoint; other
environments use the documented archive/deactivate fallback. Run stateful tests
only against a dedicated test environment. See
[TestSuite/README.md](TestSuite/README.md) for details.
