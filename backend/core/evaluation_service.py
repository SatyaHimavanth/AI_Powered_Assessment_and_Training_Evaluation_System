"""
Evaluation Job Consumer Service

This module implements a background task that processes pending evaluation jobs.
It runs as a separate thread/task and polls the database for pending evaluations.
"""

import logging
import threading
import time
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy import func

from app.llms import get_chat_model
from core.logger import get_logger
from db.database import SessionLocal
from db.models import (
    Answer,
    Assessment,
    EvaluationJob,
    EvaluationJobStatus,
    EvaluationType,
    Question,
    AssessmentQuestionItem,
    QuestionOption,
    QuestionType,
    TestCase,
    TopicScore,
    Topic,
)

from pydantic import BaseModel, Field
from core.sql_runner import run_sql_test_case

logger = get_logger(__name__)


class EvaluationResult(BaseModel):
    score: float = Field(description="Score between 0 and 1")
    feedback: str = Field(description="Concise feedback in 1-3 sentences")


def evaluate_attempt_from_job(db: Session, attempt_id: UUID):
    """
    Evaluate an attempt by processing all its answers.
    This function mirrors _evaluate_attempt logic but is called from job queue.
    """
    attempt = db.query(Answer).filter(Answer.attempt_id == attempt_id).first()
    if not attempt:
        return

    from db.models import Attempt
    attempt_record = db.query(Attempt).filter(Attempt.id == attempt_id).first()
    if not attempt_record:
        return

    assessment = db.query(Assessment).filter(Assessment.id == attempt_record.assessment_id).first()
    if not assessment:
        return

    answers = db.query(Answer).filter(Answer.attempt_id == attempt_id).all()
    total_score = 0.0
    total_questions = 0
    topic_totals = {}
    topic_counts = {}

    db.query(TopicScore).filter(TopicScore.attempt_id == attempt_id).delete(synchronize_session=False)

    for ans in answers:
        # Support answers referencing either global Question or per-assessment AssessmentQuestionItem
        question = None
        item = None
        if getattr(ans, "question_id", None):
            question = db.query(Question).filter(Question.id == ans.question_id).first()
        elif getattr(ans, "assessment_item_id", None):
            item = db.query(AssessmentQuestionItem).filter(AssessmentQuestionItem.id == ans.assessment_item_id).first()

        if not question and not item:
            continue

        total_questions += 1

        # determine topic grouping key and ensure we only create TopicScore for resolvable Topic IDs
        topic_key = None
        if question:
            topic_key = str(question.topic_id) if question.topic_id else None
        else:
            # try to resolve item.topic to an existing Topic id by name
            if item and item.topic:
                try:
                    # if it's a UUID string, use it
                    _ = UUID(str(item.topic))
                    topic_key = str(item.topic)
                except Exception:
                    t_obj = db.query(Topic).filter(func.lower(Topic.name) == str(item.topic).lower()).first()
                    topic_key = str(t_obj.id) if t_obj else None

        if topic_key:
            topic_totals.setdefault(topic_key, 0.0)
            topic_counts.setdefault(topic_key, 0)
            topic_counts[topic_key] += 1

        # Evaluate depending on type
        if question:
            q_type = question.type
        else:
            q_type = (QuestionType(item.question_type) if item and item.question_type else QuestionType.text)

        if q_type == QuestionType.single_mcq:
            if question:
                correct_ids = [str(o.id) for o in db.query(QuestionOption).filter(QuestionOption.question_id == question.id, QuestionOption.is_correct == True).all()]
            else:
                # item.options: list of dicts with id and is_correct
                correct_ids = [str(o.get("id")) for o in (item.options or []) if o.get("is_correct")]
            ans.score = 1.0 if sorted([ans.answer] if ans.answer else []) == sorted(correct_ids) else 0.0
            ans.evaluated_by = EvaluationType.auto
            ans.feedback = "Correct" if ans.score == 1 else "Incorrect"
        elif q_type == QuestionType.multi_mcq:
            if question:
                options = db.query(QuestionOption).filter(QuestionOption.question_id == question.id).all()
                correct_ids = [str(o.id) for o in options if o.is_correct]
            else:
                correct_ids = [str(o.get("id")) for o in (item.options or []) if o.get("is_correct")]
            user_ids = (ans.answer or "").split(",")
            ans.score = 1.0 if sorted(user_ids) == sorted(correct_ids) else 0.0
            ans.evaluated_by = EvaluationType.auto
            ans.feedback = "Auto-evaluated"
        elif q_type == QuestionType.coding:
            # Run code against ALL test cases and score by pass rate
            if ans.score is not None and ans.evaluated_by == EvaluationType.auto:
                total_score += float(ans.score)
                if topic_key:
                    topic_totals[topic_key] += float(ans.score)
                continue
            if question:
                score, feedback = _evaluate_coding_with_tests(db, question, ans.answer or "")
            else:
                # Evaluate using test_cases stored on the item (if any)
                from core.code_runner import run_test_case

                def _assemble_item_code(default_code: str | None, user_code: str) -> str:
                    if not default_code:
                        return user_code
                    template = default_code
                    start_idx = template.find(EDITABLE_START_MARKER)
                    end_idx = template.find(EDITABLE_END_MARKER)
                    if start_idx == -1 or end_idx == -1:
                        return user_code
                    header = template[: start_idx + len(EDITABLE_START_MARKER)]
                    footer = template[end_idx:]
                    return header + "\n" + user_code + "\n" + footer

                if not item.test_cases:
                    score, feedback = 0.0, "No test cases configured for this question."
                else:
                    # assemble full code
                    full_code = _assemble_item_code(item.default_code, ans.answer or "")
                    passed = 0
                    total = len(item.test_cases or [])
                    failures = []
                    is_sql_item = bool(item.default_code and str(item.default_code).strip().startswith("--"))
                    for tc in item.test_cases or []:
                        inp = tc.get("input", "")
                        exp = tc.get("expected_output", "")
                        if is_sql_item:
                            result = run_sql_test_case(full_code, inp, exp)
                        else:
                            result = run_test_case(full_code, inp, exp)
                        if result.get("passed"):
                            passed += 1
                        else:
                            if len(failures) < 3:
                                failures.append(result.get("error") or f"Expected: {exp[:50]}")
                    score = passed / total if total > 0 else 0.0
                    if passed == total:
                        feedback = f"All {total} test cases passed."
                    else:
                        feedback = f"{passed}/{total} test cases passed."
                        if failures:
                            feedback += " Failures: " + "; ".join(failures[:2])
            ans.score = score
            ans.evaluated_by = EvaluationType.auto
            ans.feedback = feedback
        else:
            # Subjective question - evaluate with LLM
            # If already evaluated successfully, skip re-evaluation
            if ans.score is not None and ans.evaluated_by == EvaluationType.llm:
                total_score += float(ans.score)
                if topic_key:
                    topic_totals[topic_key] += float(ans.score)
                continue
            if question:
                q_text = question.question
                ref = question.reference_answer or ""
                qtype_val = question.type.value
            else:
                q_text = item.question_text
                ref = item.reference_answer or ""
                qtype_val = (item.question_type or "text")
            score, feedback = _evaluate_subjective_with_llm(
                q_text,
                ref,
                ans.answer or "",
                qtype_val,
            )
            ans.score = score
            ans.evaluated_by = EvaluationType.llm
            ans.feedback = feedback

        total_score += float(ans.score or 0)
        if topic_key:
            topic_totals[topic_key] += float(ans.score or 0)

    for topic_id, score_total in topic_totals.items():
        db.add(
            TopicScore(
                attempt_id=attempt_id,
                topic_id=UUID(topic_id),
                score=round((score_total / max(1, topic_counts[topic_id])) * 100, 1),
            )
        )

    attempt_record.score = (
        round((total_score / max(1, total_questions)) * 100, 1) if total_questions > 0 else 0.0
    )
    db.commit()


