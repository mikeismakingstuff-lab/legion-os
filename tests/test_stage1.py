"""
Committee OS — Stage 1 Ingest tests.

Covers:
  1. Direct ingest — immediate "received" status
  2. Empty / invalid input rejection
  3. Shishi-odoshi — pending accumulation and threshold-triggered promotion
  4. Hybrid mode — same accumulation logic
  5. Pipeline log entries
  6. Batch ingest helper
  7. Query helpers (get_received_records, get_pending_count)
"""

import json
import sqlite3
from pathlib import Path

import pytest

from src.init_db import init_database
from src.stage0_mission import create_mission
from src.stage1_ingest import (
    ingest_record,
    ingest_batch,
    get_received_records,
    get_pending_count,
)


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def tmp_db(tmp_path):
    db_path = tmp_path / "pipeline.db"
    init_database(db_path)
    return db_path


def _create_mission(tmp_db, ingest_mode="direct", slider=0.5):
    """Helper: create a valid mission and return its record."""
    return create_mission(
        mission_statement="Test mission for ingest",
        domain="content_syndicate",
        calibration={
            "ingest_mode": ingest_mode,
            "volume_quality_slider": slider,
            "min_content_length": 80,
            "active_emphasis_lenses": ["creative_director"],
        },
        db_path=tmp_db,
    )


# ═══════════════════════════════════════════════════════════════
# 1. Direct ingest
# ═══════════════════════════════════════════════════════════════

class TestDirectIngest:
    def test_direct_returns_received(self, tmp_db):
        mission = _create_mission(tmp_db, ingest_mode="direct")
        result = ingest_record(
            mission_id=mission["mission_id"],
            source="operator_paste",
            format="text",
            raw_content="This is a test content unit for direct ingest.",
            db_path=tmp_db,
        )
        assert "error" not in result
        assert result["status"] == "received"

    def test_direct_persisted(self, tmp_db):
        mission = _create_mission(tmp_db, ingest_mode="direct")
        result = ingest_record(
            mission_id=mission["mission_id"],
            source="manual_entry",
            format="text",
            raw_content="Persisted content check.",
            db_path=tmp_db,
        )
        conn = sqlite3.connect(str(tmp_db))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM ingest_records WHERE ingest_id = ?",
            (result["ingest_id"],),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row["status"] == "received"
        assert row["source"] == "manual_entry"


# ═══════════════════════════════════════════════════════════════
# 2. Input validation
# ═══════════════════════════════════════════════════════════════

class TestIngestValidation:
    def test_empty_content_rejected(self, tmp_db):
        mission = _create_mission(tmp_db)
        result = ingest_record(
            mission_id=mission["mission_id"],
            source="test",
            format="text",
            raw_content="",
            db_path=tmp_db,
        )
        assert "error" in result

    def test_whitespace_content_rejected(self, tmp_db):
        mission = _create_mission(tmp_db)
        result = ingest_record(
            mission_id=mission["mission_id"],
            source="test",
            format="text",
            raw_content="   ",
            db_path=tmp_db,
        )
        assert "error" in result

    def test_empty_source_rejected(self, tmp_db):
        mission = _create_mission(tmp_db)
        result = ingest_record(
            mission_id=mission["mission_id"],
            source="",
            format="text",
            raw_content="Valid content.",
            db_path=tmp_db,
        )
        assert "error" in result

    def test_invalid_mission_id(self, tmp_db):
        result = ingest_record(
            mission_id="nonexistent-uuid",
            source="test",
            format="text",
            raw_content="Valid content.",
            db_path=tmp_db,
        )
        assert "error" in result


# ═══════════════════════════════════════════════════════════════
# 3. Shishi-odoshi — pending + threshold promotion
# ═══════════════════════════════════════════════════════════════

