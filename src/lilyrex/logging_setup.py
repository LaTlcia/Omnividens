"""UTC timestamp / level / local correlation ID logging, without packet dumps."""
from __future__ import annotations

import logging
import time


class _CorrelationFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "correlation_id"):
            record.correlation_id = "-"
        return True


def get_logger(name: str = "lilyrex") -> logging.Logger:
    logger = logging.getLogger(name)
    if not any(getattr(handler, "_lilyrex_preview_handler", False) for handler in logger.handlers):
        handler = logging.StreamHandler()
        handler._lilyrex_preview_handler = True
        formatter = logging.Formatter("%(asctime)sZ %(levelname)s [%(correlation_id)s] %(message)s",
                                      datefmt="%Y-%m-%dT%H:%M:%S")
        formatter.converter = time.gmtime
        handler.setFormatter(formatter)
        handler.addFilter(_CorrelationFilter())
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger
