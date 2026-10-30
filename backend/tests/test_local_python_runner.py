import os

import pytest

from core import local_python_runner
from core.code_runner import execute_python_code


def test_local_mode_runs_using_backend_python_with_input(monkeypatch):
    monkeypatch.setenv("PYTHON_RUNNER_MODE", "local")

    result = execute_python_code("print(input())", "candidate input")

    assert result.exit_code == 0
    assert result.stdout.strip() == "candidate input"
    assert result.stderr == ""


def test_local_runner_is_default_when_mode_is_not_set(monkeypatch):
    monkeypatch.delenv("PYTHON_RUNNER_MODE", raising=False)

    result = execute_python_code("print('default local')")

    assert result.exit_code == 0
    assert result.stdout.strip() == "default local"


def test_local_mode_caps_output(monkeypatch):
    monkeypatch.setenv("PYTHON_RUNNER_MODE", "local")

    result = execute_python_code("print('x' * 20000)")

    assert result.exit_code == -1
    assert "Output limit exceeded" in result.stderr


def test_local_mode_stops_wall_time_overrun(monkeypatch):
    monkeypatch.setenv("PYTHON_RUNNER_MODE", "local")
    monkeypatch.setattr(local_python_runner, "WALL_TIMEOUT_SECONDS", 0.1)

    result = execute_python_code("while True: pass")

    assert result.timed_out is True
    assert result.exit_code == -1
    assert result.stderr == "Time Limit Exceeded"


def test_local_mode_rejects_oversized_input_without_starting_child(monkeypatch):
    monkeypatch.setenv("PYTHON_RUNNER_MODE", "local")

    result = execute_python_code("print('ok')", "x" * (local_python_runner.MAX_INPUT_BYTES + 1))

    assert result.exit_code == -1
    assert "exceeds the execution limit" in result.stderr


def test_unknown_runner_mode_fails_closed(monkeypatch):
    monkeypatch.setenv("PYTHON_RUNNER_MODE", "typo")

    result = execute_python_code("print('never runs')")

    assert result.exit_code == -1
    assert "execution unavailable" in result.stderr


@pytest.mark.skipif(os.name != "nt", reason="Windows Winsock initialization regression")
def test_windows_runner_initializes_asyncio_and_winsock(monkeypatch):
    monkeypatch.setenv("PYTHON_RUNNER_MODE", "local")
    result = execute_python_code("import asyncio\nprint('asyncio ready')")
    assert result.exit_code == 0, result.stderr
    assert result.stdout.strip() == "asyncio ready"
    assert result.stderr == ""


@pytest.mark.skipif(os.name != "nt", reason="Windows environment allowlist regression")
def test_windows_runner_preserves_os_root_without_inheriting_application_secrets(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "synthetic-private-database")
    monkeypatch.setenv("JWT_SECRET_KEY", "synthetic-private-signing-key")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "synthetic-private-provider-key")
    captured = []
    original_popen = local_python_runner.subprocess.Popen

    def popen(*args, **kwargs):
        captured.append(kwargs["env"])
        return original_popen(*args, **kwargs)

    monkeypatch.setattr(local_python_runner.subprocess, "Popen", popen)
    result = execute_python_code("print('hello')")
    assert result.exit_code == 0, result.stderr
    assert captured[0]["SystemRoot"] == os.environ["SystemRoot"]
    assert not {"DATABASE_URL", "JWT_SECRET_KEY", "AZURE_OPENAI_API_KEY"} & captured[0].keys()
