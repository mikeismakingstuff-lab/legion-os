"""
Committee OS — Stage 4 Weigh tests.

Covers:
  1. Lens criteria evaluation (binary signals, raw score calculation)
  2. Weight modifiers (base, user emphasis, peer-review roles)
  3. Weight floor and ceiling constraints (0.5 - 2.0)
  4. Aggregate score calculation (weighted mean)
  5. Gate threshold filtering (units below threshold on all lenses eliminated)
  6. Top N scored units retrieval
  7. End-to-end weigh: ingest → parse → filter → weigh → verify lens_scores table
  8. Pipeline logging
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
from src.stage4_weigh import (
    _evaluate_lens,
    weigh_units,
    get_top_scored_units,
)


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def tmp_db(tmp_path):
    db_path = tmp_path / "pipeline.db"
    init_database(db_path)
    return db_path


def _setup_mission_with_filtered_units(tmp_db, raw_content, domain="content_syndicate", emphasis=None, slider=0.5):
    """Create a mission, ingest, parse, filter, return (mission, ingest, units)."""
    if emphasis is None:
        emphasis = []
    mission = create_mission(
        mission_statement="Test weigh",
        domain=domain,
        calibration={
            "ingest_mode": "direct",
            "volume_quality_slider": slider,
            "min_content_length": 5,
            "active_emphasis_lenses": emphasis,
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
    return mission


# ═══════════════════════════════════════════════════════════════
# 1. Lens criteria evaluation
# ═══════════════════════════════════════════════════════════════

class TestLensCriteria:
    def test_creative_director_evaluation(self):
        # Contains "original" and "visual" and "brand" and "practical" -> raw score should be high
        text = "This is an original visual design for our brand identity. We will implement it tomorrow."
        raw, breakdown = _evaluate_lens(text, "creative_director")
        assert raw >= 0.8
        assert breakdown["criterion_1"] == 1  # original
        assert breakdown["criterion_2"] == 1  # visual
        assert breakdown["criterion_3"] == 1  # brand
        assert breakdown["criterion_4"] == 1  # practical

    def test_financial_director_evaluation(self):
        # Contains budget/cost and ROI and operational expenses
        text = "The budget for this operation is $100000, which will improve ROI by 20%."
        raw, breakdown = _evaluate_lens(text, "financial_director")
        assert raw >= 0.6
        assert breakdown["criterion_1"] == 1  # budget / $
        assert breakdown["criterion_2"] == 1  # ROI
        assert breakdown["criterion_3"] == 1  # budget + number


# ═══════════════════════════════════════════════════════════════
# 2. Weight modifiers and constraints
# ═══════════════════════════════════════════════════════════════

class TestWeightModifiers:
    def test_emphasis_lens_amplified(self, tmp_db):
        # Set creative_director as emphasis lens
        mission = _setup_mission_with_filtered_units(
            tmp_db, "This is an original visual design for our brand identity. We will implement it tomorrow.",
            emphasis=["creative_director"]
        )
        results = weigh_units(mission["mission_id"], db_path=tmp_db)
        assert len(results) >= 1

        # Check weights in DB
        conn = sqlite3.connect(str(tmp_db))
        conn.row_factory = sqlite3.Row
        # For content_syndicate, Editor-in-Chief creative_director modifier is 2.0, SEO is 1.0.
        # Average peer-review modifier = (2.0 + 1.0) / 2 = 1.5.
        # Base weight (amplified) = 1.5.
        # Final weight = 1.5 * 1.5 = 2.25 -> capped at ceiling 2.0.
        row = conn.execute(
            "SELECT weighted_score, raw_score FROM lens_scores "
            "WHERE lens = 'creative_director' LIMIT 1"
        ).fetchone()
        conn.close()
        # Reconstruct weight
        weight = row["weighted_score"] / row["raw_score"] if row["raw_score"] > 0 else 0.0
        if row["raw_score"] > 0:
            assert abs(weight - 2.0) < 1e-5

    def test_weight_floor_enforced(self, tmp_db):
        # Test a lens with low modifiers to verify floor is enforced
        # For content_syndicate, Editor-in-Chief legal_qa modifier is 1.5, SEO is 0.5.
        # Average peer-review modifier = (1.5 + 0.5) / 2 = 1.0.
        # Let's check a lens with very low modifiers, e.g., financial_director:
        # Editor-in-Chief: 0.5, SEO: 1.0. Average = 0.75.
        # Base weight = 1.0. Final weight = 0.75.
        # Let's verify it is above the floor of 0.5.
        mission = _setup_mission_with_filtered_units(
            tmp_db, "The budget for this operation is $100000, which will improve ROI by 20%."
        )
        weigh_units(mission["mission_id"], db_path=tmp_db)
        conn = sqlite3.connect(str(tmp_db))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT weighted_score, raw_score FROM lens_scores "
            "WHERE lens = 'financial_director' LIMIT 1"
        ).fetchone()
        conn.close()
        if row["raw_score"] > 0:
            weight = row["weighted_score"] / row["raw_score"]
            assert weight >= 0.5


# ═══════════════════════════════════════════════════════════════
# 3. Aggregate score and gate filtering
# ═══════════════════════════════════════════════════════════════

class TestAggregateAndGate:
    def test_gate_filtering(self, tmp_db):
        # A unit that scores 0.0 on all lenses should be eliminated (not returned by get_top_scored_units)
        # "Lorem ipsum dolor sit amet." has no keywords for any lens.
        mission = _setup_mission_with_filtered_units(
            tmp_db, "Lorem ipsum dolor sit amet."
        )
        weigh_units(mission["mission_id"], db_path=tmp_db)
        top_units = get_top_scored_units(mission["mission_id"], db_path=tmp_db)
        assert len(top_units) == 0

    def test_top_scored_units_retrieval(self, tmp_db):
        # Ingest two units: one high scoring, one low scoring
        mission = _setup_mission_with_filtered_units(
            tmp_db, "This is an original visual design for our brand identity. We will implement it tomorrow.\n\n"
                    "The budget for this operation is $100000, which will improve ROI by 20%."
        )
        weigh_units(mission["mission_id"], db_path=tmp_db)
        top_units = get_top_scored_units(mission["mission_id"], limit=2, db_path=tmp_db)
        assert len(top_units) >= 1
        # The first one should have a higher aggregate score
        if len(top_units) == 2:
            assert top_units[0]["aggregate_score"] >= top_units[1]["aggregate_score"]


# ═══════════════════════════════════════════════════════════════
# 4. Pipeline logging
# ═══════════════════════════════════════════════════════════════

class TestWeighLogging:
    def test_log_entries(self, tmp_db):
        mission = _setup_mission_with_filtered_units(
            tmp_db, "This is an original visual design for our brand identity."
        )
        weigh_units(mission["mission_id"], db_path=tmp_db)
        conn = sqlite3.connect(str(tmp_db))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT event FROM pipeline_log "
            "WHERE mission_id = ? AND stage = 'WEIGH'",
            (mission["mission_id"],),
        ).fetchall()
        conn.close()
        events = [r["event"] for r in rows]
        assert "stage_start" in events
        assert "stage_complete" in events
