"""Bounded subprocess runner for the single-service compatibility mode.

This limits accidental resource exhaustion. It does not isolate candidate code
from the backend account's filesystem, network, or other OS-visible resources.
Use the queue runner for a separate networkless sandbox.
"""

import os
import logging
import signal
import subprocess
import sys
import shutil
import threading
import time
from uuid import uuid4
from pathlib import Path

MAX_CODE_BYTES = 50_000
MAX_INPUT_BYTES = 100_000
MAX_OUTPUT_BYTES = 10_000
WALL_TIMEOUT_SECONDS = 5
MAX_CONCURRENT_RUNS = 4
UNPRIVILEGED_UID = 65534
UNPRIVILEGED_GID = 65534
_RUN_SLOTS = threading.BoundedSemaphore(MAX_CONCURRENT_RUNS)
logger = logging.getLogger(__name__)


def _prepare_posix_child(workdir: str, drop_privileges: bool) -> None:
    """Apply best-effort limits and drop root when the backend runs as root."""
    if os.name != "posix":
        return
    import resource

    resource.setrlimit(resource.RLIMIT_CPU, (4, 4))
    resource.setrlimit(resource.RLIMIT_AS, (384 * 1024 * 1024, 384 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (4 * 1024 * 1024, 4 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
    if hasattr(resource, "RLIMIT_NPROC"):
        resource.setrlimit(resource.RLIMIT_NPROC, (1, 1))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    if drop_privileges:
        os.setgroups([])
        os.setgid(UNPRIVILEGED_GID)
        os.setuid(UNPRIVILEGED_UID)


def _kill(proc: subprocess.Popen) -> None:
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
    except (ProcessLookupError, OSError):
        pass


def execute_in_local_venv(code: str, stdin_input: str = "") -> dict:
    code_bytes = code.encode("utf-8")
    input_bytes = stdin_input.encode("utf-8")
    if len(code_bytes) > MAX_CODE_BYTES or len(input_bytes) > MAX_INPUT_BYTES:
        return {"stdout": "", "stderr": "Submission or input exceeds the execution limit", "exit_code": -1, "timed_out": False}
    if not _RUN_SLOTS.acquire(timeout=1):
        return {"stdout": "", "stderr": "Python execution unavailable: capacity is busy; retry shortly", "exit_code": -1, "timed_out": False}

    try:
        temp_root = Path(os.environ.get(
            "PYTHON_RUNNER_TMP_DIR",
            str(Path(__file__).resolve().parents[1] / ".candidate-tmp"),
        ))
        temp_root.mkdir(parents=True, exist_ok=True)
        workdir_path = temp_root / f"assessment-code-{uuid4().hex}"
        workdir_path.mkdir()
        workdir = str(workdir_path)
        try:
            source_path = Path(workdir) / "main.py"
            source_path.write_bytes(code_bytes)
            drop_privileges = os.name == "posix" and os.geteuid() == 0
            if drop_privileges:
                os.chown(workdir, UNPRIVILEGED_UID, UNPRIVILEGED_GID)
                os.chmod(workdir, 0o700)
                os.chown(source_path, UNPRIVILEGED_UID, UNPRIVILEGED_GID)
                os.chmod(source_path, 0o400)
            child_env = {
                "PATH": os.environ.get("PATH", ""),
                "HOME": workdir,
                "TMPDIR": workdir,
                "TEMP": workdir,
                "TMP": workdir,
            }
            if os.name == "nt":
                # Windows needs SystemRoot to initialize Winsock in Python imports.
                system_root = os.environ.get("SystemRoot")
                if system_root:
                    child_env["SystemRoot"] = system_root
            try:
                proc = subprocess.Popen(
                    [sys.executable, "-I", str(source_path)],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=workdir,
                    env=child_env,
                    close_fds=True,
                    start_new_session=(os.name == "posix"),
                    preexec_fn=(
                        (lambda: _prepare_posix_child(workdir, drop_privileges))
                        if os.name == "posix"
                        else None
                    ),
                )
            except (OSError, subprocess.SubprocessError) as exc:
                logger.exception(
                    "Could not start the local Python execution subprocess (%s)",
                    type(exc).__name__,
                )
                return {"stdout": "", "stderr": "Python execution unavailable: unable to start runner", "exit_code": -1, "timed_out": False}

            outputs = {"stdout": bytearray(), "stderr": bytearray()}
            output_exceeded = threading.Event()

            def drain(name: str, stream) -> None:
                while True:
                    chunk = stream.read(4096)
                    if not chunk:
                        return
                    target = outputs[name]
                    remaining = MAX_OUTPUT_BYTES - len(target)
                    if remaining > 0:
                        target.extend(chunk[:remaining])
                    if len(chunk) > remaining:
                        output_exceeded.set()

            readers = [
                threading.Thread(target=drain, args=("stdout", proc.stdout), daemon=True),
                threading.Thread(target=drain, args=("stderr", proc.stderr), daemon=True),
            ]
            for reader in readers:
                reader.start()

            def write_input() -> None:
                try:
                    proc.stdin.write(input_bytes)
                    proc.stdin.flush()
                except (BrokenPipeError, OSError):
                    pass
                finally:
                    try:
                        proc.stdin.close()
                    except OSError:
                        pass

            writer = threading.Thread(target=write_input, daemon=True)
            writer.start()
            deadline = time.monotonic() + WALL_TIMEOUT_SECONDS
            timed_out = False
            while proc.poll() is None:
                if output_exceeded.is_set():
                    _kill(proc)
                    break
                if time.monotonic() >= deadline:
                    timed_out = True
                    _kill(proc)
                    break
                time.sleep(0.01)
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                _kill(proc)
                proc.wait(timeout=1)
            for thread in (*readers, writer):
                thread.join(timeout=1)

            stdout = outputs["stdout"].decode("utf-8", errors="replace")
            stderr = outputs["stderr"].decode("utf-8", errors="replace")
            if output_exceeded.is_set():
                stderr, exit_code = "Output limit exceeded", -1
            elif timed_out or proc.returncode in (-getattr(signal, "SIGXCPU", 24), -getattr(signal, "SIGKILL", 9)):
                stderr, exit_code, timed_out = "Time Limit Exceeded", -1, True
            else:
                exit_code = int(proc.returncode or 0)
            return {"stdout": stdout, "stderr": stderr, "exit_code": exit_code, "timed_out": timed_out}
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
    finally:
        _RUN_SLOTS.release()
