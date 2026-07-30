import io
import asyncio
import logging
from typing import List
from uuid import UUID

import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from core.auth import require_admin
from db.database import SessionLocal
from db.async_helpers import run_db_sync
from db.models import (
    Difficulty,
    Question,
    QuestionOption,
    QuestionType,
    TestCase,
    Topic,
    User,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/questions", tags=["questions"])


# ---------- Schemas ---------- #


class TopicOut(BaseModel):
    id: UUID
    name: str
    description: str | None

    class Config:
        from_attributes = True


class QuestionOut(BaseModel):
    id: UUID
    topic: str
    type: str
    difficulty: str
    question: str
    reference_answer: str | None
    options: list[dict] | None

    class Config:
        from_attributes = True


class QuestionsListResponse(BaseModel):
    items: List[QuestionOut]
    total: int
    page: int
    limit: int


class MessageResponse(BaseModel):
    message: str


class TopicUpdateIn(BaseModel):
    name: str | None = None
    description: str | None = None


class OptionIn(BaseModel):
    text: str
    is_correct: bool = False


class TestCaseIn(BaseModel):
    input: str
    expected_output: str
    is_sample: bool = False


class QuestionUpdateIn(BaseModel):
    question: str | None = None
    type: str | None = None
    difficulty: str | None = None
    reference_answer: str | None = None
    default_code: str | None = None
    options: list[OptionIn] | None = None
    test_cases: list[TestCaseIn] | None = None


class UploadResult(BaseModel):
    topic: str
    total_rows: int
    imported: int
    skipped: int
    errors: list[str]


# ---------- Helpers ---------- #

VALID_TYPES = {t.value for t in QuestionType}
VALID_DIFFICULTIES = {d.value for d in Difficulty}

REQUIRED_COLUMNS = {"type", "difficulty", "question"}
OPTIONAL_COLUMNS = {"option_a", "option_b", "option_c", "option_d", "correct_options", "reference_answer", "function_name"}


def get_or_create_topic(db: Session, topic_name: str) -> Topic:
    topic = db.query(Topic).filter(Topic.name == topic_name).first()
    if not topic:
        topic = Topic(name=topic_name, description=f"Questions about {topic_name}")
        db.add(topic)
        db.flush()
    else:
        # If an archived topic exists with this name, unarchive it for reuse
        if getattr(topic, "is_archived", False):
            topic.is_archived = False
            if not topic.description:
                topic.description = f"Questions about {topic_name}"
            db.flush()
    return topic


def parse_row(row: pd.Series, row_num: int) -> tuple[dict | None, str | None]:
    """Parse and validate a DataFrame row. Returns (parsed_data, error_message)."""
    q_type = str(row.get("type", "")).strip().lower()
    difficulty = str(row.get("difficulty", "")).strip().lower()
    question_text = str(row.get("question", "")).strip()

    # pandas reads NaN for empty cells
    if not question_text or question_text == "nan":
        return None, f"Row {row_num}: empty question"

    if q_type not in VALID_TYPES:
        return None, f"Row {row_num}: invalid type '{q_type}'. Must be one of {VALID_TYPES}"

    if difficulty not in VALID_DIFFICULTIES:
        return None, f"Row {row_num}: invalid difficulty '{difficulty}'. Must be one of {VALID_DIFFICULTIES}"

    options = []
    correct = str(row.get("correct_options", "")).strip()
    if correct == "nan":
        correct = ""

    if q_type in ("single_mcq", "multi_mcq"):
        for key in ("option_a", "option_b", "option_c", "option_d"):
            opt_text = str(row.get(key, "")).strip()
            if opt_text and opt_text != "nan":
                letter = key[-1].upper()
                is_correct = letter in correct.upper().split("|")
                options.append({"text": opt_text, "is_correct": is_correct})

        if not options:
            return None, f"Row {row_num}: MCQ question has no options"
        if not any(o["is_correct"] for o in options):
            return None, f"Row {row_num}: MCQ question has no correct option marked"

    reference_answer = str(row.get("reference_answer", "")).strip()
    if reference_answer == "nan":
        reference_answer = ""

    default_code = str(row.get("default_code", "")).strip()
    if default_code == "nan":
        default_code = ""

    return {
        "type": q_type,
        "difficulty": difficulty,
        "question": question_text,
        "options": options,
        "reference_answer": reference_answer or None,
        "default_code": default_code or None,
    }, None


def _options_equal(db_options, parsed_options) -> bool:
    db_list = [(((o.option_text or "").strip()), bool(o.is_correct)) for o in (db_options or [])]
    parsed_list = [(((opt.get("text") or "").strip()), bool(opt.get("is_correct"))) for opt in (parsed_options or [])]
    return db_list == parsed_list


def _testcases_equal(db_tcs, parsed_tcs) -> bool:
    db_list = [(((tc.input_data or "").strip()), ((tc.expected_output or "").strip()), bool(tc.is_sample)) for tc in (db_tcs or [])]
    parsed_list = [(((t.get("input") or "").strip()), ((t.get("expected_output") or "").strip()), bool(t.get("is_sample"))) for t in (parsed_tcs or [])]
    # compare as multisets (order-insensitive)
    return sorted(db_list) == sorted(parsed_list)


def _question_matches_db(db_q: Question, parsed: dict, parsed_tcs: list[dict]) -> bool:
    # Compare core scalar fields
    if (getattr(db_q.type, "value", str(db_q.type)) != parsed.get("type")):
        return False
    if (getattr(db_q.difficulty, "value", str(db_q.difficulty)) != parsed.get("difficulty")):
        return False
    if ((db_q.reference_answer or "").strip() != (parsed.get("reference_answer") or "").strip()):
        return False
    if ((db_q.default_code or "").strip() != (parsed.get("default_code") or "").strip()):
        return False

    # Options for MCQ
    if parsed.get("type") in ("single_mcq", "multi_mcq"):
        if not _options_equal(db_q.options, parsed.get("options")):
            return False

    # Test cases for coding
    if parsed.get("type") == "coding":
        if not _testcases_equal(db_q.test_cases, parsed_tcs or []):
            return False

    return True


# ---------- Embedding helpers ---------- #


def _generate_embeddings_for_questions(questions: list[dict]) -> None:
    """Generate and store embeddings for a list of newly created questions (runs in background thread)."""
    try:
        from core.embedding_service import build_embedding_text, compute_embeddings, store_question_embedding

        # Build composite texts
        texts = [
            build_embedding_text(
                question_text=q["question_text"],
                question_type=q["question_type"],
                options=q.get("options"),
                reference_answer=q.get("reference_answer"),
            )
            for q in questions
        ]

        # Batch compute embeddings
        embeddings = compute_embeddings(texts)

        # Store each embedding
        for q, text, embedding in zip(questions, texts, embeddings):
            store_question_embedding(
                question_id=q["id"],
                staged_question_id=None,
                text=text,
                embedding=embedding,
            )

        logger.info(f"Generated embeddings for {len(questions)} uploaded questions")
    except Exception as e:
        logger.error(f"Failed to generate embeddings for uploaded questions: {e}")


# ---------- Endpoints ---------- #


@router.post("/upload", response_model=UploadResult)
async def upload_questions(
    topic_name: str,
    file: UploadFile = File(...),
    _admin: User = Depends(require_admin),
):
    """Upload an Excel (.xlsx) or CSV file of questions for a given topic.
    
    For coding questions, include a second sheet named 'test_cases' with columns:
    question_number, input, expected_output, is_sample
    where question_number maps to the row index (1-based) in the questions sheet.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    filename = file.filename.lower()
    content = await file.read()

    # uses module-level `run_db_sync` and `SessionLocal`

    def _sync_work(content_bytes: bytes, filename_local: str, topic_name_local: str):
        import io as _io
        import pandas as _pd

        test_cases_df = None
        try:
            if filename_local.endswith(".xlsx") or filename_local.endswith(".xls"):
                xls = _pd.ExcelFile(_io.BytesIO(content_bytes), engine="openpyxl")
                df = _pd.read_excel(xls, sheet_name=0)
                # Try to read test_cases sheet
                if "test_cases" in xls.sheet_names:
                    test_cases_df = _pd.read_excel(xls, sheet_name="test_cases")
                    test_cases_df.columns = test_cases_df.columns.str.strip().str.lower()
            elif filename_local.endswith(".csv"):
                df = _pd.read_csv(_io.BytesIO(content_bytes))
            else:
                raise HTTPException(status_code=400, detail="Only .xlsx and .csv files are supported")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to read file: {str(e)}")

        # Normalize column names
        df.columns = df.columns.str.strip().str.lower()

        # Validate required columns
        missing = REQUIRED_COLUMNS - set(df.columns)
        if missing:
            raise HTTPException(status_code=400, detail=f"Missing required columns: {missing}")

        # Build test case lookup: question_number -> list of test cases
        tc_lookup: dict[int, list[dict]] = {}
        if test_cases_df is not None:
            tc_required = {"question_number", "input", "expected_output"}
            tc_missing = tc_required - set(test_cases_df.columns)
            if tc_missing:
                raise HTTPException(
                    status_code=400,
                    detail=f"test_cases sheet missing columns: {tc_missing}. Required: {tc_required}",
                )
            for _, tc_row in test_cases_df.iterrows():
                qnum = int(tc_row["question_number"])
                inp = str(tc_row["input"]).strip()
                exp = str(tc_row["expected_output"]).strip()
                is_sample = str(tc_row.get("is_sample", "false")).strip().lower() in ("true", "1", "yes")
                if inp == "nan":
                    inp = ""
                if exp == "nan":
                    exp = ""
                tc_lookup.setdefault(qnum, []).append({
                    "input": inp,
                    "expected_output": exp,
                    "is_sample": is_sample,
                })

        db = SessionLocal()
        try:
            topic = get_or_create_topic(db, topic_name_local.strip())

            imported = 0
            skipped = 0
            errors: list[str] = []
            new_questions_for_embedding: list[dict] = []

            for idx, row in df.iterrows():
                row_num = idx + 2  # 1-indexed + header
                question_number = idx + 1  # 1-based question number for test case matching
                parsed, error = parse_row(row, row_num)
                if error:
                    errors.append(error)
                    skipped += 1
                    continue

                # Coding questions must have test cases
                if parsed["type"] == "coding" and question_number not in tc_lookup:
                    errors.append(f"Row {row_num}: coding question has no test cases in 'test_cases' sheet (question_number={question_number})")
                    skipped += 1
                    continue

                # Check for existing questions with same text in this topic
                existing_list = (
                    db.query(Question)
                    .filter(Question.topic_id == topic.id, Question.question == parsed["question"])
                    .all()
                )

                if existing_list:
                    # Try to find an exact match (including options/testcases) among existing rows
                    matched = None
                    parsed_tcs = tc_lookup.get(question_number, [])
                    for ex in existing_list:
                        if _question_matches_db(ex, parsed, parsed_tcs):
                            matched = ex
                            break

                    if matched:
                        # If the matching row is archived, unarchive it and treat as imported
                        if getattr(matched, "is_archived", False):
                            matched.is_archived = False
                            db.flush()
                            imported += 1
                            continue
                        # Matching active question -> skip as duplicate
                        skipped += 1
                        errors.append(f"Row {row_num}: duplicate question (already exists)")
                        continue
                    # No exact match found: fall through and create a new question record

                question = Question(
                    topic_id=topic.id,
                    type=QuestionType(parsed["type"]),
                    difficulty=Difficulty(parsed["difficulty"]),
                    question=parsed["question"],
                    reference_answer=parsed["reference_answer"],
                    default_code=parsed.get("default_code"),
                )
                db.add(question)
                db.flush()

                for opt in parsed["options"]:
                    option = QuestionOption(
                        question_id=question.id,
                        option_text=opt["text"],
                        is_correct=opt["is_correct"],
                    )
                    db.add(option)

                # Add test cases for coding questions
                if parsed["type"] == "coding" and question_number in tc_lookup:
                    for tc in tc_lookup[question_number]:
                        db.add(TestCase(
                            question_id=question.id,
                            input_data=tc["input"],
                            expected_output=tc["expected_output"],
                            is_sample=tc["is_sample"],
                        ))

                # Collect data for embedding generation
                new_questions_for_embedding.append({
                    "id": question.id,
                    "question_text": parsed["question"],
                    "question_type": parsed["type"],
                    "options": [{"option_text": o["text"], "is_correct": o["is_correct"]} for o in parsed["options"]],
                    "reference_answer": parsed["reference_answer"],
                })

                imported += 1

            db.commit()

            return {
                "topic": topic.name,
                "total_rows": imported + skipped,
                "imported": imported,
                "skipped": skipped,
                "errors": errors[:20],
                "_new_questions": new_questions_for_embedding,
            }
        finally:
            db.close()

    result = await run_db_sync(_sync_work, content, filename, topic_name)

    # Generate embeddings in background for newly imported questions
    new_questions = result.pop("_new_questions", [])
    if new_questions:
        asyncio.get_running_loop().run_in_executor(
            None, _generate_embeddings_for_questions, new_questions
        )

    return UploadResult(**result)


@router.get("/topics", response_model=List[TopicOut])
async def list_topics(include_archived: bool = False, _admin: User = Depends(require_admin)):
    def _sync_work():
        db = SessionLocal()
        try:
            q = db.query(Topic)
            if not include_archived:
                q = q.filter(Topic.is_archived == False)
            topics = q.all()
            out = []
            for t in topics:
                out.append({"id": t.id, "name": t.name, "description": t.description})
            return out
        finally:
            db.close()

    return await run_db_sync(_sync_work)


@router.post("/topics", response_model=TopicOut)
async def create_topic(
    payload: TopicUpdateIn,
    _admin: User = Depends(require_admin),
):
    """Create a topic with a name and optional description."""
    name = payload.name.strip() if payload.name else ""
    if not name:
        raise HTTPException(status_code=400, detail="Topic name is required")

    desc = payload.description

    def _sync_work():
        db = SessionLocal()
        try:
            existing = db.query(Topic).filter(Topic.name == name).first()
            if existing:
                # If there is an archived topic with this name, unarchive it instead of erroring
                if getattr(existing, "is_archived", False):
                    existing.is_archived = False
                    if desc is not None:
                        existing.description = desc
                    db.commit()
                    db.refresh(existing)
                    return {"id": existing.id, "name": existing.name, "description": existing.description}
                raise HTTPException(status_code=400, detail="Topic name already in use")

            topic = Topic(name=name, description=desc)
            db.add(topic)
            db.commit()
            db.refresh(topic)
            return {"id": topic.id, "name": topic.name, "description": topic.description}
        finally:
            db.close()

    res = await run_db_sync(_sync_work)
    return TopicOut(**res)


@router.get("/", response_model=QuestionsListResponse)
async def list_questions(
    topic_id: UUID | None = None,
    q_type: str | None = None,
    difficulty: str | None = None,
    include_archived: bool = False,
    page: int = 1,
    limit: int = 10,
    search: str | None = None,
    _admin: User = Depends(require_admin),
):
    """List questions with optional filtering, paging, and search across question/options/answers.

    Offloads the sync DB work into a threadpool via `run_db_sync`.
    """
    # uses module-level `run_db_sync` and `SessionLocal`

    def _sync_work():
        db = SessionLocal()
        try:
            page_local = max(1, int(page or 1))
            limit_local = max(1, int(limit or 10))

            # Base filters (no joins)
            base_filters = []
            if not include_archived:
                base_filters.append(Question.is_archived == False)
            if topic_id:
                base_filters.append(Question.topic_id == topic_id)
            if q_type:
                try:
                    base_filters.append(Question.type == QuestionType(q_type))
                except ValueError:
                    raise HTTPException(status_code=400, detail=f"Invalid question type: {q_type}")
            if difficulty:
                try:
                    base_filters.append(Question.difficulty == Difficulty(difficulty))
                except ValueError:
                    raise HTTPException(status_code=400, detail=f"Invalid difficulty: {difficulty}")

            offset = (page_local - 1) * limit_local

            # If search provided, include QuestionOption in the query and require all words
            if search and search.strip():
                words = [w.strip().lower() for w in search.split() if w.strip()]
                # select both id and created_at so ORDER BY created_at is valid with DISTINCT on Postgres
                id_q = db.query(Question.id, Question.created_at).outerjoin(QuestionOption)
                for f in base_filters:
                    id_q = id_q.filter(f)

                for w in words:
                    pattern = f"%{w}%"
                    id_q = id_q.filter(
                        or_(
                            func.lower(Question.question).like(pattern),
                            func.lower(Question.reference_answer).like(pattern),
                            func.lower(QuestionOption.option_text).like(pattern),
                        )
                    )

                id_q = id_q.distinct()
                total = db.query(func.count()).select_from(id_q.subquery()).scalar() or 0
                ids_page = id_q.order_by(Question.created_at.desc()).limit(limit_local).offset(offset).all()
                # ids_page contains tuples (id, created_at); extract ids
                ids = [i[0] for i in ids_page]
                if not ids:
                    return QuestionsListResponse(items=[], total=total, page=page_local, limit=limit_local)
                questions = db.query(Question).filter(Question.id.in_(ids)).all()
                # Preserve order returned by ids
                qmap = {q.id: q for q in questions}
                ordered = [qmap[i] for i in ids if i in qmap]
            else:
                q = db.query(Question)
                for f in base_filters:
                    q = q.filter(f)
                total = q.count()
                q = q.order_by(Question.created_at.desc()).limit(limit_local).offset(offset)
                ordered = q.all()

            items: List[QuestionOut] = []
            for qobj in ordered:
                opts = None
                if qobj.options:
                    opts = [{"text": o.option_text, "is_correct": o.is_correct} for o in qobj.options]
                items.append(
                    QuestionOut(
                        id=qobj.id,
                        topic=qobj.topic.name if qobj.topic else "Unknown",
                        type=qobj.type.value,
                        difficulty=qobj.difficulty.value,
                        question=qobj.question,
                        reference_answer=qobj.reference_answer,
                        options=opts,
                    )
                )

            return QuestionsListResponse(items=items, total=total, page=page_local, limit=limit_local)
        finally:
            db.close()

    return await run_db_sync(_sync_work)


@router.patch("/topics/{topic_id}", response_model=TopicOut)
async def update_topic(
    topic_id: UUID,
    payload: TopicUpdateIn,
    _admin: User = Depends(require_admin),
):
    name = payload.name
    desc = payload.description

    def _sync_work():
        db = SessionLocal()
        try:
            topic = db.query(Topic).filter(Topic.id == topic_id).first()
            if not topic:
                raise HTTPException(status_code=404, detail="Topic not found")

            if name is not None:
                # ensure uniqueness
                existing = db.query(Topic).filter(Topic.name == name).first()
                if existing and existing.id != topic.id:
                    raise HTTPException(status_code=400, detail="Topic name already in use")
                topic.name = name
            if desc is not None:
                topic.description = desc

            db.commit()
            return {"id": topic.id, "name": topic.name, "description": topic.description}
        finally:
            db.close()

    res = await run_db_sync(_sync_work)
    return TopicOut(**res)


@router.delete("/topics/{topic_id}", response_model=MessageResponse)
async def delete_topic(
    topic_id: UUID,
    mode: str | None = None,  # 'cascade' or 'reassign'
    reassign_to: UUID | None = None,
    _admin: User = Depends(require_admin),
):
    """Delete a topic.

    If `mode=cascade` the questions under the topic (and their options and assessment links)
    will be removed. If `mode=reassign` and `reassign_to` provided, questions will be moved
    to the target topic before deleting this topic. If the topic has questions and neither
    option is provided, the request will be rejected to prevent accidental data loss.
    """
    def _sync_work():
        db = SessionLocal()
        try:
            topic = db.query(Topic).filter(Topic.id == topic_id).first()
            if not topic:
                raise HTTPException(status_code=404, detail="Topic not found")

            # find question ids belonging to this topic
            q_ids = [q.id for q in db.query(Question).filter(Question.topic_id == topic_id).all()]

            if q_ids:
                if mode == "cascade":
                    # Archive questions (keep topic_id so results can still show topic name)
                    db.query(Question).filter(Question.id.in_(q_ids)).update(
                        {Question.is_archived: True}, synchronize_session='fetch'
                    )
                    topic.is_archived = True
                    db.commit()
                    return {"message": f"Topic archived and {len(q_ids)} questions archived."}

                elif mode == "reassign" and reassign_to is not None:
                    if reassign_to == topic_id:
                        raise HTTPException(status_code=400, detail="Cannot reassign to the same topic")
                    new_topic = db.query(Topic).filter(Topic.id == reassign_to).first()
                    if not new_topic:
                        raise HTTPException(status_code=404, detail="Reassign-to topic not found")
                    # reassign questions
                    db.query(Question).filter(Question.topic_id == topic_id).update({Question.topic_id: reassign_to}, synchronize_session='fetch')
                    # archive old topic
                    topic.is_archived = True
                    db.commit()
                    return {"message": f"Topic archived and questions reassigned to '{new_topic.name}'."}

                else:
                    raise HTTPException(
                        status_code=400,
                        detail="Topic contains questions; provide mode=cascade to archive questions or mode=reassign and reassign_to=<topic_id> to move them.",
                    )
            # no questions: archive the topic instead of deleting
            topic.is_archived = True
            db.commit()
            return {"message": "Topic archived."}
        finally:
            db.close()

    return await run_db_sync(_sync_work)


@router.delete("/{question_id}", response_model=MessageResponse)
async def delete_question(
    question_id: UUID,
    _admin: User = Depends(require_admin),
):
    """Archive (soft-delete) a question by id. Runs DB work in threadpool."""
    def _sync_work():
        db = SessionLocal()
        try:
            q = db.query(Question).filter(Question.id == question_id).first()
            if not q:
                raise HTTPException(status_code=404, detail="Question not found")
            if getattr(q, "is_archived", False):
                return {"message": "Question already archived."}
            q.is_archived = True
            db.commit()
            return {"message": "Question archived."}
        finally:
            db.close()

    return await run_db_sync(_sync_work)


class TestCaseOut(BaseModel):
    id: UUID
    input_data: str
    expected_output: str
    is_sample: bool

    class Config:
        from_attributes = True


class QuestionDetailOut(QuestionOut):
    default_code: str | None = None
    test_cases: list[TestCaseOut] | None = None


@router.get("/{question_id}", response_model=QuestionDetailOut)
async def get_question(
    question_id: UUID,
    _admin: User = Depends(require_admin),
):
    def _sync_work():
        db = SessionLocal()
        try:
            q = db.query(Question).filter(Question.id == question_id).first()
            if not q or getattr(q, "is_archived", False):
                raise HTTPException(status_code=404, detail="Question not found")

            opts = None
            if q.options:
                opts = [{"text": o.option_text, "is_correct": o.is_correct} for o in q.options]

            tcs = None
            if q.test_cases:
                tcs = [
                    {"id": tc.id, "input_data": tc.input_data, "expected_output": tc.expected_output, "is_sample": tc.is_sample}
                    for tc in q.test_cases
                ]

            return {
                "id": q.id,
                "topic": q.topic.name if q.topic else "Unknown",
                "type": q.type.value,
                "difficulty": q.difficulty.value,
                "question": q.question,
                "reference_answer": q.reference_answer,
                "options": opts,
                "default_code": q.default_code,
                "test_cases": tcs,
            }
        finally:
            db.close()

    res = await run_db_sync(_sync_work)
    return QuestionDetailOut(**res)


@router.patch("/{question_id}", response_model=QuestionDetailOut)
async def update_question(
    question_id: UUID,
    payload: QuestionUpdateIn,
    _admin: User = Depends(require_admin),
):
    pdata = payload.model_dump(exclude_unset=True)

    def _sync_work():
        db = SessionLocal()
        try:
            q = db.query(Question).filter(Question.id == question_id).first()
            if not q or getattr(q, "is_archived", False):
                raise HTTPException(status_code=404, detail="Question not found")

            # Validate and apply scalar fields
            if pdata.get("type") is not None:
                try:
                    q.type = QuestionType(pdata.get("type"))
                except ValueError:
                    raise HTTPException(status_code=400, detail=f"Invalid question type: {pdata.get('type')}")

            if pdata.get("difficulty") is not None:
                try:
                    q.difficulty = Difficulty(pdata.get("difficulty"))
                except ValueError:
                    raise HTTPException(status_code=400, detail=f"Invalid difficulty: {pdata.get('difficulty')}")

            if pdata.get("question") is not None:
                val = (pdata.get("question") or "").strip()
                if not val:
                    raise HTTPException(status_code=400, detail="Question text cannot be empty")
                q.question = val

            if "reference_answer" in pdata:
                q.reference_answer = pdata.get("reference_answer") or None

            if "default_code" in pdata:
                q.default_code = pdata.get("default_code") or None

            # Options: replace if provided
            if "options" in pdata:
                if getattr(q.type, "value", str(q.type)) in ("single_mcq", "multi_mcq"):
                    opts = pdata.get("options") or []
                    if not opts:
                        raise HTTPException(status_code=400, detail="MCQ must have at least one option")
                    if not any(o.get("is_correct") for o in opts):
                        raise HTTPException(status_code=400, detail="At least one option must be marked correct")
                    # Remove existing
                    db.query(QuestionOption).filter(QuestionOption.question_id == q.id).delete(synchronize_session='fetch')
                    for opt in opts:
                        db.add(QuestionOption(question_id=q.id, option_text=opt.get("text"), is_correct=bool(opt.get("is_correct"))))
                else:
                    # If question is not MCQ but options provided, reject
                    raise HTTPException(status_code=400, detail="Options provided for non-MCQ question")

            # Test cases: replace if provided
            if "test_cases" in pdata:
                if getattr(q.type, "value", str(q.type)) == "coding":
                    tcs = pdata.get("test_cases") or []
                    # Basic validation
                    for tc in tcs:
                        if not tc.get("input") or not tc.get("expected_output"):
                            raise HTTPException(status_code=400, detail="Test cases must include input and expected_output")
                    # Delete existing and add new
                    db.query(TestCase).filter(TestCase.question_id == q.id).delete(synchronize_session='fetch')
                    for tc in tcs:
                        db.add(TestCase(question_id=q.id, input_data=tc.get("input") or "", expected_output=tc.get("expected_output") or "", is_sample=bool(tc.get("is_sample"))))
                else:
                    raise HTTPException(status_code=400, detail="Test cases provided for non-coding question")

            db.commit()
            db.refresh(q)

            # Prepare response
            opts_out = None
            if q.options:
                opts_out = [{"text": o.option_text, "is_correct": o.is_correct} for o in q.options]
            tcs_out = None
            if q.test_cases:
                tcs_out = [
                    {"id": tc.id, "input_data": tc.input_data, "expected_output": tc.expected_output, "is_sample": tc.is_sample}
                    for tc in q.test_cases
                ]

            return {
                "id": q.id,
                "topic": q.topic.name if q.topic else "Unknown",
                "type": q.type.value,
                "difficulty": q.difficulty.value,
                "question": q.question,
                "reference_answer": q.reference_answer,
                "options": opts_out,
                "default_code": q.default_code,
                "test_cases": tcs_out,
            }
        finally:
            db.close()

    res = await run_db_sync(_sync_work)
    return QuestionDetailOut(**res)
