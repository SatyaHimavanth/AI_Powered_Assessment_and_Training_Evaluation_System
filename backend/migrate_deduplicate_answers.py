"""Duplicate inventory and non-destructive unique-index migration for Answer records.

There is no reliable answer timestamp or version in the current schema, so this
tool deliberately does not choose a survivor, delete rows, or add constraints.
Resolve reported groups using an approved data policy before writing a separate
migration.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db.database import SessionLocal
from sqlalchemy import text


def deduplicate_answers():
    """Return duplicate group counts without changing answer data."""
    db = SessionLocal()
    try:
        by_question = db.execute(text("""
            SELECT COUNT(*) FROM (
                SELECT attempt_id, question_id
                FROM answers WHERE question_id IS NOT NULL
                GROUP BY attempt_id, question_id HAVING COUNT(*) > 1
            ) duplicate_groups
        """)).scalar_one()
        by_item = db.execute(text("""
            SELECT COUNT(*) FROM (
                SELECT attempt_id, assessment_item_id
                FROM answers WHERE assessment_item_id IS NOT NULL
                GROUP BY attempt_id, assessment_item_id HAVING COUNT(*) > 1
            ) duplicate_groups
        """)).scalar_one()
        return {"question_groups": by_question, "item_groups": by_item}
    finally:
        db.close()


def add_constraints():
    counts = deduplicate_answers()
    if counts["question_groups"] or counts["item_groups"]:
        raise RuntimeError(
            "Refusing to add unique indexes while duplicate Answer groups remain: "
            f"question={counts['question_groups']}, item={counts['item_groups']}. "
            "No survivor policy is defined, and no rows were changed."
        )
    db = SessionLocal()
    try:
        if db.bind.dialect.name != "postgresql":
            raise RuntimeError("Unique-index migration requires PostgreSQL")
        existing_question_constraint = db.execute(
            text("SELECT to_regclass('uq_answer_attempt_question')")
        ).scalar()
        existing_item_constraint = db.execute(
            text("SELECT to_regclass('uq_answer_attempt_item')")
        ).scalar()
        if not existing_question_constraint:
            db.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_answers_attempt_question_safe "
                "ON answers (attempt_id, question_id) WHERE question_id IS NOT NULL"
            ))
        if not existing_item_constraint:
            db.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_answers_attempt_item_safe "
                "ON answers (attempt_id, assessment_item_id) WHERE assessment_item_id IS NOT NULL"
            ))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    print("=== Read-only duplicate Answer inventory ===")
    counts = deduplicate_answers()
    print(f"Duplicate (attempt_id, question_id) groups: {counts['question_groups']}")
    print(f"Duplicate (attempt_id, assessment_item_id) groups: {counts['item_groups']}")
    if "--apply-constraints" in sys.argv:
        add_constraints()
        print("Unique indexes added; no rows were changed.")
    else:
        print("No rows or schema objects were changed. Pass --apply-constraints only after reviewing the inventory.")
