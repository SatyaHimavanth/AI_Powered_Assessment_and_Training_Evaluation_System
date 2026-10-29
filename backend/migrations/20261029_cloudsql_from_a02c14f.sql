-- SQL-only upgrade from a02c14f to the 659690f migration set.
-- Take a Cloud SQL backup and stop API/worker writes first.
-- Select your application's database/schema and execute this ENTIRE DO statement.
-- One statement = one transaction: an error rolls back all changes and history.
-- No rows are deleted. Existing embedding storage and dimensions are preserved.
-- Keep EMBEDDING_STORAGE_BACKEND and EMBEDDING_DIM consistent when deploying.
DO $upgrade$
DECLARE
    target_schema text := current_schema();
    item record;
    affected bigint;
    index_oid regclass;
    embedding_type text;
    embedding_dimensions integer;
    vector_schema text;
BEGIN
    IF target_schema IS NULL THEN
        RAISE EXCEPTION 'No application schema selected';
    END IF;
    PERFORM set_config('lock_timeout', '15s', true);
    PERFORM pg_advisory_xact_lock(731204890);

    -- Require the deployed schema; this is an upgrade, not a fresh-DB bootstrap.
    FOR item IN
        SELECT unnest(ARRAY[
            'users', 'topics', 'questions', 'assessments', 'batch_users',
            'assessment_topics', 'assessment_questions', 'assessment_question_sections',
            'assessment_question_items', 'assignments', 'attempts', 'answers',
            'evaluation_jobs', 'practice_tests', 'practice_questions', 'practice_answers',
            'interview_sessions', 'interview_response_evaluations',
            'question_generation_batches', 'staged_questions', 'question_embeddings'
        ]) AS table_name
    LOOP
        IF to_regclass(format('%I.%I', target_schema, item.table_name)) IS NULL THEN
            RAISE EXCEPTION 'Expected legacy table %.% is missing; stop and inspect the deployed schema',
                target_schema, item.table_name;
        END IF;
        EXECUTE format('LOCK TABLE %I.%I IN SHARE ROW EXCLUSIVE MODE', target_schema, item.table_name);
    END LOOP;

    FOR item IN SELECT * FROM (VALUES
        ('batch_users', 'batch_id'), ('batch_users', 'user_id'),
        ('assessment_topics', 'assessment_id'), ('assessment_topics', 'topic_id'),
        ('assessment_questions', 'assessment_id'), ('assessment_question_sections', 'assessment_id'),
        ('assignments', 'assessment_id'), ('assignments', 'batch_id'),
        ('attempts', 'user_id'), ('attempts', 'assessment_id'), ('answers', 'attempt_id')
    ) AS required(table_name, column_name)
    LOOP
        EXECUTE format('SELECT count(*) FROM %I.%I WHERE %I IS NULL',
            target_schema, item.table_name, item.column_name) INTO affected;
        IF affected > 0 THEN
            RAISE EXCEPTION 'Cannot require %.%: % rows have NULL values. No data has been deleted.',
                item.table_name, item.column_name, affected;
        END IF;
    END LOOP;

    FOR item IN SELECT * FROM (VALUES
        ('assessment_questions', 'ck_assessment_questions_exactly_one_source',
            '(question_id IS NULL) <> (assessment_item_id IS NULL)'),
        ('assessment_question_sections', 'ck_assessment_question_sections_exactly_one_source',
            '(question_id IS NULL) <> (assessment_item_id IS NULL)'),
        ('answers', 'ck_answers_exactly_one_source',
            '(question_id IS NULL) <> (assessment_item_id IS NULL)'),
        ('question_embeddings', 'ck_question_embeddings_exactly_one_owner',
            '(question_id IS NULL) <> (staged_question_id IS NULL)')
    ) AS ownership(table_name, constraint_name, expression)
    LOOP
        EXECUTE format('SELECT count(*) FROM %I.%I WHERE NOT (%s)',
            target_schema, item.table_name, item.expression) INTO affected;
        IF affected > 0 THEN
            RAISE EXCEPTION 'Invalid ownership in %: % rows have zero or multiple owners. Reconcile before retrying.',
                item.table_name, affected;
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = item.constraint_name
            AND conrelid = to_regclass(format('%I.%I', target_schema, item.table_name))
        ) THEN
            EXECUTE format('ALTER TABLE %I.%I ADD CONSTRAINT %I CHECK (%s)',
                target_schema, item.table_name, item.constraint_name, item.expression);
        END IF;
    END LOOP;

    ALTER TABLE assessment_questions ADD COLUMN IF NOT EXISTS position integer;
    WITH ordered AS (
        SELECT id, row_number() OVER (
            PARTITION BY assessment_id ORDER BY coalesce(question_id, assessment_item_id), id
        ) - 1 AS position
        FROM assessment_questions WHERE position IS NULL
    )
    UPDATE assessment_questions AS target SET position = ordered.position
    FROM ordered WHERE target.id = ordered.id;
    ALTER TABLE assessment_questions ALTER COLUMN position SET DEFAULT 0;
    ALTER TABLE assessment_questions ALTER COLUMN position SET NOT NULL;

    FOR item IN SELECT * FROM (VALUES
        ('uq_topics_name_safe', 'topics', 'name', 'name IS NOT NULL'),
        ('uq_answers_attempt_question_safe', 'answers', 'attempt_id, question_id', 'question_id IS NOT NULL'),
        ('uq_answers_attempt_item_safe', 'answers', 'attempt_id, assessment_item_id', 'assessment_item_id IS NOT NULL'),
        ('uq_practice_answers_question_safe', 'practice_answers', 'question_id', 'question_id IS NOT NULL'),
        ('uq_batch_users_batch_user', 'batch_users', 'batch_id, user_id', NULL),
        ('uq_assignments_assessment_batch', 'assignments', 'assessment_id, batch_id', NULL),
        ('uq_assessment_questions_global', 'assessment_questions', 'assessment_id, question_id', 'question_id IS NOT NULL'),
        ('uq_assessment_questions_item', 'assessment_questions', 'assessment_id, assessment_item_id', 'assessment_item_id IS NOT NULL'),
        ('uq_assessment_sections_global', 'assessment_question_sections', 'assessment_id, question_id', 'question_id IS NOT NULL'),
        ('uq_assessment_sections_item', 'assessment_question_sections', 'assessment_id, assessment_item_id', 'assessment_item_id IS NOT NULL'),
        ('uq_interview_response_session_turn', 'interview_response_evaluations', 'session_id, turn_index', NULL),
        ('uq_question_embeddings_question', 'question_embeddings', 'question_id', 'question_id IS NOT NULL'),
        ('uq_question_embeddings_staged', 'question_embeddings', 'staged_question_id', 'staged_question_id IS NOT NULL'),
        ('uq_active_attempt_assessment_user', 'attempts', 'assessment_id, user_id', 'status = ''in_progress'''),
        ('uq_assessment_topics_config', 'assessment_topics', 'assessment_id, topic_id, question_type, difficulty', NULL),
        ('uq_assessment_questions_position', 'assessment_questions', 'assessment_id, position', NULL)
    ) AS uniqueness(index_name, table_name, columns_sql, predicate)
    LOOP
        EXECUTE format(
            'SELECT count(*) FROM (SELECT %s FROM %I.%I WHERE %s GROUP BY %s HAVING count(*) > 1) AS duplicates',
            item.columns_sql, target_schema, item.table_name,
            coalesce(item.predicate, 'TRUE'), item.columns_sql
        ) INTO affected;
        IF affected > 0 THEN
            RAISE EXCEPTION 'Cannot add %: % duplicate groups in %. Reconcile without deleting records blindly.',
                item.index_name, affected, item.table_name;
        END IF;
        index_oid := to_regclass(format('%I.%I', target_schema, item.index_name));
        IF index_oid IS NULL THEN
            EXECUTE format('CREATE UNIQUE INDEX %I ON %I.%I (%s)%s',
                item.index_name, target_schema, item.table_name, item.columns_sql,
                CASE WHEN item.predicate IS NULL THEN '' ELSE ' WHERE ' || item.predicate END);
        ELSIF NOT EXISTS (
            SELECT 1 FROM pg_index WHERE indexrelid = index_oid AND indisvalid AND indisunique
            AND indrelid = to_regclass(format('%I.%I', target_schema, item.table_name))
        ) THEN
            RAISE EXCEPTION 'Existing index % does not match a valid unique index on %',
                item.index_name, item.table_name;
        END IF;
    END LOOP;

    FOR item IN SELECT * FROM (VALUES
        ('batch_users', 'batch_id'), ('batch_users', 'user_id'),
        ('assessment_topics', 'assessment_id'), ('assessment_topics', 'topic_id'),
        ('assessment_questions', 'assessment_id'), ('assessment_question_sections', 'assessment_id'),
        ('assignments', 'assessment_id'), ('assignments', 'batch_id'),
        ('attempts', 'user_id'), ('attempts', 'assessment_id'), ('answers', 'attempt_id')
    ) AS required(table_name, column_name)
    LOOP
        EXECUTE format('ALTER TABLE %I.%I ALTER COLUMN %I SET NOT NULL',
            target_schema, item.table_name, item.column_name);
    END LOOP;

    CREATE TABLE IF NOT EXISTS refresh_sessions (
        jti varchar(36) PRIMARY KEY,
        user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        expires_at timestamptz NOT NULL,
        created_at timestamptz NOT NULL DEFAULT current_timestamp,
        revoked_at timestamptz
    );
    CREATE INDEX IF NOT EXISTS ix_refresh_sessions_user_id ON refresh_sessions(user_id);
    CREATE INDEX IF NOT EXISTS ix_refresh_sessions_expires_at ON refresh_sessions(expires_at);

    CREATE TABLE IF NOT EXISTS assessment_user_assignments (
        id uuid PRIMARY KEY,
        assessment_id uuid NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
        user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        CONSTRAINT uq_assessment_user_assignments_target UNIQUE(assessment_id, user_id)
    );
    CREATE INDEX IF NOT EXISTS ix_assessment_user_assignments_user_id ON assessment_user_assignments(user_id);

    CREATE TABLE IF NOT EXISTS attempt_integrity_events (
        id uuid PRIMARY KEY,
        attempt_id uuid NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
        event_id uuid NOT NULL,
        event_type varchar(32) NOT NULL,
        created_at timestamptz NOT NULL DEFAULT current_timestamp,
        CONSTRAINT ck_attempt_integrity_event_type CHECK (
            event_type IN ('focus_lost', 'fullscreen_exit', 'escape_key', 'devtools_shortcut')
        ),
        CONSTRAINT uq_attempt_integrity_event_id UNIQUE(attempt_id, event_id)
    );
    CREATE INDEX IF NOT EXISTS ix_attempt_integrity_events_attempt_created ON attempt_integrity_events(attempt_id, created_at);

    ALTER TABLE practice_tests ADD COLUMN IF NOT EXISTS generation_claimed_at timestamptz;
    CREATE INDEX IF NOT EXISTS ix_practice_tests_generation_claimed_at ON practice_tests(generation_claimed_at);
    ALTER TABLE attempts ADD COLUMN IF NOT EXISTS active_seconds double precision NOT NULL DEFAULT 0;
    ALTER TABLE attempts ALTER COLUMN active_seconds TYPE double precision USING active_seconds::double precision;
    ALTER TABLE attempts ADD COLUMN IF NOT EXISTS active_started_at timestamptz;
    ALTER TABLE attempts ADD COLUMN IF NOT EXISTS active_heartbeat_at timestamptz;
    ALTER TABLE attempts ADD COLUMN IF NOT EXISTS sync_deadline_at timestamptz;

    FOR item IN SELECT * FROM (VALUES
        ('ix_assignments_batch_id', 'assignments', 'batch_id'),
        ('ix_attempts_user_status_started', 'attempts', 'user_id, status, started_at'),
        ('ix_attempts_assessment_status', 'attempts', 'assessment_id, status'),
        ('ix_evaluation_jobs_status_created', 'evaluation_jobs', 'status, created_at'),
        ('ix_practice_tests_user_created', 'practice_tests', 'user_id, created_at'),
        ('ix_practice_questions_test_position', 'practice_questions', 'practice_test_id, position'),
        ('ix_interview_sessions_user_status_created', 'interview_sessions', 'user_id, status, created_at'),
        ('ix_interview_sessions_template_status_created', 'interview_sessions', 'template_id, status, created_at'),
        ('ix_generation_batches_status_created', 'question_generation_batches', 'status, created_at'),
        ('ix_staged_questions_batch_status_created', 'staged_questions', 'batch_id, status, created_at')
    ) AS indexes(index_name, table_name, columns_sql)
    LOOP
        EXECUTE format('CREATE INDEX IF NOT EXISTS %I ON %I.%I (%s)',
            item.index_name, target_schema, item.table_name, item.columns_sql);
    END LOOP;

    SELECT t.typname, a.atttypmod INTO embedding_type, embedding_dimensions
    FROM pg_attribute a JOIN pg_type t ON t.oid = a.atttypid
    WHERE a.attrelid = to_regclass(format('%I.question_embeddings', target_schema))
      AND a.attname = 'embedding' AND NOT a.attisdropped;
    IF embedding_type = 'vector' THEN
        SELECT n.nspname INTO vector_schema
        FROM pg_extension e JOIN pg_namespace n ON n.oid = e.extnamespace
        WHERE e.extname = 'vector';
        IF vector_schema IS NULL THEN
            RAISE EXCEPTION 'Vector column exists but the vector extension is not registered';
        END IF;
        IF embedding_dimensions BETWEEN 1 AND 2000 THEN
            EXECUTE format(
                'CREATE INDEX IF NOT EXISTS ix_question_embeddings_hnsw_cosine '
                'ON %I.question_embeddings USING hnsw (embedding %I.vector_cosine_ops) '
                'WHERE question_id IS NOT NULL', target_schema, vector_schema
            );
        END IF;
    ELSIF embedding_type NOT IN ('json', 'jsonb') OR embedding_type IS NULL THEN
        RAISE EXCEPTION 'Unsupported embedding column type: %; no storage conversion was attempted', embedding_type;
    END IF;
    RAISE NOTICE 'Embedding storage retained: %, dimensions: %', embedding_type, embedding_dimensions;

    -- Record completion only after every schema operation above has succeeded.
    CREATE TABLE IF NOT EXISTS app_schema_migrations (
        version varchar(120) PRIMARY KEY,
        applied_at timestamptz NOT NULL DEFAULT current_timestamp
    );
    INSERT INTO app_schema_migrations(version) VALUES
        ('20261028_assessment_question_positions'),
        ('20261028_refresh_sessions'),
        ('20261028_application_uniqueness_and_vector_index'),
        ('20261028_embedding_storage_backend'),
        ('20261028_association_integrity'),
        ('20261028_query_indexes'),
        ('20261028_practice_generation_claims'),
        ('20261028_attempt_integrity_events'),
        ('20261028_individual_assessment_assignments'),
        ('20261028_attempt_active_time'),
        ('20261028_attempt_active_time_precision'),
        ('20261029_attempt_offline_sync_grace')
    ON CONFLICT (version) DO NOTHING;
    RAISE NOTICE 'Upgrade from a02c14f completed. Existing application records retained.';
END
$upgrade$;
