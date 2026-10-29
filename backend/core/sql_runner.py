"""Read-only SQL test execution using a separately permissioned database role."""

from functools import lru_cache
import os
import re
from typing import Dict

from sqlalchemy import create_engine

MAX_QUERY_BYTES = 20_000
MAX_RESULT_ROWS = 1_000
MAX_RESULT_CHARS = 10_000
IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class SQLSandboxUnavailable(RuntimeError):
    pass


def _strip_comments_and_check_single_statement(query: str) -> str:
    """Strip SQL comments and reject multiple statements outside quoted text."""
    output: list[str] = []
    i = 0
    quote: str | None = None
    dollar_quote: str | None = None
    line_comment = False
    block_depth = 0
    statements = 0
    current_has_content = False

    while i < len(query):
        char = query[i]
        next_two = query[i:i + 2]
        if line_comment:
            if char == "\n":
                line_comment = False
                output.append("\n")
            i += 1
            continue
        if block_depth:
            if next_two == "/*":
                block_depth += 1
                i += 2
            elif next_two == "*/":
                block_depth -= 1
                i += 2
            else:
                i += 1
            continue
        if dollar_quote:
            if query.startswith(dollar_quote, i):
                output.append(dollar_quote)
                i += len(dollar_quote)
                dollar_quote = None
            else:
                output.append(char)
                i += 1
            continue
        if quote:
            output.append(char)
            if char == quote:
                if i + 1 < len(query) and query[i + 1] == quote:
                    output.append(query[i + 1])
                    i += 2
                    continue
                quote = None
            elif char == "\\" and quote == "'" and i + 1 < len(query):
                output.append(query[i + 1])
                i += 2
                continue
            i += 1
            continue
        if next_two == "--":
            output.append(" ")
            line_comment = True
            i += 2
            continue
        if next_two == "/*":
            output.append(" ")
            block_depth = 1
            i += 2
            continue
        if char in ("'", '"'):
            quote = char
            output.append(char)
            current_has_content = True
            i += 1
            continue
        if char == "$":
            match = re.match(r"\$[A-Za-z_0-9]*\$", query[i:])
            if match:
                dollar_quote = match.group(0)
                output.append(dollar_quote)
                current_has_content = True
                i += len(dollar_quote)
                continue
        if char == ";":
            if current_has_content:
                statements += 1
                current_has_content = False
            output.append(" ")
            i += 1
            continue
        output.append(char)
        if not char.isspace():
            current_has_content = True
        i += 1

    if quote or dollar_quote or block_depth:
        raise ValueError("SQL contains an unterminated quote or comment")
    if current_has_content:
        statements += 1
    if statements != 1:
        raise ValueError("Submit exactly one SQL query")
    normalized = "".join(output).strip()
    if not re.match(r"^(SELECT|WITH)\b", normalized, flags=re.IGNORECASE):
        raise ValueError("Only SELECT queries are allowed")
    return normalized


def _settings() -> tuple[str, str, tuple[str, ...], int]:
    database_url = os.environ.get("SQL_SANDBOX_DATABASE_URL", "").strip()
    if not database_url:
        raise SQLSandboxUnavailable("SQL_SANDBOX_DATABASE_URL is not configured")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg2://")):
        raise SQLSandboxUnavailable("SQL sandbox requires a PostgreSQL connection URL")
    schema = os.environ.get("SQL_SANDBOX_SCHEMA", "demo").strip()
    if not IDENTIFIER_RE.fullmatch(schema):
        raise SQLSandboxUnavailable("SQL_SANDBOX_SCHEMA must be a simple identifier")
    tables = tuple(
        item.strip()
        for item in os.environ.get("SQL_SANDBOX_ALLOWED_TABLES", "").split(",")
        if item.strip()
    )
    if not tables or any(not IDENTIFIER_RE.fullmatch(table) for table in tables):
        raise SQLSandboxUnavailable("SQL_SANDBOX_ALLOWED_TABLES must list allowed identifiers")
    try:
        timeout_ms = int(os.environ.get("SQL_SANDBOX_QUERY_TIMEOUT_MS", "3000"))
    except ValueError as exc:
        raise SQLSandboxUnavailable("SQL sandbox timeout must be an integer") from exc
    if not 100 <= timeout_ms <= 10_000:
        raise SQLSandboxUnavailable("SQL sandbox timeout must be between 100 and 10000 ms")
    return database_url, schema, tables, timeout_ms


@lru_cache(maxsize=4)
def _engine_for(database_url: str):
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return create_engine(database_url, pool_size=1, max_overflow=0, pool_pre_ping=True)


