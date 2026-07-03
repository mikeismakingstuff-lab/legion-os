"""
Committee OS — Retraction Engine & Blast-Radius Circuit Breaker tests.
"""

import json
import sqlite3
from pathlib import Path

import pytest

from src.init_db import init_database
from src.retraction_engine import (
    adjudicate_conflict,
    project_blast_radius,
    apply_retraction,
    ManualReviewRequired,
)


@pytest.fixture
def tmp_db(tmp_path):
    db_path = tmp_path / "pipeline.db"
    init_database(db_path)
    return db_path


def _insert_record(conn, record_id, chapter_id, assertion_key, verdict, confidence_score, supersedes_record_id=None):
    conn.execute(
        """
        INSERT INTO classified_records
            (record_id, chapter_id, assertion_key, verdict, rubric_dependencies, confidence_score, supersedes_record_id, timestamp)
        VALUES (?, ?, ?, ?, '{}', ?, ?, '2026-07-02T06:00:00Z')
        """,
        (record_id, chapter_id, assertion_key, verdict, confidence_score, supersedes_record_id),
    )


def _insert_dependency(conn, dependent_id, dependency_id):
    conn.execute(
        "INSERT INTO record_dependencies (dependent_record_id, dependency_record_id) VALUES (?, ?)",
        (dependent_id, dependency_id),
    )


