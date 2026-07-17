import json
import re
import threading
import os
from datetime import datetime, timezone
from io import BytesIO
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.llms import get_chat_model
from core.auth import get_current_user
from db.database import SessionLocal
from db.async_helpers import run_db_sync
from db.models import (
    PracticeAccessRequest,
    PracticeAccessStatus,
    PracticeAnswer,
    PracticeQuestion,
    PracticeTest,
    PracticeTestStatus,
    User,
)
from api.timezone_helper import as_utc_aware

router = APIRouter(prefix="/practice", tags=["practice"])

MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB


# ---------- Schemas ---------- #


class PracticeTestOut(BaseModel):
    id: UUID
    job_title: str
    topics: str | None
    difficulty: str
    question_count: int
    status: str
    score: float | None
    created_at: datetime
    submitted_at: datetime | None

    class Config:
        from_attributes = True


class PracticeQuestionOut(BaseModel):
    id: str
    position: int
    type: str
    question: str
    options: list | None
    topic: str | None


class PracticeTestDetail(BaseModel):
    id: str
    job_title: str
    topics: str | None
    difficulty: str
    question_count: int
    status: str
    score: float | None
    created_at: datetime
    questions: List[PracticeQuestionOut]


class PracticeResultQuestion(BaseModel):
    position: int
    type: str
    question: str
    options: list | None
    topic: str | None
    user_answer: str | None
    correct_answer: str | None
    score: float | None
    feedback: str | None


class PracticeResultOut(BaseModel):
    id: str
    job_title: str
    topics: str | None
    difficulty: str
    question_count: int
    score: float | None
    submitted_at: datetime | None
    questions: List[PracticeResultQuestion]


class SubmitAnswerItem(BaseModel):
    question_id: str
    answer: str


class SubmitPracticeIn(BaseModel):
    answers: List[SubmitAnswerItem]


class MessageResponse(BaseModel):
    message: str


class RequestAccessIn(BaseModel):
    reason: str = ""
    requested_days: int = 14
    requested_tests_per_day: int = 1


class PracticeAccessOut(BaseModel):
    has_access: bool
    expires_at: datetime | None = None
    pending_request: bool = False
    requested_tests_per_day: int | None = None
    tests_per_day_granted: int | None = None


# ---------- Helpers ---------- #


def _check_practice_access(user_id, db: Session) -> PracticeAccessOut:
    """Check if user has active practice access."""
    # Check for an approved, non-expired access
    now = datetime.now(timezone.utc)
    active = (
        db.query(PracticeAccessRequest)
        .filter(
            PracticeAccessRequest.user_id == user_id,
            PracticeAccessRequest.status == PracticeAccessStatus.approved,
            PracticeAccessRequest.expires_at > now,
        )
        .first()
    )
    if active:
        return PracticeAccessOut(
            has_access=True,
            expires_at=active.expires_at,
            tests_per_day_granted=(active.tests_per_day_granted if getattr(active, "tests_per_day_granted", None) else None),
        )

    # Check for pending request
    pending = (
        db.query(PracticeAccessRequest)
        .filter(
            PracticeAccessRequest.user_id == user_id,
            PracticeAccessRequest.status == PracticeAccessStatus.pending,
        )
        .first()
    )
    return PracticeAccessOut(
        has_access=False,
        pending_request=pending is not None,
        requested_tests_per_day=(pending.requested_tests_per_day if pending is not None and getattr(pending, "requested_tests_per_day", None) else None),
    )


def _extract_text_from_file(file: UploadFile, content: bytes) -> str:
    """Extract plain text from uploaded resume file."""
    filename = file.filename or ""
    lower = filename.lower()

    if lower.endswith(".pdf"):
        try:
            import PyPDF2
            reader = PyPDF2.PdfReader(BytesIO(content))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            return text.strip()
        except Exception:
            raise HTTPException(status_code=400, detail="Could not parse PDF file")

    elif lower.endswith(".docx"):
        try:
            import docx
            doc = docx.Document(BytesIO(content))
            text = "\n".join(p.text for p in doc.paragraphs)
            return text.strip()
        except Exception:
            raise HTTPException(status_code=400, detail="Could not parse DOCX file")

    elif lower.endswith(".txt"):
        return content.decode("utf-8", errors="ignore").strip()

    else:
        raise HTTPException(status_code=400, detail="Unsupported file type. Use PDF, DOCX, or TXT.")


