# Cloud SQL Upgrade: a02c14f to 659690f

Use this guide when the old application was deployed from `a02c14f` and you
can access PostgreSQL only through Cloud SQL Studio.

1. **Back up the Cloud SQL database.** Prefer testing on a restored clone first.
2. Finish active exams/interviews, then stop the old backend and workers.
3. Open Cloud SQL Studio, select the application database, and confirm:

   ```sql
   SELECT current_database(), current_schema();
   ```

4. Open [20261029_cloudsql_from_a02c14f.sql](20261029_cloudsql_from_a02c14f.sql).
   Copy and run the **entire file**, including the `DO $upgrade$` block and
   closing `$upgrade$;`. No application connection or Python command is required.
5. After successful execution, verify:

   ```sql
   SELECT version, applied_at
   FROM app_schema_migrations
   ORDER BY version;
   ```

   This upgrade installs 12 migration versions. Do not insert them manually.
6. Deploy the new backend and workers with the existing embedding storage mode
   and dimension unchanged. Check `/health?db=true&llm=false`, login, old
   results, and one new assessment. Users may need to sign in again.

## If anything fails

The script runs as one atomic statement. An error rolls back its changes and
migration-history entries. Do not deploy the new version until the error is
resolved and the script succeeds. Duplicate or invalid historical data needs
review; do not delete records blindly or bypass the checks.

The script does not delete application records or convert existing embeddings.
It adds schema objects and fills missing question positions. Backups remain
essential: your Cloud SQL data and the pgvector-specific branch have not been
rehearsed against your actual instance. Do not run
`20260731_recent_model_updates.sql` as a replacement; it only reports duplicates.
