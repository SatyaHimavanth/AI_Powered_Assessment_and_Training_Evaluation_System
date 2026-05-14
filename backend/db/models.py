import uuid
import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Text, Date, DateTime,
    Integer, Float, Boolean, ForeignKey, Enum, JSON
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from db.database import Base


# ---------------- ENUMS ---------------- #

class UserRole(str, enum.Enum):
    admin = "admin"
    user = "user"


class RegistrationStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class BatchStatus(str, enum.Enum):
    upcoming = "upcoming"
    current = "current"
    completed = "completed"
    archived = "archived"


class QuestionType(str, enum.Enum):
    single_mcq = "single_mcq"
    multi_mcq = "multi_mcq"
    text = "text"
    coding = "coding"


class Difficulty(str, enum.Enum):
    easy = "easy"
    medium = "medium"
    hard = "hard"


class AttemptStatus(str, enum.Enum):
    in_progress = "in_progress"
    completed = "completed"
    missed = "missed"


class EvaluationType(str, enum.Enum):
    auto = "auto"
    llm = "llm"


class EvaluationJobStatus(str, enum.Enum):
    pending = "pending"
    in_progress = "in_progress"
    completed = "completed"
    failed = "failed"


# ---------------- IMPORT MODELS ---------------- #


class ImportStatus(str, enum.Enum):
    uploaded = "uploaded"
    validated = "validated"
    used = "used"
    failed = "failed"


class ImportedAssessment(Base):
    __tablename__ = "imported_assessments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String, nullable=True)
    uploader_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    status = Column(Enum(ImportStatus), default=ImportStatus.uploaded)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    meta = Column(JSON, nullable=True)
    preview = Column(JSON, nullable=True)

    questions = relationship("ImportedQuestion", back_populates="imported_assessment", cascade="all, delete-orphan")


class ImportedQuestion(Base):
    __tablename__ = "imported_questions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    imported_assessment_id = Column(UUID(as_uuid=True), ForeignKey("imported_assessments.id"), nullable=False)
    section_name = Column(String, default="General")
    question_type = Column(String, nullable=True)
    question_text = Column(Text, nullable=False)
    reference_answer = Column(Text, nullable=True)
    options = Column(JSON, nullable=True)
    correct_answers = Column(JSON, nullable=True)
    topic = Column(String, nullable=True)
    difficulty = Column(String, nullable=True)
    row_index = Column(Integer, nullable=True)
    validated = Column(Boolean, default=False)
    errors = Column(JSON, nullable=True)

    imported_assessment = relationship("ImportedAssessment", back_populates="questions")


# ---------------- PER-ASSESSMENT QUESTION ITEMS ---------------- #


class AssessmentQuestionItem(Base):
    __tablename__ = "assessment_question_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assessment_id = Column(UUID(as_uuid=True), ForeignKey("assessments.id"), nullable=False)
    question_type = Column(String, nullable=True)
    question_text = Column(Text, nullable=False)
    reference_answer = Column(Text, nullable=True)
    options = Column(JSON, nullable=True)  # list of {id: str, option_text: str, is_correct: bool}
    correct_answers = Column(JSON, nullable=True)
    topic = Column(String, nullable=True)
    difficulty = Column(String, nullable=True)
    default_code = Column(Text, nullable=True)
    test_cases = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # no back_populates needed; referenced from AssessmentQuestion




# ---------------- MODELS ---------------- #

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String, unique=True, nullable=False, index=True)
    email = Column(String, unique=True, nullable=False)
    contact_email = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(Enum(UserRole), nullable=False, default=UserRole.user)
    is_active = Column(Boolean, default=True)
    account = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    batches = relationship("BatchUser", back_populates="user")
    attempts = relationship("Attempt", back_populates="user")


class RegistrationRequest(Base):
    __tablename__ = "registration_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String, unique=True, nullable=False, index=True)
    email = Column(String, unique=True, nullable=False)
    contact_email = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    account = Column(String, nullable=True)
    hashed_password = Column(String, nullable=False)
    status = Column(Enum(RegistrationStatus), default=RegistrationStatus.pending)
    requested_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    resolved_at = Column(DateTime, nullable=True)


