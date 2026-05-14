"""Create demo Postgres tables and seed data for SQL coding exercises.

Reads `DEMO_DB_URL` from the environment.

"""

import os
import sys
import psycopg2


def create_demo_db_for_tests():
    db_url = os.environ.get("DEMO_DB_URL")
    if not db_url:
        print("ERROR: DEMO_DB_URL environment variable is not set.")
        print("Set DEMO_DB_URL to your Postgres connection URL and re-run.")
        return

    print("Connecting to demo DB...")
    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    cur = conn.cursor()

    try:
        print("Dropping existing demo tables (if any)...")
        cur.execute("DROP TABLE IF EXISTS employees CASCADE")
        cur.execute("DROP TABLE IF EXISTS departments CASCADE")

        print("Creating tables...")
        cur.execute(
            """
            CREATE TABLE departments (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE employees (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                department_id INTEGER REFERENCES departments(id),
                salary INTEGER
            )
            """
        )

        print("Inserting sample data...")
        cur.execute("INSERT INTO departments (name) VALUES (%s), (%s), (%s)", ("Engineering", "HR", "Sales"))
        cur.execute("INSERT INTO employees (name, department_id, salary) VALUES (%s, %s, %s)", ("Alice", 1, 90000))
        cur.execute("INSERT INTO employees (name, department_id, salary) VALUES (%s, %s, %s)", ("Bob", 1, 80000))
        cur.execute("INSERT INTO employees (name, department_id, salary) VALUES (%s, %s, %s)", ("Carol", 2, 70000))
        cur.execute("INSERT INTO employees (name, department_id, salary) VALUES (%s, %s, %s)", ("Dave", 3, 65000))

    finally:
        try:
            cur.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass

