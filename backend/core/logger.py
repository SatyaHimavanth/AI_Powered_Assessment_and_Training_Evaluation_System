from __future__ import annotations

import logging
import threading

_LOG_FORMAT = "%(asctime)s - %(filename)s - %(levelname)s - %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_configure_lock = threading.Lock()
_configured = False


def configure_logging() -> None:
    global _configured
    with _configure_lock:
        if _configured:
            return
        root_logger = logging.getLogger()
        if root_logger.handlers:
            _configured = True
            return
        logging.basicConfig(
            level=logging.INFO,
            format=_LOG_FORMAT,
            datefmt=_DATE_FORMAT,
        )
        _configured = True


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)
