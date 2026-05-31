"""Create demo Postgres schema/tables and seed data for SQL coding exercises."""

import os
import re
import psycopg2

DEMO_SCHEMA = os.environ.get("SQL_SANDBOX_SCHEMA", "demo")


def _validate_identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value or ""):
        raise ValueError(f"Invalid SQL identifier: {value!r}")
    return value


def create_demo_db_for_tests():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL environment variable is not set.")
        print("Set DATABASE_URL to your assessment Postgres connection URL and re-run.")
        return

    schema = _validate_identifier(DEMO_SCHEMA)

    print("Connecting to assessment DB for SQL demo schema...")
    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    cur = conn.cursor()

    try:
        print(f"Preparing demo schema '{schema}'...")
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        cur.execute(f"DROP TABLE IF EXISTS {schema}.employees CASCADE")
        cur.execute(f"DROP TABLE IF EXISTS {schema}.departments CASCADE")

        print("Creating tables...")
        cur.execute(
            f"""
            CREATE TABLE {schema}.departments (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL
            )
            """
        )

        cur.execute(
            f"""
            CREATE TABLE {schema}.employees (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                department_id INTEGER REFERENCES {schema}.departments(id),
                salary INTEGER
            )
            """
        )

        print("Inserting sample data...")
        cur.execute(f"INSERT INTO {schema}.departments (name) VALUES (%s), (%s), (%s)", ("Engineering", "HR", "Sales"))
        cur.execute(f"INSERT INTO {schema}.employees (name, department_id, salary) VALUES (%s, %s, %s)", ("Alice", 1, 90000))
        cur.execute(f"INSERT INTO {schema}.employees (name, department_id, salary) VALUES (%s, %s, %s)", ("Bob", 1, 80000))
        cur.execute(f"INSERT INTO {schema}.employees (name, department_id, salary) VALUES (%s, %s, %s)", ("Carol", 2, 70000))
        cur.execute(f"INSERT INTO {schema}.employees (name, department_id, salary) VALUES (%s, %s, %s)", ("Dave", 3, 65000))

    finally:
        try:
            cur.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass

