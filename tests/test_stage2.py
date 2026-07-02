"""
Committee OS — Stage 2 Parse tests.

Covers:
  1. Formatting artifact stripping (HTML, markdown, entities)
  2. Unit splitting (sentences, paragraphs)
  3. Type classification (fact, figure, claim, instruction, unknown)
  4. Unknown fallback — unclassifiable units are NOT discarded
  5. End-to-end parse: ingest → parse → verify parsed_units table
  6. parse_all_received batch processing
  7. Pipeline logging
"""

import json
import sqlite3
from pathlib import Path

import pytest

from src.init_db import init_database
from src.stage0_mission import create_mission
from src.stage1_ingest import ingest_record
from src.stage2_parse import (
    _strip_formatting,
    _split_into_units,
    _classify_unit,
    parse_ingest_record,
    parse_all_received,
    get_parsed_units,
)


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def tmp_db(tmp_path):
    db_path = tmp_path / "pipeline.db"
    init_database(db_path)
    return db_path


def _setup_mission_with_ingest(tmp_db, raw_content, ingest_mode="direct"):
    """Create a mission, ingest raw_content, return (mission, ingest_result)."""
    mission = create_mission(
        mission_statement="Test parse",
        domain="content_syndicate",
        calibration={
            "ingest_mode": ingest_mode,
            "volume_quality_slider": 0.5,
            "min_content_length": 80,
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
    return mission, ingest


# ═══════════════════════════════════════════════════════════════
# 1. Formatting stripping
# ═══════════════════════════════════════════════════════════════

class TestFormatStripping:
    def test_html_tags_removed(self):
        assert "Hello" in _strip_formatting("<p>Hello</p>")
        assert "<p>" not in _strip_formatting("<p>Hello</p>")

    def test_html_entities_removed(self):
        result = _strip_formatting("A&amp;B &lt; C")
        assert "&amp;" not in result
        assert "&lt;" not in result

    def test_markdown_bold_stripped(self):
        result = _strip_formatting("This is **bold** text.")
        assert "**" not in result
        assert "bold" in result

    def test_markdown_heading_stripped(self):
        result = _strip_formatting("## Section Title")
        assert "##" not in result
        assert "Section Title" in result

    def test_inline_code_stripped(self):
        result = _strip_formatting("Use `pip install` to install.")
        assert "`" not in result
        assert "pip install" in result

    def test_whitespace_collapsed(self):
        result = _strip_formatting("Too    many    spaces.")
        assert "  " not in result

    def test_list_bullets_stripped(self):
        result = _strip_formatting("- Item one\n* Item two\n• Item three")
        assert "Item one" in result
        assert "- " not in result


# ═══════════════════════════════════════════════════════════════
# 2. Unit splitting
# ═══════════════════════════════════════════════════════════════

class TestUnitSplitting:
    def test_single_sentence(self):
        units = _split_into_units("Hello world.")
        assert len(units) == 1

    def test_multiple_sentences(self):
        text = "First sentence. Second sentence. Third sentence."
        units = _split_into_units(text)
        assert len(units) >= 2

    def test_paragraph_splitting(self):
        text = "Paragraph one content.\n\nParagraph two content."
        units = _split_into_units(text)
        assert len(units) == 2

    def test_empty_input(self):
        units = _split_into_units("")
        assert units == []

    def test_whitespace_only(self):
        units = _split_into_units("   \n\n   ")
        assert units == []


# ═══════════════════════════════════════════════════════════════
# 3. Type classification
# ═══════════════════════════════════════════════════════════════

class TestClassification:
    def test_figure_with_percentage(self):
        assert _classify_unit("Revenue grew by 45.2% year over year.") == "figure"

    def test_figure_with_currency(self):
        assert _classify_unit("The total cost was $1,234,567.") == "figure"

    def test_figure_with_measurement(self):
        assert _classify_unit("Response time dropped to 15ms.") == "figure"

    def test_claim_with_should(self):
        assert _classify_unit("Companies should not ignore this trend.") == "claim"

    def test_claim_with_studies(self):
        assert _classify_unit("Studies show that early intervention works.") == "claim"

    def test_instruction_imperative(self):
        assert _classify_unit("Install the package using pip.") == "instruction"

    def test_instruction_numbered_step(self):
        assert _classify_unit("1. Run the build script.") == "instruction"

    def test_fact_with_founded(self):
        assert _classify_unit("The company was founded in 1998.") == "fact"

    def test_fact_with_located(self):
        assert _classify_unit("The facility is located in Austin, Texas.") == "fact"

    def test_unknown_fallback(self):
        """Unclassifiable text returns 'unknown', not discarded."""
        result = _classify_unit("Lorem ipsum dolor sit amet.")
        assert result == "unknown"


# ═══════════════════════════════════════════════════════════════
# 4. End-to-end parse
# ═══════════════════════════════════════════════════════════════

class TestEndToEndParse:
    def test_parse_creates_units(self, tmp_db):
        mission, ingest = _setup_mission_with_ingest(
            tmp_db,
            "The company was founded in 2020. Revenue grew by 35% last year."
        )
        units = parse_ingest_record(
            ingest["ingest_id"], mission["mission_id"], db_path=tmp_db
        )
        assert len(units) >= 1
        assert all("error" not in u for u in units)
        assert all(u["status"] == "parsed" for u in units)

    def test_parse_persists_to_db(self, tmp_db):
        mission, ingest = _setup_mission_with_ingest(
            tmp_db,
            "Data is persisted correctly. Check the database."
        )
        parse_ingest_record(
            ingest["ingest_id"], mission["mission_id"], db_path=tmp_db
        )
        db_units = get_parsed_units(mission["mission_id"], db_path=tmp_db)
        assert len(db_units) >= 1

    def test_parse_invalid_ingest_id(self, tmp_db):
        result = parse_ingest_record(
            "nonexistent-id", "fake-mission", db_path=tmp_db
        )
        assert len(result) == 1
        assert "error" in result[0]

    def test_character_count_correct(self, tmp_db):
        mission, ingest = _setup_mission_with_ingest(
            tmp_db, "Exactly this text."
        )
        units = parse_ingest_record(
            ingest["ingest_id"], mission["mission_id"], db_path=tmp_db
        )
        for u in units:
            assert u["character_count"] == len(u["content"])

    def test_formatting_stripped_in_parse(self, tmp_db):
        mission, ingest = _setup_mission_with_ingest(
            tmp_db, "<p>This is <b>bold</b> text with &amp; entities.</p>"
        )
        units = parse_ingest_record(
            ingest["ingest_id"], mission["mission_id"], db_path=tmp_db
        )
        for u in units:
            assert "<p>" not in u["content"]
            assert "<b>" not in u["content"]
            assert "&amp;" not in u["content"]

    def test_unknown_units_not_discarded(self, tmp_db):
        """Architecture §2: units that cannot be classified → tag unknown, pass forward."""
        mission, ingest = _setup_mission_with_ingest(
            tmp_db, "Lorem ipsum dolor sit amet, consectetur adipiscing elit."
        )
        units = parse_ingest_record(
            ingest["ingest_id"], mission["mission_id"], db_path=tmp_db
        )
        assert len(units) >= 1
        # Content is preserved even if type is "unknown"
        assert all(len(u["content"]) > 0 for u in units)


# ═══════════════════════════════════════════════════════════════
# 5. Batch parse
# ═══════════════════════════════════════════════════════════════

class TestBatchParse:
    def test_parse_all_received(self, tmp_db):
        mission = create_mission(
            mission_statement="Batch parse test",
            domain="secops_triager",
            calibration={
                "ingest_mode": "direct",
                "volume_quality_slider": 0.5,
                "min_content_length": 40,
                "active_emphasis_lenses": [],
            },
            db_path=tmp_db,
        )
        # Ingest two records
        ingest_record(
            mission_id=mission["mission_id"],
            source="src1", format="text",
            raw_content="First record content here.",
            db_path=tmp_db,
        )
        ingest_record(
            mission_id=mission["mission_id"],
            source="src2", format="text",
            raw_content="Second record content here.",
            db_path=tmp_db,
        )
        units = parse_all_received(mission["mission_id"], db_path=tmp_db)
        assert len(units) >= 2


# ═══════════════════════════════════════════════════════════════
# 6. Pipeline logging
# ═══════════════════════════════════════════════════════════════

class TestParseLogging:
    def test_log_entries(self, tmp_db):
        mission, ingest = _setup_mission_with_ingest(
            tmp_db, "Log check content."
        )
        parse_ingest_record(
            ingest["ingest_id"], mission["mission_id"], db_path=tmp_db
        )
        conn = sqlite3.connect(str(tmp_db))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT event FROM pipeline_log "
            "WHERE mission_id = ? AND stage = 'PARSE'",
            (mission["mission_id"],),
        ).fetchall()
        conn.close()
        events = [r["event"] for r in rows]
        assert "stage_start" in events
        assert "stage_complete" in events
