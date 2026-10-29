"""Deterministic application scenarios using SQLite or isolated PostgreSQL schemas."""

import asyncio
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from openpyxl import Workbook

pytest.importorskip("sqlalchemy", reason="Run local regressions with the backend Python environment")
pytest.importorskip("langchain_ollama", reason="Restore backend dependencies with uv sync --extra local")

pytestmark = pytest.mark.regression


def call(function, *args, **kwargs):
    return asyncio.run(function(*args, **kwargs))


@pytest.fixture
def scenario_engine():
    from sqlalchemy import create_engine, event
    from sqlalchemy.engine import make_url
    from sqlalchemy.schema import CreateSchema, DropSchema
    from sqlalchemy.pool import StaticPool

    database_url = os.getenv("REALWORLD_TEST_DATABASE_URL")
    admin_engine = None
    schema = None
    if database_url:
        url = make_url(database_url)
        if url.get_backend_name() != "postgresql":
            raise ValueError("REALWORLD_TEST_DATABASE_URL must point to a disposable PostgreSQL database")
        url = url.set(drivername="postgresql+psycopg2")
        schema = f"realworld_{uuid4().hex}"
        admin_engine = create_engine(url)
        with admin_engine.begin() as connection:
            connection.execute(CreateSchema(schema))
        engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    else:
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

        @event.listens_for(engine, "connect")
        def enforce_foreign_keys(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")

    try:
        yield engine
    finally:
        engine.dispose()
        if admin_engine is not None:
            try:
                with admin_engine.begin() as connection:
                    connection.execute(DropSchema(schema, cascade=True))
            finally:
                admin_engine.dispose()


@pytest.fixture
def application(monkeypatch, scenario_engine):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "backend"))
    monkeypatch.setenv("JWT_SECRET_KEY", "isolated-regression-test-key")
    from sqlalchemy.orm import sessionmaker
    from db import models as m
    from db import database, async_helpers
    from api import routers_admin, routers_assessments, routers_auth, routers_interviews
    from api import routers_practice, routers_questions, routers_user_assessments
    from core import evaluation_service
    from core import practice_generation

    engine = scenario_engine
    m.Base.metadata.create_all(
        engine, tables=[table for table in m.Base.metadata.sorted_tables if table.name != "question_embeddings"]
    )
    sessions = sessionmaker(bind=engine, expire_on_commit=False)

    async def inline(callback, *args):
        return callback(*args)

    monkeypatch.setattr(database, "SessionLocal", sessions)
    monkeypatch.setattr(async_helpers, "run_db_sync", inline)
    for module in (
        routers_admin, routers_assessments, routers_auth, routers_interviews,
        routers_practice, routers_questions, routers_user_assessments, evaluation_service,
        practice_generation,
    ):
        monkeypatch.setattr(module, "SessionLocal", sessions)
        if hasattr(module, "run_db_sync"):
            monkeypatch.setattr(module, "run_db_sync", inline)
    monkeypatch.setattr(routers_auth, "get_password_hash", lambda password: f"test-only:{password}")
    monkeypatch.setattr(routers_interviews, "generate_opening_question", lambda *_args, **_kwargs: "Explain transactions.")
    monkeypatch.setattr(
        evaluation_service, "get_chat_model",
        lambda: pytest.fail("A deterministic regression must not call an external model"),
    )

    db = sessions()
    user = m.User(
        username="scenario-user", email="user@example.test", contact_email="contact@example.test",
        name="Scenario User", hashed_password="not-a-login-credential", role=m.UserRole.user,
    )
    topic = m.Topic(name="Databases")
    db.add_all([user, topic])
    db.commit()
    yield SimpleNamespace(
        db=db, sessions=sessions, models=m, user=user, topic=topic,
        admin=routers_admin, assessments=routers_assessments, auth=routers_auth,
        interviews=routers_interviews, practice=routers_practice, questions=routers_questions,
        user_assessments=routers_user_assessments, evaluation=evaluation_service,
    )
    db.close()


