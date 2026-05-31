"""Safe Postgres SQL runner for coding questions.

SQL exercises run against demo tables in the main assessment database. The
runner sets the search path to the demo schema and rejects app table/schema
access before executing a read-only query.
"""

import os
import re
import psycopg2
from typing import Dict

# Timeout for SQL statements (milliseconds)
SQL_TIMEOUT_MS = 10_000
SQL_SANDBOX_SCHEMA = os.getenv("SQL_SANDBOX_SCHEMA", "demo")
SQL_SANDBOX_ALLOWED_TABLES = {
    item.strip().lower()
    for item in os.getenv("SQL_SANDBOX_ALLOWED_TABLES", "employees,departments").split(",")
    if item.strip()
}
FORBIDDEN_SCHEMAS = {"public", "pg_catalog", "information_schema", "pg_toast"}
FORBIDDEN_CATALOG_TABLES = {
    "pg_authid",
    "pg_class",
    "pg_database",
    "pg_namespace",
    "pg_roles",
    "pg_shadow",
    "pg_stat_activity",
    "pg_tables",
    "pg_user",
    "pg_views",
}


def _app_table_names() -> set[str]:
    try:
        from db.models import Base
        return {table.name.lower() for table in Base.metadata.sorted_tables}
    except Exception:
        return {
            "answers",
            "assessments",
            "attempts",
            "batches",
            "batch_users",
            "questions",
            "question_options",
            "registration_requests",
            "test_cases",
            "topics",
            "users",
        }


APP_TABLES = _app_table_names()


def _validate_identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value or ""):
        raise ValueError(f"Invalid SQL identifier: {value!r}")
    return value


def _strip_comments(s: str) -> str:
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    return re.sub(r"--.*?(\r\n|\r|\n|$)", "\n", s)


def _normalized_query(query: str) -> str:
    q = _strip_comments(query).strip()
    if q.endswith(";"):
        q = q[:-1].strip()
    return q


def _uses_only_demo_objects(query: str) -> bool:
    q = query.lower()

    if re.match(r"^show\b", q, re.I):
        return True

    schema_ref = re.compile(r"\b([a-z_][a-z0-9_]*)\s*\.", re.I)
    for match in schema_ref.finditer(q):
        if match.group(1).lower() in FORBIDDEN_SCHEMAS:
            return False

    identifiers = {token.lower() for token in re.findall(r'"?([a-z_][a-z0-9_]*)"?', q, flags=re.I)}
    if identifiers & APP_TABLES:
        return False
    if identifiers & FORBIDDEN_CATALOG_TABLES:
        return False

    table_refs = re.findall(
        r"\b(?:from|join)\s+((?:\"?[a-z_][a-z0-9_]*\"?\s*\.\s*)?\"?[a-z_][a-z0-9_]*\"?)",
        q,
        flags=re.I,
    )
    for ref in table_refs:
        parts = [p.strip().strip('"').lower() for p in ref.split(".")]
        table_name = parts[-1]
        schema_name = parts[-2] if len(parts) > 1 else SQL_SANDBOX_SCHEMA.lower()
        if schema_name != SQL_SANDBOX_SCHEMA.lower():
            return False
        if table_name not in SQL_SANDBOX_ALLOWED_TABLES:
            return False

    return True


def _is_safe_query(query: str) -> bool:
    """Return True if the query is considered safe (read-only single statement).

    Rules:
    - Must start with SELECT/WITH/EXPLAIN/SHOW (case-insensitive)
    - Must not contain semicolons (to disallow multiple statements)
    - Must not contain DML/DDL keywords anywhere
    """
    if not query or not query.strip():
        return False

    # remove comments first so leading comments don't block detection
    q = _normalized_query(query)
    if not q:
        return False

    # allow a trailing semicolon but no other semicolons
    if ";" in q:
        return False

    # Must start with a safe verb
    if not re.match(r"^(SELECT|WITH|EXPLAIN|SHOW)\b", q, re.I):
        return False

    # Disallow dangerous keywords
    danger = re.compile(r"\b(INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|TRUNCATE|MERGE|REPLACE|GRANT|REVOKE|COMMENT|CALL|COPY)\b", re.I)
    if danger.search(q):
        return False

    return _uses_only_demo_objects(q)


def run_sql_test_case(code: str, input_data: str, expected_output: str) -> Dict:
    """Execute a single SQL test case against the demo DB.

    Returns a dict compatible with `core.code_runner.run_test_case`:
    { passed, actual_output, expected_output, error, exit_code }
    """
    if not code or not code.strip():
        return {
            "passed": False,
            "actual_output": "",
            "expected_output": (expected_output or "").strip(),
            "error": "No SQL query provided",
            "exit_code": -1,
        }

    if not _is_safe_query(code):
        return {
            "passed": False,
            "actual_output": "",
            "expected_output": (expected_output or "").strip(),
            "error": "Query rejected: only single read-only queries against demo tables are allowed",
            "exit_code": -1,
        }

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        return {
            "passed": False,
            "actual_output": "",
            "expected_output": (expected_output or "").strip(),
            "error": "DATABASE_URL not configured in environment",
            "exit_code": -1,
        }

    # Normalize query: remove comments, strip, and remove trailing semicolon
    q = _normalized_query(code or "")

    if not q:
        return {
            "passed": False,
            "actual_output": "",
            "expected_output": (expected_output or "").strip(),
            "error": "No SQL query provided after removing comments",
            "exit_code": -1,
        }

    conn = None
    cur = None
    try:
        conn = psycopg2.connect(db_url)
        conn.autocommit = False
        cur = conn.cursor()

        schema = _validate_identifier(SQL_SANDBOX_SCHEMA)
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute(f"SET LOCAL statement_timeout = {SQL_TIMEOUT_MS}")
        cur.execute(f"SET LOCAL search_path TO {schema}, pg_temp")

        cur.execute(q)
        rows = cur.fetchall()

        # Format rows as CSV-like lines
        formatted_rows = []
        for row in rows:
            formatted_rows.append(",".join(["" if v is None else str(v) for v in row]))
        actual = "\n".join(formatted_rows).strip()

        expected = (expected_output or "").strip()

        passed = actual == expected

        return {
            "passed": passed,
            "actual_output": actual,
            "expected_output": expected,
            "error": None,
            "exit_code": 0,
        }

    except Exception as e:
        return {
            "passed": False,
            "actual_output": "",
            "expected_output": (expected_output or "").strip(),
            "error": str(e)[:1000],
            "exit_code": -1,
        }
    finally:
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass
