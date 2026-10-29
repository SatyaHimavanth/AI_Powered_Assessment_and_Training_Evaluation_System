import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

import api.routers_code as code_api
from db.models import QuestionType


class Query:
    def __init__(self, model, question, cases):
        self.model = model
        self.question = question
        self.cases = cases
        self.filters = []

    def filter(self, *conditions):
        self.filters.extend(conditions)
        return self

    def limit(self, _count):
        return self

    def first(self):
        return self.question

    def all(self):
        return [case for case in self.cases if case.is_sample]


class FakeDB:
    def __init__(self, question, cases):
        self.question = question
        self.cases = cases
        self.query_objects = []

    def query(self, model):
        result = Query(model, self.question, self.cases)
        self.query_objects.append(result)
        return result

    def close(self):
        pass


def test_candidate_code_endpoint_never_runs_or_reveals_hidden_cases(monkeypatch):
    question_id = uuid4()
    sample = SimpleNamespace(
        id=uuid4(), input_data="1", expected_output="1", is_sample=True
    )
    hidden = SimpleNamespace(
        id=uuid4(), input_data="secret input", expected_output="secret answer", is_sample=False
    )
    question = SimpleNamespace(id=question_id, type=QuestionType.coding)
    database = FakeDB(question, [sample, hidden])
    monkeypatch.setattr(code_api, "SessionLocal", lambda: database)

    async def run_sync(function):
        return function()

    monkeypatch.setattr(code_api, "run_db_sync", run_sync)
    monkeypatch.setattr(code_api, "run_test_case", lambda **_kwargs: {
        "passed": True, "actual_output": "1", "expected_output": "1", "error": None,
    })

    response = asyncio.run(code_api.run_code(
        code_api.RunCodeRequest(
            question_id=question_id,
            code="print(input())",
            run_sample_only=False,
            language="python",
        ),
        _user=SimpleNamespace(id=uuid4()),
    ))

    sample_filter = str(database.query_objects[1].filters[-1]).lower()
    assert "is_sample" in sample_filter
    assert response.total == 1
    assert response.results[0].test_case_id == sample.id
    assert "secret" not in repr(response.model_dump())


def test_candidate_code_endpoint_returns_503_when_sandbox_is_unavailable(monkeypatch):
    question_id = uuid4()
    sample = SimpleNamespace(
        id=uuid4(), input_data="1", expected_output="1", is_sample=True
    )
    question = SimpleNamespace(id=question_id, type=QuestionType.coding)
    database = FakeDB(question, [sample])
    monkeypatch.setattr(code_api, "SessionLocal", lambda: database)

    async def run_sync(function):
        return function()

    monkeypatch.setattr(code_api, "run_db_sync", run_sync)
    monkeypatch.setattr(code_api, "run_test_case", lambda **_kwargs: {
        "passed": False,
        "actual_output": "",
        "expected_output": "1",
        "error": "Python execution unavailable: sandbox service not responding",
    })

    with pytest.raises(HTTPException) as error:
        asyncio.run(code_api.run_code(
            code_api.RunCodeRequest(
                question_id=question_id, code="print(1)", language="python"
            ),
            _user=SimpleNamespace(id=uuid4()),
        ))
    assert error.value.status_code == 503
