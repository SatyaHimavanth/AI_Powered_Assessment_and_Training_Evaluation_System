# AI-Powered Assessment & Training Evaluation System

A full-stack platform for managing assessments, training evaluations, and AI-generated practice tests. Built with FastAPI, React, PostgreSQL, and Azure OpenAI.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12+, FastAPI, SQLAlchemy, Uvicorn |
| Frontend | React 19, TypeScript, Vite 8, Tailwind CSS v4 |
| Database | PostgreSQL |
| LLM | Azure OpenAI (via langchain-openai) |
| Auth | JWT (access + refresh tokens), bcrypt |

## Prerequisites

- Python 3.12+
- Node.js 18+
- PostgreSQL 14+
- Azure OpenAI API access

## Quick Setup

### 1. Clone & Configure Database

```bash
# Create PostgreSQL database
psql -U postgres -c "CREATE DATABASE assessment_db;"
```

### 2. Backend Setup

```bash
cd backend

# Create virtual environment
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux/Mac

# Install dependencies
pip install -e .

# Create .env file
cp .env.example .env  # Or create manually (see below)

# Run server
uvicorn main:app --reload --port 8000
```

**Backend `.env` file:**

```env
DATABASE_URL=postgresql://postgres:yourpassword@localhost:5432/assessment_db
SECRET_KEY=your-secret-key-here
AZURE_OPENAI_API_KEY=your-azure-openai-key
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
CHAT_DEPLOYMENT_NAME=gpt-4
OPENAI_API_VERSION=2024-12-01-preview
```

### 3. Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Run dev server
npm run dev
```

Frontend runs at `http://localhost:5173`, backend at `http://localhost:8000`.

## Default Credentials

| Role | Username | Password |
|------|----------|----------|
| Admin | admin | admin123 |
| User | user | user123 |

These are auto-created on first startup.

## Project Structure

```
backend/
├── main.py              # App entry, lifespan, seed data
├── api/
│   ├── routers_auth.py          # Register, login, refresh
│   ├── routers_admin.py         # Admin management endpoints
│   ├── routers_questions.py     # Question bank upload/management
│   ├── routers_assessments.py   # Assessment CRUD
│   ├── routers_batches.py       # Batch management
│   ├── routers_user_assessments.py  # User taking assessments
│   ├── routers_practice.py      # Practice test flow
│   └── routers_question_generation.py  # AI question generation & staged review
├── app/
│   ├── llms.py          # Azure OpenAI client setup
│   └── prompts.py       # LLM prompt templates
├── core/
│   ├── auth.py          # JWT + password utilities
│   ├── evaluation_service.py  # Background eval job consumer
│   ├── logger.py
│   ├── vector_store.py        # FAISS/pgvector abstraction
│   ├── embedding_service.py   # Embedding computation & similarity search
│   ├── question_generation.py # LLM question generation pipeline
│   └── embedding_backfill.py  # Startup backfill for missing embeddings
└── db/
    ├── database.py      # SQLAlchemy engine & session
    └── models.py        # All ORM models

frontend/
├── src/
│   ├── App.tsx          # Root routes
│   ├── api.ts           # Axios instance with auth
│   ├── pages/
│   │   ├── Login.tsx / Register.tsx
│   │   ├── admin/       # Admin dashboard tabs
│   │   └── user/        # User dashboard tabs
│   └── components/
└── package.json
```

## Key Features

- **Multi-role system** — Admin and User roles with distinct capabilities
- **Two-stage registration** — Users register, admin approves
- **Question bank** — Upload via Excel/CSV, organized by topic/type/difficulty
- **Assessment builder** — Configure questions by topic mix, assign to batches
- **Auto + LLM evaluation** — MCQs scored instantly, text/coding via Azure OpenAI
- **Practice tests** — AI-generated questions based on job description and resume
- **Performance analytics** — Topic-wise scores and improvement areas
- **Export** — Download results as Excel
- **AI Question Generation** — Generate questions from source text using LLM with duplicate detection
- **Vector Similarity Search** — FAISS-based embedding store (pgvector-ready) for detecting duplicate/similar questions

## AI Question Generation

Admins can generate new questions from any source text (textbooks, notes, documentation) using Azure OpenAI, with automatic similarity checking against the existing question bank.

### How It Works

1. **Generate** — Provide source text, select topic/type/difficulty, and specify count (1–50). The LLM generates questions with correct answers and options.
2. **Similarity Check** — Each generated question is embedded (composite of question text + options/answer) and compared against all existing questions using cosine similarity.
3. **Staged Review** — Questions land in a staging area with match bands:
   - **High Duplicate** (≥ threshold) — likely duplicates, flagged for rejection
   - **Review** (≥ lower threshold) — similar to existing, needs manual review
   - **Unique** — no close matches, safe to approve
4. **Approve/Reject** — Admin reviews staged questions with a side-by-side comparison modal showing the generated question vs. the matched existing question.
5. **Auto-Approve** — Optional setting to automatically approve unique questions.

### Configuration

```env
# Similarity thresholds (0.0 to 1.0)
SIMILARITY_THRESHOLD_HIGH_DUP=0.85    # Above this = likely duplicate
SIMILARITY_THRESHOLD_REVIEW=0.70      # Above this = needs review

# Embedding model
EMBEDDING_DEPLOYMENT_NAME=text-embedding-3-small
```

### Background Processing

- **Auto-embedding on upload** — When questions are imported via Excel/CSV, embeddings are computed in the background automatically.
- **Startup backfill** — On server start, a background thread finds any questions missing embeddings and generates them.
- **FAISS index persistence** — The vector index is saved to `data/faiss_index/` and reloaded on restart.

## API Documentation

Once the backend is running, visit:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
