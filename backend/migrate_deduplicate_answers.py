"""One-time migration to remove duplicate Answer records and add unique constraints.

Run with: python -m backend.migrate_deduplicate_answers
(or: python migrate_deduplicate_answers.py from the backend directory)
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db.database import engine, SessionLocal
from db.models import Answer
from sqlalchemy import text


def deduplicate_answers():
    """Remove duplicate Answer records, keeping only the latest one for each
    (attempt_id, question_id) and (attempt_id, assessment_item_id) pair."""
    db = SessionLocal()
    try:
        # Deduplicate by (attempt_id, question_id)
        result = db.execute(text("""
            DELETE FROM answers a
            USING (
                SELECT MIN(id) as keep_id, attempt_id, question_id
                FROM answers
                WHERE question_id IS NOT NULL
                GROUP BY attempt_id, question_id
                HAVING COUNT(*) > 1
            ) dup
            WHERE a.attempt_id = dup.attempt_id
              AND a.question_id = dup.question_id
              AND a.id != dup.keep_id
        """))
        removed_by_question = result.rowcount

        # Deduplicate by (attempt_id, assessment_item_id)
        result = db.execute(text("""
            DELETE FROM answers a
            USING (
                SELECT MIN(id) as keep_id, attempt_id, assessment_item_id
                FROM answers
                WHERE assessment_item_id IS NOT NULL
                GROUP BY attempt_id, assessment_item_id
                HAVING COUNT(*) > 1
            ) dup
            WHERE a.attempt_id = dup.attempt_id
              AND a.assessment_item_id = dup.assessment_item_id
              AND a.id != dup.keep_id
        """))
        removed_by_item = result.rowcount

        db.commit()
        print(f"Cleaned up {removed_by_question} duplicate(s) by question_id")
        print(f"Cleaned up {removed_by_item} duplicate(s) by assessment_item_id")
        return removed_by_question + removed_by_item
    except Exception as e:
        db.rollback()
        print(f"Error during deduplication: {e}", file=sys.stderr)
        raise
    finally:
        db.close()


def add_constraints():
    """Add unique constraints to the answers table if they don't exist."""
    conn = engine.connect()
    try:
        # Check if constraints already exist
        existing = conn.execute(text("""
            SELECT conname FROM pg_constraint
            WHERE conname IN ('uq_answer_attempt_question', 'uq_answer_attempt_item')
        """)).fetchall()
        existing_names = {row[0] for row in existing}

        if 'uq_answer_attempt_question' not in existing_names:
            conn.execute(text("""
                ALTER TABLE answers
                ADD CONSTRAINT uq_answer_attempt_question
                UNIQUE (attempt_id, question_id)
            """))
            print("Added unique constraint uq_answer_attempt_question")
        else:
            print("Constraint uq_answer_attempt_question already exists")

        if 'uq_answer_attempt_item' not in existing_names:
            conn.execute(text("""
                ALTER TABLE answers
                ADD CONSTRAINT uq_answer_attempt_item
                UNIQUE (attempt_id, assessment_item_id)
            """))
            print("Added unique constraint uq_answer_attempt_item")
        else:
            print("Constraint uq_answer_attempt_item already exists")

        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Error adding constraints: {e}", file=sys.stderr)
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    print("=== Deduplicating Answer records ===")
    total = deduplicate_answers()
    print(f"Total duplicates removed: {total}")
    print()
    print("=== Adding unique constraints ===")
    add_constraints()
    print("=== Migration complete ===")
