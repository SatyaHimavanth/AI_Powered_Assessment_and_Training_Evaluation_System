# SQL Sandbox: Tables, Data, and Read-Only Access

SQL coding questions run against a PostgreSQL schema through a dedicated login.
Use the application/admin database account only for schema changes and data
ingestion. Candidate queries use the restricted login and can read only the
tables listed in the application's allowlist.

> Do not use the application database username for `SQL_SANDBOX_DATABASE_URL`.
> Create a new role with no role memberships, elevated attributes, or write
> grants. The API checks these permissions before executing candidate SQL.

## 1. Create the sandbox schema and tables

Connect to the **application database** as its database owner or another
administrative role. The examples use a `demo` schema with `departments` and
`employees`; change the names and columns to match your question data.

```sql
CREATE SCHEMA IF NOT EXISTS demo;

CREATE TABLE IF NOT EXISTS demo.departments (
    department_id integer PRIMARY KEY,
    department_name text NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS demo.employees (
    employee_id integer PRIMARY KEY,
    employee_name text NOT NULL,
    department_id integer NOT NULL REFERENCES demo.departments(department_id),
    salary numeric(12, 2) NOT NULL CHECK (salary >= 0),
    hired_on date
);
```

Add indexes that support the expected question queries, based on the data size
and query plans:

```sql
CREATE INDEX IF NOT EXISTS ix_demo_employees_department_id
    ON demo.employees (department_id);
```

Use PostgreSQL types and constraints that reflect the actual data. Avoid storing
real candidate or employee personal information in shared practice tables.

## 2. Ingest or update data

Run data changes as the database owner/import role, never as `assessment_sql`.
For small data sets, use parameterized application/admin tooling or inserts:

```sql
INSERT INTO demo.departments (department_id, department_name)
VALUES (10, 'Engineering'), (20, 'Operations')
ON CONFLICT (department_id) DO UPDATE
SET department_name = EXCLUDED.department_name;

INSERT INTO demo.employees
    (employee_id, employee_name, department_id, salary, hired_on)
VALUES
    (1001, 'Example Candidate', 10, 85000.00, DATE '2024-02-15')
ON CONFLICT (employee_id) DO UPDATE
SET employee_name = EXCLUDED.employee_name,
    department_id = EXCLUDED.department_id,
    salary = EXCLUDED.salary,
    hired_on = EXCLUDED.hired_on;
```

For CSV files, use `psql`'s client-side `\copy` command. The paths below are
read by the computer running `psql`, not by the PostgreSQL server:

```text
\copy demo.departments (department_id, department_name) FROM 'departments.csv' WITH (FORMAT csv, HEADER true)
\copy demo.employees (employee_id, employee_name, department_id, salary, hired_on) FROM 'employees.csv' WITH (FORMAT csv, HEADER true)
```

Check the imported data before granting access:

```sql
SELECT count(*) AS departments FROM demo.departments;
SELECT count(*) AS employees FROM demo.employees;
SELECT * FROM demo.employees ORDER BY employee_id LIMIT 10;
```

When replacing a full data set, perform the replacement as the administrative
role in a transaction and verify the row counts before commit. Do not give the
sandbox login `INSERT`, `UPDATE`, `DELETE`, `TRUNCATE`, `CREATE`, ownership, or
role-membership privileges.

## 3. Create the restricted login

Generate a unique random password (at least 24 characters). Connect as a
database administrator to the same application database and replace the
password placeholder in this SQL. Do not run this as the sandbox user.

```sql
CREATE ROLE assessment_sql
    LOGIN
    PASSWORD 'REPLACE_WITH_A_UNIQUE_RANDOM_PASSWORD'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT
    CONNECTION LIMIT 8;

GRANT CONNECT ON DATABASE assessment_db TO assessment_sql;
GRANT USAGE ON SCHEMA demo TO assessment_sql;
GRANT SELECT ON TABLE demo.departments, demo.employees TO assessment_sql;

ALTER ROLE assessment_sql SET statement_timeout = '3s';
ALTER ROLE assessment_sql SET idle_in_transaction_session_timeout = '5s';
```

The role should be new and must not inherit or be a member of another role.
Do not grant access to a whole schema or use `GRANT ... ON ALL TABLES` here:
the explicit table grants keep the database permissions aligned with the
application's allowlist. If the role already exists, inspect it and its grants
instead of blindly rerunning `CREATE ROLE` or broadening its access.

The repository also includes a guarded setup utility that validates the target
tables, refuses to alter an existing role, and creates the role with the same
least-privilege grants. See
[`backend/tools/setup_sql_sandbox_role.py`](backend/tools/setup_sql_sandbox_role.py)
and [DOCKER.md's SQL setup](DOCKER.md#sql-execution-setup).
If you use that utility instead of the manual SQL above, temporarily configure
`SQL_SANDBOX_ADMIN_DATABASE_URL`, `SQL_SANDBOX_USERNAME`, and
`SQL_SANDBOX_PASSWORD` in your local shell. Remove the admin URL and setup
password from the environment after role creation; the running application
needs only `SQL_SANDBOX_DATABASE_URL` and the schema/table/timeout settings.

## 4. Configure the application

Set these values in the backend `.env` for local use, or in the cloud platform's
secret/environment configuration. URL-encode special characters in the
password before putting it in a connection URL.

```env
# Direct local backend: localhost; Compose backend: db
SQL_SANDBOX_DATABASE_URL=postgresql://assessment_sql:URL_ENCODED_PASSWORD@localhost:5432/assessment_db
SQL_SANDBOX_SCHEMA=demo
SQL_SANDBOX_ALLOWED_TABLES=departments,employees
SQL_SANDBOX_QUERY_TIMEOUT_MS=3000
```

Keep `SQL_SANDBOX_DATABASE_URL` separate from `DATABASE_URL`. Keep the admin
connection URL and password out of the app runtime configuration. For Docker
Compose, change the host from `localhost` to `db`. In a managed deployment, use
the platform's secret manager and the managed database hostname.

## 5. Add another table later

Create and populate the new table as the administrative/import role. Then grant
only the required read permission and add its exact name to the application
allowlist. For example, to add `demo.projects`:

```sql
GRANT SELECT ON TABLE demo.projects TO assessment_sql;
```

Update the backend environment:

```env
SQL_SANDBOX_ALLOWED_TABLES=departments,employees,projects
```

Restart the API and every evaluation worker so they read the updated
configuration. The database grant takes effect immediately, but the application
checks the complete configured allowlist on each execution; it rejects
unlisted readable tables and allowlisted tables that are missing or unreadable.
No application schema migration is needed just to change this environment
allowlist. Rehearse DDL and data imports on a backup or disposable database first.

To remove a table from candidate access, revoke its grant and remove it from
the environment allowlist:

```sql
REVOKE SELECT ON TABLE demo.projects FROM assessment_sql;
```

## What the runner enforces

The runner connects only with `SQL_SANDBOX_DATABASE_URL`, rejects elevated
roles, role memberships, and readable tables outside the configured schema and
allowlist, starts a read-only transaction, sets a transaction-local schema
search path, and enforces statement/lock timeouts and row/output limits. It
accepts one `SELECT` or `WITH ... SELECT` statement. Database grants remain the
primary permission boundary; query validation is an additional restriction.
