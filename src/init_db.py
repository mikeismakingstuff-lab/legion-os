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

-- ═══════════════════════════════════════════════════════════
-- Stage 0 Extension: source_registry
-- ═══════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS source_registry (
    source_id   TEXT PRIMARY KEY,
    domain      TEXT NOT NULL,
    keyword     TEXT NOT NULL,  -- '*' matches any mission statement
    url         TEXT NOT NULL,
    priority    INTEGER NOT NULL
);

-- ═══════════════════════════════════════════════════════════
-- Stage 3/4 Extension: classified_records
-- ═══════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS classified_records (
    record_id             TEXT PRIMARY KEY,
    chapter_id            TEXT NOT NULL,
    assertion_key         TEXT NOT NULL,
    verdict               TEXT NOT NULL CHECK (verdict IN ('pass', 'fail', 'flagged')),
    rubric_dependencies   TEXT NOT NULL, -- JSON blob of evaluated criteria
    confidence_score      REAL NOT NULL CHECK (confidence_score >= 0.0 AND confidence_score <= 1.0),
    supersedes_record_id  TEXT REFERENCES classified_records(record_id),
    timestamp             TEXT NOT NULL
);

-- ═══════════════════════════════════════════════════════════
-- Stage 3/4 Extension: record_dependencies
-- ═══════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS record_dependencies (
    dependent_record_id   TEXT NOT NULL REFERENCES classified_records(record_id),
    dependency_record_id  TEXT NOT NULL REFERENCES classified_records(record_id),
    PRIMARY KEY (dependent_record_id, dependency_record_id)
);

-- ═══════════════════════════════════════════════════════════
-- Stage 3/4 Extension: quarantine_log
-- ═══════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS quarantine_log (
    quarantine_id         TEXT PRIMARY KEY,
    unit_id               TEXT NOT NULL REFERENCES parsed_units(unit_id),
    reason                TEXT NOT NULL,
    timestamp             TEXT NOT NULL
);

-- ═══════════════════════════════════════════════════════════
-- Stage 3/4 Extension: manual_review_queue
-- ═══════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS manual_review_queue (
    review_id                     TEXT PRIMARY KEY,
    contested_key_a               TEXT NOT NULL,
    contested_key_b               TEXT NOT NULL,
    loser_key                     TEXT NOT NULL,
    projected_blast_radius        REAL NOT NULL,
    affected_record_ids           TEXT NOT NULL, -- JSON list of record_ids
    timestamp                     TEXT NOT NULL,
    status                        TEXT NOT NULL DEFAULT 'awaiting_human_review'
                                     CHECK (status IN ('awaiting_human_review', 'approved', 'rejected'))
);
"""


def init_database(db_path: Path | None = None) -> None:
    """Create all pipeline tables and pre-populate source_registry.

    Parameters
    ----------
    db_path : Path, optional
        Override for testing.  Defaults to the production DB path.
    """
    conn = get_connection(db_path)
    try:
        conn.executescript(SCHEMA_SQL)

        # Migration: add manual_review_queue.status to databases created before
        # this column existed. CREATE TABLE IF NOT EXISTS above is a no-op on an
        # already-existing table, so this ALTER TABLE is what actually reaches
        # pre-existing pipeline.db files. Safe to run repeatedly.
        try:
            conn.execute(
                "ALTER TABLE manual_review_queue ADD COLUMN status TEXT "
                "NOT NULL DEFAULT 'awaiting_human_review'"
            )
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc).lower():
                raise

        # Create indexes
        conn.execute("CREATE INDEX IF NOT EXISTS idx_records_chapter ON classified_records(chapter_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_records_assertion ON classified_records(assertion_key)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_records_supersedes ON classified_records(supersedes_record_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_dep_dependency ON record_dependencies(dependency_record_id)")
        
        # Pre-populate source_registry if empty
        row = conn.execute("SELECT COUNT(*) FROM source_registry").fetchone()
        if row and row[0] == 0:
            default_sources = [
                # educational_academy
                ("src_edu_1", "educational_academy", "math", "https://en.wikipedia.org/wiki/Mathematics", 1),
                ("src_edu_2", "educational_academy", "science", "https://en.wikipedia.org/wiki/Science", 2),
                ("src_edu_3", "educational_academy", "*", "https://en.wikipedia.org/wiki/Education", 3),
                # content_syndicate
                ("src_syn_1", "content_syndicate", "tech", "https://en.wikipedia.org/wiki/Technology", 1),
                ("src_syn_2", "content_syndicate", "business", "https://en.wikipedia.org/wiki/Business", 2),
                ("src_syn_3", "content_syndicate", "*", "https://en.wikipedia.org/wiki/News", 3),
                # secops_triager
                ("src_sec_1", "secops_triager", "security", "https://en.wikipedia.org/wiki/Computer_security", 1),
                ("src_sec_2", "secops_triager", "vulnerability", "https://en.wikipedia.org/wiki/Vulnerability_(computing)", 2),
                # code_guard
                ("src_code_1", "code_guard", "code", "https://en.wikipedia.org/wiki/Source_code", 1),
                ("src_code_2", "code_guard", "refactoring", "https://en.wikipedia.org/wiki/Code_refactoring", 2),
                # video_narrative_engine
                ("src_vid_1", "video_narrative_engine", "*", "https://en.wikipedia.org/wiki/Video", 1),
                # customer_voc_synthesizer
                ("src_voc_1", "customer_voc_synthesizer", "*", "https://en.wikipedia.org/wiki/Customer", 1),
                # product_listing_machine
                ("src_prod_1", "product_listing_machine", "*", "https://en.wikipedia.org/wiki/Product_(business)", 1),
                # real_estate_qualifier
                ("src_prop_1", "real_estate_qualifier", "*", "https://en.wikipedia.org/wiki/Real_estate", 1),
                # patch_guard
                ("src_patch_1", "patch_guard", "*", "https://en.wikipedia.org/wiki/Patch_(computing)", 1),
                # digital_archival_processor
                ("src_arch_1", "digital_archival_processor", "*", "https://en.wikipedia.org/wiki/Archive", 1),
                # network_flow_hunter
                ("src_net_1", "network_flow_hunter", "*", "https://en.wikipedia.org/wiki/Computer_network", 1),
                # market_sentiment_aggregator
                ("src_mkt_1", "market_sentiment_aggregator", "*", "https://en.wikipedia.org/wiki/Market", 1),
                # telemetry_diagnostic_loop
                ("src_tel_1", "telemetry_diagnostic_loop", "*", "https://en.wikipedia.org/wiki/Telemetry", 1),
                # lit_review_examiner
                ("src_lit_1", "lit_review_examiner", "*", "https://en.wikipedia.org/wiki/Literature", 1),
            ]
            conn.executemany(
                """
                INSERT INTO source_registry (source_id, domain, keyword, url, priority)
                VALUES (?, ?, ?, ?, ?)
                """,
                default_sources,
            )
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
    "source_registry",
    "classified_records",
    "record_dependencies",
    "quarantine_log",
    "manual_review_queue",
]


if __name__ == "__main__":
    init_database()
    print("✓ pipeline.db initialised — all 8 tables created.")
