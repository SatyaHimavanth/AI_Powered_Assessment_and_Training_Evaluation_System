"""Create a least-privilege PostgreSQL role for coding-query evaluation.

Run manually with SQL_SANDBOX_ADMIN_DATABASE_URL set. This script is
non-destructive and refuses to modify an existing role.
"""

import os
import re

import psycopg2
from psycopg2 import sql

IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _identifier(value: str, setting: str) -> str:
    if not IDENTIFIER.fullmatch(value or ""):
        raise ValueError(f"{setting} must be a simple PostgreSQL identifier")
    return value


def setup_sql_sandbox_role() -> None:
    admin_url = os.environ.get("SQL_SANDBOX_ADMIN_DATABASE_URL", "").strip()
    if not admin_url:
        raise RuntimeError("Set SQL_SANDBOX_ADMIN_DATABASE_URL for this one-time setup command")
    username = _identifier(
        os.environ.get("SQL_SANDBOX_USERNAME", "assessment_sql"), "SQL_SANDBOX_USERNAME"
    )
    password = os.environ.get("SQL_SANDBOX_PASSWORD", "")
    if len(password) < 24:
        raise ValueError("Set a unique SQL_SANDBOX_PASSWORD with at least 24 characters")
    schema = _identifier(os.environ.get("SQL_SANDBOX_SCHEMA", "demo"), "SQL_SANDBOX_SCHEMA")
    tables = tuple(
        _identifier(item.strip(), "SQL_SANDBOX_ALLOWED_TABLES")
        for item in os.environ.get("SQL_SANDBOX_ALLOWED_TABLES", "").split(",")
        if item.strip()
    )
    if not tables:
        raise ValueError("SQL_SANDBOX_ALLOWED_TABLES must list at least one table")

    with psycopg2.connect(admin_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (username,))
            if cursor.fetchone():
                raise RuntimeError(
                    f"Role {username!r} already exists; refusing to change its privileges"
                )
            cursor.execute(
                "SELECT c.relname FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = %s AND c.relkind IN ('r','p','v','m')",
                (schema,),
            )
            existing_tables = {row[0] for row in cursor.fetchall()}
            missing = set(tables) - existing_tables
            if missing:
                raise RuntimeError(
                    f"Configured SQL sandbox tables do not exist in {schema}: "
                    + ", ".join(sorted(missing))
                )

            cursor.execute(sql.SQL(
                "CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB "
                "NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT CONNECTION LIMIT 8"
            ).format(sql.Identifier(username), sql.Literal(password)))
            cursor.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(connection.get_dsn_parameters()["dbname"]),
                sql.Identifier(username),
            ))
            cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                sql.Identifier(schema), sql.Identifier(username)
            ))
            for table in tables:
                cursor.execute(sql.SQL("GRANT SELECT ON TABLE {}.{} TO {}").format(
                    sql.Identifier(schema), sql.Identifier(table), sql.Identifier(username)
                ))
            cursor.execute(sql.SQL(
                "ALTER ROLE {} SET statement_timeout = '3s'"
            ).format(sql.Identifier(username)))
            cursor.execute(sql.SQL(
                "ALTER ROLE {} SET idle_in_transaction_session_timeout = '5s'"
            ).format(sql.Identifier(username)))
    print(
        f"Created read-only SQL role {username!r} for "
        f"{schema}.{', '.join(tables)}. Configure its URL for SQL_SANDBOX_DATABASE_URL."
    )


if __name__ == "__main__":
    setup_sql_sandbox_role()
