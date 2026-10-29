"""PostgreSQL integration checks for the versioned relationship constraints.

Set AUDIT_TEST_DATABASE_URL only to a disposable database after running
``python -m db.migrate``. The tests roll back every row they create.
"""

import asyncio
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

DATABASE_URL = os.getenv("AUDIT_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="requires an explicitly configured disposable PostgreSQL database",
)


@pytest.fixture(scope="module")
def db_engine():
    url = make_url(DATABASE_URL)
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg2")
    engine = create_engine(url)
    if engine.dialect.name != "postgresql":
        pytest.skip("relationship migration checks require PostgreSQL")
    yield engine
    engine.dispose()


def test_required_relationship_columns_are_not_nullable(db_engine):
    inspector = inspect(db_engine)
    expected = {
        "batch_users": {"batch_id", "user_id"},
        "assessment_topics": {"assessment_id", "topic_id"},
        "assessment_questions": {"assessment_id"},
        "assessment_question_sections": {"assessment_id"},
        "assignments": {"assessment_id", "batch_id"},
        "attempts": {"user_id", "assessment_id"},
        "answers": {"attempt_id"},
    }
    for table, names in expected.items():
        columns = {column["name"]: column for column in inspector.get_columns(table)}
        assert all(not columns[name]["nullable"] for name in names), table


def test_relationship_owner_checks_and_uniqueness_indexes_exist(db_engine):
    inspector = inspect(db_engine)
    expected_checks = {
        "assessment_questions": "ck_assessment_questions_exactly_one_source",
        "assessment_question_sections": "ck_assessment_question_sections_exactly_one_source",
        "answers": "ck_answers_exactly_one_source",
        "question_embeddings": "ck_question_embeddings_exactly_one_owner",
    }
    for table, name in expected_checks.items():
        actual = {item["name"] for item in inspector.get_check_constraints(table)}
        assert name in actual, table

    expected_indexes = {
        "batch_users": "uq_batch_users_batch_user",
        "assessment_topics": "uq_assessment_topics_config",
        "assessment_questions": "uq_assessment_questions_position",
        "assignments": "uq_assignments_assessment_batch",
        "interview_response_evaluations": "uq_interview_response_session_turn",
        "attempts": "ix_attempts_user_status_started",
        "practice_tests": "ix_practice_tests_user_created",
        "interview_sessions": "ix_interview_sessions_user_status_created",
        "question_generation_batches": "ix_generation_batches_status_created",
    }
    with db_engine.connect() as connection:
        for table, name in expected_indexes.items():
            assert connection.execute(
                text("SELECT to_regclass(:index_name)"), {"index_name": name}
            ).scalar_one() is not None, table


def test_assessment_question_rejects_no_source(db_engine):
    """A link must identify exactly one bank question or embedded item."""
    assessment_id = uuid.uuid4()
    with db_engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(
                text("INSERT INTO assessments (id, title) VALUES (:id, :title)"),
                {"id": assessment_id, "title": "constraint regression"},
            )
            with pytest.raises(IntegrityError) as error:
                with connection.begin_nested():
                    connection.execute(
                        text("INSERT INTO assessment_questions (id, assessment_id) "
                             "VALUES (:id, :assessment_id)"),
                        {"id": uuid.uuid4(), "assessment_id": assessment_id},
                    )
            assert getattr(error.value.orig.diag, "constraint_name", None) == (
                "ck_assessment_questions_exactly_one_source"
            )
        finally:
            transaction.rollback()