def question_bank(app, count=2, question_type="single_mcq"):
    m = app.models
    questions = []
    for index in range(count):
        question = m.Question(
            topic_id=app.topic.id, question=f"Question {index}", type=m.QuestionType(question_type),
            difficulty=m.Difficulty.easy, reference_answer="Reference",
        )
        app.db.add(question)
        app.db.flush()
        if question_type == "single_mcq":
            app.db.add_all([
                m.QuestionOption(question_id=question.id, option_text="Correct", is_correct=True),
                m.QuestionOption(question_id=question.id, option_text="Wrong", is_correct=False),
            ])
        questions.append(question)
    app.db.commit()
    return questions


def assessment(app, sections=1, question_type="single_mcq", negative=False):
    return call(app.assessments.create_assessment, app.assessments.CreateAssessmentRequest(
        title="Real-world scenario", duration=30, negative_marking=negative, user_ids=[app.user.id],
        topics=[
            app.assessments.TopicConfig(
                topic_id=app.topic.id, question_type=question_type, difficulty="easy",
                question_count=1, section_name=f"Section {index + 1}",
            )
            for index in range(sections)
        ],
    ), app.user)


def upload(app, rows):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Candidate questions"
    sheet.append(["type", "question", "topic", "difficulty", "option_a", "option_b", "option_c", "correct_options"])
    for row in rows:
        sheet.append(row)
    content = BytesIO()
    workbook.save(content)
    content.seek(0)
    from fastapi import UploadFile
    return call(app.admin.import_assessment_excel, UploadFile(filename="scenario.xlsx", file=content), app.user)


def create_import(app, imported):
    return call(app.admin.create_assessment_from_import, app.admin.CreateFromImportIn(
        import_id=imported["import_id"], title="Imported scenario", user_ids=[app.user.id],
    ), app.user)


def interview_access(app):
    m = app.models
    template = m.InterviewTemplate(admin_id=app.user.id, title="Scenario interview", role="Developer", duration_minutes=1)
    app.db.add(template)
    app.db.flush()
    request = m.InterviewAccessRequest(
        user_id=app.user.id, template_id=template.id, status=m.InterviewAccessStatus.approved,
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
    )
    app.db.add(request)
    app.db.commit()
    return template, request


def test_repeated_pool_across_sections_is_aggregated_without_duplicate_questions(application):
    app = application
    question_bank(app, 3)
    result = assessment(app, sections=2)
    configs = app.db.query(app.models.AssessmentTopic).all()
    links = app.db.query(app.models.AssessmentQuestion).all()
    assert len(configs) == 1
    assert configs[0].question_count == 2
    assert len({link.question_id for link in links}) == 2
    assert sorted(link.position for link in links) == [0, 1]
    assert {topic.section_name for topic in result.topics} == {"Section 1", "Section 2"}


def test_question_edit_preserves_active_answers_and_historical_grading(application):
    app = application
    question = question_bank(app, 1)[0]
    created = assessment(app)
    started = call(app.user_assessments.start_assessment, created.id, app.user)
    option_id = next(option.id for option in question.options if option.is_correct)
    call(app.user_assessments.save_answer, app.user_assessments.SubmitAnswerRequest(
        question_id=question.id, answer=str(option_id),
    ), started.attempt_id, app.user)
    edited = call(app.questions.update_question, question.id, app.questions.QuestionUpdateIn(
        question="A changed question", options=[
            app.questions.OptionIn(text="New correct", is_correct=True),
            app.questions.OptionIn(text="New wrong", is_correct=False),
        ],
    ), app.user)
    assert edited.id != question.id
    resumed = call(app.user_assessments.start_assessment, created.id, app.user)
    assert resumed.questions[0].question == question.question
    assert resumed.saved_answers[0].answer == str(option_id)
    call(app.user_assessments.submit_assessment, started.attempt_id,
         app.user_assessments.SubmitAssessmentRequest(answers=[]), app.user)
    app.evaluation.evaluate_attempt_from_job(app.db, started.attempt_id)
    app.db.expire_all()
    assert app.db.get(app.models.Attempt, started.attempt_id).score == 100
    assert app.db.get(app.models.Question, question.id).is_archived
    assert app.db.get(app.models.QuestionOption, option_id).option_text == "Correct"
    newer = assessment(app)
    new_start = call(app.user_assessments.start_assessment, newer.id, app.user)
    assert new_start.questions[0].id == edited.id


