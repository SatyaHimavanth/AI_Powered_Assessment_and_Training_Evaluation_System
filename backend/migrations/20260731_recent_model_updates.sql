-- Read-only preflight for the superseded 2026-07-31 model migration.
-- This file intentionally performs no UPDATE, DELETE, ALTER, or constraint creation.
-- Review duplicate groups and decide a domain-specific survivor policy before
-- applying any schema constraint migration. Never use UUID ordering as recency.

SELECT 'duplicate topic names' AS finding, name AS key, COUNT(*) AS row_count
FROM topics
GROUP BY name
HAVING COUNT(*) > 1
ORDER BY row_count DESC, name;

SELECT 'duplicate global answers' AS finding,
       attempt_id::text || ':' || question_id::text AS key,
       COUNT(*) AS row_count
FROM answers
WHERE question_id IS NOT NULL
GROUP BY attempt_id, question_id
HAVING COUNT(*) > 1
ORDER BY row_count DESC, key;

SELECT 'duplicate per-assessment-item answers' AS finding,
       attempt_id::text || ':' || assessment_item_id::text AS key,
       COUNT(*) AS row_count
FROM answers
WHERE assessment_item_id IS NOT NULL
GROUP BY attempt_id, assessment_item_id
HAVING COUNT(*) > 1
ORDER BY row_count DESC, key;

SELECT 'duplicate practice answers' AS finding, question_id::text AS key, COUNT(*) AS row_count
FROM practice_answers
GROUP BY question_id
HAVING COUNT(*) > 1
ORDER BY row_count DESC, key;

SELECT 'duplicate batch membership' AS finding,
       batch_id::text || ':' || user_id::text AS key,
       COUNT(*) AS row_count
FROM batch_users
GROUP BY batch_id, user_id
HAVING COUNT(*) > 1
ORDER BY row_count DESC, key;
