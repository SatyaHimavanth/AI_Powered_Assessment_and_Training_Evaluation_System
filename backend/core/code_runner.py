"""Candidate Python execution through the configured runner."""

from dataclasses import dataclass
import ast
import os
from typing import Dict, Any

from core.python_runner_queue import PythonRunnerUnavailable, execute_in_sandbox
from core.local_python_runner import execute_in_local_venv


# --- Embedded static Python analyzer (copied from scripts/python_danger_testing.py)
DANGEROUS_IMPORTS = {
    "subprocess": "Can execute system commands",
    "os": "Can access environment variables and filesystem",
    "threading": "Can create threads; may bypass sandbox/resource limits",
    "multiprocessing": "Can spawn new processes",
    "concurrent": "May spawn threads/processes via concurrent.futures",
    "futures": "May spawn threads/processes (backport)",
    "threadpool": "Thread pool utilities — may create threads",
    "gevent": "Greenlet concurrency — can perform network IO and spawn coroutines",
    "eventlet": "Eventlet concurrency — can perform network IO and spawn coroutines",
    "socket": "Can perform network communication",
    "requests": "Can send HTTP requests",
    "urllib": "Can access external URLs",
    "httpx": "Can perform HTTP requests",
    "ftplib": "Can upload/download files",
    "paramiko": "Can access SSH systems",
    "telnetlib": "Can open telnet connections",
    "smtplib": "Can send emails",
    "ctypes": "Can call native C code",
    "pickle": "Can execute arbitrary code during deserialization",
    "marshal": "Can load serialized Python code",
    "sqlite3": "Can access local databases",
    "psutil": "Can inspect system processes",
    "winreg": "Can modify Windows registry",
    "browser_cookie3": "Can access browser cookies",
    "cryptography": "May encrypt/decrypt hidden payloads",
    "importlib": "Can dynamically import modules and bypass static import checks",
    "builtins": "Can access dynamic import mechanisms and run internals"
}


DANGEROUS_CALLS = {
    "eval": "Executes arbitrary Python code",
    "exec": "Executes arbitrary Python code",
    "compile": "Compiles dynamic Python code",
    "__import__": "Performs dynamic imports",
    "open": "Reads/writes local files",
}


DANGEROUS_ATTRS = {
    "system": "Executes shell commands",
    "popen": "Starts subprocess",
    "Popen": "Starts subprocess",
    "run": "May execute commands",
    "remove": "Deletes files",
    "unlink": "Deletes files",
    "rmtree": "Deletes directories",
    "connect": "Can connect to external systems",
    "send": "Can transmit data",
    "b64decode": "May decode hidden payload",
    "environ": "Access environment variables",
    "getenv": "Reads environment variables",
    "import_module": "Dynamically imports modules at runtime"
    ,"Thread": "Starts a new thread",
    "Process": "Starts a new process",
    "ThreadPoolExecutor": "Creates a thread pool",
    "Pool": "Creates worker processes/threads",
}


SUSPICIOUS_STRINGS = [
    ".ssh",
    "passwd",
    "token",
    "apikey",
    "secret",
    "clipboard",
    "cookie",
    "wallet",
    "discord",
    "telegram",
    "webhook",
]


class SecurityVisitor(ast.NodeVisitor):
    def __init__(self):
        self.warnings = []

    def warn(self, node, message):
        self.warnings.append({
            "line": getattr(node, "lineno", "?"),
            "warning": message,
        })

    def visit_Import(self, node):
        for alias in node.names:
            root = alias.name.split(".")[0]

            if root in DANGEROUS_IMPORTS:
                self.warn(
                    node,
                    f"Import '{root}' detected: {DANGEROUS_IMPORTS[root]}",
                )

        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        if node.module:
            root = node.module.split(".")[0]

            if root in DANGEROUS_IMPORTS:
                self.warn(
                    node,
                    f"Import '{root}' detected: {DANGEROUS_IMPORTS[root]}",
                )

        self.generic_visit(node)

    def visit_Call(self, node):
        # direct function calls
        if isinstance(node.func, ast.Name):
            name = node.func.id

            if name in DANGEROUS_CALLS:
                self.warn(
                    node,
                    f"Call to '{name}': {DANGEROUS_CALLS[name]}",
                )

        # attribute calls
        elif isinstance(node.func, ast.Attribute):
            attr = node.func.attr

            if attr in DANGEROUS_ATTRS:
                self.warn(
                    node,
                    f"Attribute call '{attr}': {DANGEROUS_ATTRS[attr]}",
                )

        self.generic_visit(node)

    def visit_Attribute(self, node):
        # Detect attribute access like os.environ even when not called
        if isinstance(node.value, ast.Name) and node.value.id == "os" and node.attr in ("environ", "getenv"):
            self.warn(
                node,
                f"Attribute '{node.attr}' on 'os' detected: Accesses environment or system data",
            )

        self.generic_visit(node)

    def visit_Constant(self, node):
        if isinstance(node.value, str):
            lower = node.value.lower()

            for s in SUSPICIOUS_STRINGS:
                if s in lower:
                    self.warn(
                        node,
                        f"Suspicious string detected: '{s}'",
                    )

        self.generic_visit(node)