EDITABLE_START_MARKER = "# --- EDITABLE START ---"
EDITABLE_END_MARKER = "# --- EDITABLE END ---"


def _assemble_full_code(question: Question, user_code: str) -> str:
    """Reassemble full code from template + user's editable portion."""
    if not question.default_code:
        return user_code

    template = question.default_code
    start_idx = template.find(EDITABLE_START_MARKER)
    end_idx = template.find(EDITABLE_END_MARKER)

    if start_idx == -1 or end_idx == -1:
        return user_code

    header = template[: start_idx + len(EDITABLE_START_MARKER)]
    footer = template[end_idx:]
    return header + "\n" + user_code + "\n" + footer


def _evaluate_coding_with_tests(db: Session, question: Question, user_answer: str) -> tuple:
    """Evaluate coding answer by running against all test cases."""
    from core.code_runner import run_test_case

    # detect SQL-style questions by default_code comment template
    is_sql_question = bool(question.default_code and str(question.default_code).strip().startswith("--"))

    if not user_answer.strip():
        return 0.0, "No code provided."

    # Assemble full code (template header + user code + template footer)
    full_code = _assemble_full_code(question, user_answer)

    # Run against ALL test cases
    test_cases = db.query(TestCase).filter(TestCase.question_id == question.id).all()
    if not test_cases:
        return 0.0, "No test cases configured for this question."

    passed = 0
    total = len(test_cases)
    failures = []

    for tc in test_cases:
        if is_sql_question:
            result = run_sql_test_case(full_code, tc.input_data, tc.expected_output)
        else:
            result = run_test_case(full_code, tc.input_data, tc.expected_output)
        if result["passed"]:
            passed += 1
        else:
            if len(failures) < 3:  # Only record first 3 failures
                failures.append(result.get("error") or f"Expected: {tc.expected_output[:50]}")

    score = passed / total if total > 0 else 0.0
    if passed == total:
        feedback = f"All {total} test cases passed."
    else:
        feedback = f"{passed}/{total} test cases passed."
        if failures:
            feedback += " Failures: " + "; ".join(failures[:2])

    return score, feedback


