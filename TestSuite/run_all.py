import os
import subprocess
import sys


def main() -> int:
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173").rstrip("/")

    os.environ["RUN_STATEFUL_TESTS"] = "1"
    os.environ["RUN_E2E_TESTS"] = "1"
    os.environ.setdefault("CORS_TEST_ORIGIN", frontend_url)

    install = subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        check=False,
    )
    if install.returncode:
        return install.returncode

    return subprocess.run(
        [sys.executable, "-m", "pytest", "--browser", "chromium", *sys.argv[1:]],
        check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
