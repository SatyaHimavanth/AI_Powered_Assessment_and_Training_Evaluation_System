# AI-Powered Assessment & Training Evaluation System

A full-stack platform for managing assessments, training evaluations, AI-assisted question generation, practice tests, coding/SQL questions, and results exports. Built with FastAPI, React, PostgreSQL, pgvector, and Azure OpenAI.

## Tech Stack

| Layer | Technology |
| --- | --- |
| Backend | Python 3.12+, FastAPI, SQLAlchemy, Uvicorn |
| Frontend | React 19, TypeScript, Vite 8, Tailwind CSS v4 |
| Database | PostgreSQL with pgvector |
| LLM | Azure OpenAI via `langchain-openai` |
| Auth | JWT access/refresh tokens, bcrypt |

## Prerequisites

- Python 3.12+
- Node.js 18+
- PostgreSQL 14+
- pgvector installed on the PostgreSQL server
- Azure OpenAI API access

## Quick Setup

### 1. Create Database

```bash
psql -U postgres -c "CREATE DATABASE assessment_db;"
```

Enable pgvector once in `assessment_db` if your app DB user cannot create extensions:

```sql
\c assessment_db
CREATE EXTENSION IF NOT EXISTS vector;
```

The backend also runs `CREATE EXTENSION IF NOT EXISTS vector` during startup. Startup will fail if pgvector is not installed on the PostgreSQL server or if the DB user lacks permission and the extension has not already been created.

### 2. Backend Setup

```bash
cd backend

python -m venv .venv
.venv\Scripts\activate

pip install -e .
cp .env.example .env

uvicorn main:app --reload --port 8000
```

Example backend `.env`:

```env
DATABASE_URL=postgresql://postgres:yourpassword@localhost:5432/assessment_db
ASYNC_DATABASE_URL=postgresql+asyncpg://postgres:yourpassword@localhost:5432/assessment_db
SECRET_KEY=your-secret-key-here

AZURE_OPENAI_API_KEY=your-azure-openai-key
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
CHAT_DEPLOYMENT_NAME=gpt-4
OPENAI_API_VERSION=2024-12-01-preview

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

## Default Credentials

| Role | Username | Password |
| --- | --- | --- |
| Admin | admin | admin123 |
| User | user | user123 |

These are auto-created on first startup and can be overridden with environment variables.

## Key Features

- Multi-role system with Admin and User roles.
- Admin-created users/admins from the Admin -> Users page.
- Two-stage public registration with admin approval.
- Question bank upload and management by topic, type, and difficulty.
- Assessment builder with batch assignment.
- User assessment dashboard with attempted assessment exports.
- Admin results dashboard with per-user and filtered all-users Excel exports.
- Auto and LLM evaluation for MCQ, text, coding, and SQL questions.
- AI-generated practice tests.
- AI question generation with duplicate detection, staged review, archive, and unarchive-to-review flow.
- pgvector-based similarity search for generated/imported question embeddings.
- SQL assessment sandbox using demo tables inside the main assessment database.

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
    llms.py                       # Azure OpenAI client setup
    prompts.py                    # LLM prompt templates
  core/
    auth.py                       # JWT and password utilities
    evaluation_service.py         # Background eval job consumer
    setup_demo_db.py              # Demo SQL schema/table setup
    sql_runner.py                 # Read-only SQL sandbox runner
    vector_store.py               # pgvector setup and similarity query helpers
    embedding_service.py          # Embedding computation and storage
    question_generation.py        # LLM question generation pipeline
    embedding_backfill.py         # Startup backfill for missing embeddings
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

## pgvector Embeddings

Question embeddings are stored in PostgreSQL using the pgvector `vector` type. There is no FAISS or external vector-store fallback.

On startup, the backend:

1. Runs `CREATE EXTENSION IF NOT EXISTS vector`.
2. Creates missing tables.
3. Ensures `question_embeddings.embedding` is `vector(EMBEDDING_DIM)`.
4. Backfills embeddings for active questions that do not have one.

If pgvector is unavailable, startup fails. Install pgvector on the PostgreSQL server and create the extension in `assessment_db`.

Relevant env vars:

```env
EMBEDDING_DEPLOYMENT_NAME=text-embedding-3-small
EMBEDDING_DIM=1536
SIMILARITY_THRESHOLD_HIGH_DUP=0.85
SIMILARITY_THRESHOLD_REVIEW=0.70
```

## SQL Assessment Sandbox

SQL coding questions now use demo tables inside the main `assessment_db`, not a separate `demo_db`.

Startup creates and seeds:

- `demo.departments`
- `demo.employees`

The SQL runner connects with `DATABASE_URL`, starts a read-only transaction, sets:

```sql
SET LOCAL search_path TO demo, pg_temp;
```

So a user query like:

```sql
SELECT * FROM employees;
```

resolves to:

```sql
SELECT * FROM demo.employees;
```

The runner rejects DML/DDL and blocks access to application tables or system schemas such as `public`, `pg_catalog`, and `information_schema`.

## AI Question Generation

Admins can generate questions from source text in Admin -> AI Generate.

Flow:

1. Generate questions by topic, type, difficulty, and count.
2. Compute embeddings for generated questions.
3. Compare generated questions against the existing question bank with pgvector cosine similarity.
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