def _verify_restricted_role(connection, schema: str, allowed_tables: tuple[str, ...]) -> None:
    role = connection.exec_driver_sql(
        "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls, rolinherit "
        "FROM pg_roles WHERE rolname = current_user"
    ).one()
    if any(bool(value) for value in role[:5]) or bool(role[5]):
        raise SQLSandboxUnavailable("SQL sandbox role has elevated PostgreSQL privileges")
    memberships = connection.exec_driver_sql(
        "WITH RECURSIVE memberships(roleid) AS ("
        " SELECT m.roleid FROM pg_auth_members m "
        " JOIN pg_roles u ON u.oid = m.member WHERE u.rolname = current_user"
        " UNION SELECT m.roleid FROM pg_auth_members m "
        " JOIN memberships x ON x.roleid = m.member) "
        "SELECT 1 FROM memberships LIMIT 1"
    ).first()
    if memberships:
        raise SQLSandboxUnavailable("SQL sandbox role must not inherit or switch to other roles")
    unsafe_relations = connection.exec_driver_sql(
        "SELECT n.nspname, c.relname "
        "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE c.relkind IN ('r','p','v','m','f') "
        "AND n.nspname NOT IN ('pg_catalog','information_schema','pg_toast') "
        "AND has_table_privilege(current_user, c.oid, 'SELECT') "
    ).all()
    unexpected = [
        (namespace, relation)
        for namespace, relation in unsafe_relations
        if namespace != schema or relation not in allowed_tables
    ]
    if unexpected:
        raise SQLSandboxUnavailable(
            "SQL sandbox role has SELECT access outside its configured schema/table allowlist"
        )
    unsafe_database_privileges = connection.exec_driver_sql(
        "SELECT has_database_privilege(current_user, current_database(), 'CREATE'), "
        "EXISTS (SELECT 1 FROM pg_namespace n "
        "WHERE has_schema_privilege(current_user, n.oid, 'CREATE'))"
    ).one()
    unsafe_table_privileges = connection.exec_driver_sql(
        "SELECT bool_or(has_table_privilege(current_user, c.oid, 'INSERT') "
        "OR has_table_privilege(current_user, c.oid, 'UPDATE') "
        "OR has_table_privilege(current_user, c.oid, 'DELETE') "
        "OR has_table_privilege(current_user, c.oid, 'TRUNCATE') "
        "OR has_table_privilege(current_user, c.oid, 'REFERENCES') "
        "OR has_table_privilege(current_user, c.oid, 'TRIGGER')) "
        "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = %s AND c.relname = ANY(%s) "
        "AND c.relkind IN ('r','p','v','m','f')",
        (schema, list(allowed_tables)),
    ).one()
    if any(
        bool(value)
        for value in tuple(unsafe_database_privileges) + tuple(unsafe_table_privileges)
    ):
        raise SQLSandboxUnavailable("SQL sandbox role has write or schema-creation privileges")
    available = {
        row[0]
        for row in connection.exec_driver_sql(
            "SELECT c.relname FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = %s AND c.relname = ANY(%s) "
            "AND c.relkind IN ('r','p','v','m') "
            "AND has_table_privilege(current_user, c.oid, 'SELECT')",
            (schema, list(allowed_tables)),
        ).all()
    }
    if available != set(allowed_tables):
        raise SQLSandboxUnavailable("Configured SQL sandbox tables are missing or not readable")


def _format_rows(rows) -> str:
    return "\n".join(
        ",".join("NULL" if value is None else str(value) for value in row)
        for row in rows
    )


def run_sql_test_case(code: str, input_data: str, expected_output: str) -> Dict:
    """Evaluate one read-only query using only the dedicated sandbox role."""
    expected = (expected_output or "").strip()
    try:
        if input_data and input_data.strip():
            raise ValueError("SQL test fixtures must be preloaded into the read-only sandbox schema")
        if len(code.encode("utf-8")) > MAX_QUERY_BYTES:
            raise ValueError("SQL query exceeds 20000 bytes")
        query = _strip_comments_and_check_single_statement(code)
        database_url, schema, tables, timeout_ms = _settings()
        engine = _engine_for(database_url)
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                connection.exec_driver_sql(
                    "SELECT set_config('statement_timeout', %s, true)",
                    (f"{timeout_ms}ms",),
                )
                connection.exec_driver_sql(
                    "SELECT set_config('lock_timeout', '1000ms', true)"
                )
                _verify_restricted_role(connection, schema, tables)
                quoted_schema = '"' + schema.replace('"', '""') + '"'
                connection.exec_driver_sql(
                    f"SET LOCAL search_path TO {quoted_schema}, pg_catalog"
                )
                rows = connection.exec_driver_sql(query).fetchmany(MAX_RESULT_ROWS + 1)
                if len(rows) > MAX_RESULT_ROWS:
                    raise ValueError("SQL result exceeds 1000 rows")
                actual = _format_rows(rows)
                if len(actual) > MAX_RESULT_CHARS:
                    raise ValueError("SQL result exceeds 10000 characters")
            finally:
                transaction.rollback()
        passed = actual.strip() == expected
        return {
            "passed": passed,
            "actual_output": actual,
            "expected_output": expected,
            "error": None if passed else "Wrong Answer",
            "exit_code": 0,
        }
    except SQLSandboxUnavailable as exc:
        return {
            "passed": False, "actual_output": "", "expected_output": expected,
            "error": f"SQL execution unavailable: {exc}", "exit_code": -1,
        }
    except ValueError as exc:
        return {
            "passed": False, "actual_output": "", "expected_output": expected,
            "error": str(exc), "exit_code": -1,
        }
    except Exception:
        return {
            "passed": False, "actual_output": "", "expected_output": expected,
            "error": "SQL query failed or exceeded its execution limit", "exit_code": -1,
        }
