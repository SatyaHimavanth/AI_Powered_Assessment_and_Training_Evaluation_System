"""Seed an empty explicitly disposable DB for repeatable index-plan measurements."""
import os
from time import perf_counter

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

USER_ID = "00000000-0000-0000-0000-000000000001"
ASSESSMENT_ID = "00000000-0000-0000-0000-000000000002"
TEMPLATE_ID = "00000000-0000-0000-0000-000000000003"
ACCESS_ID = "00000000-0000-0000-0000-000000000004"


def main() -> None:
    if os.getenv("BENCHMARK_DATABASE_DISPOSABLE") != "1":
        raise SystemExit("Refusing to seed unless BENCHMARK_DATABASE_DISPOSABLE=1 is set")
    url_value = os.getenv("DATABASE_URL")
    if not url_value:
        raise SystemExit("DATABASE_URL is required")
    row_count = int(os.getenv("BENCHMARK_ROWS_PER_WORKFLOW", "30000"))
    if row_count < 1000:
        raise SystemExit("Use at least 1000 rows per workflow for representative index selection")
    url = make_url(url_value)
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg2")
    engine = create_engine(url)
    try:
        if engine.dialect.name != "postgresql":
            raise SystemExit("Benchmark seeding requires PostgreSQL")
        with engine.begin() as conn:
            for table in (
                "users", "assessments", "interview_templates", "interview_access_requests",
                "attempts", "practice_tests", "question_generation_batches", "interview_sessions",
            ):
                count = conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
                if count:
                    raise SystemExit(f"Refusing to seed non-empty table {table} ({count} rows)")
            conn.execute(text("INSERT INTO users (id,username,email,contact_email,name,hashed_password,role) "
                              "VALUES (:id,'audit_benchmark','audit-benchmark@example.invalid',"
                              "'audit-benchmark-contact@example.invalid','Benchmark','unused','admin')"),
                         {"id": USER_ID})
            conn.execute(text("INSERT INTO assessments (id,title,duration,created_by) "
                              "VALUES (:id,'Benchmark assessment',30,:user_id)"),
                         {"id": ASSESSMENT_ID, "user_id": USER_ID})
            conn.execute(text("INSERT INTO interview_templates "
                              "(id,admin_id,title,role,experience_level,difficulty,focus_areas,duration_minutes,"
                              "question_count,default_questions_or_topics,evaluation_rubric,is_active,is_archived,"
                              "max_pauses_allowed,max_followup_depth) "
                              "VALUES (:id,:user_id,'Benchmark interview','Engineer','mid','medium','[]'::json,"
                              "30,1,'[]'::json,'{}'::json,true,false,3,2)"),
                         {"id": TEMPLATE_ID, "user_id": USER_ID})
            conn.execute(text("INSERT INTO interview_access_requests (id,user_id,template_id,status,request_type) "
                              "VALUES (:id,:user_id,:template_id,'approved','initial')"),
                         {"id": ACCESS_ID, "user_id": USER_ID, "template_id": TEMPLATE_ID})
            started = perf_counter()
            conn.execute(text(
                "INSERT INTO attempts(id,user_id,assessment_id,started_at,status,tab_violations) "
                "SELECT (substr(md5('attempt-'||n),1,8)||'-'||substr(md5('attempt-'||n),9,4)||'-'||"
                "substr(md5('attempt-'||n),13,4)||'-'||substr(md5('attempt-'||n),17,4)||'-'||"
                "substr(md5('attempt-'||n),21,12))::uuid,:uid,:aid,now()-n*interval '1 second','completed',0 "
                "FROM generate_series(1,:n) n"), {"uid": USER_ID, "aid": ASSESSMENT_ID, "n": row_count})
            conn.execute(text("INSERT INTO attempts(id,user_id,assessment_id,started_at,status,tab_violations) "
                              "VALUES ('00000000-0000-0000-0000-000000000099',:uid,:aid,now(),'in_progress',0)"),
                         {"uid": USER_ID, "aid": ASSESSMENT_ID})
            conn.execute(text(
                "INSERT INTO practice_tests(id,user_id,job_title,difficulty,question_count,status,created_at) "
                "SELECT (substr(md5('practice-'||n),1,8)||'-'||substr(md5('practice-'||n),9,4)||'-'||"
                "substr(md5('practice-'||n),13,4)||'-'||substr(md5('practice-'||n),17,4)||'-'||"
                "substr(md5('practice-'||n),21,12))::uuid,:uid,'Benchmark','easy',1,'completed',"
                "now()-n*interval '1 second' FROM generate_series(1,:n) n"), {"uid": USER_ID, "n": row_count})
            conn.execute(text(
                "INSERT INTO question_generation_batches(id,admin_id,status,created_at) "
                "SELECT (substr(md5('generation-'||n),1,8)||'-'||substr(md5('generation-'||n),9,4)||'-'||"
                "substr(md5('generation-'||n),13,4)||'-'||substr(md5('generation-'||n),17,4)||'-'||"
                "substr(md5('generation-'||n),21,12))::uuid,:uid,'pending',now()-n*interval '1 second' "
                "FROM generate_series(1,:n) n"), {"uid": USER_ID, "n": row_count})
            conn.execute(text(
                "INSERT INTO interview_sessions(id,user_id,template_id,access_request_id,status,attempt_number,"
                "pause_count,disconnect_count,max_pauses_allowed_snapshot,created_at) "
                "SELECT (substr(md5('interview-'||n),1,8)||'-'||substr(md5('interview-'||n),9,4)||'-'||"
                "substr(md5('interview-'||n),13,4)||'-'||substr(md5('interview-'||n),17,4)||'-'||"
                "substr(md5('interview-'||n),21,12))::uuid,:uid,:tid,:access,'paused',1,0,0,3,"
                "now()-n*interval '1 second' FROM generate_series(1,:n) n"),
                {"uid": USER_ID, "tid": TEMPLATE_ID, "access": ACCESS_ID, "n": row_count})
            for table in ("attempts", "practice_tests", "question_generation_batches", "interview_sessions"):
                conn.execute(text(f"ANALYZE {table}"))
        print(f"Seeded {row_count:,} rows in each workflow table in {perf_counter()-started:.2f}s (plus one active attempt).")
        print(f"BENCHMARK_USER_ID={USER_ID}\nBENCHMARK_ASSESSMENT_ID={ASSESSMENT_ID}")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