def analyze_python_code(code: str) -> Dict[str, Any]:
    """
    Analyze Python code without executing it.

    Returns:
        {
            "safe": bool,
            "warnings": list
        }
    """

    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return {"safe": False, "warnings": [f"SyntaxError: {e}"]}

    visitor = SecurityVisitor()
    visitor.visit(tree)

    return {"safe": len(visitor.warnings) == 0, "warnings": visitor.warnings}

# --- end embedded analyzer

# Configuration
EXECUTION_TIMEOUT = 10  # seconds
MAX_OUTPUT_SIZE = 10_000  # characters


@dataclass
class ExecutionResult:
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool


def execute_python_code(code: str, stdin_input: str = "") -> ExecutionResult:
    """Run candidate source using the configured execution mode.

    ``local`` is a compatibility mode, not a security sandbox: it executes in
    a subprocess under the backend account and can access that account's files
    and network despite the resource and environment limits.
    """
    if len(code.encode("utf-8")) > 50_000:
        return ExecutionResult("", "Code exceeds 50000 bytes", -1, False)
    analysis = analyze_python_code(code)
    if not analysis["safe"]:
        messages = [
            str(item.get("warning") or item) for item in analysis["warnings"][:5]
        ]
        return ExecutionResult("", "Submission rejected by static safety checks: " + "; ".join(messages), -1, False)
    try:
        mode = os.environ.get("PYTHON_RUNNER_MODE", "local").strip().lower()
        if mode == "local":
            result = execute_in_local_venv(code, stdin_input)
        elif mode == "queue":
            result = execute_in_sandbox(code, stdin_input)
        else:
            raise PythonRunnerUnavailable("PYTHON_RUNNER_MODE must be 'local' or 'queue'")
    except PythonRunnerUnavailable as exc:
        return ExecutionResult("", f"Python execution unavailable: {exc}", -1, False)
    return ExecutionResult(
        stdout=str(result.get("stdout") or "")[:10_000],
        stderr=str(result.get("stderr") or "")[:10_000],
        exit_code=int(result.get("exit_code", -1)),
        timed_out=bool(result.get("timed_out", False)),
    )


def ensure_execution_available(result: dict) -> None:
    error = str(result.get("error") or "")
    if any(
        marker in error.lower()
        for marker in ("execution unavailable", "runner is not configured")
    ):
        raise RuntimeError("Coding evaluation is unavailable until a Python runner is configured")

def run_test_case(code: str, input_data: str, expected_output: str) -> dict:
    """
    Run code against a single test case.

    Returns dict with: passed, actual_output, expected_output, error
    """
    result = execute_python_code(code, stdin_input=input_data)

    actual = result.stdout.strip()
    expected = expected_output.strip()

    if result.timed_out:
        return {
            "passed": False,
            "actual_output": "",
            "expected_output": expected,
            "error": "Time Limit Exceeded",
            "exit_code": -1,
        }

    if result.exit_code != 0:
        # Runtime error
        error_msg = result.stderr.strip()
        # Extract just the last line (actual error) for brevity
        lines = error_msg.split("\n")
        short_error = lines[-1] if lines else error_msg
        return {
            "passed": False,
            "actual_output": actual,
            "expected_output": expected,
            "error": short_error[:500],
            "exit_code": result.exit_code,
        }

    passed = actual == expected

    return {
        "passed": passed,
        "actual_output": actual[:1000],
        "expected_output": expected[:1000],
        "error": None,
        "exit_code": 0,
    }
