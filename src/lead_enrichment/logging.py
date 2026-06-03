from __future__ import annotations

import logging as py_logging
from pathlib import Path


def setup_logging(log_path: Path | str | None = None) -> py_logging.Logger:
    logger = py_logging.getLogger("lead_enrichment")
    logger.setLevel(py_logging.INFO)
    logger.handlers.clear()
    formatter = py_logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    stream_handler = py_logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    if log_path:
        path = Path(log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = py_logging.FileHandler(path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    return logger
