from __future__ import annotations

import logging

_LOG_FORMAT = "%(asctime)s - %(filename)s - %(levelname)s - %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def configure_logging() -> None:
    root_logger = logging.getLogger()
    if root_logger.handlers:
        return

    logging.basicConfig(
        level=logging.INFO,
        format=_LOG_FORMAT,
        datefmt=_DATE_FORMAT,
    )


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)
