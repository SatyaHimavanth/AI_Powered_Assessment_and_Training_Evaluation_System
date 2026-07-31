-- Recent SQLAlchemy model updates through 2026-07-31.
-- Target: PostgreSQL.
--
-- This migration is idempotent. Run it while application writes are paused:
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
--     -f backend/migrations/20260731_recent_model_updates.sql
--
-- To also convert an existing vector column for JSON fallback mode:
--   $env:PGOPTIONS = "-c app.embedding_storage_backend=json"
--   psql $env:DATABASE_URL -v ON_ERROR_STOP=1 `
--     -f backend/migrations/20260731_recent_model_updates.sql
-- Without that session setting, embedding storage is left unchanged.

BEGIN;

-- Prevent concurrent writes while duplicate rows are consolidated.
LOCK TABLE topics, answers, practice_answers IN SHARE ROW EXCLUSIVE MODE;

-- Keep one topic for each exact name and repoint every known foreign key.
CREATE TEMP TABLE duplicate_topic_map ON COMMIT DROP AS
WITH ranked AS (
    SELECT
        id,
        FIRST_VALUE(id) OVER (
            PARTITION BY name
            ORDER BY id::text
        ) AS keep_id,
        ROW_NUMBER() OVER (
            PARTITION BY name
            ORDER BY id::text
        ) AS row_number
    FROM topics
)
SELECT id AS duplicate_id, keep_id
FROM ranked
WHERE row_number > 1;

UPDATE questions AS target
SET topic_id = mapping.keep_id
FROM duplicate_topic_map AS mapping
WHERE target.topic_id = mapping.duplicate_id;

UPDATE assessment_topics AS target
SET topic_id = mapping.keep_id
FROM duplicate_topic_map AS mapping
WHERE target.topic_id = mapping.duplicate_id;

UPDATE topic_scores AS target
SET topic_id = mapping.keep_id
FROM duplicate_topic_map AS mapping
WHERE target.topic_id = mapping.duplicate_id;

UPDATE question_generation_batches AS target
SET topic_id = mapping.keep_id
FROM duplicate_topic_map AS mapping
WHERE target.topic_id = mapping.duplicate_id;

UPDATE staged_questions AS target
SET topic_id = mapping.keep_id
FROM duplicate_topic_map AS mapping
WHERE target.topic_id = mapping.duplicate_id;

DELETE FROM topics AS target
USING duplicate_topic_map AS mapping
WHERE target.id = mapping.duplicate_id;

-- Keep one answer for each attempt/question pair. UUID ordering provides a
-- deterministic survivor because this table has no creation timestamp.
DELETE FROM answers AS target
USING (
    SELECT id
    FROM (
        SELECT
            id,
            ROW_NUMBER() OVER (
                PARTITION BY attempt_id, question_id
                ORDER BY id::text
            ) AS row_number
        FROM answers
        WHERE question_id IS NOT NULL
    ) AS ranked
    WHERE row_number > 1
) AS duplicates
WHERE target.id = duplicates.id;

DELETE FROM answers AS target
USING (
    SELECT id
    FROM (
        SELECT
            id,
            ROW_NUMBER() OVER (
                PARTITION BY attempt_id, assessment_item_id
                ORDER BY id::text
            ) AS row_number
        FROM answers
        WHERE assessment_item_id IS NOT NULL
    ) AS ranked
    WHERE row_number > 1
) AS duplicates
WHERE target.id = duplicates.id;

-- A practice question has one logical answer.
DELETE FROM practice_answers AS target
USING (
    SELECT id
    FROM (
        SELECT
            id,
            ROW_NUMBER() OVER (
                PARTITION BY question_id
                ORDER BY id::text
            ) AS row_number
        FROM practice_answers
    ) AS ranked
    WHERE row_number > 1
) AS duplicates
WHERE target.id = duplicates.id;

DO $migration$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'topics'::regclass
          AND contype = 'u'
          AND conname = 'topics_name_key'
    ) THEN
        ALTER TABLE topics
            ADD CONSTRAINT topics_name_key UNIQUE (name);
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'answers'::regclass
          AND conname = 'uq_answer_attempt_question'
    ) THEN
        ALTER TABLE answers
            ADD CONSTRAINT uq_answer_attempt_question
            UNIQUE (attempt_id, question_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'answers'::regclass
          AND conname = 'uq_answer_attempt_item'
    ) THEN
        ALTER TABLE answers
            ADD CONSTRAINT uq_answer_attempt_item
            UNIQUE (attempt_id, assessment_item_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'practice_answers'::regclass
          AND contype = 'u'
          AND conname = 'practice_answers_question_id_key'
    ) THEN
        ALTER TABLE practice_answers
            ADD CONSTRAINT practice_answers_question_id_key
            UNIQUE (question_id);
    END IF;
END
$migration$;

-- JSON embedding fallback migration.
DO $embedding_migration$
DECLARE
    current_type text;
    storage_backend text;
BEGIN
    storage_backend := COALESCE(
        current_setting('app.embedding_storage_backend', true),
        'pgvector'
    );
    IF storage_backend <> 'json' THEN
        RAISE NOTICE 'Embedding column unchanged (app.embedding_storage_backend is not json)';
        RETURN;
    END IF;

    IF to_regclass('public.question_embeddings') IS NULL THEN
        RAISE NOTICE 'question_embeddings does not exist; SQLAlchemy will create it with JSON storage';
        RETURN;
    END IF;

    SELECT data_type
    INTO current_type
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'question_embeddings'
      AND column_name = 'embedding';

    IF current_type NOT IN ('json', 'jsonb') THEN
        EXECUTE '
            ALTER TABLE question_embeddings
            ALTER COLUMN embedding TYPE json
            USING embedding::text::json
        ';
    END IF;
END
$embedding_migration$;

COMMIT;
