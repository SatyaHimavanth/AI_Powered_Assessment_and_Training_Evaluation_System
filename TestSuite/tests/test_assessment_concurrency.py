from concurrent.futures import ThreadPoolExecutor
import time

import pytest
import requests


pytestmark = pytest.mark.stateful


def _post(api_url, path, headers, **kwargs):
    return requests.post(f"{api_url}{path}", headers=headers, timeout=30, **kwargs)


def test_start_save_and_submit_are_race_safe(
    provisioned_assessment, api_client, api_url
):
    assessment_id = provisioned_assessment["assessment_id"]
    users = provisioned_assessment["users"]

    start_requests = [
        (users[0]["headers"], 0),
        (users[0]["headers"], 0),
        (users[1]["headers"], 1),
        (users[2]["headers"], 2),
    ]
    with ThreadPoolExecutor(max_workers=4) as pool:
        starts = list(
            pool.map(
                lambda request: _post(
                    api_url,
                    f"/user/assessments/start/{assessment_id}",
                    request[0],
                ),
                start_requests,
            )
        )
    assert {response.status_code for response in starts} == {200}
    assert starts[0].json()["attempt_id"] == starts[1].json()["attempt_id"]
    started_by_user = [starts[0].json(), starts[2].json(), starts[3].json()]
    assert all(len(started["questions"]) == 4 for started in started_by_user)

    full_attempt = started_by_user[0]
    partial_attempt = started_by_user[1]
    aborted_attempt = started_by_user[2]
    attempt_id = full_attempt["attempt_id"]
    question_id = full_attempt["questions"][0]["id"]

    def save(value):
        return _post(
            api_url,
            "/user/assessments/save-answer",
            users[0]["headers"],
            params={"attempt_id": attempt_id},
            json={"question_id": question_id, "answer": value},
        )

    saved_values = [f"answer-{index}" for index in range(12)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        saves = list(pool.map(save, saved_values))
    assert {response.status_code for response in saves} == {200}

    resumed = _post(
        api_url,
        f"/user/assessments/start/{assessment_id}",
        users[0]["headers"],
    )
    assert resumed.status_code == 200
    persisted = {
        item["question_id"]: item["answer"]
        for item in resumed.json().get("saved_answers", [])
    }
    assert persisted[question_id] in saved_values

    full_payload = {
        "answers": [
            {
                "question_id": question["id"],
                "answer": question["options"][0]["id"],
            }
            for question in full_attempt["questions"]
        ]
    }
    with ThreadPoolExecutor(max_workers=2) as pool:
        submissions = list(
            pool.map(
                lambda _: _post(
                    api_url,
                    f"/user/assessments/submit/{attempt_id}",
                    users[0]["headers"],
                    json=full_payload,
                ),
                range(2),
            )
        )
    statuses = sorted(response.status_code for response in submissions)
    assert statuses[0] == 200
    assert statuses[1] in {400, 409}
    assert 500 not in statuses

    partial_questions = partial_attempt["questions"][:2]
    partial = _post(
        api_url,
        f"/user/assessments/submit/{partial_attempt['attempt_id']}",
        users[1]["headers"],
        json={
            "answers": [
                {
                    "question_id": question["id"],
                    "answer": question["options"][0]["id"],
                }
                for question in partial_questions
            ]
        },
    )
    assert partial.status_code == 200, partial.text

    violations = _post(
        api_url,
        "/user/assessments/save-violations",
        users[2]["headers"],
        params={
            "attempt_id": aborted_attempt["attempt_id"],
            "violations": 5,
        },
    )
    assert violations.status_code == 200, violations.text
    aborted = _post(
        api_url,
        f"/user/assessments/abort/{aborted_attempt['attempt_id']}",
        users[2]["headers"],
        json={
            "answers": [
                {
                    "question_id": aborted_attempt["questions"][0]["id"],
                    "answer": aborted_attempt["questions"][0]["options"][0]["id"],
                }
            ]
        },
    )
    assert aborted.status_code == 200, aborted.text
    assert aborted.json()["status"] == "incomplete"

    expected = {
        attempt_id: (4, 100.0),
        partial_attempt["attempt_id"]: (2, 50.0),
    }
    pending = dict(expected)
    admin_results = {}
    deadline = time.monotonic() + 45
    while pending and time.monotonic() < deadline:
        for current_id, (answered, score) in list(pending.items()):
            result = api_client.get(
                f"{api_url}/admin/attempt/{current_id}/results",
                headers=provisioned_assessment["admin_headers"],
                timeout=10,
            )
            if result.status_code == 200 and result.json().get("score") is not None:
                assert result.json()["answered"] == answered
                assert result.json()["score"] == pytest.approx(score)
                admin_results[current_id] = result.json()
                pending.pop(current_id)
        if pending:
            time.sleep(2)
    assert not pending, f"Evaluation did not complete for attempts: {list(pending)}"

    for user_index, expected_score, expected_answered in (
        (0, 100.0, 4),
        (1, 50.0, 2),
    ):
        learner_result = api_client.get(
            f"{api_url}/user/assessments/{assessment_id}/results",
            headers=users[user_index]["headers"],
            timeout=10,
        )
        assert learner_result.status_code == 200, learner_result.text
        payload = learner_result.json()
        attempt_key = (
            attempt_id if user_index == 0 else partial_attempt["attempt_id"]
        )
        admin_payload = admin_results[attempt_key]

        assert payload["status"] == "completed"
        assert payload["evaluation_pending"] is False
        assert payload["score"] == pytest.approx(expected_score)
        assert payload["score"] == pytest.approx(admin_payload["score"])
        assert payload["answered"] == expected_answered
        assert payload["answered"] == admin_payload["answered"]
        assert payload["total_questions"] == 4
        assert payload["correct_count"] == expected_answered
        assert len(payload["answers"]) == 4
        assert payload["topic_scores"] == [
            {
                "topic_name": payload["topic_scores"][0]["topic_name"],
                "total": 4,
                "correct": float(expected_answered),
                "percentage": expected_score,
            }
        ]

        answered_rows = [
            answer for answer in payload["answers"] if answer["your_answer"]
        ]
        unanswered_rows = [
            answer for answer in payload["answers"] if not answer["your_answer"]
        ]
        assert len(answered_rows) == expected_answered
        assert len(unanswered_rows) == 4 - expected_answered
        assert all(answer["your_answer"] == "Correct" for answer in answered_rows)
        assert all(answer["correct_answer"] == "Correct" for answer in payload["answers"])