class TestRetractionEngine:
    def test_adjudicate_conflict_normal(self, tmp_db):
        conn = sqlite3.connect(str(tmp_db))
        # key_a: 2 chapters, high confidence (score = 2 * 0.9 = 1.8)
        _insert_record(conn, "r1", "ch1", "key_a", "pass", 0.9)
        _insert_record(conn, "r2", "ch2", "key_a", "pass", 0.9)
        
        # key_b: 1 chapter, high confidence (score = 1 * 0.95 = 0.95)
        _insert_record(conn, "r3", "ch1", "key_b", "pass", 0.95)
        conn.commit()
        conn.close()

        res = adjudicate_conflict("key_a", "key_b", db_path=tmp_db)
        assert res["winner_key"] == "key_a"
        assert res["loser_key"] == "key_b"
        assert res["winner_score"] == 1.8
        assert res["loser_score"] == 0.95

    def test_adjudicate_conflict_tie_breaker(self, tmp_db):
        conn = sqlite3.connect(str(tmp_db))
        # key_a: 2 chapters, high confidence (score = 2 * 0.95 = 1.9)
        _insert_record(conn, "r1", "ch1", "key_a", "pass", 0.95)
        _insert_record(conn, "r2", "ch2", "key_a", "pass", 0.95)
        
        # key_b: 2 chapters, lower confidence (score = 2 * 0.75 = 1.5)
        _insert_record(conn, "r3", "ch1", "key_b", "pass", 0.75)
        _insert_record(conn, "r4", "ch2", "key_b", "pass", 0.75)
        conn.commit()
        conn.close()

        res = adjudicate_conflict("key_a", "key_b", db_path=tmp_db)
        assert res["winner_key"] == "key_a"
        assert res["loser_key"] == "key_b"

    def test_adjudicate_conflict_double_zero(self, tmp_db):
        # Neither has any qualifying support (confidence >= 0.7)
        conn = sqlite3.connect(str(tmp_db))
        _insert_record(conn, "r1", "ch1", "key_a", "pass", 0.5)
        _insert_record(conn, "r2", "ch1", "key_b", "pass", 0.6)
        conn.commit()
        conn.close()

        with pytest.raises(ManualReviewRequired) as exc:
            adjudicate_conflict("key_a", "key_b", db_path=tmp_db)
        assert "both have zero qualifying support" in str(exc.value)

    def test_project_blast_radius(self, tmp_db):
        conn = sqlite3.connect(str(tmp_db))
        # Setup dependency graph:
        # r1 (loser)
        # r2 depends on r1
        # r3 depends on r2
        # r4 (independent)
        # r5 (independent)
        # Total active records = 5
        _insert_record(conn, "r1", "ch1", "key_a", "pass", 0.9)
        _insert_record(conn, "r2", "ch1", "key_b", "pass", 0.8)
        _insert_record(conn, "r3", "ch1", "key_c", "pass", 0.8)
        _insert_record(conn, "r4", "ch1", "key_d", "pass", 0.8)
        _insert_record(conn, "r5", "ch1", "key_e", "pass", 0.8)
        
        _insert_dependency(conn, "r2", "r1")
        _insert_dependency(conn, "r3", "r2")
        conn.commit()
        conn.close()

        # Retracting r1 should affect r1, r2, r3 (3 out of 5 active records = 60.0%)
        percentage, affected = project_blast_radius("r1", db_path=tmp_db)
        assert percentage == 60.0
        assert sorted(affected) == ["r1", "r2", "r3"]

    def test_apply_retraction_proceed(self, tmp_db):
        conn = sqlite3.connect(str(tmp_db))
        # Total active records = 10 (so 1 affected record = 10.0% <= 15.0%)
        for i in range(1, 11):
            _insert_record(conn, f"r{i}", "ch1", f"key_{i}", "pass", 0.9)
        conn.commit()
        conn.close()

        # Adjudicate conflict between key_1 and key_2 (key_2 has lower score if we don't insert it, wait, let's make key_2 have lower score)
        # Actually, key_1 has score 0.9, key_2 has score 0.9. Let's make key_2 have 0.75 score.
        conn = sqlite3.connect(str(tmp_db))
        conn.execute("UPDATE classified_records SET confidence_score = 0.75 WHERE record_id = 'r2'")
        conn.commit()
        conn.close()

        # Retract key_2 (loser). Blast radius is 10% (1 record: r2).
        apply_retraction("key_1", "key_2", db_path=tmp_db)

        # Verify r2 is superseded by a failed record
        conn = sqlite3.connect(str(tmp_db))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT verdict, confidence_score FROM classified_records WHERE supersedes_record_id = 'r2'"
        ).fetchone()
        conn.close()
        assert row is not None
        assert row["verdict"] == "fail"
        assert row["confidence_score"] == 0.0

    def test_apply_retraction_block(self, tmp_db):
        conn = sqlite3.connect(str(tmp_db))
        # Total active records = 5 (so 1 affected record = 20.0% > 15.0%)
        for i in range(1, 6):
            _insert_record(conn, f"r{i}", "ch1", f"key_{i}", "pass", 0.9)
        conn.execute("UPDATE classified_records SET confidence_score = 0.75 WHERE record_id = 'r2'")
        conn.commit()
        conn.close()

        # Retract key_2 (loser). Blast radius is 20% (1 record: r2). Should block.
        with pytest.raises(ManualReviewRequired) as exc:
            apply_retraction("key_1", "key_2", db_path=tmp_db)
        
        assert "Retraction blocked" in str(exc.value)
        payload = exc.value.payload
        assert payload["projected_blast_radius"] == 20.0
        assert payload["loser_key"] == "key_2"

        # Verify a record was written to manual_review_queue
        conn = sqlite3.connect(str(tmp_db))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM manual_review_queue").fetchone()
        conn.close()
        assert row is not None
        assert row["loser_key"] == "key_2"
        assert row["projected_blast_radius"] == 20.0
        assert "r2" in json.loads(row["affected_record_ids"])

    def test_adjudicate_one_sided_contradiction(self, tmp_db):
        # One key has evidence, the other has none. Should resolve without escalating.
        conn = sqlite3.connect(str(tmp_db))
        _insert_record(conn, "r1", "ch1", "key_a", "pass", 0.9)
        conn.commit()
        conn.close()

        res = adjudicate_conflict("key_a", "key_b", db_path=tmp_db)
        assert res["winner_key"] == "key_a"
        assert res["loser_key"] == "key_b"
        assert res["winner_score"] == 0.9
        assert res["loser_score"] == 0.0

    def test_circular_dependency_termination(self, tmp_db):
        # Setup circular dependency:
        # r1 depends on r2
        # r2 depends on r1
        # Total active records = 2
        conn = sqlite3.connect(str(tmp_db))
        _insert_record(conn, "r1", "ch1", "key_a", "pass", 0.9)
        _insert_record(conn, "r2", "ch1", "key_b", "pass", 0.8)
        _insert_dependency(conn, "r1", "r2")
        _insert_dependency(conn, "r2", "r1")
        conn.commit()
        conn.close()

        # Should terminate successfully and return 100% blast radius (both records affected)
        percentage, affected = project_blast_radius("r1", db_path=tmp_db)
        assert percentage == 100.0
        assert sorted(affected) == ["r1", "r2"]