def test_worker_recovery_requeues_interrupted_evaluation_and_fails_partial_generation(db_engine):
    from core.evaluation_service import _recover_interrupted_evaluation_jobs
    from core.question_generation import _recover_interrupted_generation_batches
    from db.models import Assessment, Attempt, AttemptStatus, EvaluationJob, EvaluationJobStatus, GenerationBatchStatus, QuestionGenerationBatch, User, UserRole
    suffix = uuid.uuid4().hex
    user = User(username=f"worker_recovery_{suffix}", email=f"worker_recovery_{suffix}@example.test", contact_email=f"worker_recovery_{suffix}@example.test", name="Worker Recovery Test", hashed_password="unused-test-hash", role=UserRole.user)
    assessment = Assessment(title="Worker recovery test", duration=10)
    generation = QuestionGenerationBatch(admin_id=None, source_text="test input", status=GenerationBatchStatus.processing)
    with Session(db_engine) as db:
        try:
            db.add_all([user, assessment]); db.flush()
            generation.admin_id = user.id
            attempt = Attempt(user_id=user.id, assessment_id=assessment.id, started_at=datetime.now(timezone.utc), status=AttemptStatus.in_progress)
            db.add_all([attempt, generation]); db.flush()
            job = EvaluationJob(attempt_id=attempt.id, status=EvaluationJobStatus.in_progress, started_at=datetime.now(timezone.utc))
            db.add(job); db.commit()
            assert _recover_interrupted_evaluation_jobs(db) == 1
            assert _recover_interrupted_generation_batches(db) == 1
            db.refresh(job); db.refresh(generation)
            assert job.status == EvaluationJobStatus.pending and job.started_at is None
            assert generation.status == GenerationBatchStatus.failed
            assert "Worker restarted" in generation.error_message
        finally:
            db.rollback()
            if generation.id:
                db.query(QuestionGenerationBatch).filter_by(id=generation.id).delete()
            if 'attempt' in locals() and attempt.id:
                db.query(EvaluationJob).filter_by(attempt_id=attempt.id).delete()
                db.query(Attempt).filter_by(id=attempt.id).delete()
            if assessment.id:
                db.query(Assessment).filter_by(id=assessment.id).delete()
            if user.id:
                db.query(User).filter_by(id=user.id).delete()
            db.commit()


def test_interview_pause_resume_persists_server_accounting(db_engine, monkeypatch):
    """Exercise pause/resume API handlers against PostgreSQL, including persisted counters."""
    import asyncio
    from api import routers_interviews
    from db.models import (
        InterviewAccessRequest, InterviewAccessStatus, InterviewRequestType,
        InterviewSession, InterviewSessionStatus, InterviewTemplate,
        User, UserRole,
    )

    suffix = uuid.uuid4().hex
    with Session(db_engine) as db:
        admin = User(username=f"pause_admin_{suffix}", email=f"pa_{suffix}@test.invalid",
                     contact_email=f"pa_{suffix}@test.invalid", name="Admin",
                     hashed_password="unused", role=UserRole.admin)
        candidate = User(username=f"pause_user_{suffix}", email=f"pu_{suffix}@test.invalid",
                         contact_email=f"pu_{suffix}@test.invalid", name="Candidate",
                         hashed_password="unused", role=UserRole.user)
        db.add_all([admin, candidate]); db.flush()
        template = InterviewTemplate(admin_id=admin.id, title="Pause test", role="Engineer",
                                     duration_minutes=30, question_count=1, is_active=True)
        db.add(template); db.flush()
        access = InterviewAccessRequest(user_id=candidate.id, template_id=template.id,
                                        status=InterviewAccessStatus.approved,
                                        request_type=InterviewRequestType.initial)
        db.add(access); db.flush()
        session = InterviewSession(user_id=candidate.id, template_id=template.id,
                                   access_request_id=access.id, status=InterviewSessionStatus.in_progress,
                                   started_at=datetime.now(timezone.utc), duration_seconds=1800,
                                   pause_count=0, max_pauses_allowed_snapshot=3)
        db.add(session); db.commit()
        user_id, admin_id, session_id, access_id, template_id = candidate.id, admin.id, session.id, access.id, template.id

    monkeypatch.setattr(routers_interviews, "SessionLocal", lambda: Session(db_engine))
    current_user = type("CurrentUser", (), {"id": user_id})()
    try:
        asyncio.run(routers_interviews.pause_interview(session_id, current_user))
        with Session(db_engine) as db:
            persisted = db.get(InterviewSession, session_id)
            assert persisted.status == InterviewSessionStatus.paused
            assert persisted.pause_count == 1
            assert persisted.paused_at is not None
        asyncio.run(routers_interviews.resume_interview(session_id, current_user))
        with Session(db_engine) as db:
            persisted = db.get(InterviewSession, session_id)
            assert persisted.status == InterviewSessionStatus.in_progress
            assert persisted.pause_count == 1
            assert persisted.paused_at is None
            assert persisted.resumed_at is not None
    finally:
        with Session(db_engine) as db:
            db.query(InterviewSession).filter_by(id=session_id).delete()
            db.query(InterviewAccessRequest).filter_by(id=access_id).delete()
            db.query(InterviewTemplate).filter_by(id=template_id).delete()
            db.query(User).filter(User.id.in_([user_id, admin_id])).delete(synchronize_session=False)
            db.commit()


