import pytest

from core.code_runner import execute_python_code, ensure_execution_available, run_test_case
from core.sql_runner import run_sql_test_case


def test_python_runner_fails_closed_when_isolated_job_service_is_missing(monkeypatch):
    monkeypatch.setenv("PYTHON_RUNNER_MODE", "queue")
    monkeypatch.delenv("PYTHON_RUNNER_QUEUE_DIR", raising=False)
    result = execute_python_code("print('candidate code')")

    assert result.exit_code == -1
    assert "execution unavailable" in result.stderr


def test_python_static_filter_runs_before_a_job_is_queued():
    result = execute_python_code("import os\nprint('candidate code')")

    assert result.exit_code == -1
    assert "static safety checks" in result.stderr


def test_python_test_case_reports_missing_sandbox_as_execution_unavailable(monkeypatch):
    monkeypatch.setenv("PYTHON_RUNNER_MODE", "queue")
    monkeypatch.delenv("PYTHON_RUNNER_QUEUE_DIR", raising=False)
    result = run_test_case("print('should not run')", "", "should not run")

    assert result["passed"] is False
    assert "execution unavailable" in result["error"]


def test_sql_runner_fails_closed_without_dedicated_read_only_database(monkeypatch):
    monkeypatch.delenv("SQL_SANDBOX_DATABASE_URL", raising=False)
    result = run_sql_test_case("SELECT pg_read_file('/etc/passwd')", "", "")

    assert result["passed"] is False
    assert "SQL execution unavailable" in result["error"]


def test_sql_policy_allows_one_select_and_with_query_only():
    from core.sql_runner import _strip_comments_and_check_single_statement

    assert _strip_comments_and_check_single_statement("-- comment\nSELECT 1;") == "SELECT 1"
    assert "WITH ranked AS" in _strip_comments_and_check_single_statement(
        "WITH ranked AS (SELECT 1 AS n) SELECT n FROM ranked"
    )


@pytest.mark.parametrize("query", [
    "DELETE FROM employees",
    "SELECT 1; DELETE FROM employees",
    "SELECT 1; SELECT 2",
    "SELECT 1 /* unterminated",
])
def test_sql_policy_rejects_mutations_multiple_statements_and_malformed_comments(query):
    from core.sql_runner import _strip_comments_and_check_single_statement

    with pytest.raises(ValueError):
        _strip_comments_and_check_single_statement(query)


def test_sql_restricted_role_rejects_superuser_before_running_candidate_query():
    from core.sql_runner import SQLSandboxUnavailable, _verify_restricted_role

    class Connection:
        def exec_driver_sql(self, statement, *_params):
            assert "FROM pg_roles" in statement
            return self

        def one(self):
            return (True, False, False, False, False, False)

    with pytest.raises(SQLSandboxUnavailable, match="elevated"):
        _verify_restricted_role(Connection(), "demo", ("employees",))


@pytest.mark.parametrize(
    "privileges",
    [(True, False), (False, True)],
    ids=["database-create", "schema-create"],
)
def test_sql_restricted_role_rejects_database_or_schema_creation(privileges):
    from core.sql_runner import SQLSandboxUnavailable, _verify_restricted_role

    class Result:
        def __init__(self, rows=(), value=None):
            self.rows = rows
            self.value = value

        def one(self):
            return self.value

        def first(self):
            return self.value

        def all(self):
            return self.rows

    class Connection:
        def exec_driver_sql(self, statement, *_params):
            if "FROM pg_roles" in statement:
                return Result(value=(False, False, False, False, False, False))
            if "WITH RECURSIVE memberships" in statement:
                return Result(value=None)
            if "AND n.nspname NOT IN" in statement:
                return Result(rows=[("demo", "employees")])
            if "has_database_privilege" in statement:
                return Result(value=privileges)
            if "bool_or(" in statement:
                return Result(value=(False,))
            if "SELECT c.relname FROM pg_class" in statement:
                return Result(rows=[("employees",)])
            raise AssertionError("Unexpected SQL privilege check")

    with pytest.raises(SQLSandboxUnavailable, match="write or schema-creation"):
        _verify_restricted_role(Connection(), "demo", ("employees",))


def test_sql_restricted_role_accepts_only_the_configured_readable_table():
    from core.sql_runner import _verify_restricted_role

    class Result:
        def __init__(self, value=None, rows=()):
            self.value = value
            self.rows = rows

        def one(self):
            return self.value

        def first(self):
            return self.value

        def all(self):
            return self.rows

    class Connection:
        def exec_driver_sql(self, statement, *_params):
            if "FROM pg_roles" in statement:
                return Result(value=(False, False, False, False, False, False))
            if "WITH RECURSIVE memberships" in statement:
                return Result(value=None)
            if "AND n.nspname NOT IN" in statement:
                return Result(rows=[("demo", "employees")])
            if "has_database_privilege" in statement:
                return Result(value=(False, False))
            if "bool_or(" in statement:
                return Result(value=(False,))
            if "SELECT c.relname FROM pg_class" in statement:
                return Result(rows=[("employees",)])
            raise AssertionError("Unexpected SQL privilege check")

    _verify_restricted_role(Connection(), "demo", ("employees",))


def test_coding_evaluation_does_not_record_disabled_runner_as_zero_score():
    with pytest.raises(RuntimeError, match="Python runner"):
        ensure_execution_available(
            {
                "passed": False,
                "error": "Python execution unavailable: runner is not configured",
            }
        )