def test_failed_question_edit_rolls_back_version_and_archive(application):
    from fastapi import HTTPException
    app = application
    question = question_bank(app, 1)[0]
    assessment(app)
    with pytest.raises(HTTPException):
        call(app.questions.update_question, question.id,
             app.questions.QuestionUpdateIn(question=" "), app.user)
    app.db.expire_all()
    assert app.db.query(app.models.Question).count() == 1
    assert not app.db.get(app.models.Question, question.id).is_archived


@pytest.mark.parametrize("topic", [None, "Not in the global bank", "Databases"])
def test_imported_topics_do_not_require_global_bank_records(application, topic):
    app = application
    imported = upload(app, [["single_mcq", "Choose", topic, "easy", "Business", "Other", None, "Business"]])
    assert imported["errors"] == []
    create_import(app, imported)
    assert app.db.query(app.models.AssessmentQuestionItem).one().topic == topic
    assert app.db.query(app.models.Topic).count() == 1
    configs = app.db.query(app.models.AssessmentTopic).all()
    assert len(configs) == (1 if topic == "Databases" else 0)


@pytest.mark.parametrize(
    "answer,expected",
    [("A B", ["A", "B"]), ("A|B", ["A", "B"]), ("A; B", ["A", "B"]),
     ("Business", ["A"]), ("Operating system", ["B"]), ("Business|Operating system", ["A", "B"])],
)
def test_import_answer_separators_and_whole_option_text(application, answer, expected):
    app = application
    imported = upload(app, [["multi_mcq", "Choose", None, "easy", "Business", "Operating system", None, answer]])
    assert imported["errors"] == []
    row = app.db.query(app.models.ImportedQuestion).one()
    assert row.correct_answers == expected
    create_import(app, imported)
    item = app.db.query(app.models.AssessmentQuestionItem).one()
    assert sum(bool(option["is_correct"]) for option in item.options) == len(expected)


def test_import_option_gaps_keep_the_correct_letter_mapping(application):
    app = application
    imported = upload(app, [["single_mcq", "Choose C", None, "easy", "Wrong", None, "Right", "C"]])
    create_import(app, imported)
    item = app.db.query(app.models.AssessmentQuestionItem).one()
    assert [option["option_text"] for option in item.options if option["is_correct"]] == ["Right"]


@pytest.mark.parametrize("kind,difficulty,key", [
    ("single_mcq", "easy", None), ("single_mcq", "easy", "A B"),
    ("multi_mcq", "easy", "D"), ("coding", "easy", None),
    ("unknown", "easy", None), ("single_mcq", "impossible", "A"),
])
def test_invalid_import_rows_have_actionable_errors_and_cannot_create_tests(application, kind, difficulty, key):
    from fastapi import HTTPException
    app = application
    imported = upload(app, [[kind, "Invalid question", None, difficulty, "One", "Two", None, key]])
    assert imported["errors"]
    assert imported["preview"]["total_questions"] == 0
    assert not app.db.query(app.models.ImportedQuestion).one().validated
    with pytest.raises(HTTPException) as exc:
        create_import(app, imported)
    assert exc.value.status_code == 400
    assert app.db.query(app.models.Assessment).count() == 0


