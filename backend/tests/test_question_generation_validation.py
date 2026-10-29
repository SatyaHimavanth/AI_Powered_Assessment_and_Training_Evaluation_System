import pytest

from core.question_generation import _validate_generated_questions


def test_question_generation_rejects_short_or_wrong_type_responses():
    with pytest.raises(ValueError, match="exactly 1"):
        _validate_generated_questions([], count=1, question_type="text")

    with pytest.raises(ValueError, match="invalid type or text"):
        _validate_generated_questions(
            [{
                "question_type": "multi_mcq",
                "question_text": "Question?",
                "options": [],
                "reference_answer": None,
            }],
            count=1,
            question_type="single_mcq",
        )


def test_question_generation_requires_one_correct_single_choice_answer():
    question = {
        "question_type": "single_mcq",
        "question_text": "Question?",
        "options": [
            {"option_text": "A", "is_correct": True},
            {"option_text": "B", "is_correct": True},
            {"option_text": "C", "is_correct": False},
            {"option_text": "D", "is_correct": False},
        ],
        "reference_answer": None,
    }
    with pytest.raises(ValueError, match="exactly one"):
        _validate_generated_questions([question], count=1, question_type="single_mcq")


def test_question_generation_accepts_exactly_shaped_text_answer():
    validated = _validate_generated_questions(
        [{
            "question_type": "text",
            "question_text": "Explain transactions.",
            "options": None,
            "reference_answer": "A transaction is an atomic unit of database work.",
        }],
        count=1,
        question_type="text",
    )
    assert validated[0]["question_text"] == "Explain transactions."
