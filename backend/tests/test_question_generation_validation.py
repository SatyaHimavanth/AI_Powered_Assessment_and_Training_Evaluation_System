import pytest
import copy
import json
from types import SimpleNamespace

from core import question_generation
from core.question_generation import _validate_generated_questions, generate_questions_from_text


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


def _single_choice_question():
    return {
        "question_type": "single_mcq",
        "question_text": "Which number is even?",
        "difficulty": "easy",
        "reference_answer": None,
        "options": [
            {"option_text": "2", "is_correct": True},
            {"option_text": "3", "is_correct": False},
            {"option_text": "5", "is_correct": False},
            {"option_text": "7", "is_correct": False},
        ],
    }


@pytest.mark.parametrize("correct_count", [0, 2, 4])
def test_generation_regenerates_invalid_third_answer_key_without_guessing(monkeypatch, correct_count):
    invalid = [_single_choice_question() for _ in range(3)]
    for index, option in enumerate(invalid[2]["options"]):
        option["is_correct"] = index < correct_count
    valid = [_single_choice_question() for _ in range(3)]
    for index in range(3):
        invalid[index]["question_text"] += f" Example {index}"
        valid[index]["question_text"] += f" Example {index}"
    original = copy.deepcopy(invalid)
    responses = iter([invalid, valid])
    prompts = []

    def invoke(prompt):
        prompts.append(prompt)
        return SimpleNamespace(content=json.dumps(next(responses)))

    monkeypatch.setattr(question_generation, "get_chat_model", lambda: SimpleNamespace(invoke=invoke))
    result = generate_questions_from_text("Synthetic source", "single_mcq", "easy", "Numbers", count=3)

    assert result == valid
    assert invalid == original
    assert len(prompts) == 2
    assert "question 3 needs exactly one correct option" in prompts[1]
    assert "Regenerate the entire array of exactly 3 questions" in prompts[1]


def test_generation_recovers_from_invalid_json_then_wrong_question_count(monkeypatch):
    responses = iter(["not JSON", "[]", json.dumps([_single_choice_question()])])
    prompts = []

    def invoke(prompt):
        prompts.append(prompt)
        return SimpleNamespace(content=next(responses))

    monkeypatch.setattr(question_generation, "get_chat_model", lambda: SimpleNamespace(invoke=invoke))
    assert len(generate_questions_from_text("Source", "single_mcq", "easy", "Numbers", count=1)) == 1
    assert len(prompts) == 3
    assert "not valid JSON" in prompts[1]
    assert "Expected exactly 1" in prompts[2]


def test_generation_stops_after_bounded_validation_failures(monkeypatch, caplog):
    calls = []

    def invoke(prompt):
        calls.append(prompt)
        return SimpleNamespace(content="[]")

    monkeypatch.setattr(question_generation, "get_chat_model", lambda: SimpleNamespace(invoke=invoke))
    with pytest.raises(ValueError, match="failed validation after 3 attempts: Expected exactly 1"):
        generate_questions_from_text("Source", "single_mcq", "easy", "Numbers", count=1)
    assert len(calls) == question_generation.MAX_GENERATION_ATTEMPTS == 3
    assert "regenerating" in caplog.text


def test_generation_does_not_repeat_provider_errors(monkeypatch):
    calls = []

    def invoke(prompt):
        calls.append(prompt)
        raise RuntimeError("Provider unavailable")

    monkeypatch.setattr(question_generation, "get_chat_model", lambda: SimpleNamespace(invoke=invoke))
    with pytest.raises(RuntimeError, match="Provider unavailable"):
        generate_questions_from_text("Source", "single_mcq", "easy", "Numbers", count=1)
    assert len(calls) == 1


def test_valid_generation_uses_only_one_provider_call(monkeypatch):
    calls = []

    def invoke(prompt):
        calls.append(prompt)
        return SimpleNamespace(content=json.dumps([_single_choice_question()]))

    monkeypatch.setattr(question_generation, "get_chat_model", lambda: SimpleNamespace(invoke=invoke))
    generate_questions_from_text("Source", "single_mcq", "easy", "Numbers", count=1)
    assert len(calls) == 1


