"""Capture representative PostgreSQL plans; requires an explicitly disposable, seeded DB."""
import json
import os
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


QUERIES = {
    "candidate_attempt_history": "SELECT id FROM attempts WHERE user_id=:uid AND status='completed' ORDER BY started_at DESC LIMIT 50",
    "assessment_active_attempts": "SELECT id FROM attempts WHERE assessment_id=:aid AND status='in_progress'",
    "practice_history": "SELECT id FROM practice_tests WHERE user_id=:uid ORDER BY created_at DESC LIMIT 50",
    "generation_queue": "SELECT id FROM question_generation_batches WHERE status='pending' ORDER BY created_at LIMIT 20",
    "interview_user_history": "SELECT id FROM interview_sessions WHERE user_id=:uid AND status='paused' ORDER BY created_at DESC LIMIT 50",
}


def main() -> None:
    if os.getenv("BENCHMARK_DATABASE_DISPOSABLE") != "1":
        raise SystemExit("Refusing to run unless BENCHMARK_DATABASE_DISPOSABLE=1 is explicitly set")
    raw_url = os.getenv("DATABASE_URL")
    if not raw_url:
        raise SystemExit("DATABASE_URL is required")
    url = make_url(raw_url)
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg2")
    engine = create_engine(url)
    params = {
        "uid": os.environ.get("BENCHMARK_USER_ID", "00000000-0000-0000-0000-000000000001"),
        "aid": os.environ.get("BENCHMARK_ASSESSMENT_ID", "00000000-0000-0000-0000-000000000001"),
    }
    try:
        if engine.dialect.name != "postgresql":
            raise SystemExit("Representative plan benchmark requires PostgreSQL")
        with engine.connect() as conn:
            for label, sql in QUERIES.items():
                plan = conn.execute(text("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql), params).scalar_one()
                print(json.dumps({"query": label, "plan": plan}, default=str))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
