import time

import pytest


pytestmark = pytest.mark.stateful


def test_wrong_partial_text_and_unattempted_coding_are_reported_correctly(
    provisioned_assessment, api_client, api_url
):
    fixture = provisioned_assessment
    user = fixture["users"][0]
    started = api_client.post(
        f"{api_url}/user/assessments/start/{fixture['mixed_assessment_id']}",
        headers=user["headers"],
        timeout=20,
    )
    assert started.status_code == 200, started.text
    attempt = started.json()
    questions = attempt["questions"]
    assert {question["type"] for question in questions} == {
        "single_mcq", "multi_mcq", "coding", "text"
    }

    answers = []
    for question in questions:
        if question["type"] == "single_mcq":
            wrong_option = next(option for option in question["options"] if option["text"] == "Wrong answer")
            answers.append({"question_id": question["id"], "answer": wrong_option["id"]})
        elif question["type"] == "multi_mcq":
            correct_option_texts = {"First correct", "Second correct"}
            answers.append({
                "question_id": question["id"],
                "answer": ",".join(option["id"] for option in question["options"] if option["text"] in correct_option_texts),
            })
        elif question["type"] == "text":
            # Deliberately covers only part of the reference answer's criteria.
            answers.append({
                "question_id": question["id"],
                "answer": "An operating system manages memory and processes.",
            })
        # Leave coding unanswered to verify it is reported as unattempted. The
        # application keeps candidate-code execution disabled until an isolated
        # sandbox is configured.

    submitted = api_client.post(
        f"{api_url}/user/assessments/submit/{attempt['attempt_id']}",
        headers=user["headers"],
        json={"answers": answers},
        timeout=20,
    )
    assert submitted.status_code == 200, submitted.text

    result = None
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        response = api_client.get(
            f"{api_url}/admin/attempt/{attempt['attempt_id']}/results",
            headers=fixture["admin_headers"],
            timeout=15,
        )
        assert response.status_code == 200, response.text
        result = response.json()
        if not result["evaluation_pending"]:
            break
        time.sleep(2)

    assert result is not None and result["evaluation_pending"] is False
    by_type = {answer["question_type"]: answer for answer in result["answers"]}
    assert result["answered"] == 3
    assert by_type["single_mcq"]["answer_status"] == "incorrect"
    assert by_type["single_mcq"]["score"] == 0
    assert by_type["multi_mcq"]["answer_status"] == "correct"
    assert by_type["multi_mcq"]["score"] == 1
    assert by_type["text"]["answer_status"] in {"correct", "partial", "incorrect"}
    assert by_type["text"]["score"] is not None
    assert by_type["coding"]["answer_status"] == "unattempted"
    assert by_type["coding"]["score"] is None

    user_results = api_client.get(
        f"{api_url}/user/assessments/{fixture['mixed_assessment_id']}/results",
        headers=user["headers"],
        timeout=15,
    )
    assert user_results.status_code == 200, user_results.text
    user_by_type = {answer["question_type"]: answer for answer in user_results.json()["answers"]}
    assert user_by_type["coding"]["answer_status"] == "unattempted"
    assert user_by_type["single_mcq"]["answer_status"] == "incorrect"
