"""
Committee OS — Stage 5: Deliberate.

Pure deterministic deliberation stage.
Selects the top 3 units by aggregate_score, computes flags via threshold checks,
and emits rationale_facts for each unit.
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from src.db import get_connection
from src.stage4_weigh import get_top_scored_units

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
        VALUES (?, ?, 'DELIBERATE', ?, ?, ?, ?)
        """,
        (str(uuid.uuid4()), mission_id, event, detail, _iso_now(), error_code),
    )


def _load_config() -> dict:
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ──────────────────────────────────────────────────────────────
# Validation
# ──────────────────────────────────────────────────────────────

def _validate_deliberation_output(output: dict, top_unit_ids: set[str]) -> str | None:
    """Validate deliberation output contract.

    Returns error message if invalid, or None if valid.
    """
    if not isinstance(output, dict):
        return "Output must be a JSON object."

    if "mission_id" not in output:
        return "Missing mission_id."

    if "deliberation_id" not in output:
        return "Missing deliberation_id."

    recs = output.get("recommendations")
    if not isinstance(recs, list):
        return "recommendations must be a list."

    slots_seen = set()
    expected_slots = {f"{i+1}A" for i in range(len(recs))}
    valid_ranks = {str(i+1) for i in range(len(recs))}

    for idx, rec in enumerate(recs):
        if not isinstance(rec, dict):
            return f"Recommendation {idx} is not an object."

        rank = rec.get("rank")
        slot = rec.get("slot")
        unit_id = rec.get("unit_id")
        rationale_facts = rec.get("rationale_facts")
        confidence = rec.get("confidence")

        if rank not in valid_ranks:
            return f"Invalid rank '{rank}' in recommendation {idx}."

        if slot not in expected_slots:
            return f"Invalid slot '{slot}' in recommendation {idx}."

        if slot in slots_seen:
            return f"Duplicate slot '{slot}'."
        slots_seen.add(slot)

        if unit_id not in top_unit_ids:
            return f"unit_id '{unit_id}' not in top_units."

        if not isinstance(rationale_facts, dict):
            return f"Missing or invalid rationale_facts in recommendation {idx}."

        expected_keys = {'rank', 'unit_id', 'top_lens', 'top_lens_score', 'aggregate_score'}
        if not expected_keys.issubset(rationale_facts.keys()):
            return f"rationale_facts in recommendation {idx} is missing required keys."

        if not isinstance(confidence, (int, float)) or not (0.0 <= confidence <= 1.0):
            return f"Invalid confidence '{confidence}' in recommendation {idx}."

    if slots_seen != expected_slots:
        return f"Missing slots. Expected {expected_slots}, got {slots_seen}."

    return None


# ──────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────

def deliberate_mission(
    mission_id: str,
    db_path: Path | None = None,
) -> dict:
    """Run the Stage 5 Deliberation stage for a mission."""
    conn = get_connection(db_path)
    try:
        # ── Fetch mission statement ───────────────────────────
        row = conn.execute(
            "SELECT statement FROM missions WHERE mission_id = ?",
            (mission_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"mission_id '{mission_id}' not found.")

        cfg = _load_config()
        top_n = cfg.get("top_units_to_deliberation", 5)

        # ── Fetch top scored units ────────────────────────────
        top_units = get_top_scored_units(mission_id, limit=top_n, db_path=db_path)
        if not top_units:
            # Complete failure (0 valid recommendations): halt pipeline
            _log(conn, mission_id, "pipeline_halt", "No units passed the gate threshold.")
            conn.commit()
            raise ValueError("No units passed the gate threshold. Pipeline halted.")

        _log(conn, mission_id, "stage_start", f"Deliberation started with {len(top_units)} units.")

        # Select top 3 units by aggregate score descending
        top_3 = top_units[:3]
        recommendations = []

        for idx, unit in enumerate(top_3):
            # Find the highest-scoring lens name and its score
            lens_scores = unit.get("lens_scores", {})
            if lens_scores:
                top_lens = max(lens_scores, key=lens_scores.get)
                top_lens_score = float(lens_scores[top_lens])
            else:
                top_lens = "unknown"
                top_lens_score = 0.0

            recommendations.append({
                "rank": str(idx + 1),
                "slot": f"{idx + 1}A",
                "unit_id": unit["unit_id"],
                "rationale_facts": {
                    "rank": str(idx + 1),
                    "unit_id": unit["unit_id"],
                    "top_lens": top_lens,
                    "top_lens_score": top_lens_score,
                    "aggregate_score": float(unit["aggregate_score"]),
                },
                "confidence": round(unit["aggregate_score"], 2),
            })

        # Compute warning flags via threshold checks
        top_unit_score = top_3[0]["aggregate_score"]
        flags = []
        if top_unit_score < 0.6:
            flags.append({"type": "low_confidence", "detail": "Top unit aggregate score is below 0.6"})

        if len(top_3) >= 3:
            third_unit_score = top_3[2]["aggregate_score"]
            score_difference = top_unit_score - third_unit_score
            if score_difference < 0.05:
                flags.append({"type": "narrow_margin", "detail": "Score difference between 1st and 3rd unit is below 0.05"})

        # Check for individual lens disagreement on the top unit
        top_unit_lens_scores = top_3[0].get("lens_scores", {})
        for lens_name, score in top_unit_lens_scores.items():
            if float(score) < 0.4:
                flags.append({
                    "type": "lens_disagreement",
                    "detail": f"Top unit has a low individual lens score of {score} for '{lens_name}'"
                })

        deliberation_id = str(uuid.uuid4())
        output = {
            "mission_id": mission_id,
            "deliberation_id": deliberation_id,
            "recommendations": recommendations,
            "flags": flags,
        }

        # Validate output contract
        top_unit_ids = {u["unit_id"] for u in top_units}
        validation_err = _validate_deliberation_output(output, top_unit_ids)
        if validation_err is not None:
            _log(conn, mission_id, "pipeline_halt", f"Deliberation output validation failed: {validation_err}")
            conn.commit()
            raise ValueError(f"Deliberation output validation failed: {validation_err}")

        # ── Persist results ───────────────────────────────────
        conn.execute(
            """
            INSERT OR REPLACE INTO deliberation_results (deliberation_id, mission_id, recommendations, flags)
            VALUES (?, ?, ?, ?)
            """,
            (
                deliberation_id,
                mission_id,
                json.dumps(recommendations),
                json.dumps(flags),
            ),
        )

        _log(conn, mission_id, "stage_complete", f"Deliberation complete: {deliberation_id}")
        conn.commit()
        return output

    except Exception as exc:
        conn.rollback()
        raise exc
    finally:
        conn.close()
