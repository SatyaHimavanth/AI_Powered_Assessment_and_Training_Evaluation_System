from api import routers_practice
from core import evaluation_service
from core.evaluation_service import _evaluate_coding_with_tests, _objective_score


def test_generated_practice_mcq_answer_key_is_derived_from_options():
    questions = routers_practice._validate_generated_questions([
        {
            "type": "single_mcq",
            "question": "Which value is correct?",
            "options": [
                {"text": "A", "is_correct": False},
                {"text": "B", "is_correct": True},
            ],
        }
    ], 1)
    assert questions[0]["correct_answer"] == ["B"]
    assert routers_practice._public_practice_options(
        '[{"text":"A","is_correct":false},{"text":"B","is_correct":true}]'
    ) == [{"text": "A"}, {"text": "B"}]


def test_generated_practice_questions_reject_wrong_count_or_invalid_mcq():
    import pytest

    with pytest.raises(ValueError, match="exactly"):
        routers_practice._validate_generated_questions([], 1)
    with pytest.raises(ValueError, match="correct-option"):
        routers_practice._validate_generated_questions([
            {
                "type": "single_mcq",
                "question": "Which value is correct?",
                "options": [
                    {"text": "A", "is_correct": True},
                    {"text": "B", "is_correct": True},
                ],
            }
        ], 1)


def test_negative_marking_subtracts_one_point_for_wrong_objective_answers():
    assert _objective_score(False, True, "wrong-option") == -1.0


def test_negative_marking_does_not_penalize_unanswered_questions():
    assert _objective_score(False, True, "  ") == 0.0


def test_correct_objective_answer_keeps_one_point_with_negative_marking():
    assert _objective_score(True, True, "correct-option") == 1.0


def test_coding_score_is_partial_when_only_some_test_cases_pass(monkeypatch):
    from types import SimpleNamespace
    from db.models import TestCase
    import core.code_runner

    class Query:
        def filter(self, *_args):
            return self

        def all(self):
            return [
                SimpleNamespace(input_data="one", expected_output="one"),
                SimpleNamespace(input_data="two", expected_output="two"),
                SimpleNamespace(input_data="three", expected_output="three"),
            ]

    class FakeDB:
        def query(self, model):
            assert model is TestCase
            return Query()

    outcomes = iter([True, False, True])
    monkeypatch.setattr(
        core.code_runner,
        "run_test_case",
        lambda *_args: {
            "passed": next(outcomes),
            "error": None,
        },
    )

    score, feedback = _evaluate_coding_with_tests(
        FakeDB(), SimpleNamespace(id="question-id", default_code=None), "candidate code"
    )

    assert score == 2 / 3
    assert feedback.startswith("2/3 test cases passed")


def test_text_answer_accepts_deterministic_partial_llm_evaluation(monkeypatch):
    prompts = []

    class StructuredModel:
        def invoke(self, prompt):
            prompts.append(prompt)
            return evaluation_service.EvaluationResult(score=0.4, feedback="Partially correct")

    class ChatModel:
        def with_structured_output(self, schema):
            assert schema is evaluation_service.EvaluationResult
            return StructuredModel()

    monkeypatch.setattr(evaluation_service, "get_chat_model", lambda: ChatModel())
    score, feedback = evaluation_service._evaluate_subjective_with_llm(
        "Explain process scheduling", "Reference rubric", "Only one relevant detail", "text"
    )

    assert score == 0.4
    assert feedback == "Partially correct"
    assert '"Only one relevant detail"' in prompts[0]


def test_practice_multi_select_requires_an_exact_match():
    assert routers_practice._score_practice_question(
        "multi_mcq", '["a", "b"]', "a|||b"
    ) == (1.0, "Correct")
    assert routers_practice._score_practice_question(
        "multi_mcq", '["a", "b"]', "a"
    ) == (0.0, "Incorrect")


def test_practice_text_answer_is_evaluated_against_reference(monkeypatch):
    observed = {}

    def evaluate(question, reference, answer, question_type):
        observed.update(
            question=question,
            reference=reference,
            answer=answer,
            question_type=question_type,
        )
        return 0.75, "Mostly correct"

    monkeypatch.setattr(routers_practice, "_evaluate_subjective_with_llm", evaluate)

    result = routers_practice._score_practice_question(
        "text", "ideal answer", "candidate response", "Question?"
    )

    assert result == (0.75, "Mostly correct")
    assert observed == {
        "question": "Question?",
        "reference": "ideal answer",
        "answer": "candidate response",
        "question_type": "practice",
    }


def test_blank_practice_text_answer_does_not_call_evaluator(monkeypatch):
    monkeypatch.setattr(
        routers_practice,
        "_evaluate_subjective_with_llm",
        lambda *_args: (_ for _ in ()).throw(AssertionError("must not evaluate blank text")),
    )

    assert routers_practice._score_practice_question("text", "ideal", "  ") == (
        0.0,
        "No answer provided.",
    )


def test_practice_rejects_indistinguishable_correct_and_wrong_options():
    import pytest

    with pytest.raises(ValueError, match="duplicate option text"):
        routers_practice._validate_generated_questions([{
            "type": "single_mcq", "question": "Choose",
            "options": [
                {"text": "Same", "is_correct": True},
                {"text": " same ", "is_correct": False},
            ],
        }], 1)


def test_practice_multi_choice_needs_multiple_correct_and_an_incorrect_option():
    import pytest

    for correct_count in (1, 4):
        with pytest.raises(ValueError, match="multiple correct options"):
            routers_practice._validate_generated_questions([{
                "type": "multi_mcq", "question": "Choose",
                "options": [{"text": str(index), "is_correct": index < correct_count} for index in range(4)],
            }], 1)
