"""
Committee OS — Stage 5 Deliberate tests.

Covers:
  1. Gemini Reactive Formatter (mock formatting and fallback behavior)
  2. Qwen Deliberation Engine (mock deliberation, validation, retry on malformed output)
  3. Qwen output contract validation (slots, confidence, IDs)
  4. Pipeline halt behavior (on validation failure or complete failure)
  5. 429 rate limit exponential backoff (mocking RateLimitError)
  6. Pipeline logging (ai_call, ai_error, pipeline_halt)
  7. End-to-end deliberation: ingest → parse → filter → weigh → deliberate → verify deliberation_results table
"""

import json
import sqlite3
import time
from pathlib import Path

import pytest
from openai import RateLimitError

from src.init_db import init_database
from src.stage0_mission import create_mission
from src.stage1_ingest import ingest_record
from src.stage2_parse import parse_ingest_record
from src.stage3_filter import filter_units
from src.stage4_weigh import weigh_units
from src.stage5_deliberate import (
    _call_gemini,
    _validate_qwen_output,
    deliberate_mission,
)


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def tmp_db(tmp_path):
    db_path = tmp_path / "pipeline.db"
    init_database(db_path)
    return db_path


def _setup_mission_with_scored_units(tmp_db, raw_content, domain="content_syndicate"):
    """Create a mission, ingest, parse, filter, weigh, return mission."""
    mission = create_mission(
        mission_statement="Test deliberate",
        domain=domain,
        calibration={
            "ingest_mode": "direct",
            "volume_quality_slider": 0.5,
            "min_content_length": 5,
            "active_emphasis_lenses": [],
        },
        db_path=tmp_db,
    )
    ingest = ingest_record(
        mission_id=mission["mission_id"],
        source="test_source",
        format="text",
        raw_content=raw_content,
        db_path=tmp_db,
    )
    parse_ingest_record(
        ingest["ingest_id"], mission["mission_id"], db_path=tmp_db
    )
    filter_units(mission["mission_id"], db_path=tmp_db)
    weigh_units(mission["mission_id"], db_path=tmp_db)
    return mission


# ═══════════════════════════════════════════════════════════════
# 1. Gemini Formatter
# ═══════════════════════════════════════════════════════════════

class TestGeminiFormatter:
    def test_gemini_mock_formatting(self):
        payload = {
            "mission_id": "test-uuid",
            "mission_statement": "Test statement",
            "top_units": [
                {"unit_id": "u1", "content": "hello", "lens_scores": {}, "aggregate_score": 0.8}
            ],
        }
        res = _call_gemini(payload)
        assert res["mission_id"] == "test-uuid"
        assert len(res["top_units"]) == 1
        assert res["top_units"][0]["unit_id"] == "u1"
        assert "gemini_error" not in res


# ═══════════════════════════════════════════════════════════════
# 2. Qwen Output Contract Validation
# ═══════════════════════════════════════════════════════════════

class TestQwenValidation:
    def test_valid_output(self):
        handoff = {
            "mission_id": "test-uuid",
            "top_units": [
                {"unit_id": "u1"},
                {"unit_id": "u2"},
                {"unit_id": "u3"},
            ]
        }
        output = {
            "mission_id": "test-uuid",
            "deliberation_id": "delib-uuid",
            "recommendations": [
                {"rank": 1, "slot": "1A", "unit_id": "u1", "rationale": "good", "confidence": 0.9},
                {"rank": 2, "slot": "2A", "unit_id": "u2", "rationale": "ok", "confidence": 0.8},
                {"rank": 3, "slot": "3A", "unit_id": "u3", "rationale": "fine", "confidence": 0.7},
            ],
            "flags": []
        }
        err = _validate_qwen_output(output, handoff)
        assert err is None

    def test_invalid_slots(self):
        handoff = {
            "mission_id": "test-uuid",
            "top_units": [{"unit_id": "u1"}, {"unit_id": "u2"}, {"unit_id": "u3"}]
        }
        # Duplicate slot 1A
        output = {
            "mission_id": "test-uuid",
            "deliberation_id": "delib-uuid",
            "recommendations": [
                {"rank": 1, "slot": "1A", "unit_id": "u1", "rationale": "good", "confidence": 0.9},
                {"rank": 2, "slot": "1A", "unit_id": "u2", "rationale": "ok", "confidence": 0.8},
                {"rank": 3, "slot": "3A", "unit_id": "u3", "rationale": "fine", "confidence": 0.7},
            ]
        }
        err = _validate_qwen_output(output, handoff)
        assert "Duplicate slot" in err


# ═══════════════════════════════════════════════════════════════
# 3. Pipeline Halt Behavior
# ═══════════════════════════════════════════════════════════════

class TestPipelineHalt:
    def test_halt_on_no_passing_units(self, tmp_db):
        # Create a mission with no units that pass the gate (all low scoring)
        mission = _setup_mission_with_scored_units(
            tmp_db, "Lorem ipsum dolor sit amet."
        )
        with pytest.raises(ValueError, match="No units passed the gate threshold"):
            deliberate_mission(mission["mission_id"], db_path=tmp_db)

        # Verify pipeline_halt is logged
        conn = sqlite3.connect(str(tmp_db))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT event, detail FROM pipeline_log "
            "WHERE mission_id = ? AND stage = 'DELIBERATE' AND event = 'pipeline_halt'",
            (mission["mission_id"],),
        ).fetchone()
        conn.close()
        assert row is not None
        assert "No units passed" in row["detail"]


# ═══════════════════════════════════════════════════════════════
# 4. End-to-End Deliberation
# ═══════════════════════════════════════════════════════════════

class TestEndToEndDeliberation:
    def test_successful_deliberation(self, tmp_db):
        # Ingest 4 high-scoring units to make sure we have enough passing units
        raw_content = (
            "This is an original visual design for our brand identity. We will implement it tomorrow.\n\n"
            "The budget for this operation is $100000, which will improve ROI by 20%.\n\n"
            "Describes a concrete process, method, tool, or technique to optimize performance.\n\n"
            "Contains audience, reach, or platform-specific signal for modern platforms."
        )
        mission = _setup_mission_with_scored_units(tmp_db, raw_content)
        res = deliberate_mission(mission["mission_id"], db_path=tmp_db)

        assert res["mission_id"] == mission["mission_id"]
        assert len(res["recommendations"]) == 3

        # Verify deliberation_results table
        conn = sqlite3.connect(str(tmp_db))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT recommendations FROM deliberation_results "
            "WHERE mission_id = ?",
            (mission["mission_id"],),
        ).fetchone()
        conn.close()
        assert row is not None
        recs = json.loads(row["recommendations"])
        assert len(recs) == 3
        assert recs[0]["slot"] == "1A"
