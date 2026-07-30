import os
import uuid

import pytest
import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/")
ADMIN_USERNAME = os.environ.get("TEST_ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "admin123")
ADMIN_EMAIL = os.environ.get("TEST_ADMIN_EMAIL", "admin@assessment.com")
ADMIN_CONTACT_EMAIL = os.environ.get("TEST_ADMIN_CONTACT_EMAIL", "admin@assessment.com")
ADMIN_NAME = os.environ.get("TEST_ADMIN_NAME", "System Admin")

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/assessment_db")


@pytest.fixture(scope="session")
def db_engine():
    engine = create_engine(DATABASE_URL, isolation_level="AUTOCOMMIT")
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def db_session(db_engine):
    session = Session(db_engine)
    yield session
    session.close()


@pytest.fixture(scope="session")
def api_client():
    session = requests.Session()
    yield session
    session.close()


@pytest.fixture(scope="session")
def admin_token(api_client):
    try:
        resp = api_client.post(
            f"{BASE_URL}/auth/login",
            json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json().get("access_token")
    except Exception:
        pass
    return None


def _cleanup_assessment(db_session, assessment_id):
    from db.models import (
        Answer,
        Assessment,
        AssessmentQuestion,
        AssessmentQuestionItem,
        AssessmentQuestionSection,
        AssessmentTopic,
        Assignment,
        Attempt,
        EvaluationJob,
        TopicScore,
    )

    uid = uuid.UUID(assessment_id)
    attempts = db_session.query(Attempt).filter(Attempt.assessment_id == uid).all()
    attempt_ids = [a.id for a in attempts]

    for attempt in attempts:
        db_session.query(Answer).filter(Answer.attempt_id == attempt.id).delete()
        db_session.query(TopicScore).filter(TopicScore.attempt_id == attempt.id).delete()
        db_session.query(EvaluationJob).filter(EvaluationJob.attempt_id == attempt.id).delete()

    if attempt_ids:
        db_session.query(Attempt).filter(Attempt.id.in_(attempt_ids)).delete()

    db_session.query(AssessmentQuestionSection).filter(
        AssessmentQuestionSection.assessment_id == uid
    ).delete(synchronize_session="fetch")
    db_session.query(AssessmentQuestionItem).filter(
        AssessmentQuestionItem.assessment_id == uid
    ).delete(synchronize_session="fetch")
    db_session.query(AssessmentQuestion).filter(
        AssessmentQuestion.assessment_id == uid
    ).delete(synchronize_session="fetch")
    db_session.query(AssessmentTopic).filter(
        AssessmentTopic.assessment_id == uid
    ).delete(synchronize_session="fetch")
    db_session.query(Assignment).filter(Assignment.assessment_id == uid).delete(
        synchronize_session="fetch"
    )
    db_session.query(Assessment).filter(Assessment.id == uid).delete(
        synchronize_session="fetch"
    )
    db_session.commit()


def _cleanup_batch(db_session, batch_id):
    from db.models import Batch, BatchUser

    existing = db_session.query(BatchUser).filter(BatchUser.batch_id == batch_id).all()
    for bu in existing:
        db_session.delete(bu)
    db_session.commit()
    batch = db_session.query(Batch).filter(Batch.id == batch_id).first()
    if batch:
        db_session.delete(batch)
    db_session.commit()


def _cleanup_users(db_session, usernames):
    from db.models import User

    for username in usernames:
        user = db_session.query(User).filter(User.username == username).first()
        if user:
            db_session.delete(user)
    db_session.commit()


def _cleanup_topics(db_session, topic_names):
    from db.models import Topic

    for name in topic_names:
        topic = db_session.query(Topic).filter(Topic.name == name).first()
        if topic:
            db_session.delete(topic)
    db_session.commit()


@pytest.fixture(scope="session")
def seeded_assessment(api_client, db_session, admin_token):
    if not admin_token:
        pytest.skip("Could not obtain admin token; backend may not be running or credentials wrong")

    headers = {"Authorization": f"Bearer {admin_token}"}
    cleanup_assessment_id = None

    created_usernames = []
    created_batch_id = None
    cleanup_topic_names = []

    try:
        from db.models import (
            Batch,
            BatchUser,
            Difficulty,
            Question,
            QuestionOption,
            QuestionType,
            Topic,
            User,
        )

        # --- Ensure admin user exists ---
        admin_user = db_session.query(User).filter(User.username == ADMIN_USERNAME).first()
        if not admin_user:
            admin_user = User(
                username=ADMIN_USERNAME,
                email=ADMIN_EMAIL,
                contact_email=ADMIN_CONTACT_EMAIL,
                name=ADMIN_NAME,
                hashed_password=__import__("core.auth", fromlist=["get_password_hash"]).get_password_hash(ADMIN_PASSWORD),
                role="admin",
                is_active=True,
            )
            db_session.add(admin_user)
            db_session.commit()
            db_session.refresh(admin_user)

        # --- Create Topics ---
        topic_names = ["TestTopicA", "TestTopicB", "TestTopicC"]
        for name in topic_names:
            existing = db_session.query(Topic).filter(Topic.name == name).first()
            if existing:
                db_session.delete(existing)
                db_session.commit()

            topic = Topic(name=name, description=f"Auto-test topic: {name}")
            db_session.add(topic)
            db_session.commit()
            db_session.refresh(topic)
            cleanup_topic_names.append(name)

        topics = {name: db_session.query(Topic).filter(Topic.name == name).first() for name in topic_names}

        # --- Create Questions (easy + medium per topic) ---
        for topic in topics.values():
            for diff in [Difficulty.easy, Difficulty.medium]:
                for q_idx in range(4):
                    q = Question(
                        topic_id=topic.id,
                        question=f"Auto-test Q {topic.name} {diff.value} #{q_idx}",
                        type=QuestionType.single_mcq,
                        difficulty=diff,
                        reference_answer="A",
                        default_code=None,
                    )
                    db_session.add(q)
                    db_session.commit()
                    db_session.refresh(q)

                    db_session.add_all([
                        QuestionOption(question_id=q.id, option_text="A", is_correct=True),
                        QuestionOption(question_id=q.id, option_text="B", is_correct=False),
                        QuestionOption(question_id=q.id, option_text="C", is_correct=False),
                        QuestionOption(question_id=q.id, option_text="D", is_correct=False),
                    ])

        db_session.commit()

        # --- Create Test Users ---
        user_configs = [
            ("assessment_tester_1", "Alice Tester", "alice@test.assessment.com", "alice@test.assessment.com"),
            ("assessment_tester_2", "Bob Tester", "bob@test.assessment.com", "bob@test.assessment.com"),
            ("assessment_tester_3", "Carol Tester", "carol@test.assessment.com", "carol@test.assessment.com"),
        ]
        for username, name, email, contact in user_configs:
            existing = db_session.query(User).filter(User.username == username).first()
            if existing:
                db_session.delete(existing)
                db_session.commit()

            user = User(
                username=username,
                email=email,
                contact_email=contact,
                name=name,
                hashed_password=__import__("core.auth", fromlist=["get_password_hash"]).get_password_hash("testpass123"),
                role="user",
                is_active=True,
            )
            db_session.add(user)
            db_session.commit()
            db_session.refresh(user)
            created_usernames.append(username)

        # --- Create Batch and assign users ---
        batch_name = "assessment_test_batch"
        batch = db_session.query(Batch).filter(Batch.name == batch_name).first()
        if batch:
            _cleanup_batch(db_session, batch.id)

        batch = Batch(name=batch_name, description="Test batch for multi-user assessment")
        db_session.add(batch)
        db_session.commit()
        db_session.refresh(batch)
        created_batch_id = batch.id

        for username in created_usernames:
            user = db_session.query(User).filter(User.username == username).first()
            if user:
                bu = BatchUser(batch_id=batch.id, user_id=user.id)
                db_session.add(bu)
        db_session.commit()

        # --- Create Assessment via API ---
        topic_configs = [
            {
                "topic_id": str(topics["TestTopicA"].id),
                "question_type": "single_mcq",
                "difficulty": "easy",
                "question_count": 3,
                "section_name": "Section-Alpha",
            },
            {
                "topic_id": str(topics["TestTopicB"].id),
                "question_type": "single_mcq",
                "difficulty": "medium",
                "question_count": 3,
                "section_name": "Section-Beta",
            },
        ]

        create_resp = api_client.post(
            f"{BASE_URL}/assessments/create",
            json={
                "title": "Multi-User Assessment Lifecycle Test",
                "description": "Automated test assessment for multi-user scenario validation",
                "duration": 30,
                "negative_marking": False,
                "topics": topic_configs,
                "batch_ids": [str(batch.id)],
            },
            headers=headers,
            timeout=30,
        )

        if create_resp.status_code != 200:
            pytest.skip(
                f"Failed to create assessment: {create_resp.status_code} - {create_resp.text}"
            )

        created_assessment = create_resp.json()
        cleanup_assessment_id = created_assessment["id"]

        # Collect Question objects with their options for correct-answer lookup
        all_questions = (
            db_session.query(Question)
            .filter(
                Question.topic_id.in_([t.id for t in topics.values()])
            )
            .all()
        )

        yield {
            "assessment": created_assessment,
            "usernames": created_usernames,
            "batch_id": created_batch_id,
            "admin_token": admin_token,
            "admin_user": admin_user,
            "_seeded_questions": all_questions,
        }

    finally:
        try:
            if cleanup_assessment_id:
                _cleanup_assessment(db_session, cleanup_assessment_id)
        except Exception:
            db_session.rollback()

        try:
            if created_batch_id:
                _cleanup_batch(db_session, created_batch_id)
        except Exception:
            db_session.rollback()

        try:
            _cleanup_users(db_session, created_usernames)
        except Exception:
            db_session.rollback()

        try:
            _cleanup_topics(db_session, cleanup_topic_names)
        except Exception:
            db_session.rollback()