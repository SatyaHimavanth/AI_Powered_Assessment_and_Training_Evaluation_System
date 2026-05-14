# Docker Setup

## Prerequisites

- Docker & Docker Compose installed
- A `backend/.env` file with your configuration

## Environment File

Create `backend/.env`:

```env
# Database (used by both db and backend containers)
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=assessment_db
DATABASE_URL=postgresql://postgres:postgres@db:5432/assessment_db

# JWT
SECRET_KEY=your-secret-key

# Azure OpenAI
AZURE_OPENAI_API_KEY=your-key
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
CHAT_DEPLOYMENT_NAME=gpt-4
OPENAI_API_VERSION=2024-12-01-preview
```

---

## Option 1: Docker Compose (Recommended)

Starts PostgreSQL, backend, and frontend together:

```bash
# Build and start all services
docker compose up --build

# Run in background
docker compose up --build -d

# Stop all services
docker compose down

# Stop and remove volumes (wipes database)
docker compose down -v
```

**Access:**
- Frontend: http://localhost
- Backend API: http://localhost:8000
- API Docs: http://localhost:8000/docs

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
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=assessment_db \
  -p 5432:5432 \
  -v pgdata:/var/lib/postgresql/data \
  postgres:16-alpine
```

### 3. Build & Run Backend

```bash
# Build
docker build -t assessment-backend ./backend

# Run (update DATABASE_URL to point to the db container)
docker run -d \
  --name assessment-backend \
  --network assessment-net \
  --env-file ./backend/.env \
  -e DATABASE_URL=postgresql://postgres:postgres@assessment-db:5432/assessment_db \
  -p 8000:8000 \
  assessment-backend
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
docker stop assessment-frontend assessment-backend assessment-db
docker rm assessment-frontend assessment-backend assessment-db
docker network rm assessment-net
```

---

## Notes

- The frontend nginx config proxies `/api/*` requests to the backend container
- Database data persists in a Docker volume (`pgdata`)
- Default credentials created on first backend startup: `admin/admin123`
- For local development without Docker, see [README.md](README.md)
