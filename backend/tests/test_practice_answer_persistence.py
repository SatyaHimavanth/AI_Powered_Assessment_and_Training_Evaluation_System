import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from api import routers_practice
from db.models import PracticeAnswer, PracticeQuestion, PracticeTest, PracticeTestStatus


class FakeQuery:
    def __init__(self, model, values):
        self.model = model
        self.values = values

    def filter(self, *_args, **_kwargs):
        return self

    def with_for_update(self):
        return self

    def first(self):
        return self.values.get(self.model)


class FakeDB:
    def __init__(self, test, question, answer=None):
        self.values = {PracticeTest: test, PracticeQuestion: question, PracticeAnswer: answer}
        self.added = []
        self.commits = 0

    def query(self, model):
        return FakeQuery(model, self.values)

    def add(self, row):
        self.added.append(row)

    def commit(self):
        self.commits += 1

    def close(self):
        pass


def invoke_save(monkeypatch, db, test_id, question_id, answer="saved"):
    async def run_db_sync(callback):
        return callback()

    monkeypatch.setattr(routers_practice, "SessionLocal", lambda: db)
    monkeypatch.setattr(routers_practice, "run_db_sync", run_db_sync)
    user = SimpleNamespace(id=uuid4())
    payload = routers_practice.SavePracticeAnswerIn(question_id=question_id, answer=answer)
    return asyncio.run(routers_practice.save_practice_answer(test_id, payload, user))


def test_saves_answer_only_for_owned_in_progress_test(monkeypatch):
    test_id, question_id = uuid4(), uuid4()
    test = SimpleNamespace(id=test_id, user_id=uuid4(), status=PracticeTestStatus.in_progress)
    question = SimpleNamespace(id=question_id, practice_test_id=test_id)
    db = FakeDB(test, question)

    response = invoke_save(monkeypatch, db, test_id, question_id, "candidate response")

    assert response["message"] == "Answer saved"
    assert len(db.added) == 1
    assert isinstance(db.added[0], PracticeAnswer)
    assert db.added[0].answer == "candidate response"
    assert db.commits == 1


@pytest.mark.parametrize("status", [PracticeTestStatus.ready, PracticeTestStatus.completed])
def test_rejects_answers_outside_in_progress_state(monkeypatch, status):
    test_id, question_id = uuid4(), uuid4()
    db = FakeDB(
        SimpleNamespace(id=test_id, user_id=uuid4(), status=status),
        SimpleNamespace(id=question_id, practice_test_id=test_id),
    )

    with pytest.raises(HTTPException) as exc:
        invoke_save(monkeypatch, db, test_id, question_id)

    assert exc.value.status_code == 409
    assert db.commits == 0


def test_rejects_question_from_another_test(monkeypatch):
    test_id, question_id = uuid4(), uuid4()
    db = FakeDB(
        SimpleNamespace(id=test_id, user_id=uuid4(), status=PracticeTestStatus.in_progress),
        None,
    )

    with pytest.raises(HTTPException) as exc:
        invoke_save(monkeypatch, db, test_id, question_id)

    assert exc.value.status_code == 400
    assert db.commits == 0
