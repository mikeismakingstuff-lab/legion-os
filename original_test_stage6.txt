"""
Committee OS — Stage 6 Output tests.

Covers:
  1. Output contract validation (slots, confidence, ranks, IDs)
  2. Content retrieval from SQLite by unit_id
  3. Pipeline summary metrics (ingested, parsed, filtered, gate)
  4. Pipeline halt behavior on validation failure
  5. DB persistence (pipeline_outputs table)
  6. Pipeline logging (stage_start, stage_complete, pipeline_halt)
  7. End-to-end output generation
"""

import json
import sqlite3
from pathlib import Path

import pytest

from src.init_db import init_database
from src.stage0_mission import create_mission
from src.stage1_ingest import ingest_record
from src.stage2_parse import parse_ingest_record
from src.stage3_filter import filter_units
from src.stage4_weigh import weigh_units
from src.stage5_deliberate import deliberate_mission
from src.stage6_output import (
    _validate_deliberation_output,
    generate_pipeline_output,
)


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def tmp_db(tmp_path):
    db_path = tmp_path / "pipeline.db"
    init_database(db_path)
    return db_path


def _setup_mission_with_deliberation(tmp_db, raw_content, domain="content_syndicate"):
    """Create a mission, ingest, parse, filter, weigh, deliberate, return (mission, delib_out)."""
    mission = create_mission(
        mission_statement="Test output",
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
    delib_out = deliberate_mission(mission["mission_id"], db_path=tmp_db)
    return mission, delib_out


# ═══════════════════════════════════════════════════════════════
# 1. Output Contract Validation
# ═══════════════════════════════════════════════════════════════

class TestOutputValidation:
    def test_valid_deliberation_output(self):
        output = {
            "mission_id": "m1",
            "deliberation_id": "d1",
            "recommendations": [
                {"rank": 1, "slot": "1A", "unit_id": "u1", "rationale": "good", "confidence": 0.9},
                {"rank": 2, "slot": "2A", "unit_id": "u2", "rationale": "ok", "confidence": 0.8},
                {"rank": 3, "slot": "3A", "unit_id": "u3", "rationale": "fine", "confidence": 0.7},
            ]
        }
        err = _validate_deliberation_output(output)
        assert err is None

    def test_missing_slot(self):
        output = {
            "mission_id": "m1",
            "deliberation_id": "d1",
            "recommendations": [
                {"rank": 1, "slot": "1A", "unit_id": "u1", "rationale": "good", "confidence": 0.9},
                {"rank": 2, "slot": "2A", "unit_id": "u2", "rationale": "ok", "confidence": 0.8},
            ]
        }
        err = _validate_deliberation_output(output)
        assert "Expected exactly 3 recommendations" in err


# ═══════════════════════════════════════════════════════════════
# 2. Pipeline Halt Behavior
# ═══════════════════════════════════════════════════════════════

class TestPipelineHalt:
    def test_halt_on_validation_failure(self, tmp_db):
        mission = create_mission(
            mission_statement="Test output",
            domain="content_syndicate",
            calibration={
                "ingest_mode": "direct",
                "volume_quality_slider": 0.5,
                "min_content_length": 5,
                "active_emphasis_lenses": [],
            },
            db_path=tmp_db,
        )
        invalid_output = {
            "mission_id": mission["mission_id"],
            "deliberation_id": "d1",
            "recommendations": []
        }
        with pytest.raises(ValueError, match="Deliberation output validation failed"):
            generate_pipeline_output(invalid_output, db_path=tmp_db)

        # Verify pipeline_halt is logged
        conn = sqlite3.connect(str(tmp_db))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT event, detail FROM pipeline_log "
            "WHERE stage = 'OUTPUT' AND event = 'pipeline_halt'"
        ).fetchone()
        conn.close()
        assert row is not None
        assert "Validation failed" in row["detail"]


# ═══════════════════════════════════════════════════════════════
# 3. End-to-End Output Generation & Metrics
# ═══════════════════════════════════════════════════════════════

class TestEndToEndOutput:
    def test_successful_output_generation(self, tmp_db):
        raw_content = (
            "This is an original visual design for our brand identity. We will implement it tomorrow.\n\n"
            "The budget for this operation is $100000, which will improve ROI by 20%.\n\n"
            "Describes a concrete process, method, tool, or technique to optimize performance.\n\n"
            "Contains audience, reach, or platform-specific signal for modern platforms."
        )
        mission, delib_out = _setup_mission_with_deliberation(tmp_db, raw_content)
        res = generate_pipeline_output(delib_out, db_path=tmp_db)

        assert res["mission_id"] == mission["mission_id"]
        assert "slots" in res
        assert "1A" in res["slots"]
        assert "2A" in res["slots"]
        assert "3A" in res["slots"]

        # Verify content is populated
        assert res["slots"]["1A"]["content"] is not None
        assert res["slots"]["1A"]["rationale"] is not None

        # Verify pipeline summary metrics
        summary = res["pipeline_summary"]
        assert summary["total_units_ingested"] == 1
        assert summary["units_parsed"] == 5
        assert summary["units_passed_filter"] == 5
        assert summary["units_passed_gate"] == 5

        # Verify DB persistence
        conn = sqlite3.connect(str(tmp_db))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT slots, pipeline_summary FROM pipeline_outputs "
            "WHERE mission_id = ?",
            (mission["mission_id"],),
        ).fetchone()
        conn.close()
        assert row is not None
        slots_db = json.loads(row["slots"])
        summary_db = json.loads(row["pipeline_summary"])
        assert "1A" in slots_db
        assert summary_db["units_parsed"] == 5
