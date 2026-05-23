"""
Question generation service using LLM.

Generates questions from source text/documents and runs similarity checking.
"""

import json
import logging
import uuid as uuid_mod
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select

from app.llms import get_chat_model
from core.embedding_service import (
    build_embedding_text,
    check_similarity,
    compute_embeddings,
    store_question_embedding,
    get_match_band,
    THRESHOLD_HIGH_DUP,
)
from db.database import SessionLocal
from db.models import (
    GenerationBatchStatus,
    MatchBand,
    Question,
    QuestionGenerationBatch,
    QuestionOption,
    QuestionType,
    StagedQuestion,
    StagedQuestionStatus,
    Topic,
)

logger = logging.getLogger(__name__)


GENERATION_PROMPT = """You are an expert question generator for educational assessments.

Given the following source material, generate {count} high-quality questions.

STRICT Requirements:
- Question type: {question_type}
- ALL questions MUST be of type "{question_type}" — do NOT generate any other type
- Difficulty: {difficulty}
- Topic: {topic}
- Each question must be distinct and test different concepts
{type_instructions}

Source Material:
---
{source_text}
---

Respond with a JSON array of questions. Each question object must have:
- "question_text": the question string
- "question_type": "{question_type}"
- "difficulty": "{difficulty}"
- "reference_answer": reference answer text (for text questions) or null
- "options": array of {{"option_text": "...", "is_correct": true/false}} (for MCQ) or null (for text)

IMPORTANT: Every question MUST have "question_type" set to exactly "{question_type}".
Return ONLY valid JSON, no markdown fencing or explanation.
"""

TYPE_INSTRUCTIONS = {
    "text": "- Generate open-ended text questions that require descriptive answers\n- Provide a comprehensive reference answer for each question\n- Do NOT include options — set options to null",
    "single_mcq": "- Generate multiple-choice questions with exactly ONE correct answer\n- Provide exactly 4 options per question\n- Mark exactly one option as is_correct: true",
    "multi_mcq": "- Generate multiple-choice questions with MULTIPLE correct answers\n- Provide exactly 4 options per question\n- Mark 2 or 3 options as is_correct: true",
}


def _parse_generated_questions(response_text: str) -> List[dict]:
    """Parse LLM response into a list of question dicts."""
    # Strip any markdown code fencing
    text = response_text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first and last lines (```json and ```)
        lines = [l for l in lines[1:] if not l.strip().startswith("```")]
        text = "\n".join(lines)

    try:
        questions = json.loads(text)
        if isinstance(questions, list):
            return questions
        if isinstance(questions, dict) and "questions" in questions:
            return questions["questions"]
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse LLM response as JSON: {e}")
        raise ValueError(f"LLM response is not valid JSON: {e}")

    raise ValueError("Unexpected LLM response format")


def generate_questions_from_text(
    source_text: str,
    question_type: str,
    difficulty: str,
    topic_name: str,
    count: int = 10,
) -> List[dict]:
    """Generate questions using LLM from source text."""
    llm = get_chat_model()

    prompt = GENERATION_PROMPT.format(
        count=count,
        question_type=question_type,
        difficulty=difficulty,
        topic=topic_name,
        source_text=source_text[:8000],  # Limit context size
        type_instructions=TYPE_INSTRUCTIONS.get(question_type, TYPE_INSTRUCTIONS["text"]),
    )

    response = llm.invoke(prompt)
    return _parse_generated_questions(response.content)


