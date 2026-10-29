"""Offline compatibility checks for the test-only client and structured calls."""

import importlib
from pathlib import Path
from unittest.mock import Mock

import pytest

pytest.importorskip("langchain_openai", reason="Run with backend dependencies")


@pytest.fixture
def adapter(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2]))
    return importlib.import_module("TestSuite.client_llms.llms")


def test_import_is_lazy_and_factory_reuses_one_model(adapter, monkeypatch):
    adapter.get_chat_model.cache_clear()
    monkeypatch.setattr(adapter, "load_dotenv", lambda *_args, **_kwargs: None)
    for key in ("MBR_AI_CANVAS_Ingest_Client_ID", "MBR_AI_CANVAS_Ingest_Client_Secret", "MBR_AI_CANVAS_APP_KEY"):
        monkeypatch.setenv(key, "synthetic-test-value")
    provider = Mock()
    provider.default_model = "test-deployment"
    factory = Mock(return_value=provider)
    monkeypatch.setattr(adapter, "CiscoAzureChatOpenAIProvider", factory)
    importlib.import_module(adapter.__name__)
    factory.assert_not_called()
    assert adapter.get_chat_model() is adapter.get_chat_model()
    factory.assert_called_once()
    assert provider.get_chat_model.call_args.kwargs["timeout"] == 60
    adapter.get_chat_model.cache_clear()


def test_missing_configuration_fails_before_network(adapter, monkeypatch):
    adapter.get_chat_model.cache_clear()
    monkeypatch.setattr(adapter, "load_dotenv", lambda *_args, **_kwargs: None)
    monkeypatch.delenv("MBR_AI_CANVAS_Ingest_Client_ID", raising=False)
    with pytest.raises(RuntimeError, match="Missing test client configuration"):
        adapter.get_chat_model()


def test_structured_invocations_request_current_oauth_token(adapter):
    import httpx
    from pydantic import BaseModel
    from TestSuite.client_llms.cisco_llm_client import CiscoAzureChatOpenAIProvider

    class Grade(BaseModel):
        score: float
        feedback: str

    authorization = []

    def respond(request):
        authorization.append(request.headers["authorization"])
        return httpx.Response(200, json={
            "id": "test", "object": "chat.completion", "created": 1, "model": "test",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {
                "role": "assistant", "content": '{"score":0.8,"feedback":"Synthetic feedback"}',
            }}],
        })

    provider = CiscoAzureChatOpenAIProvider(
        client_id="synthetic", client_secret="synthetic", app_key="synthetic",
        azure_endpoint="https://synthetic.invalid",
    )
    tokens = iter(["first-test-token", "second-test-token"])
    provider._get_valid_access_token = lambda: next(tokens)
    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        model = provider.get_chat_model(http_client=http)
        structured = model.with_structured_output(Grade, method="json_schema")
        assert structured.invoke("Synthetic input").score == 0.8
        assert structured.invoke("Synthetic input").score == 0.8
    assert authorization == ["Bearer first-test-token", "Bearer second-test-token"]