GENERATION_PROMPT = """You are an expert assessment creator. Generate exactly {question_count} questions for a candidate based on the following context:

**Job Title:** {job_title}
**Job Description:** {job_description}
**Topics to cover:** {topics}
**Difficulty Level:** {difficulty}
**Candidate Resume (for context/relevance):**
{resume_text}

Generate a mix of question types:
- About 40% Single-choice MCQ (type: "single_mcq")
- About 30% Multiple-choice MCQ (type: "multi_mcq")
- About 30% Text/Short answer (type: "text")

For each question provide:
- "position": sequential number starting from 1
- "type": one of "single_mcq", "multi_mcq", "text"
- "question": the question text
- "options": array of {{"text": "...", "is_correct": true/false}} for MCQs, null for text
- "correct_answer": for MCQs provide the correct option text(s) as a JSON array, for text provide an ideal reference answer
- "topic": which topic this question belongs to

Return ONLY a valid JSON array of question objects. No markdown, no explanation.
"""


def _generate_questions_background(practice_test_id: UUID):
    """Background thread that calls LLM and populates questions."""
    db = SessionLocal()
    try:
        test = db.query(PracticeTest).filter(PracticeTest.id == practice_test_id).first()
        if not test:
            return

        llm = get_chat_model()
        prompt = GENERATION_PROMPT.format(
            question_count=test.question_count,
            job_title=test.job_title,
            job_description=test.job_description or "Not provided",
            topics=test.topics or "General knowledge relevant to the role",
            difficulty=test.difficulty,
            resume_text=(test.resume_text or "Not provided")[:3000],  # Limit to avoid token overflow
        )

        response = llm.invoke(prompt)
        content = response.content.strip()

        # Try to parse JSON from response
        # Handle markdown code blocks
        if "```" in content:
            match = re.search(r"```(?:json)?\s*\n?(.*?)```", content, re.DOTALL)
            if match:
                content = match.group(1).strip()

        questions_data = json.loads(content)
        if not isinstance(questions_data, list):
            raise ValueError("Expected JSON array")

        # Store questions
        for i, q in enumerate(questions_data[: test.question_count]):
            pq = PracticeQuestion(
                practice_test_id=test.id,
                position=i + 1,
                type=q.get("type", "text"),
                question=q.get("question", ""),
                options=json.dumps(q.get("options")) if q.get("options") else None,
                correct_answer=json.dumps(q.get("correct_answer")) if q.get("correct_answer") else None,
                topic=q.get("topic"),
            )
            db.add(pq)

        test.status = PracticeTestStatus.ready
        db.commit()

    except Exception as e:
        test = db.query(PracticeTest).filter(PracticeTest.id == practice_test_id).first()
        if test:
            test.status = PracticeTestStatus.failed
            test.error_message = str(e)[:500]
            db.commit()
    finally:
        db.close()


# ---------- Endpoints ---------- #


@router.get("/access", response_model=PracticeAccessOut)
async def check_access(
    current_user: User = Depends(get_current_user),
):
    """Check if current user has practice test access."""
    user_id = current_user.id

    def _sync_work():
        db = SessionLocal()
        try:
            val = _check_practice_access(user_id, db)
            return val.dict() if hasattr(val, "dict") else val
        finally:
            db.close()

    return await run_db_sync(_sync_work)


@router.post("/request-access", response_model=MessageResponse)
async def request_access(
    payload: RequestAccessIn,
    current_user: User = Depends(get_current_user),
):
    """Request practice test access."""
    user_id = current_user.id

    def _sync_work():
        db = SessionLocal()
        try:
            access = _check_practice_access(user_id, db)
            if access.has_access:
                raise HTTPException(status_code=400, detail="You already have active practice test access")
            if access.pending_request:
                raise HTTPException(status_code=400, detail="You already have a pending access request")

            days = min(max(payload.requested_days, 1), 30)
            req = PracticeAccessRequest(
                user_id=user_id,
                reason=payload.reason or None,
                requested_days=days,
                requested_tests_per_day=(payload.requested_tests_per_day if getattr(payload, "requested_tests_per_day", None) else 1),
            )
            db.add(req)
            db.commit()
            return {"message": "Access request submitted. An admin will review it shortly."}
        finally:
            db.close()

    return await run_db_sync(_sync_work)