def test_integrity_event_endpoint_deduplicates_and_aborts_on_fifth_exit(db_engine, monkeypatch):
    import asyncio
    from api import routers_user_assessments
    from db.models import Attempt, AttemptStatus, Assessment, EvaluationJob, User, UserRole

    suffix = uuid.uuid4().hex
    with Session(db_engine) as db:
        user = User(username=f"event_{suffix}", email=f"event_{suffix}@test.invalid",
                    contact_email=f"event_{suffix}@test.invalid", name="Candidate",
                    hashed_password="unused", role=UserRole.user)
        assessment = Assessment(title="Integrity event test", duration=10)
        db.add_all([user, assessment]); db.flush()
        attempt = Attempt(user_id=user.id, assessment_id=assessment.id,
                          status=AttemptStatus.in_progress, tab_violations=0)
        db.add(attempt); db.commit()
        user_id, attempt_id, assessment_id = user.id, attempt.id, assessment.id

    monkeypatch.setattr(routers_user_assessments, "SessionLocal", lambda: Session(db_engine))
    candidate = type("CurrentUser", (), {"id": user_id})()
    try:
        request = routers_user_assessments.IntegrityEventRequest(event_id=uuid.uuid4(), event_type="focus_lost")
        async def duplicate_request_race():
            return await asyncio.gather(
                routers_user_assessments.save_violations(attempt_id, request, candidate),
                routers_user_assessments.save_violations(attempt_id, request, candidate),
            )
        first, duplicate = asyncio.run(duplicate_request_race())
        escape = asyncio.run(routers_user_assessments.save_violations(
            attempt_id,
            routers_user_assessments.IntegrityEventRequest(event_id=uuid.uuid4(), event_type="escape_key"),
            candidate,
        ))
        assert {first["status"], duplicate["status"]} == {"saved", "duplicate"}
        assert first["violations"] == duplicate["violations"] == 1
        assert escape == {"status": "saved", "violations": 1}
        for _ in range(4):
            event = routers_user_assessments.IntegrityEventRequest(
                event_id=uuid.uuid4(), event_type="focus_lost"
            )
            final = asyncio.run(routers_user_assessments.save_violations(attempt_id, event, candidate))
        assert final == {"status": "aborted", "violations": 5}
        with Session(db_engine) as db:
            persisted = db.get(Attempt, attempt_id)
            assert persisted.status == AttemptStatus.missed
            assert persisted.tab_violations == 5
            assert db.query(EvaluationJob).filter_by(attempt_id=attempt_id).count() == 1
    finally:
        with Session(db_engine) as db:
            db.query(EvaluationJob).filter_by(attempt_id=attempt_id).delete()
            db.query(Attempt).filter_by(id=attempt_id).delete()
            db.query(Assessment).filter_by(id=assessment_id).delete()
            db.query(User).filter_by(id=user_id).delete()
            db.commit()


