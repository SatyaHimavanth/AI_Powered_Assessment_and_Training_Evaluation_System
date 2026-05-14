# PROJECT.md — Complete System Workflow

This document describes the end-to-end workflow of the AI-Powered Assessment & Training Evaluation System, covering every feature and process in detail.

---

## Table of Contents

1. [System Overview](#system-overview)
2. [User Roles](#user-roles)
3. [Authentication Flow](#authentication-flow)
4. [Admin Workflows](#admin-workflows)
5. [Question Bank Management](#question-bank-management)
6. [Assessment Lifecycle](#assessment-lifecycle)
7. [Evaluation Engine](#evaluation-engine)
8. [Batch Management](#batch-management)
9. [Practice Test System](#practice-test-system)
10. [Performance Analytics](#performance-analytics)
11. [Data Models](#data-models)
12. [API Reference](#api-reference)
13. [LLM Integration](#llm-integration)
14. [Environment Configuration](#environment-configuration)

---

## System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Frontend (React + Vite)                       │
│   Login/Register │ Admin Dashboard │ User Dashboard │ Practice Tests │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ REST API (JWT Auth)
┌──────────────────────────────┴──────────────────────────────────────┐
│                        Backend (FastAPI)                             │
│  Auth │ Admin │ Questions │ Assessments │ Batches │ Practice │ User  │
└───────┬──────────────────────┬──────────────────────────────────────┘
        │                      │
   ┌────┴────┐          ┌─────┴─────┐
   │PostgreSQL│          │Azure OpenAI│
   │(All Data)│          │(Eval + Gen)│
   └──────────┘          └───────────┘
```

The system supports two core workflows:
1. **Formal Assessments** — Admin creates structured tests, assigns to user batches, scores automatically
2. **Practice Tests** — Users request access, generate AI-powered tests based on their job profile

---

## User Roles

### Admin
- Approve/reject user registrations
- Manage users (activate, deactivate, edit)
- Upload and organize question banks
- Create and assign assessments
- Manage batches (create, upload users)
- View results and analytics
- Approve/reject practice access requests
- Monitor evaluation job health

### User (Student/Trainee)
- Register and wait for approval
- Take assigned assessments within time windows
- View results and topic-wise performance
- Request practice test access
- Create and take daily practice tests
- Export results as Excel

---

## Authentication Flow

```
┌──────────┐       ┌──────────┐       ┌──────────┐       ┌──────────┐
│  Register │──────▶│  Pending  │──────▶│  Approved │──────▶│   Login   │
│  (User)   │       │  (Admin)  │       │  (User)   │       │  (Tokens) │
└──────────┘       └──────────┘       └──────────┘       └──────────┘
```

### Registration
1. User submits: username, email, name, password, account (optional)
2. System validates: no duplicate username/email, no pending request
3. Creates `RegistrationRequest` with status=pending

### Admin Approval
1. Admin sees pending requests in "Registrations" tab
2. On **Approve**: Creates User record, sets request status=approved
3. On **Reject**: Sets status=rejected (user can retry after 30 days)

### Login
1. User submits username + password
2. System validates: user exists, password matches, account is active
3. Returns: access_token (30 min), refresh_token, user role
4. Frontend stores tokens in localStorage, routes to role-appropriate dashboard

### Token Refresh
- Access token expires after 30 minutes
- Frontend calls `/auth/refresh` with refresh_token
- New access_token issued without re-login

---

## Admin Workflows

### User Management
| Action | Description |
|--------|-------------|
| View Users | List all users with role, status, account, creation date |
| Toggle Active | Deactivate (block login) or reactivate a user |
| Edit Account | Update the account/organization field |
| Manage Batches | Assign/remove users from batches |

### Evaluation Monitoring
| Action | Description |
|--------|-------------|
| View Stalled | Jobs pending > 10 minutes |
| View Failed | Jobs that errored (with messages) |
| Retry Job | Requeue a failed evaluation |

---

## Question Bank Management

### Structure
```
Topic (e.g., "Python Basics")
└── Question
    ├── type: single_mcq | multi_mcq | text | coding
    ├── difficulty: easy | medium | hard
    ├── question_text: The question content
    ├── reference_answer: For LLM evaluation context
    └── Options (for MCQs)
        ├── option_text: "Option A text"
        └── is_correct: true/false
```

### Upload Process (Excel/CSV)
1. Admin uploads file to a specific topic
2. Required columns: `type`, `difficulty`, `question`
3. Optional columns: `option_a` through `option_d`, `correct_options` (e.g., "A|C"), `reference_answer`
4. System processes each row:
   - Validates non-empty question, valid type/difficulty
   - Creates Topic if new
   - For MCQs: creates Question + QuestionOption records
   - Skips duplicates (same question_text + topic)
5. Returns summary: imported count, skipped, errors

### Question Types

| Type | Options | Scoring | Evaluation |
|------|---------|---------|------------|
| single_mcq | 2-4 options, 1 correct | Exact match → 1.0 or 0.0 | Auto |
| multi_mcq | 2-4 options, 1+ correct | All-or-nothing (or partial with negative marking) | Auto |
| text | None | LLM-evaluated (0–1 scale) | Azure OpenAI |
| coding | None | LLM-evaluated (0–1 scale) | Azure OpenAI |

---

## Assessment Lifecycle

### Phase 1: Create Assessment (Admin)

```json
{
  "title": "Python Intermediate Assessment",
  "description": "OOP and functional programming",
  "duration": 60,
  "negative_marking": false,
  "topics": [
    { "topic_id": "uuid", "question_type": "single_mcq", "difficulty": "medium", "question_count": 10, "section_name": "Part A" },
    { "topic_id": "uuid", "question_type": "text", "difficulty": "hard", "question_count": 5, "section_name": "Part B" }
  ],
  "batch_ids": ["uuid1", "uuid2"],
  "start_time": "2026-05-01T09:00:00Z",
  "end_time": "2026-05-01T10:00:00Z"
}
```

**Process:**
1. Validate all referenced batches and topics exist
2. For each topic config: randomly select questions matching (topic, type, difficulty)
3. Create assessment with selected questions and section metadata
4. Create assignments linking assessment to batches

### Phase 2: Assign to Users
- Assessments are assigned to **batches**, not individual users
- All users in assigned batches can access the assessment
- Time window (start_time/end_time) controls availability

### Phase 3: Take Assessment (User)

```
User opens assessment
    ↓
POST /user/assessments/start/{id}
    ↓ Validates: user in batch, within time window, no prior completion
Creates Attempt (status=in_progress)
    ↓
Returns questions (shuffled per section)
    ↓
User answers questions
    ↓
POST /user/assessments/submit/{attempt_id}
    ↓
Auto-scores MCQs, queues LLM eval for text/coding
    ↓
Attempt marked as completed with score
```

**Resumption Logic:**
- In-progress attempts < 30 min old can be resumed
- Attempts > 30 min old are marked as "missed"
- A new attempt is created for the user

### Phase 4: Evaluate

| Question Type | Method | Timing |
|---------------|--------|--------|
| single_mcq | Exact option match | Instant |
| multi_mcq | Set comparison (with optional negative marking) | Instant |
| text | LLM evaluation against reference_answer | Async (seconds) |
| coding | LLM evaluation against reference_answer | Async (seconds) |

### Phase 5: Results

**Scoring:**
- Overall: (total_earned / total_questions) × 100
- Topic-wise: Average score per topic
- TopicScore records stored for analytics

**User sees:**
- Total score percentage
- Question-by-question breakdown (their answer, correct answer, feedback)
- Topic-wise performance chart
- Export option (Excel download)

---

## Evaluation Engine

### Architecture
```
Assessment Submitted
    ↓
MCQ answers scored immediately (auto)
    ↓
Text/Coding answers → EvaluationJob (status=pending)
    ↓
Background Consumer Thread (polls every 5s)
    ↓
Picks pending job → status=in_progress
    ↓
Calls Azure OpenAI with question + reference + user answer
    ↓
Parses JSON response: {score: 0-1, feedback: "..."}
    ↓
Updates Answer record → job status=completed
    ↓
Recalculates attempt total score
```

### Error Handling
- **Retry Logic**: Up to 3 retries on LLM failure
- **Stalled Detection**: Jobs pending > 10 minutes flagged
- **Admin Controls**: View failed/stalled jobs, manual retry

### Multi-MCQ Scoring (with negative marking)

```
Without negative marking:
  All correct selected AND no wrong → 1.0, else → 0.0

With negative marking:
  score = (correct_selected / total_correct) - (wrong_selected / total_wrong_options)
  Final score = max(0, score)
```

---

## Batch Management

### Purpose
Batches group users for assessment assignment. A user can belong to multiple batches.

### Workflows

**Create Batch:**
- Admin specifies name (unique) and description
- Status: upcoming | current | completed

**Upload Users to Batch (Excel/CSV):**
- Columns: name, username, email, password, account (optional)
- For each row:
  - If user doesn't exist → Create user + add to batch
  - If user exists but not in batch → Add to batch
  - If user already in batch → Skip
- Returns counts: created, added, skipped

**Assign Assessments:**
- When creating an assessment, admin selects target batches
- All users in those batches gain access to the assessment

---

## Practice Test System

### Complete Flow

```
┌───────────┐     ┌───────────┐     ┌───────────┐     ┌───────────┐     ┌───────────┐
│  Request   │────▶│  Admin     │────▶│  Create    │────▶│  Take      │────▶│  Results   │
│  Access    │     │  Approves  │     │  Test (AI) │     │  Test      │     │           │
└───────────┘     └───────────┘     └───────────┘     └───────────┘     └───────────┘
```

### Step 1: Request Access
- User fills form: reason for access + requested duration (1–30 days)
- Creates PracticeAccessRequest (status=pending)
- Admin reviews in "Practice Access" tab

### Step 2: Admin Approves/Rejects
- Admin sees: user name, reason, requested days
- On **Approve**: Sets days granted (clamped 1–30), calculates expires_at
- On **Reject**: Sets status=rejected
- User can re-request after rejection

### Step 3: Create Practice Test
User provides:
- Job title (required)
- Difficulty: easy | medium | hard
- Topics (comma-separated)
- Job description (optional)
- Resume file (PDF/DOCX/TXT, max 5 MB, optional)
- Question count (5–50, default 25)

**Limit:** One practice test per day per user

**Background Generation:**
1. PracticeTest created with status=generating
2. Daemon thread invokes Azure OpenAI with GENERATION_PROMPT
3. LLM generates mix: ~40% single_mcq, ~30% multi_mcq, ~30% text
4. Questions parsed from JSON response and stored
5. Status updated: generating → ready (or failed with error)

**Frontend polls every 3 seconds** until status changes from "generating"

### Step 4: Take Test
- No time limit
- User answers all questions and submits
- Practice tests can be started and submitted at any time while access is valid

### Step 5: Scoring
| Type | Logic |
|------|-------|
| single_mcq | Exact match with correct_answer → 1.0 or 0.0 |
| multi_mcq | Exact match with correct_answer → 1.0 or 0.0 |
| text | Non-empty answer → 0.5, empty → 0.0 |

### Step 6: Results & History
- View detailed results per test
- History of all past practice tests (score, date, topic)
- Export individual test results as Excel

---

## Performance Analytics

### User Performance Report
Available for both users (self) and admins (any user):

```json
{
  "user_name": "John Doe",
  "total_assessments": 5,
  "completed_assessments": 4,
  "average_score": 78.3,
  "topic_performance": [
    { "topic_name": "OOP", "average_percentage": 85.5, "assessment_count": 3 },
    { "topic_name": "Databases", "average_percentage": 62.3, "assessment_count": 2 }
  ],
  "improvement_areas": [
    "Focus on Databases (Current: 62.3%)",
    "Strengthen Networking (Current: 55.0%)"
  ]
}
```

### Topic-wise Tracking
- Each completed attempt generates TopicScore records
- Aggregated across assessments for trend analysis
- Identifies weakest topics for targeted improvement

---

## Data Models

### Core Entities

```
User
├── id (UUID, PK)
├── username (unique)
├── email (unique)
├── name
├── hashed_password
├── role (admin | user)
├── is_active
├── account
└── created_at

RegistrationRequest
├── id (UUID, PK)
├── username, email, name, hashed_password, account
├── status (pending | approved | rejected)
└── created_at

Batch
├── id (UUID, PK)
├── name (unique)
├── description
└── status (upcoming | current | completed)

BatchUser (M:M join)
├── batch_id → Batch
└── user_id → User
```

### Assessment Entities

```
Topic
├── id (UUID, PK)
├── name (unique)
└── description

Question
├── id (UUID, PK)
├── topic_id → Topic
├── question_text
├── type (single_mcq | multi_mcq | text | coding)
├── difficulty (easy | medium | hard)
└── reference_answer

QuestionOption
├── id (UUID, PK)
├── question_id → Question
├── option_text
└── is_correct

Assessment
├── id (UUID, PK)
├── title, description
├── duration (minutes)
├── negative_marking (bool)
├── start_time, end_time
└── created_by → User

AssessmentQuestion (links selected Qs to assessment)
├── assessment_id → Assessment
├── question_id → Question
└── position

Assignment (links assessment to batch)
├── assessment_id → Assessment
└── batch_id → Batch

Attempt
├── id (UUID, PK)
├── user_id → User
├── assessment_id → Assessment
├── status (in_progress | completed | missed)
├── score
├── started_at, submitted_at
└── tab_violations

Answer
├── id (UUID, PK)
├── attempt_id → Attempt
├── question_id → Question
├── answer_text
├── selected_options (JSON)
├── score (0–1)
└── feedback

TopicScore
├── attempt_id → Attempt
├── topic_id → Topic
└── percentage

EvaluationJob
├── id (UUID, PK)
├── attempt_id → Attempt
├── status (pending | in_progress | completed | failed)
├── retries
└── error_message
```

### Practice Entities

```
PracticeAccessRequest
├── id (UUID, PK)
├── user_id → User
├── status (pending | approved | rejected)
├── reason
├── requested_days
├── days_granted
├── requested_at
├── approved_at
└── expires_at

PracticeTest
├── id (UUID, PK)
├── user_id → User
├── job_title, topics, difficulty
├── job_description, resume_text
├── question_count
├── status (generating | ready | in_progress | completed | failed)
├── score
├── error_message
└── created_at, submitted_at

PracticeQuestion
├── id (UUID, PK)
├── practice_test_id → PracticeTest
├── position, type, question
├── options (JSON)
├── correct_answer, topic

PracticeAnswer
├── id (UUID, PK)
├── practice_test_id → PracticeTest
├── question_id → PracticeQuestion
├── answer_text
├── selected_options (JSON)
├── score, feedback
```

---

## API Reference

### Authentication (Public)
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/auth/register` | Submit registration request |
| POST | `/auth/login` | Login, returns tokens |
| POST | `/auth/refresh` | Refresh access token |
| GET | `/auth/me` | Get current user info |

### Admin — Registrations
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/admin/pending-registrations` | List pending requests |
| POST | `/admin/approve/{id}` | Approve registration |
| POST | `/admin/reject/{id}` | Reject registration |

### Admin — Users
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/admin/users` | List all users |
| POST | `/admin/users/{id}/toggle-active` | Activate/deactivate |
| PATCH | `/admin/users/{id}` | Update account field |
| GET | `/admin/users/{id}/batches` | Get user's batches |
| PUT | `/admin/users/{id}/batches` | Replace batch membership |

### Admin — Practice Access
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/admin/practice-access-requests` | List pending requests |
| POST | `/admin/practice-access-requests/{id}/approve` | Approve (body: {days}) |
| POST | `/admin/practice-access-requests/{id}/reject` | Reject request |

### Admin — Evaluations
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/admin/evaluations/stalled` | Jobs pending > 10 min |
| GET | `/admin/evaluations/pending` | All pending jobs |
| GET | `/admin/evaluations/failed` | Failed jobs |
| POST | `/admin/evaluations/{id}/retry` | Retry failed job |

### Admin — Analytics
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/admin/user/{id}/performance` | User performance report |
| GET | `/admin/attempt/{id}/topics` | Topic scores for attempt |
| POST | `/admin/reset-attempt/{id}` | Reset user attempt |

### Batches
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/batches/` | List all batches |
| POST | `/batches/create` | Create batch |
| POST | `/batches/upload` | Upload users to batch (file) |
| DELETE | `/batches/{id}` | Delete batch |
| POST | `/batches/{id}/users` | Add existing users |

### Questions
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/questions/upload` | Upload questions (file) |
| GET | `/questions/topics` | List topics |
| GET | `/questions/` | List questions (with filters) |

### Assessments
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/assessments/create` | Create assessment |
| GET | `/assessments/` | List all |
| GET | `/assessments/{id}` | Get details |
| DELETE | `/assessments/{id}` | Delete |
| PATCH | `/assessments/{id}` | Update time window |
| POST | `/assessments/available-count` | Check available Q count |

### User — Assessments
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/user/assessments/` | List assigned assessments |
| POST | `/user/assessments/start/{id}` | Start attempt |
| POST | `/user/assessments/submit/{attempt_id}` | Submit answers |
| POST | `/user/assessments/abort/{attempt_id}` | Abort (tab violation) |
| GET | `/user/assessments/{id}/results` | Get results |
| GET | `/user/assessments/{id}/export` | Export as Excel |
| GET | `/user/assessments/me/performance` | Self performance report |

### User — Practice Tests
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/practice/access` | Check access status |
| POST | `/practice/request-access` | Request access (body: reason, days) |
| POST | `/practice/create` | Create test (multipart form) |
| GET | `/practice/today` | Get today's test |
| GET | `/practice/history` | Past tests list |
| GET | `/practice/{id}` | Get test with questions |
| POST | `/practice/{id}/start` | Mark as in_progress |
| POST | `/practice/{id}/submit` | Submit and score |
| GET | `/practice/{id}/result` | Get detailed results |
| GET | `/practice/{id}/export` | Export as Excel |

---

## LLM Integration

### 1. Assessment Evaluation (Text/Coding Questions)

**Trigger:** User submits assessment containing text or coding questions

**Prompt:**
```
You are grading a {question_type} assessment answer.
Question: {question}
Reference answer/rubric: {reference_answer}
User answer: {user_answer}

Return strict JSON: {"score": 0-1, "feedback": "concise string"}
```

**Processing:** Background job consumer → Azure OpenAI → Parse JSON → Update answer score

### 2. Practice Test Generation

**Trigger:** User creates a practice test

**Prompt:**
```
Generate exactly {question_count} questions for:
Job Title: {job_title}
Topics: {topics}
Difficulty: {difficulty}
Job Description: {job_description}
Resume: {resume_text}

Mix: ~40% single_mcq, ~30% multi_mcq, ~30% text
Return ONLY valid JSON array with: position, type, question, options, correct_answer, topic
```

**Processing:** Background daemon thread → Azure OpenAI → Parse JSON → Store PracticeQuestion records

### Error Recovery
- JSON extraction handles markdown code blocks (```json ... ```)
- Failed generation: PracticeTest.status=failed with error_message
- Failed evaluation: EvaluationJob retries up to 3 times

---

## Environment Configuration

### Required `.env` Variables (backend/)

```env
# Database
DATABASE_URL=postgresql://postgres:password@localhost:5432/assessment_db

# JWT
SECRET_KEY=your-random-secret-key

# Azure OpenAI
AZURE_OPENAI_API_KEY=your-api-key
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
CHAT_DEPLOYMENT_NAME=gpt-4
OPENAI_API_VERSION=2024-12-01-preview

# Optional: Embeddings (if used)
EMBEDDING_DEPLOYMENT_NAME=text-embedding-ada-002
```

### Key Configuration Constants (in code)

| Constant | Value | Location |
|----------|-------|----------|
| Access token expiry | 30 minutes | core/auth.py |
| Registration re-request cooldown | 30 days | main.py |
| Practice test daily limit | 1 per user | routers_practice.py |
| Practice access max duration | 30 days | routers_admin.py |
| Evaluation poll interval | 5 seconds | evaluation_service.py |
| Stalled job threshold | 10 minutes | routers_admin.py |
| Max retry count | 3 | evaluation_service.py |
| Resume max size | 5 MB | routers_practice.py |
| Attempt resumption window | 30 minutes | routers_user_assessments.py |

---

## Frontend Pages

### Admin Dashboard Tabs
| Tab | Purpose |
|-----|---------|
| Dashboard | Overview stats (users, pending, topics, batches) |
| Registrations | Approve/reject new user signups |
| Users | Manage users, toggle active, edit, batch membership |
| Batches | Create batches, upload users, manage membership |
| Assessments | Create assessments, assign to batches |
| Questions | Upload question banks, browse by topic |
| Results | View user attempts, scores, export |
| Practice Access | Approve/reject practice test access requests |

### User Dashboard Tabs
| Tab | Purpose |
|-----|---------|
| Dashboard | Overview of assigned and completed assessments |
| Exam | Take active assessments |
| Performance | View scores, topic-wise analysis |
| Practice | Request access, create tests, take tests, view history |