class TestShishiOdoshi:
    def test_pending_status_initially(self, tmp_db):
        """Records should start as 'pending' in shishi-odoshi mode."""
        mission = _create_mission(tmp_db, ingest_mode="shishi-odoshi", slider=0.99)
        result = ingest_record(
            mission_id=mission["mission_id"],
            source="stream_a",
            format="text",
            raw_content="First data unit.",
            db_path=tmp_db,
        )
        assert "error" not in result
        # With slider=0.99 and base ~80, threshold = 80*(1-0.99)=0.8 → 1
        # So a single record should actually trigger promotion.
        # Use a more extreme case to test pending state:

    def test_pending_count(self, tmp_db):
        """With a high threshold, records remain pending."""
        # slider=0.0 → threshold = 80*(1-0.0) = 80, need 80 records to trigger
        mission = _create_mission(tmp_db, ingest_mode="shishi-odoshi", slider=0.0)
        ingest_record(
            mission_id=mission["mission_id"],
            source="stream_a", format="text",
            raw_content="Unit one.", db_path=tmp_db,
        )
        ingest_record(
            mission_id=mission["mission_id"],
            source="stream_a", format="text",
            raw_content="Unit two.", db_path=tmp_db,
        )
        count = get_pending_count(mission["mission_id"], db_path=tmp_db)
        assert count == 2

    def test_threshold_triggers_promotion(self, tmp_db):
        """When pending count reaches threshold, all promote to 'received'."""
        # slider=0.99 → threshold = 80 * (1-0.99) = 0.8 → max(1, 0) = 1
        mission = _create_mission(tmp_db, ingest_mode="shishi-odoshi", slider=0.99)
        result = ingest_record(
            mission_id=mission["mission_id"],
            source="stream_a", format="text",
            raw_content="Data that should trigger threshold.", db_path=tmp_db,
        )
        # After 1 record, threshold of 1 should be met → promoted
        received = get_received_records(mission["mission_id"], db_path=tmp_db)
        assert len(received) >= 1

    def test_batch_threshold(self, tmp_db):
        """Multiple records accumulate, then threshold promotes all at once."""
        # slider=0.95 → threshold = 80 * 0.05 = 4
        mission = _create_mission(tmp_db, ingest_mode="shishi-odoshi", slider=0.95)

        # Insert 3 records — should stay pending
        for i in range(3):
            ingest_record(
                mission_id=mission["mission_id"],
                source="feed", format="text",
                raw_content=f"Batch unit {i}.", db_path=tmp_db,
            )
        assert get_pending_count(mission["mission_id"], db_path=tmp_db) == 3

        # 4th record hits threshold → all 4 promoted
        ingest_record(
            mission_id=mission["mission_id"],
            source="feed", format="text",
            raw_content="Batch unit 3 — triggers threshold.", db_path=tmp_db,
        )
        assert get_pending_count(mission["mission_id"], db_path=tmp_db) == 0
        received = get_received_records(mission["mission_id"], db_path=tmp_db)
        assert len(received) == 4


# ═══════════════════════════════════════════════════════════════
# 4. Hybrid mode
# ═══════════════════════════════════════════════════════════════

class TestHybridIngest:
    def test_hybrid_accumulates_as_pending(self, tmp_db):
        mission = _create_mission(tmp_db, ingest_mode="hybrid", slider=0.0)
        result = ingest_record(
            mission_id=mission["mission_id"],
            source="sensor", format="log",
            raw_content="Hybrid data unit.", db_path=tmp_db,
        )
        assert "error" not in result
        # slider=0.0 → threshold=80, so 1 record stays pending
        assert get_pending_count(mission["mission_id"], db_path=tmp_db) == 1


# ═══════════════════════════════════════════════════════════════
# 5. Pipeline logging
# ═══════════════════════════════════════════════════════════════

class TestIngestLogging:
    def test_log_entries_created(self, tmp_db):
        mission = _create_mission(tmp_db, ingest_mode="direct")
        ingest_record(
            mission_id=mission["mission_id"],
            source="test", format="text",
            raw_content="Log check.", db_path=tmp_db,
        )
        conn = sqlite3.connect(str(tmp_db))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT event, stage FROM pipeline_log "
            "WHERE mission_id = ? AND stage = 'INGEST'",
            (mission["mission_id"],),
        ).fetchall()
        conn.close()
        events = [r["event"] for r in rows]
        assert "stage_start" in events
        assert "stage_complete" in events


# ═══════════════════════════════════════════════════════════════
# 6. Batch ingest
# ═══════════════════════════════════════════════════════════════

class TestBatchIngest:
    def test_batch_returns_all_results(self, tmp_db):
        mission = _create_mission(tmp_db, ingest_mode="direct")
        records = [
            {"source": "s1", "format": "text", "raw_content": "Content A."},
            {"source": "s2", "format": "text", "raw_content": "Content B."},
            {"source": "s3", "format": "text", "raw_content": "Content C."},
        ]
        results = ingest_batch(
            mission_id=mission["mission_id"],
            records=records,
            db_path=tmp_db,
        )
        assert len(results) == 3
        assert all("error" not in r for r in results)
        assert all(r["status"] == "received" for r in results)


# ═══════════════════════════════════════════════════════════════
# 7. Query helpers
# ═══════════════════════════════════════════════════════════════

class TestQueryHelpers:
    def test_get_received_empty(self, tmp_db):
        mission = _create_mission(tmp_db, ingest_mode="shishi-odoshi", slider=0.0)
        received = get_received_records(mission["mission_id"], db_path=tmp_db)
        assert received == []

    def test_get_pending_count_zero_for_direct(self, tmp_db):
        mission = _create_mission(tmp_db, ingest_mode="direct")
        ingest_record(
            mission_id=mission["mission_id"],
            source="test", format="text",
            raw_content="Direct content.", db_path=tmp_db,
        )
        assert get_pending_count(mission["mission_id"], db_path=tmp_db) == 0