def test_mixed_import_skips_invalid_rows_and_legacy_imports_are_revalidated(application):
    from fastapi import HTTPException
    app = application
    imported = upload(app, [
        ["single_mcq", "Valid", None, "easy", "One", "Two", None, "A"],
        ["coding", "No test cases", None, "easy", None, None, None, None],
    ])
    assert imported["errors"] and imported["preview"]["total_questions"] == 1
    bad = app.db.query(app.models.ImportedQuestion).filter_by(question_type="coding").one()
    bad.validated = True
    app.db.commit()
    with pytest.raises(HTTPException) as exc:
        create_import(app, imported)
    assert exc.value.status_code == 400
    assert app.db.query(app.models.Assessment).count() == 0
    bad.validated = False
    app.db.commit()
    create_import(app, imported)
    assert app.db.query(app.models.AssessmentQuestionItem).count() == 1


@pytest.mark.parametrize("negative,expected", [(False, 50.0), (True, 0.0)])
def test_partial_attempt_scores_agree_in_all_reports(application, negative, expected):
    app = application
    question_bank(app, 2)
    created = assessment(app, sections=2, negative=negative)
    started = call(app.user_assessments.start_assessment, created.id, app.user)
    first = app.db.get(app.models.Question, started.questions[0].id)
    correct = next(option for option in first.options if option.is_correct)
    payload = [app.user_assessments.SubmitAnswerRequest(question_id=first.id, answer=str(correct.id))]
    if negative:
        second = app.db.get(app.models.Question, started.questions[1].id)
        wrong = next(option for option in second.options if not option.is_correct)
        payload.append(app.user_assessments.SubmitAnswerRequest(question_id=second.id, answer=str(wrong.id)))
    call(app.user_assessments.submit_assessment, started.attempt_id,
         app.user_assessments.SubmitAssessmentRequest(answers=payload), app.user)
    app.evaluation.evaluate_attempt_from_job(app.db, started.attempt_id)
    app.db.expire_all()
    attempt = app.db.get(app.models.Attempt, started.attempt_id)
    assert attempt.score == expected
    assert app.db.query(app.models.TopicScore).one().score == expected
    topic = app.assessments._calculate_topic_performance(app.db, created.id, [attempt])[0]
    assert topic.total_questions == 2 and topic.percentage == expected
    for report in (
        call(app.user_assessments.get_my_performance, app.user),
        call(app.admin.get_user_performance, app.user.id, app.user),
    ):
        payload = report if isinstance(report, dict) else report.model_dump()
        assert payload["topic_performance"][0]["average_percentage"] == expected
    admin_topics = call(app.admin.get_attempt_topic_scores, started.attempt_id, app.user)
    admin_results = call(app.admin.get_attempt_results, started.attempt_id, app.user)
    assert admin_topics["topic_scores"][0]["percentage"] == expected
    assert admin_results["topic_scores"][0]["percentage"] == expected


@pytest.mark.parametrize("days_ago,allowed", [(30, True), (0, False)])
def test_registration_resubmission_obeys_cooldown_without_duplicate_rows(application, days_ago, allowed):
    from fastapi import HTTPException
    app = application
    m = app.models
    rejected = m.RegistrationRequest(
        username="reapply", email="reapply@example.test", contact_email="reapply-contact@example.test",
        name="Candidate", hashed_password="old", status=m.RegistrationStatus.rejected,
        resolved_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
    )
    app.db.add(rejected)
    app.db.commit()
    payload = app.auth.UserRegister(
        username=rejected.username, email=rejected.email, contact_email=rejected.contact_email,
        name="Updated candidate", password="new-test-password",
    )
    if not allowed:
        with pytest.raises(HTTPException) as exc:
            call(app.auth.register, payload)
        assert exc.value.status_code == 400
    else:
        call(app.auth.register, payload)
        app.db.refresh(rejected)
        assert rejected.status == m.RegistrationStatus.pending and rejected.resolved_at is None
        assert rejected.hashed_password == "test-only:new-test-password"
        with pytest.raises(HTTPException) as exc:
            call(app.auth.register, payload)
        assert exc.value.status_code == 400
    assert app.db.query(m.RegistrationRequest).count() == 1