class Batch(Base):
    __tablename__ = "batches"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String)
    description = Column(Text)
    start_date = Column(Date)
    end_date = Column(Date)
    status = Column(Enum(BatchStatus))

    users = relationship("BatchUser", back_populates="batch")
    assignments = relationship("Assignment", back_populates="batch")


class BatchUser(Base):
    __tablename__ = "batch_users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    batch_id = Column(UUID(as_uuid=True), ForeignKey("batches.id"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))

    batch = relationship("Batch", back_populates="users")
    user = relationship("User", back_populates="batches")


class Topic(Base):
    __tablename__ = "topics"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String)
    description = Column(Text)
    is_archived = Column(Boolean, default=False)

    questions = relationship("Question", back_populates="topic")


class Question(Base):
    __tablename__ = "questions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    topic_id = Column(UUID(as_uuid=True), ForeignKey("topics.id"))
    type = Column(Enum(QuestionType))
    question = Column(Text)
    difficulty = Column(Enum(Difficulty))
    reference_answer = Column(Text)
    default_code = Column(Text, nullable=True)  # Pre-filled code template for coding questions
    is_archived = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    topic = relationship("Topic", back_populates="questions")
    options = relationship("QuestionOption", back_populates="question")
    test_cases = relationship("TestCase", back_populates="question", cascade="all, delete-orphan")


class QuestionOption(Base):
    __tablename__ = "question_options"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    question_id = Column(UUID(as_uuid=True), ForeignKey("questions.id"))
    option_text = Column(Text)
    is_correct = Column(Boolean)

    question = relationship("Question", back_populates="options")


class TestCase(Base):
    __tablename__ = "test_cases"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    question_id = Column(UUID(as_uuid=True), ForeignKey("questions.id"))
    input_data = Column(Text, nullable=False)
    expected_output = Column(Text, nullable=False)
    is_sample = Column(Boolean, default=False)  # True = visible to user during exam

    question = relationship("Question", back_populates="test_cases")


class Assessment(Base):
    __tablename__ = "assessments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String)
    description = Column(Text)
    duration = Column(Integer)
    negative_marking = Column(Boolean, default=False)
    start_time = Column(DateTime, nullable=True)
    end_time = Column(DateTime, nullable=True)
    is_archived = Column(Boolean, default=False)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    topics = relationship("AssessmentTopic", back_populates="assessment")
    questions = relationship("AssessmentQuestion", back_populates="assessment")
    assignments = relationship("Assignment", back_populates="assessment")


class AssessmentTopic(Base):
    __tablename__ = "assessment_topics"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assessment_id = Column(UUID(as_uuid=True), ForeignKey("assessments.id"))
    topic_id = Column(UUID(as_uuid=True), ForeignKey("topics.id"))
    question_type = Column(Enum(QuestionType))
    difficulty = Column(Enum(Difficulty))
    question_count = Column(Integer)

    assessment = relationship("Assessment", back_populates="topics")


class AssessmentQuestion(Base):
    __tablename__ = "assessment_questions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assessment_id = Column(UUID(as_uuid=True), ForeignKey("assessments.id"))
    question_id = Column(UUID(as_uuid=True), ForeignKey("questions.id"))
    assessment_item_id = Column(UUID(as_uuid=True), ForeignKey("assessment_question_items.id"), nullable=True)

    assessment = relationship("Assessment", back_populates="questions")


class AssessmentQuestionSection(Base):
    __tablename__ = "assessment_question_sections"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assessment_id = Column(UUID(as_uuid=True), ForeignKey("assessments.id"))
    question_id = Column(UUID(as_uuid=True), ForeignKey("questions.id"))
    assessment_item_id = Column(UUID(as_uuid=True), ForeignKey("assessment_question_items.id"), nullable=True)
    section_name = Column(String, default="General")


class Assignment(Base):
    __tablename__ = "assignments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assessment_id = Column(UUID(as_uuid=True), ForeignKey("assessments.id"))
    batch_id = Column(UUID(as_uuid=True), ForeignKey("batches.id"))
    assigned_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    due_date = Column(DateTime)

    assessment = relationship("Assessment", back_populates="assignments")
    batch = relationship("Batch", back_populates="assignments")


