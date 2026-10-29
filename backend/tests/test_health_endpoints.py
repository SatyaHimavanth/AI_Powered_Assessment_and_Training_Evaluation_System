import asyncio
import json

import pytest
from fastapi import HTTPException

import main


def test_default_health_check_does_not_probe_llm(monkeypatch):
    class SessionStub:
        def execute(self, *_args):
            return None

        def close(self):
            pass

    monkeypatch.setattr(main, "SessionLocal", SessionStub)
    response = asyncio.run(main.health_check(db=True, llm=False))
    payload = json.loads(response.body)

    assert "llm" not in payload["checks"]
    assert payload["checks"].get("db") == "healthy"
    assert response.status_code == 200, payload


def test_speed_test_is_unavailable_unless_explicitly_enabled(monkeypatch):
    monkeypatch.delenv("ENABLE_SPEED_TEST", raising=False)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.speed_test())

    assert exc.value.status_code == 404


def test_speed_test_returns_requested_bounded_payload_when_enabled(monkeypatch):
    monkeypatch.setenv("ENABLE_SPEED_TEST", "true")

    response = asyncio.run(main.speed_test(size=4096))

    assert response.status_code == 200
    assert response.media_type == "application/octet-stream"
    assert len(response.body) == 4096