@router.post("/create", response_model=PracticeTestOut)
async def create_practice_test(
    job_title: str = Form(...),
    difficulty: str = Form(...),
    topics: str = Form(""),
    job_description: str = Form(""),
    question_count: int = Form(30),
    resume: UploadFile | None = File(None),
    current_user: User = Depends(get_current_user),
):
    """Create a new practice test. Daily limit controlled by `PRACTICE_TESTS_PER_DAY` env var (default 1)."""
    # Validate question count (fast local check)
    if question_count < 10 or question_count > 30:
        raise HTTPException(status_code=400, detail="Question count must be between 10 and 30")

    # Process resume file (async I/O)
    resume_text = None
    if resume:
        content = await resume.read()
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(status_code=400, detail="File size exceeds 5 MB limit")
        resume_text = _extract_text_from_file(resume, content)

    # Offload all DB work (access check, per-day count, create record, start background generation)
    user_id = current_user.id

    def _sync_create():
        db = SessionLocal()
        try:
            # Check access
            access = _check_practice_access(user_id, db)
            if not access.has_access:
                raise HTTPException(status_code=403, detail="Practice test access not granted. Please request access first.")

            # Check per-day limit (configurable via PRACTICE_TESTS_PER_DAY)
            try:
                system_max = int(os.getenv("PRACTICE_TESTS_MAX_PER_DAY", "3"))
            except Exception:
                system_max = 3
            try:
                env_default = int(os.getenv("PRACTICE_TESTS_PER_DAY", "1"))
            except Exception:
                env_default = 1

            per_day_limit = env_default
            if access and getattr(access, "tests_per_day_granted", None):
                per_day_limit = int(access.tests_per_day_granted)
            per_day_limit = max(1, min(per_day_limit, system_max))
            today_start = datetime.combine(datetime.now(timezone.utc).date(), datetime.min.time()).replace(tzinfo=timezone.utc)
            existing_count = (
                db.query(PracticeTest)
                .filter(
                    PracticeTest.user_id == user_id,
                    PracticeTest.created_at >= today_start,
                )
                .count()
            )
            if existing_count >= per_day_limit:
                raise HTTPException(
                    status_code=400,
                    detail=f"You can create at most {per_day_limit} practice tests per day. Please try again later."
                )

            # Create practice test record
            practice_test = PracticeTest(
                user_id=user_id,
                job_title=job_title,
                job_description=job_description or None,
                topics=topics or None,
                difficulty=difficulty,
                question_count=question_count,
                resume_text=resume_text,
                status=PracticeTestStatus.generating,
            )
            db.add(practice_test)
            db.commit()
            db.refresh(practice_test)

            # Start background generation (runs in separate thread and uses its own SessionLocal)
            thread = threading.Thread(target=_generate_questions_background, args=(practice_test.id,))
            thread.daemon = True
            thread.start()

            return practice_test
        finally:
            db.close()

    practice_test = await run_db_sync(_sync_create)

    return PracticeTestOut(
        id=practice_test.id,
        job_title=practice_test.job_title,
        topics=practice_test.topics,
        difficulty=practice_test.difficulty,
        question_count=practice_test.question_count,
        status=practice_test.status.value,
        score=None,
        created_at=practice_test.created_at,
        submitted_at=None,
    )


@router.get("/today", response_model=PracticeTestOut | None)
async def get_today_test(
    current_user: User = Depends(get_current_user),
):
    """Get today's practice test if one exists (runs DB work in threadpool)."""
    user_id = current_user.id

    def _sync_work():
        db = SessionLocal()
        try:
            today_start = datetime.combine(datetime.now(timezone.utc).date(), datetime.min.time()).replace(tzinfo=timezone.utc)
            test = (
                db.query(PracticeTest)
                .filter(
                    PracticeTest.user_id == user_id,
                    PracticeTest.created_at >= today_start,
                )
                .order_by(PracticeTest.created_at.desc())
                .first()
            )
            if not test:
                return None
            return {
                "id": test.id,
                "job_title": test.job_title,
                "topics": test.topics,
                "difficulty": test.difficulty,
                "question_count": test.question_count,
                "status": test.status.value,
                "score": test.score,
                "created_at": test.created_at,
                "submitted_at": test.submitted_at,
            }
        finally:
            db.close()

    return await run_db_sync(_sync_work)


@router.get("/history", response_model=List[PracticeTestOut])
async def get_practice_history(
    current_user: User = Depends(get_current_user),
):
    """Get all past practice tests for the user (runs DB work in threadpool)."""
    user_id = current_user.id

    def _sync_work():
        db = SessionLocal()
        try:
            tests = (
                db.query(PracticeTest)
                .filter(PracticeTest.user_id == user_id)
                .order_by(PracticeTest.created_at.desc())
                .all()
            )
            out = []
            for t in tests:
                out.append({
                    "id": t.id,
                    "job_title": t.job_title,
                    "topics": t.topics,
                    "difficulty": t.difficulty,
                    "question_count": t.question_count,
                    "status": t.status.value,
                    "score": t.score,
                    "created_at": t.created_at,
                    "submitted_at": t.submitted_at,
                })
            return out
        finally:
            db.close()

    return await run_db_sync(_sync_work)