class Attempt(Base):
    __tablename__ = "attempts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    assessment_id = Column(UUID(as_uuid=True), ForeignKey("assessments.id"))
    started_at = Column(DateTime)
    submitted_at = Column(DateTime)
    score = Column(Float)
    status = Column(Enum(AttemptStatus))
    tab_violations = Column(Integer, default=0)

    user = relationship("User", back_populates="attempts")
    answers = relationship("Answer", back_populates="attempt")


class Answer(Base):
    __tablename__ = "answers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    attempt_id = Column(UUID(as_uuid=True), ForeignKey("attempts.id"))
    question_id = Column(UUID(as_uuid=True), ForeignKey("questions.id"))
    assessment_item_id = Column(UUID(as_uuid=True), ForeignKey("assessment_question_items.id"), nullable=True)
    answer = Column(Text)
    score = Column(Float)
    evaluated_by = Column(Enum(EvaluationType))
    feedback = Column(Text)

    attempt = relationship("Attempt", back_populates="answers")


class TopicScore(Base):
    __tablename__ = "topic_scores"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    attempt_id = Column(UUID(as_uuid=True), ForeignKey("attempts.id"))
    topic_id = Column(UUID(as_uuid=True), ForeignKey("topics.id"))
    score = Column(Float)


class EvaluationJob(Base):
    __tablename__ = "evaluation_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    attempt_id = Column(UUID(as_uuid=True), ForeignKey("attempts.id"), unique=True)
    status = Column(Enum(EvaluationJobStatus), default=EvaluationJobStatus.pending)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0)

    attempt = relationship("Attempt", foreign_keys=[attempt_id])


# -------------- PRACTICE TEST (Self-Assessment) -------------- #

class PracticeAccessStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class PracticeAccessRequest(Base):
    __tablename__ = "practice_access_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    reason = Column(Text, nullable=True)
    requested_days = Column(Integer, default=14)
    requested_tests_per_day = Column(Integer, default=1)
    status = Column(Enum(PracticeAccessStatus), default=PracticeAccessStatus.pending)
    requested_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    approved_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    days_granted = Column(Integer, nullable=True)
    tests_per_day_granted = Column(Integer, nullable=True)
    admin_note = Column(Text, nullable=True)

    user = relationship("User")


class PracticeTestStatus(str, enum.Enum):
    generating = "generating"
    ready = "ready"
    in_progress = "in_progress"
    completed = "completed"
    failed = "failed"


class PracticeTest(Base):
    __tablename__ = "practice_tests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    job_title = Column(String, nullable=False)
    job_description = Column(Text, nullable=True)
    topics = Column(Text, nullable=True)  # comma-separated
    difficulty = Column(String, nullable=False)
    question_count = Column(Integer, default=30)
    resume_text = Column(Text, nullable=True)
    status = Column(Enum(PracticeTestStatus), default=PracticeTestStatus.generating)
    score = Column(Float, nullable=True)
    started_at = Column(DateTime, nullable=True)
    submitted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    error_message = Column(Text, nullable=True)

    user = relationship("User")
    questions = relationship("PracticeQuestion", back_populates="practice_test", order_by="PracticeQuestion.position")


class PracticeQuestion(Base):
    __tablename__ = "practice_questions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    practice_test_id = Column(UUID(as_uuid=True), ForeignKey("practice_tests.id"), nullable=False)
    position = Column(Integer, nullable=False)
    type = Column(String, nullable=False)  # single_mcq, multi_mcq, text
    question = Column(Text, nullable=False)
    options = Column(Text, nullable=True)  # JSON array for MCQs
    correct_answer = Column(Text, nullable=True)  # JSON for MCQs, text for text
    topic = Column(String, nullable=True)

    practice_test = relationship("PracticeTest", back_populates="questions")
    answer = relationship("PracticeAnswer", back_populates="question", uselist=False)


class PracticeAnswer(Base):
    __tablename__ = "practice_answers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    question_id = Column(UUID(as_uuid=True), ForeignKey("practice_questions.id"), nullable=False)
    answer = Column(Text, nullable=True)
    score = Column(Float, nullable=True)
    feedback = Column(Text, nullable=True)

    question = relationship("PracticeQuestion", back_populates="answer")