def process_generation_batch(batch_id: uuid_mod.UUID) -> None:
    """
    Process a question generation batch:
    1. Generate questions via LLM
    2. Compute embeddings
    3. Check similarity against existing question bank
    4. Store as staged questions with match bands
    """
    db = SessionLocal()
    try:
        batch = db.execute(
            select(QuestionGenerationBatch).where(QuestionGenerationBatch.id == batch_id)
        ).scalar_one_or_none()

        if not batch:
            logger.error(f"Batch {batch_id} not found")
            return

        # Update status
        batch.status = GenerationBatchStatus.processing
        db.commit()

        # Resolve topic name
        topic_name = "General"
        if batch.topic_id:
            topic = db.execute(
                select(Topic).where(Topic.id == batch.topic_id)
            ).scalar_one_or_none()
            if topic:
                topic_name = topic.name

        # 1. Generate questions
        try:
            q_type = batch.question_type.value if batch.question_type else "text"
            diff = batch.difficulty.value if batch.difficulty else "medium"
            generated = generate_questions_from_text(
                source_text=batch.source_text or "",
                question_type=q_type,
                difficulty=diff,
                topic_name=topic_name,
                count=batch.requested_count,
            )
        except Exception as e:
            batch.status = GenerationBatchStatus.failed
            batch.error_message = str(e)
            db.commit()
            logger.error(f"Generation failed for batch {batch_id}: {e}")
            return

        if not generated:
            batch.status = GenerationBatchStatus.failed
            batch.error_message = "LLM returned no questions"
            db.commit()
            return

        # 2. Compute embeddings for all generated questions (composite text)
        batch.status = GenerationBatchStatus.embedding
        db.commit()

        embedding_texts = [
            build_embedding_text(
                question_text=q.get("question_text", ""),
                question_type=q.get("question_type", "text"),
                options=q.get("options"),
                reference_answer=q.get("reference_answer"),
            )
            for q in generated
        ]
        try:
            embeddings = compute_embeddings(embedding_texts)
        except Exception as e:
            batch.status = GenerationBatchStatus.failed
            batch.error_message = f"Embedding computation failed: {e}"
            db.commit()
            return

        # 3. Similarity check and stage questions
        batch.status = GenerationBatchStatus.similarity_check
        db.commit()

        staged_count = 0
        auto_rejected_count = 0
        auto_approved_ids: list = []
        staged_for_embedding: list[tuple] = []  # (staged_id, emb_text, embedding)

        for q_data, emb_text, embedding in zip(generated, embedding_texts, embeddings):
            # Check similarity using composite text
            sim_score, matched_id, band = check_similarity(emb_text)

            # Determine status
            status = StagedQuestionStatus.pending
            if band == "high_dup":
                status = StagedQuestionStatus.auto_rejected
                auto_rejected_count += 1
            elif band == "unique" and batch.auto_approve_unique:
                status = StagedQuestionStatus.approved

            # Map question type
            q_type_enum = None
            raw_type = q_data.get("question_type", "text")
            for qt in QuestionType:
                if qt.value == raw_type:
                    q_type_enum = qt
                    break
            if not q_type_enum:
                q_type_enum = batch.question_type or QuestionType.text

            # Map difficulty
            from db.models import Difficulty
            diff_enum = None
            raw_diff = q_data.get("difficulty", "medium")
            for d in Difficulty:
                if d.value == raw_diff:
                    diff_enum = d
                    break
            if not diff_enum:
                diff_enum = batch.difficulty or Difficulty.medium

            # Map match band enum
            band_enum = None
            for mb in MatchBand:
                if mb.value == band:
                    band_enum = mb
                    break

            staged = StagedQuestion(
                id=uuid_mod.uuid4(),
                batch_id=batch_id,
                question_type=q_type_enum,
                question_text=q_data.get("question_text", ""),
                reference_answer=q_data.get("reference_answer"),
                options=q_data.get("options"),
                correct_answers=q_data.get("correct_answers"),
                topic_id=batch.topic_id,
                difficulty=diff_enum,
                similarity_score=sim_score,
                matched_question_id=matched_id,
                match_band=band_enum,
                status=status,
            )
            db.add(staged)
            staged_for_embedding.append((staged.id, emb_text, embedding))
            if status == StagedQuestionStatus.approved:
                auto_approved_ids.append(staged.id)
            staged_count += 1

        # Commit staged questions first so FK references exist
        db.commit()

        # Now store embeddings (uses separate session internally)
        for staged_id, emb_text, embedding in staged_for_embedding:
            store_question_embedding(
                question_id=None,
                staged_question_id=staged_id,
                text=emb_text,
                embedding=embedding,
            )

        # Auto-approve: promote staged questions to real questions
        auto_approved_count = 0
        for staged_id in auto_approved_ids:
            result = approve_staged_question(staged_id, batch.admin_id)
            if result:
                auto_approved_count += 1

        # Update batch totals
        batch.total_generated = staged_count
        batch.total_approved = auto_approved_count
        batch.total_rejected = auto_rejected_count
        batch.status = GenerationBatchStatus.completed
        batch.completed_at = datetime.now(timezone.utc)
        db.commit()

        logger.info(
            f"Batch {batch_id} completed: {staged_count} generated, "
            f"{auto_approved_count} auto-approved, {auto_rejected_count} auto-rejected"
        )

    except Exception as e:
        db.rollback()
        logger.error(f"Unexpected error processing batch {batch_id}: {e}")
        try:
            batch = db.execute(
                select(QuestionGenerationBatch).where(QuestionGenerationBatch.id == batch_id)
            ).scalar_one_or_none()
            if batch:
                batch.status = GenerationBatchStatus.failed
                batch.error_message = str(e)
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