@router.get("/{test_id}", response_model=PracticeTestDetail)
async def get_practice_test(
    test_id: UUID,
    current_user: User = Depends(get_current_user),
):
    """Get practice test with questions (for taking the test). Runs DB work in threadpool."""
    user_id = current_user.id

    def _sync_work():
        db = SessionLocal()
        try:
            test = db.query(PracticeTest).filter(
                PracticeTest.id == test_id,
                PracticeTest.user_id == user_id,
            ).first()
            if not test:
                raise HTTPException(status_code=404, detail="Practice test not found")

            questions = []
            for q in test.questions:
                questions.append({
                    "id": str(q.id),
                    "position": q.position,
                    "type": q.type,
                    "question": q.question,
                    "options": json.loads(q.options) if q.options else None,
                    "topic": q.topic,
                })

            return {
                "id": str(test.id),
                "job_title": test.job_title,
                "topics": test.topics,
                "difficulty": test.difficulty,
                "question_count": test.question_count,
                "status": test.status.value,
                "score": test.score,
                "created_at": test.created_at,
                "questions": questions,
            }
        finally:
            db.close()

    return await run_db_sync(_sync_work)


@router.post("/{test_id}/start", response_model=MessageResponse)
async def start_practice_test(
    test_id: UUID,
    current_user: User = Depends(get_current_user),
):
    """Mark practice test as in_progress. Runs DB work in threadpool."""
    user_id = current_user.id

    def _sync_work():
        db = SessionLocal()
        try:
            test = db.query(PracticeTest).filter(
                PracticeTest.id == test_id,
                PracticeTest.user_id == user_id,
            ).first()
            if not test:
                raise HTTPException(status_code=404, detail="Practice test not found")
            if test.status not in (PracticeTestStatus.ready, PracticeTestStatus.in_progress):
                raise HTTPException(status_code=400, detail=f"Cannot start test in '{test.status.value}' state")

            if test.status == PracticeTestStatus.ready:
                test.status = PracticeTestStatus.in_progress
                test.started_at = datetime.now(timezone.utc)
                db.commit()

            return {"message": "Practice test started"}
        finally:
            db.close()

    return await run_db_sync(_sync_work)


@router.post("/{test_id}/submit", response_model=MessageResponse)
async def submit_practice_test(
    test_id: UUID,
    payload: SubmitPracticeIn,
    current_user: User = Depends(get_current_user),
):
    """Submit answers for a practice test and auto-evaluate. Runs DB work in threadpool."""
    user_id = current_user.id

    def _sync_work():
        db = SessionLocal()
        try:
            test = db.query(PracticeTest).filter(
                PracticeTest.id == test_id,
                PracticeTest.user_id == user_id,
            ).first()
            if not test:
                raise HTTPException(status_code=404, detail="Practice test not found")
            if test.status == PracticeTestStatus.completed:
                raise HTTPException(status_code=400, detail="Test already submitted")

            # Save answers and evaluate
            total_score = 0.0
            total_questions = len(test.questions)

            answer_map = {a.question_id: a.answer for a in payload.answers}

            for q in test.questions:
                user_answer = answer_map.get(str(q.id), "")

                # Auto-evaluate MCQs
                score = 0.0
                feedback = ""
                if q.type in ("single_mcq", "multi_mcq") and q.correct_answer:
                    correct = json.loads(q.correct_answer)
                    if isinstance(correct, list):
                        correct_set = set(c.strip().lower() for c in correct)
                    else:
                        correct_set = {str(correct).strip().lower()}

                    # Parse user answer (could be comma-separated for multi)
                    user_set = set(a.strip().lower() for a in user_answer.split("|||") if a.strip())

                    if user_set == correct_set:
                        score = 1.0
                        feedback = "Correct"
                    elif user_set & correct_set:
                        score = 0.5
                        feedback = "Partially correct"
                    else:
                        feedback = "Incorrect"

                elif q.type == "text":
                    # For text questions, give full credit if answer is non-empty (LLM eval would be better but keep it simple)
                    if user_answer.strip():
                        score = 0.5  # Partial credit for attempting
                        feedback = "Answered (auto-scored)"
                    else:
                        feedback = "Not answered"

                total_score += score

                # Save/update answer
                existing_answer = db.query(PracticeAnswer).filter(PracticeAnswer.question_id == q.id).first()
                if existing_answer:
                    existing_answer.answer = user_answer
                    existing_answer.score = score
                    existing_answer.feedback = feedback
                else:
                    db.add(PracticeAnswer(
                        question_id=q.id,
                        answer=user_answer,
                        score=score,
                        feedback=feedback,
                    ))

            # Calculate percentage
            test.score = round((total_score / total_questions) * 100, 1) if total_questions > 0 else 0
            test.status = PracticeTestStatus.completed
            test.submitted_at = datetime.now(timezone.utc)
            db.commit()

            return {"message": f"Test submitted! Score: {test.score}%"}
        finally:
            db.close()

    return await run_db_sync(_sync_work)


