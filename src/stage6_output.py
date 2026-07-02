"""
Committee OS — Stage 6: Output.

Deterministic output formatter. No AI involvement.
Validates Qwen output, retrieves unit content, queries summary metrics,
and persists to pipeline_outputs.

Architecture §4 Contract
-------------------------
INPUT   : Qwen deliberation output
PROCESS : 1. Validate Qwen output against contract.
             - If invalid (partial or complete failure): log pipeline_halt, halt.
          2. Map recommendations to slots 1A, 2A, 3A.
          3. Retrieve full unit content from SQLite by unit_id.
          4. Query pipeline summary metrics (ingested, parsed, filtered, gate).
          5. Store to pipeline_outputs table.
OUTPUT  : final output record per §4 schema
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from src.db import get_connection

# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _PROJECT_ROOT / "config.json"


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(conn, mission_id: str, event: str, detail: str,
         error_code: str | None = None) -> None:
    conn.execute(
        """
        INSERT INTO pipeline_log
            (log_id, mission_id, stage, event, detail, timestamp, error_code)
        VALUES (?, ?, 'OUTPUT', ?, ?, ?, ?)
        """,
        (str(uuid.uuid4()), mission_id, event, detail, _iso_now(), error_code),
    )


def _load_config() -> dict:
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ──────────────────────────────────────────────────────────────
# Validation
# ──────────────────────────────────────────────────────────────

def _validate_deliberation_output(output: dict) -> str | None:
    """Validate Qwen output contract.

    Returns error message if invalid, or None if valid.
    """
    if not isinstance(output, dict):
        return "Output must be a JSON object."

    if "mission_id" not in output:
        return "Missing mission_id."

    recs = output.get("recommendations")
    if not isinstance(recs, list):
        return "recommendations must be a list."

    if len(recs) != 3:
        return f"Expected exactly 3 recommendations, got {len(recs)}."

    slots_seen = set()
    valid_slots = {"1A", "2A", "3A"}
    valid_ranks = {"1", "2", "3", 1, 2, 3}

    for idx, rec in enumerate(recs):
        if not isinstance(rec, dict):
            return f"Recommendation {idx} is not an object."

        rank = rec.get("rank")
        slot = rec.get("slot")
        unit_id = rec.get("unit_id")
        rationale = rec.get("rationale")
        confidence = rec.get("confidence")

        if rank not in valid_ranks:
            return f"Invalid rank '{rank}' in recommendation {idx}."

        if slot not in valid_slots:
            return f"Invalid slot '{slot}' in recommendation {idx}."

        if slot in slots_seen:
            return f"Duplicate slot '{slot}'."
        slots_seen.add(slot)

        if not isinstance(unit_id, str) or not unit_id.strip():
            return f"Invalid unit_id in recommendation {idx}."

        if not isinstance(rationale, str) or not rationale.strip():
            return f"Missing rationale in recommendation {idx}."

        if not isinstance(confidence, (int, float)) or not (0.0 <= confidence <= 1.0):
            return f"Invalid confidence '{confidence}' in recommendation {idx}."

    if slots_seen != valid_slots:
        return f"Missing slots. Expected exactly 1A, 2A, 3A, got {slots_seen}."

    return None


# ──────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────

def generate_pipeline_output(
    deliberation_output: dict,
    db_path: Path | None = None,
) -> dict:
    """Generate the final pipeline output from Qwen deliberation results."""
    conn = get_connection(db_path)
    try:
        # ── 1. Validate Deliberation Output ───────────────────
        validation_err = _validate_deliberation_output(deliberation_output)
        mission_id = deliberation_output.get("mission_id", "unknown-mission")

        if validation_err is not None:
            _log(conn, mission_id, "pipeline_halt", f"Validation failed: {validation_err}")
            conn.commit()
            raise ValueError(f"Deliberation output validation failed: {validation_err}")

        _log(conn, mission_id, "stage_start", "Generating final pipeline output.")

        # ── 2. Map recommendations & Retrieve content ─────────
        slots = {}
        for rec in deliberation_output["recommendations"]:
            slot = rec["slot"]
            unit_id = rec["unit_id"]
            rationale = rec["rationale"]
            confidence = rec["confidence"]

            # Fetch unit content from SQLite
            row = conn.execute(
                "SELECT content FROM parsed_units WHERE unit_id = ?",
                (unit_id,),
            ).fetchone()
            if row is None:
                err_msg = f"unit_id '{unit_id}' not found in parsed_units."
                _log(conn, mission_id, "pipeline_halt", err_msg)
                conn.commit()
                raise ValueError(err_msg)

            slots[slot] = {
                "unit_id": unit_id,
                "content": row["content"],
                "rationale": rationale,
                "confidence": float(confidence),
            }

        # ── 3. Query pipeline summary metrics ─────────────────
        # Ingested records count
        row_ingested = conn.execute(
            "SELECT COUNT(*) FROM ingest_records WHERE mission_id = ?",
            (mission_id,),
        ).fetchone()
        total_units_ingested = row_ingested[0] if row_ingested else 0

        # Parsed units count
        row_parsed = conn.execute(
            """
            SELECT COUNT(*) FROM parsed_units pu
            JOIN ingest_records ir ON pu.ingest_id = ir.ingest_id
            WHERE ir.mission_id = ?
            """,
            (mission_id,),
        ).fetchone()
        units_parsed = row_parsed[0] if row_parsed else 0

        # Filtered units count (passed filter)
        row_filtered = conn.execute(
            """
            SELECT COUNT(*) FROM filter_results fr
            JOIN parsed_units pu ON fr.unit_id = pu.unit_id
            JOIN ingest_records ir ON pu.ingest_id = ir.ingest_id
            WHERE ir.mission_id = ? AND fr.status = 'pass'
            """,
            (mission_id,),
        ).fetchone()
        units_passed_filter = row_filtered[0] if row_filtered else 0

        # Gate passed count
        cfg = _load_config()
        gate_threshold = cfg.get("gate_threshold", 0.55)
        row_gate = conn.execute(
            """
            SELECT COUNT(DISTINCT ls.unit_id) FROM lens_scores ls
            JOIN parsed_units pu ON ls.unit_id = pu.unit_id
            JOIN ingest_records ir ON pu.ingest_id = ir.ingest_id
            WHERE ir.mission_id = ? AND ls.raw_score >= ?
            """,
            (mission_id, gate_threshold),
        ).fetchone()
        units_passed_gate = row_gate[0] if row_gate else 0

        pipeline_summary = {
            "total_units_ingested": total_units_ingested,
            "units_parsed": units_parsed,
            "units_passed_filter": units_passed_filter,
            "units_passed_gate": units_passed_gate,
        }

        # ── 4. Assemble output record ─────────────────────────
        output_id = str(uuid.uuid4())
        timestamp = _iso_now()

        output_record = {
            "output_id": output_id,
            "mission_id": mission_id,
            "timestamp": timestamp,
            "slots": slots,
            "pipeline_summary": pipeline_summary,
        }

        # Store to SQLite
        conn.execute(
            """
            INSERT OR REPLACE INTO pipeline_outputs
                (output_id, mission_id, timestamp, slots, pipeline_summary)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                output_id,
                mission_id,
                timestamp,
                json.dumps(slots),
                json.dumps(pipeline_summary),
            ),
        )

        _log(conn, mission_id, "stage_complete", f"Pipeline output generated: {output_id}")
        conn.commit()
        return output_record

    except Exception as exc:
        conn.rollback()
        raise exc
    finally:
        conn.close()
