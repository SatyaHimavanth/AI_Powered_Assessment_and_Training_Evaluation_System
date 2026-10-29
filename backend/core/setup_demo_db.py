"""Explicitly provision the optional SQL practice schema with sample rows.

This is a one-shot, additive development command. It never drops or resets data.
"""

import os
import re

import psycopg2

DEMO_SCHEMA = os.environ.get("SQL_SANDBOX_SCHEMA", "demo")


def _validate_identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value or ""):
        raise ValueError("SQL_SANDBOX_SCHEMA must be a simple SQL identifier")
    return value


def create_demo_db_for_tests() -> None:
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL is required to provision the demo schema")

    schema = _validate_identifier(DEMO_SCHEMA)
    with psycopg2.connect(db_url) as conn:
        conn.autocommit = False
        with conn.cursor() as cursor:
            cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
            cursor.execute(
                f"CREATE TABLE IF NOT EXISTS {schema}.departments ("
                "id SERIAL PRIMARY KEY, name TEXT NOT NULL)"
            )
            cursor.execute(
                f"CREATE TABLE IF NOT EXISTS {schema}.employees ("
                "id SERIAL PRIMARY KEY, name TEXT NOT NULL, "
                f"department_id INTEGER REFERENCES {schema}.departments(id), "
                "salary INTEGER)"
            )
            for name in ("Engineering", "HR", "Sales"):
                cursor.execute(
                    f"INSERT INTO {schema}.departments(name) "
                    "SELECT %s WHERE NOT EXISTS ("
                    f"SELECT 1 FROM {schema}.departments WHERE name = %s)",
                    (name, name),
                )
            samples = (
                ("Alice", "Engineering", 90000),
                ("Bob", "Engineering", 80000),
                ("Carol", "HR", 70000),
                ("Dave", "Sales", 65000),
            )
            for name, department, salary in samples:
                cursor.execute(
                    f"INSERT INTO {schema}.employees(name, department_id, salary) "
                    "SELECT %s, d.id, %s "
                    f"FROM {schema}.departments AS d WHERE d.name = %s "
                    "AND NOT EXISTS ("
                    f"SELECT 1 FROM {schema}.employees WHERE name = %s)",
                    (name, salary, department, name),
                )
        conn.commit()


if __name__ == "__main__":
    create_demo_db_for_tests()