def approve_staged_question(staged_id: uuid_mod.UUID, reviewer_id: uuid_mod.UUID) -> Optional[uuid_mod.UUID]:
    """
    Approve a staged question: create actual Question + QuestionOptions,
    update embedding to point to new question, return new question ID.
    """
    db = SessionLocal()
    try:
        staged = db.execute(
            select(StagedQuestion).where(StagedQuestion.id == staged_id)
        ).scalar_one_or_none()

        if not staged or staged.status != StagedQuestionStatus.pending:
            return None

        # Create the real Question
        new_question = Question(
            id=uuid_mod.uuid4(),
            topic_id=staged.topic_id,
            type=staged.question_type,
            question=staged.question_text,
            difficulty=staged.difficulty,
            reference_answer=staged.reference_answer,
        )
        db.add(new_question)
        db.flush()

        # Create options if MCQ
        if staged.options and staged.question_type in (QuestionType.single_mcq, QuestionType.multi_mcq):
            for opt in staged.options:
                option = QuestionOption(
                    id=uuid_mod.uuid4(),
                    question_id=new_question.id,
                    option_text=opt.get("option_text", ""),
                    is_correct=opt.get("is_correct", False),
                )
                db.add(option)

        # Update staged question status
        staged.status = StagedQuestionStatus.approved
        staged.reviewer_id = reviewer_id
        staged.reviewed_at = datetime.now(timezone.utc)

        # Update embedding to point to actual question
        from db.models import QuestionEmbedding
        emb = db.execute(
            select(QuestionEmbedding).where(QuestionEmbedding.staged_question_id == staged_id)
        ).scalar_one_or_none()
        if emb:
            emb.question_id = new_question.id

        # Update batch counters
        batch = db.execute(
            select(QuestionGenerationBatch).where(QuestionGenerationBatch.id == staged.batch_id)
        ).scalar_one_or_none()
        if batch:
            batch.total_approved = (batch.total_approved or 0) + 1

        db.commit()
        return new_question.id

    except Exception as e:
        db.rollback()
        logger.error(f"Failed to approve staged question {staged_id}: {e}")
        return None
    finally:
        db.close()


def reject_staged_question(staged_id: uuid_mod.UUID, reviewer_id: uuid_mod.UUID) -> bool:
    """Reject a staged question."""
    db = SessionLocal()
    try:
        staged = db.execute(
            select(StagedQuestion).where(StagedQuestion.id == staged_id)
        ).scalar_one_or_none()

        if not staged or staged.status != StagedQuestionStatus.pending:
            return False

        staged.status = StagedQuestionStatus.rejected
        staged.reviewer_id = reviewer_id
        staged.reviewed_at = datetime.now(timezone.utc)

        # Update batch counters
        batch = db.execute(
            select(QuestionGenerationBatch).where(QuestionGenerationBatch.id == staged.batch_id)
        ).scalar_one_or_none()
        if batch:
            batch.total_rejected = (batch.total_rejected or 0) + 1

        db.commit()
        return True
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to reject staged question {staged_id}: {e}")
        return False
    finally:
        db.close()