@pytest.mark.parametrize("prior_status", ["completed", "missed", "abandoned"])
def test_admin_approved_interview_retry_is_usable_exactly_once(application, prior_status):
    from fastapi import HTTPException
    app = application
    m = app.models
    template, grant = interview_access(app)
    app.db.add(m.InterviewSession(
        user_id=app.user.id, template_id=template.id, access_request_id=grant.id,
        status=m.InterviewSessionStatus(prior_status), attempt_number=1,
    ))
    app.db.commit()
    call(app.interviews.request_retry, app.interviews.InterviewAccessRequestIn(template_id=template.id), app.user)
    retry = app.db.query(m.InterviewAccessRequest).filter_by(request_type=m.InterviewRequestType.retry).one()
    call(app.interviews.approve_access_request, retry.id, app.interviews.ApproveInterviewAccessIn(days=1), app.user)
    started = call(app.interviews.start_interview, app.interviews.InterviewStartIn(template_id=template.id), app.user)
    assert started.attempt_number == 2
    with pytest.raises(HTTPException):
        call(app.interviews.start_interview, app.interviews.InterviewStartIn(template_id=template.id), app.user)
    assert app.db.query(m.InterviewSession).count() == 2
    assert all(row["used"] for row in call(app.interviews.my_requests, app.user))
    call(app.interviews.end_interview, started.id, app.user)
    with pytest.raises(HTTPException) as exc:
        call(app.interviews.start_interview, app.interviews.InterviewStartIn(template_id=template.id), app.user)
    assert exc.value.status_code == 403


def test_interview_time_limit_and_duplicate_end_requests_complete_normally(application):
    app = application
    template, _grant = interview_access(app)
    started = call(app.interviews.start_interview, app.interviews.InterviewStartIn(template_id=template.id), app.user)
    session = app.db.get(app.models.InterviewSession, started.id)
    session.started_at = datetime.now(timezone.utc) - timedelta(seconds=61)
    app.db.commit()
    call(app.interviews.end_interview, started.id, app.user)
    call(app.interviews.end_interview, started.id, app.user)
    result = call(app.interviews.get_my_result, started.id, app.user)
    assert result["status"] == "completed" and result["remaining_seconds"] == 0


def test_interview_answer_accepted_before_end_keeps_its_delayed_evaluation(application, monkeypatch):
    app = application
    template, _grant = interview_access(app)
    started = call(app.interviews.start_interview, app.interviews.InterviewStartIn(template_id=template.id), app.user)

    def finish_while_evaluating(*_args, **_kwargs):
        with app.sessions() as db:
            session = db.get(app.models.InterviewSession, started.id)
            session.status = app.models.InterviewSessionStatus.completed
            db.commit()
        return {"score": 8, "feedback": "Good answer", "next_question": "Next question"}

    monkeypatch.setattr(app.interviews, "evaluate_and_generate_followup", finish_while_evaluating)
    call(app.interviews.interview_message, started.id,
         app.interviews.InterviewMessageIn(response_text="An atomic unit of work"), app.user)
    assert app.db.query(app.models.InterviewResponseEvaluation).count() == 1
    app.db.expire_all()
    assert app.db.get(app.models.InterviewSession, started.id).total_score == 80


