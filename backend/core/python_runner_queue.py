"""File-queue client for the network-isolated Python sandbox container."""

import json
import os
import time
from pathlib import Path
from uuid import uuid4

MAX_CODE_BYTES = 50_000
MAX_INPUT_BYTES = 100_000
MAX_RESULT_BYTES = 150_000
RUNNER_WAIT_SECONDS = 120
MAX_PENDING_JOBS = 100


class PythonRunnerUnavailable(RuntimeError):
    pass


def execute_in_sandbox(code: str, stdin_input: str = "") -> dict:
    queue_root = os.environ.get("PYTHON_RUNNER_QUEUE_DIR")
    if not queue_root:
        raise PythonRunnerUnavailable(
            "Python sandbox is not configured; run the isolated sandbox service"
        )
    if len(code.encode("utf-8")) > MAX_CODE_BYTES:
        return {"stdout": "", "stderr": "Code exceeds 50000 bytes", "exit_code": -1, "timed_out": False}
    if len(stdin_input.encode("utf-8")) > MAX_INPUT_BYTES:
        return {"stdout": "", "stderr": "Input exceeds 100000 bytes", "exit_code": -1, "timed_out": False}

    root = Path(queue_root)
    requests = root / "requests"
    responses = root / "responses"
    try:
        requests.mkdir(parents=True, exist_ok=True)
        responses.mkdir(parents=True, exist_ok=True)
        if sum(1 for _ in requests.glob("*.json")) >= MAX_PENDING_JOBS:
            raise PythonRunnerUnavailable("Python sandbox queue is full")
        job_id = uuid4().hex
        request_path = requests / f"{job_id}.json"
        response_path = responses / f"{job_id}.json"
        temporary = requests / f".{job_id}.tmp"
        temporary.write_text(
            json.dumps({"code": code, "stdin": stdin_input}, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(temporary, request_path)

        deadline = time.monotonic() + RUNNER_WAIT_SECONDS
        while time.monotonic() < deadline:
            if response_path.is_file():
                raw = response_path.read_bytes()
                response_path.unlink(missing_ok=True)
                if len(raw) > MAX_RESULT_BYTES:
                    raise PythonRunnerUnavailable("Python sandbox returned an invalid response")
                result = json.loads(raw.decode("utf-8"))
                if not isinstance(result, dict):
                    raise PythonRunnerUnavailable("Python sandbox returned an invalid response")
                return result
            time.sleep(0.05)
        request_path.unlink(missing_ok=True)
        raise PythonRunnerUnavailable("Python sandbox did not respond before the queue timeout")
    except PythonRunnerUnavailable:
        raise
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise PythonRunnerUnavailable("Python sandbox queue is unavailable") from exc
