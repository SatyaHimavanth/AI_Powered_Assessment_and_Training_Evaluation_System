import json

import pytest

import core.python_runner_queue as queue
from core.python_runner_queue import PythonRunnerUnavailable, execute_in_sandbox


class MemoryPath:
    files: dict[str, bytes] = {}
    directories: set[str] = set()

    def __init__(self, value):
        self.value = str(value)

    def __truediv__(self, other):
        return MemoryPath(f"{self.value}/{other}")

    def __str__(self):
        return self.value

    def mkdir(self, parents=False, exist_ok=False):
        self.directories.add(self.value)

    def glob(self, pattern):
        return [
            MemoryPath(path)
            for path in self.files
            if path.startswith(self.value + "/")
            and "/" not in path[len(self.value) + 1:]
            and path.endswith(pattern.removeprefix("*"))
        ]

    def write_text(self, value, encoding="utf-8"):
        self.files[self.value] = value.encode(encoding)

    def read_bytes(self):
        return self.files[self.value]

    def is_file(self):
        return self.value in self.files

    def unlink(self, missing_ok=False):
        if self.value not in self.files and not missing_ok:
            raise FileNotFoundError(self.value)
        self.files.pop(self.value, None)


def _memory_fs(monkeypatch):
    MemoryPath.files = {}
    MemoryPath.directories = set()
    monkeypatch.setattr(queue, "Path", MemoryPath)

    def replace(source, destination):
        source = str(source)
        destination = str(destination)
        MemoryPath.files[destination] = MemoryPath.files.pop(source)

    monkeypatch.setattr(queue.os, "replace", replace)


def test_queue_client_receives_result_from_sandbox_worker(monkeypatch):
    _memory_fs(monkeypatch)
    monkeypatch.setenv("PYTHON_RUNNER_QUEUE_DIR", "/jobs")

    def fake_worker_sleep(_delay):
        request_dir = MemoryPath("/jobs/requests")
        requests = request_dir.glob("*.json")
        assert len(requests) == 1
        request = requests[0]
        job = json.loads(request.read_bytes())
        response = MemoryPath("/jobs/responses") / request.value.rsplit("/", 1)[-1]
        response.write_text(json.dumps({
            "stdout": job["stdin"].upper(),
            "stderr": "",
            "exit_code": 0,
            "timed_out": False,
        }))
        request.unlink()

    monkeypatch.setattr(queue.time, "sleep", fake_worker_sleep)
    result = execute_in_sandbox("print(input())", "hello")

    assert result["stdout"] == "HELLO"
    assert result["exit_code"] == 0
    assert not MemoryPath.files


def test_queue_client_times_out_when_sandbox_service_is_missing(monkeypatch):
    _memory_fs(monkeypatch)
    monkeypatch.setenv("PYTHON_RUNNER_QUEUE_DIR", "/jobs")
    monkeypatch.setattr(queue, "RUNNER_WAIT_SECONDS", 0)

    with pytest.raises(PythonRunnerUnavailable, match="not respond"):
        execute_in_sandbox("print('x')")


@pytest.mark.parametrize(
    ("code", "stdin_data", "message"),
    [
        ("x" * 50_001, "", "Code exceeds"),
        ("print('x')", "a" * 100_001, "Input exceeds"),
    ],
)
def test_queue_client_rejects_oversized_submission_before_queueing(
    monkeypatch, code, stdin_data, message
):
    _memory_fs(monkeypatch)
    monkeypatch.setenv("PYTHON_RUNNER_QUEUE_DIR", "/jobs")

    result = execute_in_sandbox(code, stdin_data)

    assert result["exit_code"] == -1
    assert message in result["stderr"]
    assert not MemoryPath.files
