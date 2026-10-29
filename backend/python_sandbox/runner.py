"""Single-job-at-a-time supervisor for the network-isolated Python container."""

import json
import logging
import os
import resource
import selectors
import signal
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

QUEUE = Path(os.environ.get("PYTHON_RUNNER_QUEUE_DIR", "/run/python-jobs"))
REQUESTS = QUEUE / "requests"
PROCESSING = QUEUE / "processing"
RESPONSES = QUEUE / "responses"
RUN_TIMEOUT_SECONDS = 5
MAX_OUTPUT_BYTES = 10_000
MAX_CODE_BYTES = 50_000
MAX_INPUT_BYTES = 100_000
SANDBOX_UID = 65534
SANDBOX_GID = 65534
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOGGER = logging.getLogger("python_sandbox")


def _make_queue_dirs() -> None:
    for path in (REQUESTS, PROCESSING, RESPONSES):
        path.mkdir(parents=True, exist_ok=True)
        path.chmod(0o700)


def _drop_privileges(workdir: str) -> None:
    os.setgroups([])
    os.setgid(SANDBOX_GID)
    os.setuid(SANDBOX_UID)
    resource.setrlimit(resource.RLIMIT_CPU, (4, 4))
    resource.setrlimit(resource.RLIMIT_AS, (384 * 1024 * 1024, 384 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (4 * 1024 * 1024, 4 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
    resource.setrlimit(resource.RLIMIT_NPROC, (1, 1))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def _read_process(proc: subprocess.Popen, started: float) -> tuple[str, str, bool, bool]:
    selector = selectors.DefaultSelector()
    stdout = bytearray()
    stderr = bytearray()
    buffers = {proc.stdout: stdout, proc.stderr: stderr}
    for stream in buffers:
        os.set_blocking(stream.fileno(), False)
        selector.register(stream, selectors.EVENT_READ)

    timed_out = False
    output_limited = False
    try:
        while selector.get_map():
            if time.monotonic() - started > RUN_TIMEOUT_SECONDS:
                timed_out = True
                proc.kill()
            if output_limited or timed_out:
                proc.kill()

            for key, _ in selector.select(timeout=0.05):
                stream = key.fileobj
                try:
                    chunk = os.read(stream.fileno(), 4096)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(stream)
                    stream.close()
                    continue
                target = buffers[stream]
                remaining = MAX_OUTPUT_BYTES - len(target)
                if remaining > 0:
                    target.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    output_limited = True

            if proc.poll() is not None and not selector.get_map():
                break
    finally:
        selector.close()
    return (
        stdout.decode("utf-8", errors="replace"),
        stderr.decode("utf-8", errors="replace"),
        timed_out,
        output_limited,
    )


def _run_candidate(code: str, stdin_data: str) -> dict:
    if len(code.encode("utf-8")) > MAX_CODE_BYTES or len(stdin_data.encode("utf-8")) > MAX_INPUT_BYTES:
        return {"stdout": "", "stderr": "Submission or input exceeds the execution limit", "exit_code": -1, "timed_out": False}

    workdir = tempfile.mkdtemp(prefix="candidate-", dir="/tmp")
    proc = None
    try:
        code_path = Path(workdir) / "main.py"
        input_path = Path(workdir) / "stdin.txt"
        code_path.write_text(code, encoding="utf-8")
        input_path.write_text(stdin_data, encoding="utf-8")
        code_path.chmod(0o444)
        input_path.chmod(0o400)
        stdin_stream = input_path.open("rb")
        # Leave only a group traversal bit for the root-spawned subprocess to
        # chdir before preexec drops it to the candidate identity.
        os.chmod(workdir, 0o710)
        os.chown(workdir, SANDBOX_UID, 0)
        with stdin_stream:
            proc = subprocess.Popen(
                [sys.executable, "-I", str(code_path)],
                stdin=stdin_stream,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=workdir,
                env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": workdir, "TMPDIR": workdir},
                close_fds=True,
                preexec_fn=lambda: _drop_privileges(workdir),
            )
        started = time.monotonic()
        stdout, stderr, timed_out, output_limited = _read_process(proc, started)
        proc.wait(timeout=1)
        # The CPU hard limit terminates the candidate with SIGKILL; report it
        # through the same time-limit contract as the wall-clock watchdog.
        if proc.returncode in (-signal.SIGXCPU, -signal.SIGKILL):
            timed_out = True
        if output_limited:
            stderr = "Output limit exceeded"
            exit_code = -1
        elif timed_out:
            stderr = "Time Limit Exceeded"
            exit_code = -1
        else:
            exit_code = int(proc.returncode or 0)
        return {"stdout": stdout, "stderr": stderr, "exit_code": exit_code, "timed_out": timed_out}
    finally:
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.wait(timeout=1)
        shutil.rmtree(workdir, ignore_errors=True)


def _write_response(job_id: str, result: dict) -> None:
    target = RESPONSES / f"{job_id}.json"
    temporary = RESPONSES / f".{job_id}.tmp"
    temporary.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    temporary.chmod(0o600)
    os.replace(temporary, target)


def _process_one(request_path: Path) -> None:
    job_id = request_path.stem
    processing_path = PROCESSING / request_path.name
    try:
        os.replace(request_path, processing_path)
    except FileNotFoundError:
        return
    try:
        payload = json.loads(processing_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("code"), str):
            raise ValueError("Invalid execution job")
        result = _run_candidate(payload["code"], str(payload.get("stdin") or ""))
    except Exception:
        LOGGER.exception("Sandbox job %s failed", job_id)
        result = {"stdout": "", "stderr": "Sandbox execution failed", "exit_code": -1, "timed_out": False}
    finally:
        processing_path.unlink(missing_ok=True)
    _write_response(job_id, result)


def main() -> None:
    if os.geteuid() != 0:
        raise RuntimeError("Sandbox supervisor must start as root to drop candidate privileges")
    _make_queue_dirs()
    # Requeue interrupted work. The execution is deterministic and each API
    # ticket consumes only one response, so replay after a crash is harmless.
    for path in PROCESSING.glob("*.json"):
        os.replace(path, REQUESTS / path.name)
    while True:
        pending = sorted(REQUESTS.glob("*.json"))
        if not pending:
            now = time.time()
            for response in RESPONSES.glob("*.json"):
                if now - response.stat().st_mtime > 3600:
                    response.unlink(missing_ok=True)
            time.sleep(0.05)
            continue
        _process_one(pending[0])


if __name__ == "__main__":
    main()
