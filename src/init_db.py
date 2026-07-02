"""
Committee OS — SQLite schema initialisation.

Creates all 8 stage-owned tables defined in Architecture §4.
Idempotent: safe to run multiple times (CREATE TABLE IF NOT EXISTS).

Tables
------
missions            Stage 0
ingest_records      Stage 1
parsed_units        Stage 2
filter_results      Stage 3
lens_scores         Stage 4
deliberation_results Stage 5
pipeline_outputs    Stage 6
pipeline_log        All stages
"""

import sqlite3
from pathlib import Path

from src.db import get_connection


SCHEMA_SQL = """
-- ═══════════════════════════════════════════════════════════
-- Stage 0: missions
-- ═══════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS missions (
    mission_id   TEXT PRIMARY KEY,
    statement    TEXT    NOT NULL,
    domain       TEXT    NOT NULL,
    timestamp    TEXT    NOT NULL,
    calibration  TEXT    NOT NULL   -- JSON blob
);

-- ═══════════════════════════════════════════════════════════
-- Stage 1: ingest_records
-- ═══════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS ingest_records (
    ingest_id    TEXT PRIMARY KEY,
    mission_id   TEXT    NOT NULL REFERENCES missions(mission_id),
    source       TEXT    NOT NULL,
    format       TEXT    NOT NULL,
    raw_content  TEXT    NOT NULL,
    timestamp    TEXT    NOT NULL,
    status       TEXT    NOT NULL DEFAULT 'received'
);

-- ═══════════════════════════════════════════════════════════
-- Stage 2: parsed_units
-- ═══════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS parsed_units (
    unit_id         TEXT PRIMARY KEY,
    ingest_id       TEXT    NOT NULL REFERENCES ingest_records(ingest_id),
    type            TEXT    NOT NULL CHECK (type IN ('fact','figure','claim','instruction','unknown')),
    content         TEXT    NOT NULL,
    character_count INTEGER NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'parsed'
);

-- ═══════════════════════════════════════════════════════════
-- Stage 3: filter_results
-- ═══════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS filter_results (
    unit_id     TEXT PRIMARY KEY REFERENCES parsed_units(unit_id),
    status      TEXT NOT NULL CHECK (status IN ('pass','fail')),
    fail_reason TEXT          -- NULL when status = 'pass'
);

-- ═══════════════════════════════════════════════════════════
-- Stage 4: lens_scores
-- ═══════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS lens_scores (
    unit_id             TEXT NOT NULL REFERENCES parsed_units(unit_id),
    lens                TEXT NOT NULL,
    raw_score           REAL NOT NULL,
    criteria_breakdown  TEXT NOT NULL,   -- JSON blob
    weighted_score      REAL NOT NULL,
    PRIMARY KEY (unit_id, lens)
);

-- ═══════════════════════════════════════════════════════════
-- Stage 5: deliberation_results
-- ═══════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS deliberation_results (
    deliberation_id TEXT PRIMARY KEY,
    mission_id      TEXT NOT NULL REFERENCES missions(mission_id),
    recommendations TEXT NOT NULL,   -- JSON blob
    flags           TEXT NOT NULL    -- JSON blob
);

-- ═══════════════════════════════════════════════════════════
-- Stage 6: pipeline_outputs
-- ═══════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS pipeline_outputs (
    output_id        TEXT PRIMARY KEY,
    mission_id       TEXT NOT NULL REFERENCES missions(mission_id),
    timestamp        TEXT NOT NULL,
    slots            TEXT NOT NULL,   -- JSON blob
    pipeline_summary TEXT NOT NULL    -- JSON blob
);

-- ═══════════════════════════════════════════════════════════
-- All stages: pipeline_log
-- ═══════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS pipeline_log (
    log_id      TEXT PRIMARY KEY,
    mission_id  TEXT NOT NULL REFERENCES missions(mission_id),
    stage       TEXT NOT NULL CHECK (stage IN (
                    'MISSION','INGEST','PARSE','FILTER','WEIGH','DELIBERATE','OUTPUT'
                )),
    event       TEXT NOT NULL CHECK (event IN (
                    'stage_start','stage_complete',
                    'unit_pass','unit_fail',
                    'ai_call','ai_error',
                    'pipeline_halt'
                )),
    detail      TEXT NOT NULL,
    timestamp   TEXT NOT NULL,
    error_code  TEXT              -- NULL when no error
);
"""


def init_database(db_path: Path | None = None) -> None:
    """Create all pipeline tables.

    Parameters
    ----------
    db_path : Path, optional
        Override for testing.  Defaults to the production DB path.
    """
    conn = get_connection(db_path)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()


EXPECTED_TABLES = [
    "missions",
    "ingest_records",
    "parsed_units",
    "filter_results",
    "lens_scores",
    "deliberation_results",
    "pipeline_outputs",
    "pipeline_log",
]


if __name__ == "__main__":
    init_database()
    print("✓ pipeline.db initialised — all 8 tables created.")