def test_offline_sync_applies_only_within_same_attempt_grace_and_is_idempotent(db_engine, monkeypatch):
    import asyncio
    from datetime import datetime, timedelta, timezone
    from api import routers_user_assessments
    from db.models import (
        Answer, Assessment, AssessmentQuestion, AssessmentQuestionItem, Attempt,
        AttemptStatus, EvaluationJob, EvaluationJobStatus, User, UserRole,
    )

    suffix = uuid.uuid4().hex
    with Session(db_engine) as db:
        user = User(username=f"offline_{suffix}", email=f"offline_{suffix}@test.invalid",
                    contact_email=f"offline_{suffix}@test.invalid", name="Candidate",
                    hashed_password="unused", role=UserRole.user)
        assessment = Assessment(title="Offline sync test", duration=10)
        db.add_all([user, assessment]); db.flush()
        item = AssessmentQuestionItem(
            assessment_id=assessment.id, question_type="single_mcq",
            question_text="Example_Data option question", options=[],
        )
        db.add(item); db.flush()
        db.add(AssessmentQuestion(
            assessment_id=assessment.id, assessment_item_id=item.id, position=0,
        ))
        attempt = Attempt(
            user_id=user.id, assessment_id=assessment.id,
            status=AttemptStatus.completed,
            submitted_at=datetime.now(timezone.utc),
            sync_deadline_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        db.add(attempt); db.flush()
        job = EvaluationJob(attempt_id=attempt.id, status=EvaluationJobStatus.pending)
        db.add(job); db.commit()
        user_id, attempt_id, assessment_id, item_id = user.id, attempt.id, assessment.id, item.id

    monkeypatch.setattr(routers_user_assessments, "SessionLocal", lambda: Session(db_engine))
    candidate = type("CurrentUser", (), {"id": user_id})()
    try:
        payload = routers_user_assessments.SubmitAssessmentRequest(answers=[
            routers_user_assessments.SubmitAnswerRequest(question_id=item_id, answer="example-option-b")
        ])
        first = asyncio.run(routers_user_assessments.sync_offline_assessment_answers(
            attempt_id, payload, candidate
        ))
        retried = asyncio.run(routers_user_assessments.sync_offline_assessment_answers(
            attempt_id,
            routers_user_assessments.SubmitAssessmentRequest(answers=[
                routers_user_assessments.SubmitAnswerRequest(question_id=item_id, answer="stale-value")
            ]),
            candidate,
        ))
        assert first["status"] == retried["status"] == "finished"
        with Session(db_engine) as db:
            persisted = db.query(Answer).filter_by(attempt_id=attempt_id).one()
            assert persisted.answer == "example-option-b"
            assert db.get(Attempt, attempt_id).sync_deadline_at is None
            assert db.query(EvaluationJob).filter_by(attempt_id=attempt_id).one().status == EvaluationJobStatus.pending
    finally:
        with Session(db_engine) as db:
            db.query(EvaluationJob).filter_by(attempt_id=attempt_id).delete()
            db.query(Answer).filter_by(attempt_id=attempt_id).delete()
            db.query(Attempt).filter_by(id=attempt_id).delete()
            db.query(AssessmentQuestion).filter_by(assessment_id=assessment_id).delete()
            db.query(AssessmentQuestionItem).filter_by(id=item_id).delete()
            db.query(Assessment).filter_by(id=assessment_id).delete()
            db.query(User).filter_by(id=user_id).delete()
            db.commit()


def test_evaluation_worker_advisory_lock_releases_after_connection_crash(db_engine):
    # A live worker may already own the production key in this test database.
    # Use an isolated key to test PostgreSQL's connection-scoped lock behavior.
    lock_id = uuid.uuid4().int & 0x7FFFFFFF

    owner = db_engine.connect()
    contender = db_engine.connect()
    try:
        assert owner.execute(
            text("SELECT pg_try_advisory_lock(:lock_id)"),
            {"lock_id": lock_id},
        ).scalar_one()
        owner.commit()
        assert not contender.execute(
            text("SELECT pg_try_advisory_lock(:lock_id)"),
            {"lock_id": lock_id},
        ).scalar_one()
        contender.commit()

        # Drop the owning DB connection without sending pg_advisory_unlock,
        # matching the lock-release behavior after a worker process crash.
        owner.invalidate()
        assert contender.execute(
            text("SELECT pg_try_advisory_lock(:lock_id)"),
            {"lock_id": lock_id},
        ).scalar_one()
        contender.commit()
        contender.execute(
            text("SELECT pg_advisory_unlock(:lock_id)"),
            {"lock_id": lock_id},
        )
        contender.commit()
    finally:
        owner.close()
        contender.close()


def test_practice_generation_queue_persists_claim_and_recovers_after_restart(db_engine):
    from core.practice_generation import (
        _claim_next_practice_test,
        _recover_interrupted_practice_tests,
    )
    from db.models import PracticeTest, PracticeTestStatus, User, UserRole

    suffix = uuid.uuid4().hex
    user = User(
        username=f"practice_queue_{suffix}",
        email=f"practice_queue_{suffix}@example.test",
        contact_email=f"practice_queue_{suffix}@example.test",
        name="Practice Queue Test",
        hashed_password="unused-test-hash",
        role=UserRole.user,
    )
    test = PracticeTest(
        user=user,
        job_title="Queue recovery",
        difficulty="easy",
        question_count=10,
        status=PracticeTestStatus.generating,
    )

    with Session(db_engine) as db:
        try:
            db.add(test)
            db.commit()

            assert _claim_next_practice_test(db) == test.id
            db.refresh(test)
            assert test.generation_claimed_at is not None
            assert _claim_next_practice_test(db) is None

            assert _recover_interrupted_practice_tests(db) == 1
            db.refresh(test)
            assert test.generation_claimed_at is None
            assert test.status == PracticeTestStatus.generating
            assert _claim_next_practice_test(db) == test.id
        finally:
            db.rollback()
            if test.id is not None:
                db.query(PracticeTest).filter_by(id=test.id).delete()
            if user.id is not None:
                db.query(User).filter_by(id=user.id).delete()
            db.commit()


def test_database_rejects_duplicate_active_attempt_and_interview_turn(db_engine):
    from db.models import (
        Assessment,
        Attempt,
        AttemptStatus,
        InterviewAccessRequest,
        InterviewResponseEvaluation,
        InterviewSession,
        InterviewTemplate,
        User,
        UserRole,
    )

    suffix = uuid.uuid4().hex
    user = User(
        username=f"db_invariants_{suffix}",
        email=f"db_invariants_{suffix}@example.test",
        contact_email=f"db_invariants_{suffix}@example.test",
        name="Database Invariants Test",
        hashed_password="unused-test-hash",
        role=UserRole.user,
    )
    assessment = Assessment(title="Attempt race invariant", duration=10)
    template = InterviewTemplate(
        admin_id=None,
        title="Turn race invariant",
        role="Engineer",
    )

    with db_engine.connect() as connection:
        outer = connection.begin()
        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            try:
                db.add(user)
                db.flush()
                template.admin_id = user.id
                db.add_all([assessment, template])
                db.flush()

                db.add(Attempt(
                    user_id=user.id,
                    assessment_id=assessment.id,
                    status=AttemptStatus.in_progress,
                ))
                db.flush()
                with pytest.raises(IntegrityError) as duplicate_attempt:
                    with db.begin_nested():
                        db.add(Attempt(
                            user_id=user.id,
                            assessment_id=assessment.id,
                            status=AttemptStatus.in_progress,
                        ))
                        db.flush()
                assert getattr(duplicate_attempt.value.orig.diag, "constraint_name", None) == (
                    "uq_active_attempt_assessment_user"
                )

                access = InterviewAccessRequest(user_id=user.id, template_id=template.id)
                db.add(access)
                db.flush()
                session = InterviewSession(
                    user_id=user.id,
                    template_id=template.id,
                    access_request_id=access.id,
                )
                db.add(session)
                db.flush()
                db.add(InterviewResponseEvaluation(session_id=session.id, turn_index=1))
                db.flush()
                with pytest.raises(IntegrityError) as duplicate_turn:
                    with db.begin_nested():
                        db.add(InterviewResponseEvaluation(session_id=session.id, turn_index=1))
                        db.flush()
                assert getattr(duplicate_turn.value.orig.diag, "constraint_name", None) == (
                    "uq_interview_response_session_turn"
                )
            finally:
                db.rollback()
                outer.rollback()


def test_practice_daily_quota_serializes_concurrent_creation(db_engine, monkeypatch):
    from types import SimpleNamespace
    from sqlalchemy.orm import sessionmaker

    from api import routers_practice
    from db.models import (
        PracticeAccessRequest,
        PracticeAccessStatus,
        PracticeTest,
        User,
        UserRole,
    )

    suffix = uuid.uuid4().hex
    user = User(
        username=f"quota_race_{suffix}",
        email=f"quota_race_{suffix}@example.test",
        contact_email=f"quota_race_{suffix}@example.test",
        name="Quota Race Test",
        hashed_password="unused-test-hash",
        role=UserRole.user,
    )
    access = PracticeAccessRequest(
        user=user,
        status=PracticeAccessStatus.approved,
        requested_tests_per_day=1,
        tests_per_day_granted=1,
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
    )

    with Session(db_engine) as db:
        try:
            db.add_all([user, access])
            db.commit()
            user_id = user.id
        finally:
            db.rollback()

    monkeypatch.setattr(routers_practice, "SessionLocal", sessionmaker(bind=db_engine))
    monkeypatch.setenv("PRACTICE_TESTS_PER_DAY", "1")
    monkeypatch.setenv("PRACTICE_TESTS_MAX_PER_DAY", "3")

    async def create_one():
        return await routers_practice.create_practice_test(
            job_title="Concurrent quota test",
            difficulty="easy",
            topics="",
            job_description="",
            question_count=10,
            resume=None,
            current_user=SimpleNamespace(id=user_id),
        )

    async def create_two_concurrently():
        return await asyncio.gather(create_one(), create_one(), return_exceptions=True)

    try:
        outcomes = asyncio.run(create_two_concurrently())
        assert sum(not isinstance(item, Exception) for item in outcomes) == 1
        failures = [item for item in outcomes if isinstance(item, Exception)]
        assert len(failures) == 1
        assert getattr(failures[0], "status_code", None) == 400

        with Session(db_engine) as db:
            assert db.query(PracticeTest).filter(PracticeTest.user_id == user_id).count() == 1
    finally:
        with Session(db_engine) as db:
            db.query(PracticeTest).filter(PracticeTest.user_id == user_id).delete()
            db.query(PracticeAccessRequest).filter(PracticeAccessRequest.user_id == user_id).delete()
            db.query(User).filter(User.id == user_id).delete()
            db.commit()


def test_concurrent_interview_retry_persists_only_one_turn(db_engine, monkeypatch):
    from types import SimpleNamespace
    from sqlalchemy.orm import sessionmaker
    from fastapi import HTTPException

    from api import routers_interviews
    from db.models import (
        InterviewAccessRequest,
        InterviewResponseEvaluation,
        InterviewSession,
        InterviewSessionStatus,
        InterviewTemplate,
        User,
        UserRole,
    )

    suffix = uuid.uuid4().hex
    user = User(
        username=f"interview_race_{suffix}",
        email=f"interview_race_{suffix}@example.test",
        contact_email=f"interview_race_{suffix}@example.test",
        name="Interview Race Test",
        hashed_password="unused-test-hash",
        role=UserRole.user,
    )
    template = InterviewTemplate(
        admin_id=None,
        title="Turn race test",
        role="Engineer",
        focus_areas=["problem solving"],
    )
    with Session(db_engine) as db:
        db.add(user)
        db.flush()
        template.admin_id = user.id
        db.add(template)
        db.flush()
        access = InterviewAccessRequest(user_id=user.id, template_id=template.id)
        db.add(access)
        db.flush()
        interview = InterviewSession(
            user_id=user.id,
            template_id=template.id,
            access_request_id=access.id,
            status=InterviewSessionStatus.in_progress,
            started_at=datetime.now(timezone.utc),
            duration_seconds=600,
            transcript=[{"role": "assistant", "content": "Opening question"}],
            feedback={"turns": []},
        )
        db.add(interview)
        db.commit()
        user_id, session_id, template_id, access_id = user.id, interview.id, template.id, access.id

    rendezvous = threading.Barrier(2)

    def stub_evaluation(*_args, **_kwargs):
        rendezvous.wait(timeout=10)
        return {
            "score": 7,
            "strengths": ["Clear reasoning"],
            "improvements": ["Add an example"],
            "feedback": "Good answer",
            "next_question": "What tradeoff would you choose?",
            "raw": "{}",
        }

    monkeypatch.setattr(routers_interviews, "SessionLocal", sessionmaker(bind=db_engine))
    monkeypatch.setattr(routers_interviews, "evaluate_and_generate_followup", stub_evaluation)

    async def post_same_answer_twice():
        payload = routers_interviews.InterviewMessageIn(response_text="My answer")
        user_context = SimpleNamespace(id=user_id)
        return await asyncio.gather(
            routers_interviews.interview_message(session_id, payload, user_context),
            routers_interviews.interview_message(session_id, payload, user_context),
            return_exceptions=True,
        )

    try:
        outcomes = asyncio.run(post_same_answer_twice())
        assert sum(not isinstance(item, Exception) for item in outcomes) == 1
        failures = [item for item in outcomes if isinstance(item, Exception)]
        assert len(failures) == 1
        assert isinstance(failures[0], HTTPException)
        assert failures[0].status_code == 409

        with Session(db_engine) as db:
            persisted = db.query(InterviewSession).filter_by(id=session_id).one()
            assert [item["role"] for item in persisted.transcript] == [
                "assistant", "user", "assistant"
            ]
            assert len(persisted.feedback["turns"]) == 1
            assert db.query(InterviewResponseEvaluation).filter_by(
                session_id=session_id
            ).count() == 1
    finally:
        with Session(db_engine) as db:
            db.query(InterviewResponseEvaluation).filter_by(session_id=session_id).delete()
            db.query(InterviewSession).filter_by(id=session_id).delete()
            db.query(InterviewAccessRequest).filter_by(id=access_id).delete()
            db.query(InterviewTemplate).filter_by(id=template_id).delete()
            db.query(User).filter_by(id=user_id).delete()
            db.commit()