def test_previous_day_practice_resume_preserves_saved_answers_and_is_idempotent(application):
    app = application
    m = app.models
    test = m.PracticeTest(
        user_id=app.user.id, job_title="Yesterday's practice", difficulty="easy", question_count=1,
        status=m.PracticeTestStatus.ready, created_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    app.db.add(test)
    app.db.flush()
    question = m.PracticeQuestion(
        practice_test_id=test.id, position=0, type="single_mcq", question="Choose",
        options=json.dumps([{"text": "Correct"}, {"text": "Wrong"}]), correct_answer='["Correct"]',
    )
    app.db.add(question)
    app.db.commit()
    call(app.practice.start_practice_test, test.id, app.user)
    call(app.practice.save_practice_answer, test.id,
         app.practice.SavePracticeAnswerIn(question_id=question.id, answer="Correct"), app.user)
    restored = call(app.practice.get_practice_test, test.id, app.user)
    assert restored["saved_answers"] == {str(question.id): "Correct"}
    payload = app.practice.SubmitPracticeIn(answers=[
        app.practice.SubmitAnswerItem(question_id=str(question.id), answer="Correct"),
    ])
    call(app.practice.submit_practice_test, test.id, payload, app.user)
    call(app.practice.submit_practice_test, test.id, payload, app.user)
    app.db.expire_all()
    assert app.db.get(m.PracticeTest, test.id).score == 100
    assert app.db.query(m.PracticeAnswer).count() == 1


def test_offline_deadline_sync_accepts_one_draft_and_rejects_late_overwrites(application):
    app = application
    m = app.models
    question = question_bank(app, 1)[0]
    created = assessment(app)
    started = call(app.user_assessments.start_assessment, created.id, app.user)
    persisted = app.db.get(m.Assessment, created.id)
    persisted.end_time = datetime.now(timezone.utc) - timedelta(seconds=1)
    app.db.commit()
    correct = next(option for option in question.options if option.is_correct)
    body = app.user_assessments.SubmitAssessmentRequest(answers=[
        app.user_assessments.SubmitAnswerRequest(question_id=question.id, answer=str(correct.id)),
    ])
    call(app.user_assessments.assessment_heartbeat, started.attempt_id, app.user)
    result = call(app.user_assessments.sync_offline_assessment_answers, started.attempt_id, body, app.user)
    assert result["status"] == "finished"
    late = app.user_assessments.SubmitAssessmentRequest(answers=[
        app.user_assessments.SubmitAnswerRequest(question_id=question.id, answer="late overwrite"),
    ])
    call(app.user_assessments.sync_offline_assessment_answers, started.attempt_id, late, app.user)
    app.evaluation.evaluate_attempt_from_job(app.db, started.attempt_id)
    app.db.expire_all()
    assert app.db.get(m.Attempt, started.attempt_id).score == 100
    assert app.db.query(m.Answer).one().answer == str(correct.id)


def test_malformed_persisted_option_selection_does_not_break_reports(application):
    app = application
    m = app.models
    question = question_bank(app, 1)[0]
    created = assessment(app)
    started = call(app.user_assessments.start_assessment, created.id, app.user)
    call(app.user_assessments.submit_assessment, started.attempt_id,
         app.user_assessments.SubmitAssessmentRequest(answers=[
             app.user_assessments.SubmitAnswerRequest(question_id=question.id, answer="not-a-uuid"),
         ]), app.user)
    app.evaluation.evaluate_attempt_from_job(app.db, started.attempt_id)
    result = call(app.user_assessments.get_my_results, created.id, app.user)
    admin = call(app.admin.get_attempt_results, started.attempt_id, app.user)
    assert result["score"] == admin["score"] == 0
    assert result["answers"][0]["answer_status"] == "incorrect"
    assert app.db.query(m.Answer).count() == 1


def test_failed_practice_evaluation_preserves_work_for_retry(application, monkeypatch):
    app = application
    m = app.models
    test = m.PracticeTest(
        user_id=app.user.id, job_title="Provider outage", difficulty="easy",
        question_count=1, status=m.PracticeTestStatus.in_progress,
    )
    app.db.add(test)
    app.db.flush()
    question = m.PracticeQuestion(
        practice_test_id=test.id, position=0, type="text", question="Explain a transaction",
        correct_answer="An atomic unit of work",
    )
    app.db.add(question)
    app.db.commit()
    text = "Candidate response with Unicode: \u4f60\u597d \u00e9\n" * 100
    payload = app.practice.SubmitPracticeIn(answers=[
        app.practice.SubmitAnswerItem(question_id=str(question.id), answer=text),
    ])

    def unavailable(*_args):
        raise RuntimeError("Simulated provider outage")

    monkeypatch.setattr(app.practice, "_score_practice_question", unavailable)
    with pytest.raises(RuntimeError, match="Simulated provider outage"):
        call(app.practice.submit_practice_test, test.id, payload, app.user)
    app.db.expire_all()
    assert app.db.get(m.PracticeTest, test.id).status == m.PracticeTestStatus.in_progress
    assert app.db.query(m.PracticeAnswer).one().answer == text
    monkeypatch.setattr(app.practice, "_score_practice_question", lambda *_args: (0.75, "Partially correct"))
    call(app.practice.submit_practice_test, test.id, payload, app.user)
    app.db.expire_all()
    assert app.db.get(m.PracticeTest, test.id).score == 75


def test_concurrent_interview_starts_consume_one_approval(application):
    from fastapi import HTTPException
    app = application
    if app.db.bind.dialect.name != "postgresql":
        pytest.skip("Requires PostgreSQL row locks and independent connections")
    template, _grant = interview_access(app)
    template_id, user_id = template.id, app.user.id
    ready = threading.Barrier(2)

    def start():
        ready.wait(timeout=10)
        try:
            return call(app.interviews.start_interview,
                        app.interviews.InterviewStartIn(template_id=template_id),
                        SimpleNamespace(id=user_id))
        except HTTPException as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _index: start(), range(2)))
    assert sum(not isinstance(outcome, HTTPException) for outcome in outcomes) == 1
    assert [outcome.status_code for outcome in outcomes if isinstance(outcome, HTTPException)] == [400]
    assert app.db.query(app.models.InterviewSession).count() == 1