def _evaluate_subjective_with_llm(
    question_text: str, reference_answer: str, user_answer: str, question_type: str
) -> tuple:
    """Evaluate subjective answer using LLM."""
    if not user_answer.strip():
        return 0.0, "No answer provided."

    prompt = f"""
You are grading a {question_type} assessment answer.

Question:
{question_text}

Reference answer / rubric:
{reference_answer or 'No reference answer provided. Use best-effort grading based on relevance, correctness, and completeness.'}

User answer:
{user_answer}

Rules:
- score must be between 0 and 1
- give concise feedback in 1-3 sentences
- reward partial understanding proportionally
""".strip()
    try:
        model = get_chat_model()
        structured_llm = model.with_structured_output(schema=EvaluationResult)
        result = structured_llm.invoke(prompt)
        score = max(0.0, min(1.0, result.score))
        feedback = result.feedback.strip() or "Evaluated by LLM."
        return score, feedback
    except Exception as e:
        logger.error(f"LLM evaluation failed: {str(e)}")
        raise  # Propagate so the job is retried, not scored as 0


def process_evaluation_jobs(poll_interval: int = 5, max_retries: int = 3):
    """
    Main job processor function that polls for pending evaluation jobs.
    
    Args:
        poll_interval: Seconds to wait between polls (default 5)
        max_retries: Maximum retries for failed jobs (default 3)
    """
    logger.info("Evaluation job consumer started")

    # On startup, recover any jobs stuck in "in_progress" (e.g., server crashed mid-evaluation)
    try:
        startup_db = SessionLocal()
        stalled = (
            startup_db.query(EvaluationJob)
            .filter(EvaluationJob.status == EvaluationJobStatus.in_progress)
            .all()
        )
        for job in stalled:
            job.status = EvaluationJobStatus.pending
            logger.info(f"Recovered stalled job {job.id} (was in_progress) -> pending")
        if stalled:
            startup_db.commit()
        startup_db.close()
    except Exception as e:
        logger.error(f"Error recovering stalled jobs on startup: {e}")

    while True:
        db = None
        try:
            db = SessionLocal()

            # Find pending jobs (oldest first)
            pending_jobs = (
                db.query(EvaluationJob)
                .filter(EvaluationJob.status == EvaluationJobStatus.pending)
                .order_by(EvaluationJob.created_at.asc())
                .limit(5)  # Process up to 5 jobs per cycle
                .all()
            )

            for job in pending_jobs:
                try:
                    logger.info(f"Processing evaluation job {job.id} for attempt {job.attempt_id}")

                    # Update job status to in_progress
                    job.status = EvaluationJobStatus.in_progress
                    job.started_at = datetime.now(timezone.utc)
                    db.commit()

                    # Evaluate the attempt
                    evaluate_attempt_from_job(db, job.attempt_id)

                    # Mark job as completed
                    job.status = EvaluationJobStatus.completed
                    job.completed_at = datetime.now(timezone.utc)
                    db.commit()

                    logger.info(f"Evaluation job {job.id} completed successfully")

                except Exception as e:
                    logger.error(f"Error processing job {job.id}: {str(e)}")
                    db.rollback()

                    # Handle retry logic
                    job.retry_count += 1
                    job.error_message = str(e)

                    if job.retry_count >= max_retries:
                        job.status = EvaluationJobStatus.failed
                        logger.error(
                            f"Evaluation job {job.id} failed after {max_retries} retries: {str(e)}"
                        )
                    else:
                        # Keep as pending for retry
                        job.status = EvaluationJobStatus.pending

                    db.commit()

            # Close and recreate session to avoid stale connections
            db.close()
            db = None

            # Sleep before next poll
            time.sleep(poll_interval)

        except Exception as e:
            logger.error(f"Unexpected error in job consumer: {str(e)}")
            if db:
                try:
                    db.close()
                except:
                    pass
            time.sleep(poll_interval)


def start_evaluation_job_consumer(daemon: bool = True):
    """
    Start the evaluation job consumer in a background thread.

    Args:
        daemon: If True, thread will be a daemon thread (default True)
    """
    consumer_thread = threading.Thread(
        target=process_evaluation_jobs, kwargs={"poll_interval": 5, "max_retries": 3}, daemon=daemon
    )
    consumer_thread.start()
    logger.info("Evaluation job consumer thread started")
    return consumer_thread
