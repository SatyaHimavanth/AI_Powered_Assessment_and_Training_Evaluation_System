FROM python:3.12-slim

WORKDIR /app

# Install system dependencies for psycopg2
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libc6-dev libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Install from the committed lockfile so container builds use the same
# dependency versions as local development.
RUN pip install --no-cache-dir uv==0.13.6
COPY . .
RUN uv sync --locked --no-dev --extra local

EXPOSE 8000

ENV RUN_WORKER_IN_API=true PYTHON_RUNNER_MODE=local

CMD ["sh", "-c", "exec /app/.venv/bin/uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
