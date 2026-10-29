FROM python:3.12-slim AS dependencies

WORKDIR /build
RUN pip install --no-cache-dir uv==0.13.6
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project --only-group testvenv

FROM python:3.12-slim

ENV VIRTUAL_ENV=/opt/testvenv \
    PATH="/opt/testvenv/bin:$PATH" \
    PYTHON_RUNNER_QUEUE_DIR=/run/python-jobs \
    PYTHONDONTWRITEBYTECODE=1

COPY --from=dependencies /build/.venv /opt/testvenv
COPY python_sandbox/runner.py /app/runner.py
WORKDIR /app

CMD ["/opt/testvenv/bin/python", "/app/runner.py"]