def test_concurrent_registration_resubmission_keeps_one_pending_request(application):
    from fastapi import HTTPException
    app = application
    if app.db.bind.dialect.name != "postgresql":
        pytest.skip("Requires PostgreSQL row locks and independent connections")
    m = app.models
    rejected = m.RegistrationRequest(
        username="concurrent-reapply", email="reapply@example.test", contact_email="contact-reapply@example.test",
        name="Candidate", hashed_password="old", status=m.RegistrationStatus.rejected,
        resolved_at=datetime.now(timezone.utc) - timedelta(days=30),
    )
    app.db.add(rejected)
    app.db.commit()
    payload = app.auth.UserRegister(
        username=rejected.username, email=rejected.email, contact_email=rejected.contact_email,
        name="Candidate", password="test-only",
    )
    ready = threading.Barrier(2)

    def register():
        ready.wait(timeout=10)
        try:
            return call(app.auth.register, payload)
        except HTTPException as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _index: register(), range(2)))
    assert sum(not isinstance(outcome, HTTPException) for outcome in outcomes) == 1
    assert [outcome.status_code for outcome in outcomes if isinstance(outcome, HTTPException)] == [400]
    app.db.expire_all()
    assert app.db.query(m.RegistrationRequest).one().status == m.RegistrationStatus.pending


def test_duplicate_interview_resume_does_not_add_pause_time_twice(application):
    app = application
    template, _grant = interview_access(app)
    started = call(app.interviews.start_interview, app.interviews.InterviewStartIn(template_id=template.id), app.user)
    call(app.interviews.pause_interview, started.id, app.user)
    call(app.interviews.resume_interview, started.id, app.user)
    app.db.expire_all()
    session = app.db.get(app.models.InterviewSession, started.id)
    duration, pause_count, resumed_at = session.duration_seconds, session.pause_count, session.resumed_at
    call(app.interviews.resume_interview, started.id, app.user)
    app.db.refresh(session)
    assert session.status == app.models.InterviewSessionStatus.in_progress
    assert (session.duration_seconds, session.pause_count, session.resumed_at) == (duration, pause_count, resumed_at)


def test_concurrent_assessment_creation_from_overlapping_section_pools(application):
    app = application
    if app.db.bind.dialect.name != "postgresql":
        pytest.skip("Requires PostgreSQL row locks and independent connections")
    question_bank(app, 6)
    topic_id, user_id = app.topic.id, app.user.id
    ready = threading.Barrier(4)

    def create(index):
        body = app.assessments.CreateAssessmentRequest(
            title=f"Concurrent publish {index}", user_ids=[user_id],
            topics=[
                app.assessments.TopicConfig(
                    topic_id=topic_id, question_type="single_mcq", difficulty="easy",
                    question_count=1, section_name=f"Section {section}",
                )
                for section in range(3)
            ],
        )
        ready.wait(timeout=10)
        return call(app.assessments.create_assessment, body, SimpleNamespace(id=user_id))

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(create, range(4)))
    assert len(results) == 4
    for result in results:
        links = app.db.query(app.models.AssessmentQuestion).filter_by(assessment_id=result.id).all()
        assert len({link.question_id for link in links}) == 3


