"""
Committee OS — SourceMapper tests.

Covers:
  1. source_registry table creation and pre-population
  2. SourceMapper matching logic (exact domain, keyword matching, wildcard keyword, priority sorting)
"""

import sqlite3
from pathlib import Path

import pytest

from src.init_db import init_database
from src.stage0_mission import SourceMapper


@pytest.fixture
def tmp_db(tmp_path):
    db_path = tmp_path / "pipeline.db"
    init_database(db_path)
    return db_path


class TestSourceMapper:
    def test_pre_population(self, tmp_db):
        conn = sqlite3.connect(str(tmp_db))
        row = conn.execute("SELECT COUNT(*) FROM source_registry").fetchone()
        conn.close()
        assert row is not None
        assert row[0] > 0

    def test_mapping_exact_keyword(self, tmp_db):
        # educational_academy has keyword "math" mapped to "https://en.wikipedia.org/wiki/Mathematics"
        urls = SourceMapper.map_mission_to_sources(
            mission_statement="We want to study math and algebra.",
            domain="educational_academy",
            db_path=tmp_db,
        )
        assert "https://en.wikipedia.org/wiki/Mathematics" in urls
        assert "https://en.wikipedia.org/wiki/Science" not in urls

    def test_mapping_wildcard(self, tmp_db):
        # educational_academy has wildcard "*" mapped to "https://en.wikipedia.org/wiki/Education"
        urls = SourceMapper.map_mission_to_sources(
            mission_statement="Random statement with no keywords.",
            domain="educational_academy",
            db_path=tmp_db,
        )
        assert "https://en.wikipedia.org/wiki/Education" in urls

    def test_priority_sorting(self, tmp_db):
        # educational_academy:
        # - "math" has priority 1
        # - "science" has priority 2
        # - "*" has priority 3
        urls = SourceMapper.map_mission_to_sources(
            mission_statement="We want to study math and science.",
            domain="educational_academy",
            db_path=tmp_db,
        )
        # Priority 1 (math) should come before Priority 2 (science) and Priority 3 (*)
        assert urls == [
            "https://en.wikipedia.org/wiki/Mathematics",
            "https://en.wikipedia.org/wiki/Science",
            "https://en.wikipedia.org/wiki/Education",
        ]
