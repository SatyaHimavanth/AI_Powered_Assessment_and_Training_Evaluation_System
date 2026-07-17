from typing import Any
from sqlalchemy.orm import Session
from api.timezone_helper import to_utc_iso


def build_attempt_results(db: Session, attempt) -> dict[str, Any]:
    """Build a results payload for an Attempt.

    Accepts either an Attempt ORM instance or an attempt id; if an id is
    provided the Attempt is loaded from the provided `db` session.

    Returns a dict compatible with both the user and admin results response models.
    """
    from db.models import (
        Attempt,
        Assessment,
        AssessmentQuestion,
        AssessmentQuestionItem,
        Question,
        QuestionOption,
        QuestionType,
        Topic,
        Answer,
        AttemptStatus,
    )

    # If caller passed an id, load the attempt here so callers can safely pass
    # either an ORM object or a scalar id.
    if not hasattr(attempt, "id"):
        attempt = db.query(Attempt).filter(Attempt.id == attempt).first()

    if not attempt:
        raise ValueError("Attempt or assessment not found")

    assessment = db.query(Assessment).filter(Assessment.id == attempt.assessment_id).first()
    if not assessment:
        raise ValueError("Assessment not found")

    aq_links = (
        db.query(AssessmentQuestion)
        .filter(AssessmentQuestion.assessment_id == assessment.id)
        .all()
    )

    item_ids = [aq.assessment_item_id for aq in aq_links if getattr(aq, "assessment_item_id", None)]
    question_ids = [aq.question_id for aq in aq_links if getattr(aq, "question_id", None)]

    items = db.query(AssessmentQuestionItem).filter(AssessmentQuestionItem.id.in_(item_ids)).all() if item_ids else []
    questions = db.query(Question).filter(Question.id.in_(question_ids)).all() if question_ids else []

    # Use integer keys to avoid unnecessary str conversions
    items_map = {i.id: i for i in items}
    q_map = {q.id: q for q in questions}

    user_answers = db.query(Answer).filter(Answer.attempt_id == attempt.id).all()
    answer_map = { (a.assessment_item_id or a.question_id): a for a in user_answers }

    # Preload topics for questions to avoid per-loop queries
    topic_ids = list({q.topic_id for q in questions if q.topic_id})
    topics = db.query(Topic).filter(Topic.id.in_(topic_ids)).all() if topic_ids else []
    topic_map = {t.id: t for t in topics}

    answers_out: list[dict[str, Any]] = []
    topic_stats: dict[str, dict] = {}
    correct_count = 0
    pending_answers = db.query(Answer).filter(Answer.attempt_id == attempt.id, Answer.score.is_(None)).count()
    evaluation_pending = pending_answers > 0 or attempt.score is None

    for aq in aq_links:
        user_ans = None
        topic_name = "Unknown"
        question_text = ""
        question_type = "text"
        correct_answer_text = ""
        user_answer_text = ""
        is_correct = False

        if getattr(aq, "assessment_item_id", None):
            item = items_map.get(aq.assessment_item_id)
            if not item:
                continue
            question_text = item.question_text
            question_type = item.question_type or "text"
            topic_name = item.topic or "Unknown"

            if item.options:
                correct_opts = [o for o in item.options if o.get("is_correct")]
                correct_answer_text = ", ".join(o.get("option_text") for o in correct_opts) if correct_opts else (item.reference_answer or "")
            else:
                correct_answer_text = item.reference_answer or ""

            user_ans = answer_map.get(item.id)
            if user_ans and user_ans.answer:
                if question_type in ("single_mcq", "multi_mcq") and item.options:
                    selected_ids = [s for s in user_ans.answer.split(",") if s]
                    selected_texts = [next((o.get("option_text") for o in item.options if str(o.get("id")) == s), "") for s in selected_ids]
                    user_answer_text = ", ".join([t for t in selected_texts if t])
                    is_correct = (user_ans.score or 0) >= 0.999 if user_ans.score is not None else False
                else:
                    user_answer_text = user_ans.answer
                    is_correct = (user_ans.score or 0) >= 0.999 if user_ans.score is not None else False

            earned_score = float(user_ans.score or 0) if user_ans and user_ans.score is not None else 0.0
            topic_stats.setdefault(topic_name, {"total": 0, "correct": 0})
            topic_stats[topic_name]["total"] += 1
            topic_stats[topic_name]["correct"] += earned_score
            if is_correct:
                correct_count += 1

            score_val = round(float(user_ans.score), 2) if user_ans and user_ans.score is not None else None
            answers_out.append({
                "question_id": item.id,
                "question_text": question_text,
                "question_type": question_type,
                "topic_name": topic_name,
                "your_answer": user_answer_text,
                "correct_answer": correct_answer_text,
                "is_correct": is_correct,
                "score": score_val,
                "suggestion": (user_ans.feedback if user_ans and user_ans.feedback else None),
            })
        else:
            q = q_map.get(aq.question_id)
            if not q:
                continue
            question_text = q.question
            question_type = q.type.value
            topic = topic_map.get(q.topic_id)
            topic_name = topic.name if topic else "Unknown"

            correct_opts = (
                db.query(QuestionOption)
                .filter(QuestionOption.question_id == q.id, QuestionOption.is_correct == True)
                .all()
            )
            correct_answer_text = ", ".join(o.option_text for o in correct_opts) if correct_opts else (q.reference_answer or "")

            user_ans = answer_map.get(q.id)
            user_answer_text = ""
            is_correct = False
            if user_ans and user_ans.answer:
                if q.type in (QuestionType.single_mcq, QuestionType.multi_mcq):
                    selected_ids = [s for s in user_ans.answer.split(",") if s]
                    if selected_ids:
                        # convert to ints where possible
                        try:
                            sel_ints = [int(s) for s in selected_ids]
                        except Exception:
                            sel_ints = selected_ids
                        selected_opts = db.query(QuestionOption).filter(QuestionOption.id.in_(sel_ints)).all()
                        user_answer_text = ", ".join(o.option_text for o in selected_opts)
                    else:
                        user_answer_text = ""
                    is_correct = (user_ans.score or 0) >= 0.999 if user_ans.score is not None else False
                else:
                    user_answer_text = user_ans.answer
                    is_correct = (user_ans.score or 0) >= 0.999 if user_ans.score is not None else False

            earned_score = float(user_ans.score or 0) if user_ans and user_ans.score is not None else 0.0
            topic_stats.setdefault(topic_name, {"total": 0, "correct": 0})
            topic_stats[topic_name]["total"] += 1
            topic_stats[topic_name]["correct"] += earned_score
            if is_correct:
                correct_count += 1

            score_val = round(float(user_ans.score), 2) if user_ans and user_ans.score is not None else None
            answers_out.append({
                "question_id": q.id,
                "question_text": question_text,
                "question_type": question_type,
                "topic_name": topic_name,
                "your_answer": user_answer_text,
                "correct_answer": correct_answer_text,
                "is_correct": is_correct,
                "score": score_val,
                "suggestion": (user_ans.feedback if user_ans and user_ans.feedback else None),
            })

    total_questions = len(questions) + len(items)
    answered = len(user_answers)
    score = attempt.score

    topic_scores: list[dict[str, Any]] = []
    for name, stats in topic_stats.items():
        pct = round((stats["correct"] / stats["total"]) * 100, 1) if stats["total"] > 0 else 0
        topic_scores.append({"topic_name": name, "total": stats["total"], "correct": stats["correct"], "percentage": pct})

    status = ("evaluating" if evaluation_pending and attempt.status == AttemptStatus.completed else (attempt.status.value if attempt.status else "unknown"))

    return {
        "assessment_title": assessment.title,
        "status": status,
        "score": score,
        "evaluation_pending": evaluation_pending,
        "total_questions": total_questions,
        "answered": answered,
        "correct_count": correct_count,
        "started_at": to_utc_iso(attempt.started_at),
        "submitted_at": to_utc_iso(attempt.submitted_at),
        "topic_scores": topic_scores,
        "answers": answers_out,
    }