@pytest.mark.parametrize("invalid", [False, True])
def test_actual_practice_worker_persists_only_a_complete_valid_generation(application, monkeypatch, invalid):
    from app import llms
    from core.practice_generation import _claim_next_practice_test, _generate_claimed_practice_test

    app = application
    m = app.models
    test = m.PracticeTest(
        user_id=app.user.id, job_title="Synthetic developer", topics="SQL", difficulty="easy",
        question_count=2, status=m.PracticeTestStatus.generating,
    )
    app.db.add(test)
    app.db.commit()
    generated = [
        {"type": "single_mcq", "question": "Which command saves changes?", "topic": "SQL",
         "options": [{"text": "COMMIT", "is_correct": True}, {"text": "ROLLBACK", "is_correct": False}]},
        {"type": "text", "question": "Explain rollback.", "topic": "SQL", "correct_answer": "Discards changes"},
    ]
    monkeypatch.setattr(llms, "get_chat_model", lambda: SimpleNamespace(
        invoke=lambda _prompt: SimpleNamespace(content=json.dumps(generated[:1] if invalid else generated))
    ))
    assert _claim_next_practice_test(app.db) == test.id
    if invalid:
        with pytest.raises(ValueError, match="exactly"):
            _generate_claimed_practice_test(test.id)
        assert app.db.query(m.PracticeQuestion).count() == 0
    else:
        _generate_claimed_practice_test(test.id)
        _generate_claimed_practice_test(test.id)
        app.db.refresh(test)
        assert test.status == m.PracticeTestStatus.ready
        assert test.generation_claimed_at is None
        rows = app.db.query(m.PracticeQuestion).order_by(m.PracticeQuestion.position).all()
        assert len(rows) == 2 and rows[0].correct_answer == '["COMMIT"]'


def test_practice_worker_provider_failure_is_visible_and_retryable(application, monkeypatch):
    from app import llms
    from core import practice_generation

    app = application
    m = app.models
    test = m.PracticeTest(
        user_id=app.user.id, job_title="Provider outage", difficulty="easy",
        question_count=10, status=m.PracticeTestStatus.generating,
    )
    access = m.PracticeAccessRequest(
        user_id=app.user.id, status=m.PracticeAccessStatus.approved,
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
    )
    app.db.add_all([test, access])
    app.db.commit()

    def unavailable():
        raise RuntimeError("Simulated provider outage")

    class StopWorker(BaseException):
        pass

    def stop_after_empty_queue(_interval):
        raise StopWorker()

    lock = SimpleNamespace(
        execute=lambda *_args: SimpleNamespace(scalar=lambda: True),
        commit=lambda: None,
        close=lambda: None,
    )
    monkeypatch.setattr(llms, "get_chat_model", unavailable)
    monkeypatch.setattr(practice_generation, "engine", SimpleNamespace(
        dialect=SimpleNamespace(name="postgresql"), connect=lambda: lock,
    ))
    monkeypatch.setattr(practice_generation.time, "sleep", stop_after_empty_queue)
    with pytest.raises(StopWorker):
        practice_generation.process_practice_generation_queue()
    app.db.refresh(test)
    assert test.status == m.PracticeTestStatus.failed
    assert "Retry generation" in test.error_message
    assert test.generation_claimed_at is None
    assert app.db.query(m.PracticeQuestion).count() == 0
    call(app.practice.retry_practice_generation, test.id, app.user)
    app.db.refresh(test)
    assert test.status == m.PracticeTestStatus.generating and test.error_message is None
