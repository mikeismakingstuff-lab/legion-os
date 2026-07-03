"""
Committee OS — Phase 1 automated verification.

Tests cover:
  1. config.json integrity
  2. system_modes.json integrity (14 modes, 28 roles, modifier bounds)
  3. SQLite schema creation (8 tables)
  4. Stage 0 — valid mission creation and persistence
  5. Stage 0 — rejection of invalid inputs
  6. Stage 0 — pipeline_log entries
"""

import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

# ── Paths ─────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
MODES_PATH = ROOT / "system_modes.json"

# ── Imports under test ────────────────────────────────────────
from src.init_db import init_database, EXPECTED_TABLES
from src.stage0_mission import create_mission


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def tmp_db(tmp_path):
    """Return a path to a temporary pipeline.db, schema already init'd."""
    db_path = tmp_path / "pipeline.db"
    init_database(db_path)
    return db_path


@pytest.fixture
def valid_calibration():
    return {
        "ingest_mode": "direct",
        "volume_quality_slider": 0.5,
        "min_content_length": 80,
        "active_emphasis_lenses": ["creative_director", "archivist"],
    }


# ═══════════════════════════════════════════════════════════════
# 1. config.json
# ═══════════════════════════════════════════════════════════════

class TestConfig:
    def test_config_loads(self):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        assert isinstance(cfg, dict)

    def test_required_keys_present(self):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        required = [
            "gate_threshold", "max_ai_calls_per_run",
            "qwen_max_tokens", "gemini_max_tokens",
            "qwen_retry_max", "qwen_retry_backoff_ms",
            "qwen_request_min_interval_ms", "qwen_429_type_check",
            "parse_min_length", "top_units_to_deliberation",
            "lens_weight_default", "lens_weight_amplified",
            "lens_weight_floor", "user_emphasis_max_selections",
            "lens_weights",
        ]
        for key in required:
            assert key in cfg, f"Missing key: {key}"

    def test_lens_weights_has_all_eight(self):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        expected_lenses = {
            "creative_director", "financial_director", "technical_director",
            "marketing_director", "audience_retention", "chief_executor",
            "archivist", "legal_qa",
        }
        assert set(cfg["lens_weights"].keys()) == expected_lenses

    def test_gate_threshold_value(self):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        assert cfg["gate_threshold"] == 0.55

    def test_max_ai_calls(self):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        assert cfg["max_ai_calls_per_run"] == 2


# ═══════════════════════════════════════════════════════════════
# 2. system_modes.json
# ═══════════════════════════════════════════════════════════════

class TestSystemModes:
    def test_modes_loads(self):
        with open(MODES_PATH, "r", encoding="utf-8") as f:
            modes = json.load(f)
        assert isinstance(modes, list)

    def test_fourteen_modes(self):
        with open(MODES_PATH, "r", encoding="utf-8") as f:
            modes = json.load(f)
        assert len(modes) == 14

    def test_required_mode_fields(self):
        with open(MODES_PATH, "r", encoding="utf-8") as f:
            modes = json.load(f)
        for mode in modes:
            assert "mode_id" in mode, f"Missing mode_id in {mode}"
            assert "display_name" in mode
            assert "peer_review_roles" in mode
            assert "ingest_formats" in mode
            assert "default_min_length" in mode

    def test_each_mode_has_two_roles(self):
        with open(MODES_PATH, "r", encoding="utf-8") as f:
            modes = json.load(f)
        for mode in modes:
            assert len(mode["peer_review_roles"]) == 2, (
                f"{mode['mode_id']} should have exactly 2 peer-review roles"
            )

    def test_modifier_bounds(self):
        """All lens modifiers must be within [0.5, 2.0] per Architecture §4b."""
        with open(MODES_PATH, "r", encoding="utf-8") as f:
            modes = json.load(f)
        for mode in modes:
            for role in mode["peer_review_roles"]:
                for lens, value in role["lens_modifiers"].items():
                    assert 0.5 <= value <= 2.0, (
                        f"{mode['mode_id']}/{role['role_name']}/{lens} = {value} "
                        f"is outside [0.5, 2.0]"
                    )

    def test_all_expected_mode_ids_present(self):
        with open(MODES_PATH, "r", encoding="utf-8") as f:
            modes = json.load(f)
        expected = {
            "educational_academy", "content_syndicate", "secops_triager",
            "code_guard", "video_narrative_engine", "customer_voc_synthesizer",
            "product_listing_machine", "real_estate_qualifier", "patch_guard",
            "digital_archival_processor", "network_flow_hunter",
            "market_sentiment_aggregator", "telemetry_diagnostic_loop",
            "lit_review_examiner",
        }
        actual = {m["mode_id"] for m in modes}
        assert actual == expected


# ═══════════════════════════════════════════════════════════════
# 3. SQLite schema
# ═══════════════════════════════════════════════════════════════

