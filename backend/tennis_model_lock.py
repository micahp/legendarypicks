"""Serialize scheduled tennis projection work that targets the same database."""
from __future__ import annotations

import fcntl
import os
from contextlib import contextmanager


@contextmanager
def projection_job_lock(db_path: str):
    """Hold an exclusive per-database lock until a projection job finishes."""
    database = os.path.realpath(db_path)
    stem = os.path.splitext(os.path.basename(database))[0]
    lock_path = "/run/lock/legendarypicks-tennis-model-{}.lock".format(stem)
    with open(lock_path, "a+") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
