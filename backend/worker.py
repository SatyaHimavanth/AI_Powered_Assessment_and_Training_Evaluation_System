"""Dedicated process for recoverable evaluation jobs and embedding backfill."""

import logging
import os
import time
from pathlib import Path
from threading import Thread

from dotenv import load_dotenv

# The standalone worker is launched separately from the FastAPI process. Load
# the backend's local configuration before importing services that read env.
# Platform-provided variables still take precedence over .env values.
load_dotenv(Path(__file__).resolve().parent / ".env", override=False)

from core.embedding_backfill import backfill_missing_embeddings
from core.evaluation_service import process_evaluation_jobs
from core.question_generation import process_generation_batch_queue
from core.practice_generation import process_practice_generation_queue


def _retry_embedding_backfill() -> None:
    interval = max(60, int(os.getenv("EMBEDDING_BACKFILL_INTERVAL_SECONDS", "3600")))
    while True:
        time.sleep(interval)
        try:
            backfill_missing_embeddings()
        except Exception:
            logging.exception("Embedding backfill failed; it will be retried")


def _initial_embedding_backfill() -> None:
    try:
        backfill_missing_embeddings()
    except Exception:
        # Do not delay evaluation and deadline jobs if the embedding provider
        # is unavailable during worker startup.
        logging.exception("Initial embedding backfill failed; it will be retried")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    runner_mode = os.getenv("PYTHON_RUNNER_MODE", "local").strip().lower()
    if runner_mode == "local":
        logging.info(
            "Python execution runner mode: local backend subprocess (not an OS sandbox)"
        )
    elif runner_mode == "queue":
        logging.info("Python execution runner mode: isolated queue service")
    else:
        logging.error("Invalid PYTHON_RUNNER_MODE; expected 'local' or 'queue'")
    # This idempotent scan runs whenever the worker restarts, so interrupted
    # embeddings remain eligible for a later retry. Evaluation jobs are polled
    # continuously and protected by a PostgreSQL advisory lock.
    Thread(
        target=_initial_embedding_backfill,
        daemon=True,
        name="embedding-backfill-startup",
    ).start()
    Thread(
        target=process_generation_batch_queue,
        daemon=True,
        name="question-generation-worker",
    ).start()
    Thread(
        target=process_practice_generation_queue,
        daemon=True,
        name="practice-generation-worker",
    ).start()
    Thread(
        target=_retry_embedding_backfill,
        daemon=True,
        name="embedding-backfill-retry",
    ).start()
    process_evaluation_jobs()


if __name__ == "__main__":
    main()