class TestSchema:
    def test_all_tables_created(self, tmp_db):
        conn = sqlite3.connect(str(tmp_db))
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = sorted([row[0] for row in cursor.fetchall()])
        conn.close()
        assert tables == sorted(EXPECTED_TABLES)

    def test_idempotent(self, tmp_db):
        """Running init twice must not error."""
        init_database(tmp_db)
        conn = sqlite3.connect(str(tmp_db))
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = [row[0] for row in cursor.fetchall()]
        conn.close()
        assert len(tables) == 13


# ═══════════════════════════════════════════════════════════════
# 4. Stage 0 — valid mission
# ═══════════════════════════════════════════════════════════════

class TestMissionValid:
    def test_creates_mission(self, tmp_db, valid_calibration):
        result = create_mission(
            mission_statement="Analyse Q2 earnings for tech sector",
            domain="market_sentiment_aggregator",
            calibration=valid_calibration,
            db_path=tmp_db,
        )
        assert "error" not in result
        assert "mission_id" in result
        assert result["domain"] == "market_sentiment_aggregator"

    def test_mission_persisted(self, tmp_db, valid_calibration):
        result = create_mission(
            mission_statement="Audit latest CVEs for Node.js deps",
            domain="patch_guard",
            calibration=valid_calibration,
            db_path=tmp_db,
        )
        conn = sqlite3.connect(str(tmp_db))
        row = conn.execute(
            "SELECT * FROM missions WHERE mission_id = ?",
            (result["mission_id"],),
        ).fetchone()
        conn.close()
        assert row is not None

    def test_calibration_stored_as_json(self, tmp_db, valid_calibration):
        result = create_mission(
            mission_statement="Test calibration storage",
            domain="code_guard",
            calibration=valid_calibration,
            db_path=tmp_db,
        )
        conn = sqlite3.connect(str(tmp_db))
        row = conn.execute(
            "SELECT calibration FROM missions WHERE mission_id = ?",
            (result["mission_id"],),
        ).fetchone()
        conn.close()
        cal = json.loads(row[0])
        assert cal["ingest_mode"] == "direct"
        assert cal["volume_quality_slider"] == 0.5


# ═══════════════════════════════════════════════════════════════
# 5. Stage 0 — rejection
# ═══════════════════════════════════════════════════════════════

class TestMissionRejection:
    def test_empty_statement(self, tmp_db, valid_calibration):
        result = create_mission(
            mission_statement="",
            domain="code_guard",
            calibration=valid_calibration,
            db_path=tmp_db,
        )
        assert "error" in result

    def test_whitespace_statement(self, tmp_db, valid_calibration):
        result = create_mission(
            mission_statement="   ",
            domain="code_guard",
            calibration=valid_calibration,
            db_path=tmp_db,
        )
        assert "error" in result

    def test_invalid_domain(self, tmp_db, valid_calibration):
        result = create_mission(
            mission_statement="Valid statement",
            domain="nonexistent_mode",
            calibration=valid_calibration,
            db_path=tmp_db,
        )
        assert "error" in result

    def test_invalid_ingest_mode(self, tmp_db):
        result = create_mission(
            mission_statement="Valid statement",
            domain="code_guard",
            calibration={
                "ingest_mode": "invalid",
                "volume_quality_slider": 0.5,
                "min_content_length": 80,
                "active_emphasis_lenses": [],
            },
            db_path=tmp_db,
        )
        assert "error" in result

    def test_slider_out_of_range(self, tmp_db):
        result = create_mission(
            mission_statement="Valid statement",
            domain="code_guard",
            calibration={
                "ingest_mode": "direct",
                "volume_quality_slider": 1.5,
                "min_content_length": 80,
                "active_emphasis_lenses": [],
            },
            db_path=tmp_db,
        )
        assert "error" in result

    def test_too_many_emphasis_lenses(self, tmp_db):
        result = create_mission(
            mission_statement="Valid statement",
            domain="code_guard",
            calibration={
                "ingest_mode": "direct",
                "volume_quality_slider": 0.5,
                "min_content_length": 80,
                "active_emphasis_lenses": ["a", "b", "c", "d"],
            },
            db_path=tmp_db,
        )
        assert "error" in result


# ═══════════════════════════════════════════════════════════════
# 6. Stage 0 — pipeline_log
# ═══════════════════════════════════════════════════════════════

class TestMissionLogging:
    def test_log_entries_created(self, tmp_db, valid_calibration):
        result = create_mission(
            mission_statement="Test logging",
            domain="secops_triager",
            calibration=valid_calibration,
            db_path=tmp_db,
        )
        conn = sqlite3.connect(str(tmp_db))
        rows = conn.execute(
            "SELECT event FROM pipeline_log WHERE mission_id = ? ORDER BY timestamp",
            (result["mission_id"],),
        ).fetchall()
        conn.close()
        events = [r[0] for r in rows]
        assert "stage_start" in events
        assert "stage_complete" in events