@router.get("/{test_id}/result", response_model=PracticeResultOut)
async def get_practice_result(
    test_id: UUID,
    current_user: User = Depends(get_current_user),
):
    """Get detailed results for a completed practice test. Runs DB work in threadpool."""
    user_id = current_user.id

    def _sync_work():
        db = SessionLocal()
        try:
            test = db.query(PracticeTest).filter(
                PracticeTest.id == test_id,
                PracticeTest.user_id == user_id,
            ).first()
            if not test:
                raise HTTPException(status_code=404, detail="Practice test not found")

            questions = []
            for q in test.questions:
                answer = db.query(PracticeAnswer).filter(PracticeAnswer.question_id == q.id).first()
                questions.append({
                    "position": q.position,
                    "type": q.type,
                    "question": q.question,
                    "options": json.loads(q.options) if q.options else None,
                    "topic": q.topic,
                    "user_answer": answer.answer if answer else None,
                    "correct_answer": q.correct_answer,
                    "score": answer.score if answer else None,
                    "feedback": answer.feedback if answer else None,
                })

            return {
                "id": str(test.id),
                "job_title": test.job_title,
                "topics": test.topics,
                "difficulty": test.difficulty,
                "question_count": test.question_count,
                "score": test.score,
                "submitted_at": test.submitted_at,
                "questions": questions,
            }
        finally:
            db.close()

    return await run_db_sync(_sync_work)


@router.get("/{test_id}/export")
async def export_practice_result(
    test_id: UUID,
    current_user: User = Depends(get_current_user),
):
    """Export practice test result as Excel. Runs DB + workbook generation in threadpool."""
    user_id = current_user.id

    def _sync_work():
        db = SessionLocal()
        try:
            test = db.query(PracticeTest).filter(
                PracticeTest.id == test_id,
                PracticeTest.user_id == user_id,
            ).first()
            if not test:
                raise HTTPException(status_code=404, detail="Practice test not found")
            if test.status != PracticeTestStatus.completed:
                raise HTTPException(status_code=400, detail="Test not yet completed")

            wb = Workbook()
            ws = wb.active
            ws.title = "Practice Test Results"

            # Summary row
            ws.append(["Practice Test Results"])
            ws.append(["Job Title", test.job_title])
            ws.append(["Topics", test.topics or "General"])
            ws.append(["Difficulty", test.difficulty])
            ws.append(["Score", f"{test.score}%"])
            ws.append(["Date", test.created_at.strftime("%Y-%m-%d")])
            ws.append([])

            # Headers
            ws.append(["#", "Type", "Topic", "Question", "Your Answer", "Correct Answer", "Score", "Feedback"])

            for q in test.questions:
                answer = db.query(PracticeAnswer).filter(PracticeAnswer.question_id == q.id).first()
                correct = q.correct_answer
                if correct:
                    try:
                        parsed = json.loads(correct)
                        if isinstance(parsed, list):
                            correct = ", ".join(str(x) for x in parsed)
                        else:
                            correct = str(parsed)
                    except (json.JSONDecodeError, TypeError):
                        pass

                ws.append([
                    q.position,
                    q.type,
                    q.topic or "",
                    q.question,
                    answer.answer if answer else "",
                    correct or "",
                    answer.score if answer else 0,
                    answer.feedback if answer else "",
                ])

            # Auto-size columns
            for col in ws.columns:
                max_length = 0
                col_letter = col[0].column_letter
                for cell in col:
                    if cell.value:
                        max_length = max(max_length, min(len(str(cell.value)), 50))
                ws.column_dimensions[col_letter].width = max_length + 2

            buf = BytesIO()
            wb.save(buf)
            buf.seek(0)

            data = buf.getvalue()
            filename = f"practice_test_{test.created_at.strftime('%Y%m%d')}.xlsx"
            return {"data": data, "filename": filename}
        finally:
            db.close()

    res = await run_db_sync(_sync_work)
    buf = BytesIO(res["data"])
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{res["filename"]}"'},
    )