@pytest.mark.parametrize("requested,sizes", [(25, [10, 10, 5]), (50, [10, 10, 10, 10, 10])])
def test_large_generation_chunks_requests_and_preserves_requested_count(monkeypatch, requested, sizes):
    calls = []

    def invoke(prompt):
        calls.append(prompt)
        size = sizes[len(calls) - 1]
        questions = []
        for index in range(size):
            question = _single_choice_question()
            question["question_text"] += f" Batch {len(calls)}, question {index}"
            questions.append(question)
        return SimpleNamespace(content=json.dumps(questions))

    monkeypatch.setattr(question_generation, "get_chat_model", lambda: SimpleNamespace(invoke=invoke))
    result = generate_questions_from_text("Source", "single_mcq", "hard", "Numbers", count=requested)
    assert len(result) == len({question["question_text"] for question in result}) == requested
    assert len(calls) == len(sizes)
    for prompt, size in zip(calls, sizes):
        assert f"Generate {size} high-quality questions" in prompt
    assert result[0]["question_text"] in calls[1]


def test_chunk_retries_repeated_questions_instead_of_accepting_duplicates(monkeypatch):
    prompts = []

    def invoke(prompt):
        prompts.append(prompt)
        first = len(prompts) == 1
        questions = []
        for index in range(10 if first else 1):
            question = _single_choice_question()
            question["question_text"] += f" Example {index if len(prompts) < 3 else 10}"
            questions.append(question)
        return SimpleNamespace(content=json.dumps(questions))

    monkeypatch.setattr(question_generation, "get_chat_model", lambda: SimpleNamespace(invoke=invoke))
    result = generate_questions_from_text("Source", "single_mcq", "easy", "Numbers", count=11)
    assert len(result) == len({question["question_text"] for question in result}) == 11
    assert len(prompts) == 3
    assert "repeats an already accepted question text" in prompts[2]


@pytest.mark.parametrize("count", [0, 51])
def test_invalid_generation_size_is_rejected_before_provider_access(monkeypatch, count):
    def unexpected_provider():
        pytest.fail("Invalid requests must not authenticate or call a model")

    monkeypatch.setattr(question_generation, "get_chat_model", unexpected_provider)
    with pytest.raises(ValueError, match="between 1 and 50"):
        generate_questions_from_text("Source", "single_mcq", "easy", "Numbers", count=count)


def test_invalid_later_chunk_never_returns_a_partial_generation(monkeypatch):
    calls = []

    def invoke(prompt):
        calls.append(prompt)
        questions = []
        if len(calls) == 1:
            for index in range(10):
                question = _single_choice_question()
                question["question_text"] += f" Example {index}"
                questions.append(question)
        return SimpleNamespace(content=json.dumps(questions))

    monkeypatch.setattr(question_generation, "get_chat_model", lambda: SimpleNamespace(invoke=invoke))
    with pytest.raises(ValueError, match="failed validation after 3 attempts"):
        generate_questions_from_text("Source", "single_mcq", "easy", "Numbers", count=11)
    assert len(calls) == 4


@pytest.mark.parametrize("correct_count", [0, 1, 2, 3, 4])
def test_multi_choice_requires_two_or_three_correct_options(correct_count):
    question = _single_choice_question()
    question["question_type"] = "multi_mcq"
    for index, option in enumerate(question["options"]):
        option["is_correct"] = index < correct_count
    if correct_count in (2, 3):
        assert _validate_generated_questions([question], count=1, question_type="multi_mcq")
    else:
        with pytest.raises(ValueError, match="invalid answer key"):
            _validate_generated_questions([question], count=1, question_type="multi_mcq")


def test_bank_generation_rejects_duplicate_option_labels():
    question = _single_choice_question()
    question["options"][1]["option_text"] = " 2 "
    with pytest.raises(ValueError, match="duplicate option text"):
        _validate_generated_questions([question], count=1, question_type="single_mcq")
