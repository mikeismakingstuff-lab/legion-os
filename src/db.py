"""
Committee OS — Database connection helper.

Provides a single function to obtain a SQLite connection to the pipeline
database. Every stage module imports this instead of managing its own path.

Database location per Architecture §4:
    Documents\\ContentPipeline\\pipeline.db
"""

import os
import sqlite3
from pathlib import Path


def _resolve_db_path() -> Path:
    """Return the canonical path to pipeline.db.

    Resolves to the user's Documents\\ContentPipeline directory.
    Creates the directory if it does not exist.
    """
    documents = Path(os.environ.get(
        "COMMITTEE_OS_DATA_ROOT",
        Path.home() / "Documents" / "ContentPipeline"
    ))
    documents.mkdir(parents=True, exist_ok=True)
    return documents / "pipeline.db"


DB_PATH: Path = _resolve_db_path()


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    """Return a SQLite connection with foreign keys enforced.

    Parameters
    ----------
    db_path : Path, optional
        Override for testing. Defaults to the production DB_PATH.

    Returns
    -------
    sqlite3.Connection
    """
    path = db_path or DB_PATH
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn
