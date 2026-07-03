"""
Committee OS — Retraction Engine & Blast-Radius Circuit Breaker.

Implements:
  1. Conflict adjudication (symmetry-safe, memory-gravity free)
  2. Blast-radius projection (SQLite-compatible recursive CTE, active-only denominator)
  3. Circuit breaker (proceeds if <= 15%, blocks and queues if > 15%)
  4. Transactional safety (all-or-nothing cascade commit)
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from src.db import get_connection

# ──────────────────────────────────────────────────────────────
# Exceptions & Helpers
# ──────────────────────────────────────────────────────────────

class ManualReviewRequired(Exception):
    """Raised when a retraction is blocked by the circuit breaker or lacks support."""
    def __init__(self, message: str, payload: dict | None = None):
        super().__init__(message)
        self.payload = payload or {}


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ──────────────────────────────────────────────────────────────
# Adjudication
# ──────────────────────────────────────────────────────────────

def adjudicate_conflict(
    key_a: str,
    key_b: str,
    db_path: Path | None = None,
) -> dict:
    """Adjudicate a conflict between two assertion keys.

    Returns a dict with:
      - winner_key
      - loser_key
      - winner_score
      - loser_score
    Raises ManualReviewRequired if both scores are 0.0.
    """
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            """
            WITH contenders(assertion_key) AS (
                SELECT ?
                UNION ALL
                SELECT ?
            ),
            scores AS (
                SELECT 
                    c.assertion_key,
                    COALESCE(COUNT(DISTINCT r.chapter_id), 0) as qualified_chapters,
                    COALESCE(AVG(r.confidence_score), 0.0) as mean_confidence
                FROM contenders c
                LEFT JOIN classified_records r ON c.assertion_key = r.assertion_key 
                                              AND r.verdict = 'pass' 
                                              AND r.confidence_score >= 0.7
                GROUP BY c.assertion_key
            )
            SELECT 
                assertion_key,
                (qualified_chapters * mean_confidence) as entrenchment_score
            FROM scores
            ORDER BY entrenchment_score ASC
            """,
            (key_a, key_b),
        )
        rows = cursor.fetchall()
        
        # Since it's ordered ASC:
        loser_row = rows[0]
        winner_row = rows[1]
        
        loser_key = loser_row[0]
        loser_score = loser_row[1]
        winner_key = winner_row[0]
        winner_score = winner_row[1]
        
        # Exact float equality is safe because 0.0 is returned by COALESCE when no rows match
        if winner_score == 0.0:
            raise ManualReviewRequired(
                f"Conflict between '{key_a}' and '{key_b}' cannot be resolved automatically: "
                "both have zero qualifying support.",
                payload={"contested_key_a": key_a, "contested_key_b": key_b}
            )
            
        return {
            "winner_key": winner_key,
            "loser_key": loser_key,
            "winner_score": winner_score,
            "loser_score": loser_score,
        }
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────
# Blast Radius Projection
# ──────────────────────────────────────────────────────────────

def project_blast_radius(
    target_record_id: str,
    db_path: Path | None = None,
) -> tuple[float, list[str]]:
    """Project the dataset-wide blast radius of retracting target_record_id.

    Returns a tuple: (blast_radius_percentage, list_of_affected_record_ids)
    """
    conn = get_connection(db_path)
    try:
        # 1. Get the affected graph of record_ids
        cursor = conn.execute(
            """
            WITH RECURSIVE affected_graph(record_id) AS (
                SELECT ?
                UNION
                SELECT r.record_id
                FROM classified_records r
                JOIN affected_graph ag ON (
                    r.supersedes_record_id = ag.record_id
                    OR EXISTS (
                        SELECT 1 
                        FROM record_dependencies d 
                        WHERE d.dependent_record_id = r.record_id 
                          AND d.dependency_record_id = ag.record_id
                    )
                )
            )
            SELECT record_id FROM affected_graph
            """,
            (target_record_id,),
        )
        affected_ids = [row[0] for row in cursor.fetchall()]
        
        if not affected_ids:
            return 0.0, []
            
        # 2. Count active (non-superseded) records in the dataset
        row_active = conn.execute(
            """
            SELECT COUNT(*) 
            FROM classified_records r1
            LEFT JOIN classified_records r2 ON r1.record_id = r2.supersedes_record_id
            WHERE r2.record_id IS NULL
            """
        ).fetchone()
        active_count = row_active[0] if row_active else 0
        
        if active_count == 0:
            return 0.0, affected_ids
            
        percentage = (len(affected_ids) * 100.0) / active_count
        return percentage, affected_ids
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────
# Apply Retraction
# ──────────────────────────────────────────────────────────────

def apply_retraction(
    key_a: str,
    key_b: str,
    db_path: Path | None = None,
) -> None:
    """Adjudicate conflict, project blast radius, and apply or queue the retraction.

    All-or-nothing transactional safety.
    """
    # 1. Adjudicate
    adj = adjudicate_conflict(key_a, key_b, db_path=db_path)
    loser_key = adj["loser_key"]
    
    conn = get_connection(db_path)
    try:
        # Find the active record for the loser key
        row = conn.execute(
            """
            SELECT r1.record_id 
            FROM classified_records r1
            LEFT JOIN classified_records r2 ON r1.record_id = r2.supersedes_record_id
            WHERE r1.assertion_key = ? AND r1.verdict = 'pass' AND r2.record_id IS NULL
            """,
            (loser_key,),
        ).fetchone()
        
        if row is None:
            # No active record to retract
            return
            
        loser_record_id = row[0]
        
        # 2. Project blast radius
        percentage, affected_ids = project_blast_radius(loser_record_id, db_path=db_path)
        
        # 3. Circuit Breaker
        if percentage > 15.0:
            # Block and queue
            review_id = str(uuid.uuid4())
            timestamp = _iso_now()
            conn.execute(
                """
                INSERT INTO manual_review_queue
                    (review_id, contested_key_a, contested_key_b, loser_key, projected_blast_radius, affected_record_ids, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    review_id,
                    key_a,
                    key_b,
                    loser_key,
                    percentage,
                    json.dumps(affected_ids),
                    timestamp,
                ),
            )
            conn.commit()
            
            raise ManualReviewRequired(
                f"Retraction blocked: projected blast radius {percentage:.2f}% exceeds 15% threshold.",
                payload={
                    "review_id": review_id,
                    "contested_key_a": key_a,
                    "contested_key_b": key_b,
                    "loser_key": loser_key,
                    "projected_blast_radius": percentage,
                    "affected_record_ids": affected_ids,
                }
            )
            
        # 4. Proceed: Commit retraction cascade in a single transaction
        timestamp = _iso_now()
        for old_id in affected_ids:
            # Fetch old record details
            old_row = conn.execute(
                "SELECT chapter_id, assertion_key, rubric_dependencies FROM classified_records WHERE record_id = ?",
                (old_id,),
            ).fetchone()
            if old_row:
                new_id = str(uuid.uuid4())
                conn.execute(
                    """
                    INSERT INTO classified_records
                        (record_id, chapter_id, assertion_key, verdict, rubric_dependencies, confidence_score, supersedes_record_id, timestamp)
                    VALUES (?, ?, ?, 'fail', ?, 0.0, ?, ?)
                    """,
                    (
                        new_id,
                        old_row["chapter_id"],
                        old_row["assertion_key"],
                        old_row["rubric_dependencies"],
                        old_id,
                        timestamp,
                    ),
                )
        conn.commit()
        
    except Exception as exc:
        conn.rollback()
        raise exc
    finally:
        conn.close()
