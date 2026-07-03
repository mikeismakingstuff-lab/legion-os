"""
Committee OS — Web Ingest tests.

Covers:
  1. ingest_from_urls with mocked HTTP responses
  2. HTML cleaning via BeautifulSoup and Markdown conversion via MarkItDown
  3. Error handling: logging and skipping unreachable URLs
  4. Integration with the existing parse/filter pipeline
"""

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from src.init_db import init_database
from src.stage0_mission import create_mission
from src.stage1_ingest import ingest_from_urls, get_received_records
from src.stage2_parse import parse_ingest_record
from src.stage3_filter import filter_units


@pytest.fixture
def tmp_db(tmp_path):
    db_path = tmp_path / "pipeline.db"
    init_database(db_path)
    return db_path


@pytest.fixture
def mission(tmp_db):
    return create_mission(
        mission_statement="Test web ingest",
        domain="educational_academy",
        calibration={
            "ingest_mode": "direct",
            "volume_quality_slider": 0.5,
            "min_content_length": 5,
            "active_emphasis_lenses": [],
        },
        db_path=tmp_db,
    )


class TestWebIngest:
    @patch("requests.get")
    def test_successful_web_ingest(self, mock_get, tmp_db, mission):
        # Mock successful HTTP response
        mock_resp = MagicMock()
        mock_resp.text = "<html><body><header>Nav</header><h1>Hello World</h1><p>This is a test paragraph.</p></body></html>"
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp

        urls = ["https://example.com/test"]
        records = ingest_from_urls(mission["mission_id"], urls, db_path=tmp_db)

        assert len(records) == 1
        assert records[0]["source"] == "https://example.com/test"
        assert records[0]["format"] == "markdown"
        
        # Verify MarkItDown conversion (header should be decomposed, h1 and p converted to Markdown)
        assert "# Hello World" in records[0]["raw_content"]
        assert "This is a test paragraph." in records[0]["raw_content"]
        assert "Nav" not in records[0]["raw_content"]

    @patch("requests.get")
    def test_unreachable_url_logged_and_skipped(self, mock_get, tmp_db, mission):
        # Mock connection error
        mock_get.side_effect = requests.exceptions.ConnectionError("Connection refused")

        urls = ["https://unreachable.com"]
        records = ingest_from_urls(mission["mission_id"], urls, db_path=tmp_db)

        # Should skip and return empty list
        assert len(records) == 0

        # Verify pipeline_log contains the scrape_error
        conn = sqlite3.connect(str(tmp_db))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT event, detail, error_code FROM pipeline_log "
            "WHERE stage = 'INGEST' AND event = 'ai_error'"
        ).fetchone()
        conn.close()
        assert row is not None
        assert "Failed to scrape URL" in row["detail"]
        assert row["error_code"] == "scrape_error"

    @patch("requests.get")
    def test_integration_with_parse_and_filter(self, mock_get, tmp_db, mission):
        mock_resp = MagicMock()
        mock_resp.text = "<html><body><p>This is a valid sentence for parsing.</p></body></html>"
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp

        urls = ["https://example.com/test"]
        records = ingest_from_urls(mission["mission_id"], urls, db_path=tmp_db)
        assert len(records) == 1

        # Run parse stage
        parse_res = parse_ingest_record(records[0]["ingest_id"], mission["mission_id"], db_path=tmp_db)
        assert len(parse_res) == 1
        assert parse_res[0]["content"] == "This is a valid sentence for parsing."

        # Run filter stage
        filter_units(mission["mission_id"], db_path=tmp_db)

        # Verify filter result
        conn = sqlite3.connect(str(tmp_db))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT status FROM filter_results WHERE unit_id = ?",
            (parse_res[0]["unit_id"],),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row["status"] == "pass"
