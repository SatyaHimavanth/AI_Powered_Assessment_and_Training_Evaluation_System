"""Safe Postgres SQL runner for coding questions.

Only allows read-only SELECT/EXPLAIN/WITH/SHOW statements. Any DML/DDL
keywords (INSERT/UPDATE/DELETE/CREATE/ALTER/DROP/TRUNCATE/...) will be
rejected and not executed.

This module expects a `DEMO_DB_URL` environment variable containing a
Postgres connection URL.
"""

import os
import re
import psycopg2
from typing import Dict

# Timeout for SQL statements (milliseconds)
SQL_TIMEOUT_MS = 10_000


def _is_safe_query(query: str) -> bool:
    """Return True if the query is considered safe (read-only single statement).

    Rules:
    - Must start with SELECT/WITH/EXPLAIN/SHOW (case-insensitive)
    - Must not contain semicolons (to disallow multiple statements)
    - Must not contain DML/DDL keywords anywhere
    """
    if not query or not query.strip():
        return False

    def _strip_comments(s: str) -> str:
        # remove C-style multiline comments /* ... */
        s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
        # remove SQL single-line comments -- ... (to end of line)
        s = re.sub(r"--.*?(\r\n|\r|\n|$)", "\n", s)
        return s

    # remove comments first so leading comments don't block detection
    q = _strip_comments(query).strip()
    if not q:
        return False

    # allow a trailing semicolon but no other semicolons
    if q.endswith(";"):
        q = q[:-1].strip()
    if ";" in q:
        return False

    # Must start with a safe verb
    if not re.match(r"^(SELECT|WITH|EXPLAIN|SHOW)\b", q, re.I):
        return False

    # Disallow dangerous keywords
    danger = re.compile(r"\b(INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|TRUNCATE|MERGE|REPLACE|GRANT|REVOKE|COMMENT|CALL|COPY)\b", re.I)
    if danger.search(q):
        return False

    return True


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
            "error": "Query rejected: only single read-only SELECT/WITH/EXPLAIN/SHOW statements are allowed",
            "exit_code": -1,
        }

    db_url = os.environ.get("DEMO_DB_URL")
    if not db_url:
        return {
            "passed": False,
            "actual_output": "",
            "expected_output": (expected_output or "").strip(),
            "error": "DEMO_DB_URL not configured in environment",
            "exit_code": -1,
        }

    # Normalize query: remove comments, strip, and remove trailing semicolon
    def _strip_comments(s: str) -> str:
        s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
        s = re.sub(r"--.*?(\r\n|\r|\n|$)", "\n", s)
        return s

    q = _strip_comments(code or "").strip()
    if q.endswith(";"):
        q = q[:-1].strip()

    if not q:
        return {
            "passed": False,
            "actual_output": "",
            "expected_output": (expected_output or "").strip(),
            "error": "No SQL query provided after removing comments",
            "exit_code": -1,
        }

    try:
        conn = psycopg2.connect(db_url)
        conn.autocommit = True
        cur = conn.cursor()

        # set a statement timeout for safety
        try:
            cur.execute(f"SET statement_timeout = {SQL_TIMEOUT_MS}")
        except Exception:
            # ignore if setting timeout fails for any reason
            pass

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
            cur.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass
