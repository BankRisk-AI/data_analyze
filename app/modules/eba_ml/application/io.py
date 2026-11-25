"""Logger setup and atomic JSON write (shared by training and evaluation).

One logger; one writer. No business logic here.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path


def get_logger(name: str = "eba.ml_redo") -> logging.Logger:
    """Return a file-backed logger, initialising it once.

    Creates logs/ if needed. Calling twice returns the same logger.
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        Path("logs").mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler("logs/ml_redo.log")
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


def write_json(path: Path, data: object) -> None:
    """Write data as indented JSON atomically (rename-on-close).

    Prevents a partial file if the process is interrupted mid-write.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp_")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except Exception:
        os.unlink(tmp)
        raise
