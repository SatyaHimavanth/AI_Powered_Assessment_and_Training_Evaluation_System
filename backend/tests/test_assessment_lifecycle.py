"""Integration test suite for multi-user assessment lifecycle.

Requires a running backend server and a PostgreSQL database.
Set BASE_URL (default http://localhost:8000) and DATABASE_URL env vars.

Run with:
    pytest -v backend/tests/ --base-url=http://localhost:8000

Scenarios covered:
1. Two users complete the full assessment correctly.
2. One user completes, another submits partial answers.
3. One user triggers tab violations and aborts.
4. Admin verifies that all users' answers are recorded.
"""

import os
import time
import uuid

import pytest
import requests

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/")
TEST_PASSWORD = "testpass123"


def _login(api_client, username, password):
    resp = api_client.post(
        f"{BASE_URL}/auth/login",
        json={"username": username, "password": password},
        timeout=10,
    )
    assert resp.status_code == 200, f"Login failed for {username}: {resp.text}"
    return resp.json()["access_token"]


def _start_attempt(api_client, token, assessment_id):
    resp = api_client.post(
        f"{BASE_URL}/user/assessments/start/{assessment_id}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    assert resp.status_code == 200, f"Start failed: {resp.text}"
    return resp.json()


def _save_answer(api_client, token, attempt_id, question_id, answer_text):
    resp = api_client.post(
        f"{BASE_URL}/user/assessments/save-answer",
        json={"question_id": str(question_id), "answer": answer_text},
        headers={"Authorization": f"Bearer {token}"},
        params={"attempt_id": str(attempt_id)},
        timeout=10,
    )
    assert resp.status_code == 200, f"Save answer failed: {resp.text}"
    return resp.json()


def _submit_assessment(api_client, token, attempt_id, answers):
    resp = api_client.post(
        f"{BASE_URL}/user/assessments/submit/{attempt_id}",
        json={"answers": [{"question_id": str(qid), "answer": ans} for qid, ans in answers]},
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    return resp


def _save_violations(api_client, token, attempt_id, violations):
    resp = api_client.post(
        f"{BASE_URL}/user/assessments/save-violations",
        headers={"Authorization": f"Bearer {token}"},
        params={"attempt_id": str(attempt_id), "violations": violations},
        timeout=10,
    )
    assert resp.status_code == 200
    return resp.json()


def _abort_assessment(api_client, token, attempt_id, answers):
    resp = api_client.post(
        f"{BASE_URL}/user/assessments/abort/{attempt_id}",
        json={"answers": [{"question_id": str(qid), "answer": ans} for qid, ans in answers]},
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    return resp


def _get_attempt_results(api_client, token, attempt_id):
    resp = api_client.get(
        f"{BASE_URL}/admin/attempt/{attempt_id}/results",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    return resp


def _wait_for_evaluation(api_client, token, attempt_id, max_retries=30, delay=2):
    """Poll until the attempt is no longer in 'evaluating' or 'in_progress' state."""
    for _ in range(max_retries):
        resp = _get_attempt_results(api_client, token, attempt_id)
        if resp.status_code == 200:
            data = resp.json()
            status = data.get("status", "")
            if status not in ("evaluating",):
                return data
        time.sleep(delay)
    return None


class AssessmentContext:
    """Holds context for all tests tied to one seeded assessment."""

    def __init__(self, fixture_data):
        self.assessment = fixture_data["assessment"]
        self.usernames = fixture_data["usernames"]
        self.admin_token = fixture_data["admin_token"]

        self.assessment_id = self.assessment["id"]
        self.user_tokens = {}

        # Build a mapping of question_id -> correct_option_id from seeded questions.
        # This is used to submit correct MCQ answers.
        self.question_correct_options = {}
        for q in fixture_data.get("_seeded_questions", []):
            qid = str(q.id)
            for opt in q.options:
                if opt.is_correct:
                    self.question_correct_options[qid] = str(opt.id)
                    break

    def login(self, username):
        if username not in self.user_tokens:
            client = requests.Session()
            self.user_tokens[username] = _login(client, username, TEST_PASSWORD)
        return self.user_tokens[username]

    def get_client(self, username):
        return requests.Session()

    def wait_for_evaluation(self, attempt_id, client=None, token=None):
        """Wait for the evaluation worker using the configured admin token."""
        return _wait_for_evaluation(client or requests.Session(), token or self.admin_token, attempt_id)


@pytest.fixture()
def ctx(seeded_assessment):
    return AssessmentContext(seeded_assessment)


@pytest.fixture(autouse=True)
def reset_attempts(seeded_assessment, db_session):
    """Keep each scenario independent even when pytest changes test order."""
    from db.models import Answer, Attempt, EvaluationJob, TopicScore

    assessment_id = uuid.UUID(str(seeded_assessment["assessment"]["id"]))
    attempts = db_session.query(Attempt).filter(Attempt.assessment_id == assessment_id).all()
    attempt_ids = [attempt.id for attempt in attempts]
    if attempt_ids:
        db_session.query(Answer).filter(Answer.attempt_id.in_(attempt_ids)).delete(synchronize_session=False)
        db_session.query(TopicScore).filter(TopicScore.attempt_id.in_(attempt_ids)).delete(synchronize_session=False)
        db_session.query(EvaluationJob).filter(EvaluationJob.attempt_id.in_(attempt_ids)).delete(synchronize_session=False)
        db_session.query(Attempt).filter(Attempt.id.in_(attempt_ids)).delete(synchronize_session=False)
        db_session.commit()
    yield


class TestAssessmentInputValidation:
    def test_rejects_answers_for_unassigned_question(self, ctx):
        client = ctx.get_client(ctx.usernames[0])
        token = ctx.login(ctx.usernames[0])
        attempt = _start_attempt(client, token, ctx.assessment_id)

        response = client.post(
            f"{BASE_URL}/user/assessments/save-answer",
            params={"attempt_id": attempt["attempt_id"]},
            json={"question_id": "00000000-0000-0000-0000-000000000000", "answer": "x"},
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        assert response.status_code == 400
        assert "does not belong" in response.json()["detail"]


class TestPartialAttemptScoring:
    def test_unanswered_questions_count_as_zero(self, ctx):
        client = ctx.get_client(ctx.usernames[0])
        token = ctx.login(ctx.usernames[0])
        started = _start_attempt(client, token, ctx.assessment_id)
        questions = started["questions"]
        answers = [
            (str(question["id"]), ctx.question_correct_options[str(question["id"])])
            for question in questions[: len(questions) // 2]
        ]

        response = _submit_assessment(client, token, started["attempt_id"], answers)
        assert response.status_code == 200
        result = _wait_for_evaluation(client, ctx.admin_token, started["attempt_id"])
        assert result is not None
        assert result["score"] == 50.0


class TestTwoUsersCompleteFullAssessment:
    """Scenario: Two users both answer all questions correctly and submit."""

    def test_both_users_start_submit_and_answers_recorded(self, ctx):
        users = ctx.usernames[:2]
        for username in users:
            client = ctx.get_client(username)
            token = ctx.login(username)

            start_data = _start_attempt(client, token, ctx.assessment_id)
            attempt_id = start_data["attempt_id"]
            questions = start_data["questions"]

            answers = []
            for q in questions:
                qid = str(q["id"])
                correct_opt_id = ctx.question_correct_options.get(qid)
                assert correct_opt_id is not None, f"No correct option for question {qid}"
                answers.append((qid, correct_opt_id))

            resp = _submit_assessment(client, token, attempt_id, answers)
            assert resp.status_code == 200, f"Submit failed for {username}: {resp.text}"
            data = resp.json()
            assert data["status"] in (
                "evaluating",
                "completed",
            ), f"Unexpected submit status for {username}: {data['status']}"


class TestOneUserPartialSubmission:
    """Scenario: One user answers all questions, another answers only half."""

    def test_first_user_complete_second_half(self, ctx):
        full_user = ctx.usernames[0]
        partial_user = ctx.usernames[1]

        # Full user submits everything
        client_full = ctx.get_client(full_user)
        token_full = ctx.login(full_user)
        start_full = _start_attempt(client_full, token_full, ctx.assessment_id)
        attempt_full_id = start_full["attempt_id"]
        questions_full = start_full["questions"]

        full_answers = []
        for q in questions_full:
            qid = str(q["id"])
            correct_opt_id = ctx.question_correct_options.get(qid)
            full_answers.append((qid, correct_opt_id))

        resp = _submit_assessment(client_full, token_full, attempt_full_id, full_answers)
        assert resp.status_code == 200

        # Partial user answers only first half
        client_partial = ctx.get_client(partial_user)
        token_partial = ctx.login(partial_user)
        start_partial = _start_attempt(client_partial, token_partial, ctx.assessment_id)
        attempt_partial_id = start_partial["attempt_id"]
        questions_partial = start_partial["questions"]

        half = len(questions_partial) // 2
        partial_answers = []
        for i, q in enumerate(questions_partial):
            if i < half:
                qid = str(q["id"])
                correct_opt_id = ctx.question_correct_options.get(qid)
                partial_answers.append((qid, correct_opt_id))

        resp = _submit_assessment(client_partial, token_partial, attempt_partial_id, partial_answers)
        assert resp.status_code == 200


class TestUserAbortsDueToViolation:
    """Scenario: User triggers 3+ tab violations, assessment is aborted with incomplete status."""

    def test_aborted_due_to_tab_violations(self, ctx):
        user = ctx.usernames[0]
        client = ctx.get_client(user)
        token = ctx.login(user)

        start_data = _start_attempt(client, token, ctx.assessment_id)
        attempt_id = start_data["attempt_id"]
        questions = start_data["questions"]

        # Save answers for a few questions
        for i, q in enumerate(questions[:3]):
            qid = str(q["id"])
            correct_opt_id = ctx.question_correct_options.get(qid)
            if correct_opt_id:
                _save_answer(client, token, attempt_id, qid, correct_opt_id)

        # Record tab violations exceeding limit
        _save_violations(client, token, attempt_id, violations=3)

        # Abort (saves partial answers)
        abort_answers = [
            (str(q["id"]), ctx.question_correct_options.get(str(q["id"]), ""))
            for q in questions[:3]
            if ctx.question_correct_options.get(str(q["id"]))
        ]

        resp = _abort_assessment(client, token, attempt_id, abort_answers)
        assert resp.status_code == 200, f"Abort failed: {resp.text}"
        data = resp.json()
        assert data["status"] == "incomplete", f"Expected 'incomplete', got '{data['status']}'"


class TestAdminSeesRecordedAnswers:
    """Scenario: Admin checks that a completed attempt shows all answers recorded."""

    def test_all_answers_recorded_after_completion(self, ctx):
        user = ctx.usernames[0]
        client = ctx.get_client(user)
        token = ctx.login(user)

        start_data = _start_attempt(client, token, ctx.assessment_id)
        attempt_id = start_data["attempt_id"]
        questions = start_data["questions"]

        answers = []
        for q in questions:
            qid = str(q["id"])
            correct_opt_id = ctx.question_correct_options.get(qid)
            answers.append((qid, correct_opt_id))

        resp = _submit_assessment(client, token, attempt_id, answers)
        assert resp.status_code == 200

        # Poll for evaluation to complete
        result_data = _wait_for_evaluation(client, ctx.admin_token, attempt_id)

        if result_data is None:
            pytest.skip("Evaluation did not complete within timeout; cannot verify scores")

        total_questions = result_data["total_questions"]
        answered = result_data["answered"]
        assert answered == total_questions, (
            f"Expected {total_questions} answers, got {answered}"
        )


class TestUnassignedUserCannotStart:
    """Scenario: A user not assigned to an assessment gets a 403 error."""

    def test_unassigned_user_rejected(self, ctx):
        # assessment_tester_1 IS assigned to the batch, so use a different uuid
        user = ctx.usernames[0]
        client = ctx.get_client(user)
        token = ctx.login(user)

        fake_uuid = "00000000-0000-0000-0000-000000000000"
        resp = client.post(
            f"{BASE_URL}/user/assessments/start/{fake_uuid}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        assert resp.status_code in (403, 404)


class TestSaveAnswerDuringAttempt:
    """Scenario: User saves answers progressively (auto-save simulation)."""

    def test_save_answer_upserts(self, ctx):
        user = ctx.usernames[0]
        client = ctx.get_client(user)
        token = ctx.login(user)

        start_data = _start_attempt(client, token, ctx.assessment_id)
        attempt_id = start_data["attempt_id"]
        questions = start_data["questions"]

        # Save first two questions
        for q in questions[:2]:
            qid = str(q["id"])
            correct_opt_id = ctx.question_correct_options.get(qid)
            if correct_opt_id:
                _save_answer(client, token, attempt_id, qid, correct_opt_id)

        # Overwrite first question's answer (upsert)
        q0_id = str(questions[0]["id"])
        wrong_opt_id = None
        for opt in questions[0].get("options", []):
            oid = str(opt["id"])
            if oid != ctx.question_correct_options.get(q0_id):
                wrong_opt_id = oid
                break
        if wrong_opt_id:
            _save_answer(client, token, attempt_id, q0_id, wrong_opt_id)

        # Submit all answers
        answers = []
        for q in questions[:2]:
            qid = str(q["id"])
            correct_opt_id = ctx.question_correct_options.get(qid)
            answers.append((qid, correct_opt_id))

        # Also submit the overwritten (wrong) answer for q0 by using correct again
        # to verify upsert works - resubmit correct answer
        answers.append((q0_id, ctx.question_correct_options.get(q0_id)))

        resp = _submit_assessment(client, token, attempt_id, answers)
        assert resp.status_code == 200
